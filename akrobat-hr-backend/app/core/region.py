"""
Chennai / Singapore data separation -- one central place.

How it works
------------
1. RegionMiddleware (added in main.py) works out the *active region* for
   every HTTP request and stores it in a ContextVar:

     * SUPER ADMIN -> whatever the header toggle sends in `X-Region`
                      ("CHENNAI" / "SINGAPORE"). No header -> all regions.
     * HR          -> same header toggle, but no header -> own region
                      (never "all regions").
     * everyone else -> locked to their own employees.region. The header
                      is ignored, so nobody can peek into the other region
                      by editing a request.

2. app/core/database.py wraps `supabase_admin.table(...)`. For the tables
   listed below it automatically:

     * select / update / delete  -> adds `region = <active>` filter
     * insert / upsert           -> stamps `region` on new rows
                                    (employee-keyed tables get it from the
                                    DB trigger in sql/034 instead)

   So no service file needs `if region == ...` code. Every module that
   already reads these tables becomes region-aware at once.

3. Background jobs (APScheduler), websockets and /auth/* have no active
   region -> unscoped, exactly like before.

Add a table to STRICT_TABLES / SHARED_TABLES (and to sql/034) and it is
automatically separated too.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional

REGION_CHENNAI = "CHENNAI"
REGION_SINGAPORE = "SINGAPORE"
REGIONS = (REGION_CHENNAI, REGION_SINGAPORE)

# Employee data: a row belongs to exactly ONE region.
STRICT_TABLES = {
    "employees",
    "attendance",
    "attendance_corrections",
    "attendance_site_visits",
    "attendance_outdoor_visits",
    "employee_site_assignments",
    "employee_shift_history",
    "leave_requests",
    "leave_balances",
    "leave_replacement_credits",
    "employee_leave_overrides",
    "employee_leave_tier",
    "overtime_requests",
    "overtime_summary",
    "ot_adjustments",
    "payroll",
    "employee_resignations",
    "saturday_swaps",
    "employee_documents",
    "documents",
    "expenses",
}

# Master data: region NULL = shared by both regions.
SHARED_TABLES = {
    "departments",
    "designations",
    "shifts",
    "announcements",
    "locations",
    "company_locations",
    # Follow the region of the acting employee (DB trigger, sql/035).
    # NULL = system action -> visible in both regions.
    "audit_logs",
    "login_lockouts",
}

# Region is filled in by a DB trigger from employee_id, so don't stamp the
# viewer's region on inserts for these.
TRIGGER_STAMPED_TABLES = {"audit_logs", "login_lockouts"}

# Paths that must never be region-scoped (login, /auth/me, docs...).
UNSCOPED_PREFIXES = ("/auth", "/docs", "/redoc", "/openapi.json")

SUPER_ADMIN_ROLE = "SUPER ADMIN"
HR_ROLE = "HR"


_current_region: ContextVar[Optional[str]] = ContextVar("current_region", default=None)


# ---------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------
def normalize_region(value: Any) -> Optional[str]:
    v = str(value or "").strip().upper()
    return v if v in REGIONS else None


def region_from_location_text(text: Any) -> Optional[str]:
    """Chennai (or India) in the work location -> CHENNAI; anything else
    (Singapore, blank, other) -> SINGAPORE."""
    t = str(text or "").lower()
    if "chennai" in t or "india" in t:
        return REGION_CHENNAI
    return REGION_SINGAPORE


def get_region() -> Optional[str]:
    """Active region of the current request (None = all regions)."""
    return _current_region.get()


@contextmanager
def region_scope(region: Optional[str]):
    """Run a block under a specific region (None = all)."""
    token = _current_region.set(normalize_region(region))
    try:
        yield
    finally:
        _current_region.reset(token)


@contextmanager
def all_regions():
    """Temporarily disable scoping, e.g. for a cross-region report."""
    with region_scope(None):
        yield


# ---------------------------------------------------------------------
# Query wrapper used by database.py
# ---------------------------------------------------------------------
class _RegionScopedTable:
    def __init__(self, table, name: str):
        self._t = table
        self._name = name
        self._strict = name in STRICT_TABLES

    def _scope(self, query):
        region = get_region()
        if not region:
            return query
        if self._strict:
            return query.eq("region", region)
        return query.or_(f"region.eq.{region},region.is.null")

    def _stamp(self, values):
        region = get_region()
        if not region:
            return values
        # Employee-keyed tables get region from the employee via a DB
        # trigger (more accurate than the viewer's region). Only the
        # employees table itself and master tables are stamped here.
        if self._name in TRIGGER_STAMPED_TABLES or (
            self._strict and self._name != "employees"
        ):
            return values

        def one(row):
            if isinstance(row, dict) and not row.get("region"):
                return {**row, "region": region}
            return row

        if isinstance(values, list):
            return [one(r) for r in values]
        return one(values)

    def select(self, *args, **kwargs):
        return self._scope(self._t.select(*args, **kwargs))

    def update(self, values, *args, **kwargs):
        return self._scope(self._t.update(values, *args, **kwargs))

    def delete(self, *args, **kwargs):
        return self._scope(self._t.delete(*args, **kwargs))

    def insert(self, values, *args, **kwargs):
        return self._t.insert(self._stamp(values), *args, **kwargs)

    def upsert(self, values, *args, **kwargs):
        return self._t.upsert(self._stamp(values), *args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._t, item)


def scope_table(table, name: str):
    """Called by database.py for every .table(name)."""
    if name in STRICT_TABLES or name in SHARED_TABLES:
        return _RegionScopedTable(table, name)
    return table


# ---------------------------------------------------------------------
# Who is the caller, and which region do they get?
# ---------------------------------------------------------------------
_CACHE_TTL_SECONDS = 60
# auth_user_id -> (expires_at, role_name, own_region)
_actor_cache: dict[str, tuple[float, str, Optional[str]]] = {}


def invalidate_region_cache(auth_user_id: Optional[str] = None) -> None:
    if auth_user_id:
        _actor_cache.pop(str(auth_user_id), None)
    else:
        _actor_cache.clear()


def _lookup_actor(auth_user_id: str) -> tuple[str, Optional[str]]:
    now = time.time()
    hit = _actor_cache.get(auth_user_id)
    if hit and hit[0] > now:
        return hit[1], hit[2]

    # Imported lazily: database.py imports this module.
    from app.core.database import supabase_admin

    role_name, own_region = "", None
    try:
        # user_profiles / roles are not scoped tables, and no region is
        # active yet at this point, so this lookup is never filtered.
        resp = (
            supabase_admin.table("user_profiles")
            .select("roles(role_name), employees(region, work_location)")
            .eq("auth_user_id", auth_user_id)
            .maybe_single()
            .execute()
        )
        data = (resp.data if resp else None) or {}
        role_name = ((data.get("roles") or {}).get("role_name") or "").strip().upper()
        emp = data.get("employees") or {}
        own_region = normalize_region(emp.get("region")) or region_from_location_text(
            emp.get("work_location")
        )
    except Exception as e:  # never break a request because of this lookup
        print("REGION ACTOR LOOKUP WARNING:", e)
        return "", None

    _actor_cache[auth_user_id] = (now + _CACHE_TTL_SECONDS, role_name, own_region)
    return role_name, own_region


def resolve_region(token: Optional[str], header_value: Optional[str]) -> Optional[str]:
    from app.core.security import verify_access_token

    user = verify_access_token(token) if token else None
    if not user:
        return None

    role_name, own_region = _lookup_actor(str(user.id))

    if role_name == SUPER_ADMIN_ROLE:
        return normalize_region(header_value)  # None -> all regions

    if role_name == HR_ROLE:
        # HR can switch region, but never sees "all regions": no/invalid
        # header -> fall back to HR's own region.
        return normalize_region(header_value) or own_region

    return own_region  # locked; header ignored


class RegionMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware context quirks)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if scope.get("method") == "OPTIONS" or path.startswith(UNSCOPED_PREFIXES):
            return await self.app(scope, receive, send)

        import anyio
        from starlette.requests import Request

        from app.core.config import ACCESS_TOKEN_COOKIE

        request = Request(scope)
        token = request.cookies.get(ACCESS_TOKEN_COOKIE)
        header = request.headers.get("x-region")

        region = await anyio.to_thread.run_sync(resolve_region, token, header)

        ctx_token = _current_region.set(region)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_region.reset(ctx_token)


# ---------------------------------------------------------------------
# Keep an employee's region in step with their work location
# ---------------------------------------------------------------------
def region_for_work_location(work_location: Any) -> Optional[str]:
    """Region implied by the work-location text, or None if it is blank
    (blank -> keep whatever region the row already has / the viewer's)."""
    if not str(work_location or "").strip():
        return None
    return region_from_location_text(work_location)


def sync_employee_region(employee_pk: str, region: str) -> None:
    """Move every region-stamped row of one employee (attendance, leaves,
    payroll...) to `region`. Runs unscoped so rows of the OLD region are
    found too. Best-effort per table: a table without employee_id/region is
    skipped, never an error."""
    region = normalize_region(region)
    if not region:
        return
    from app.core.database import supabase_admin

    with all_regions():
        for name in sorted(STRICT_TABLES - {"employees"}):
            try:
                supabase_admin.table(name).update({"region": region}).eq(
                    "employee_id", employee_pk
                ).execute()
            except Exception as e:  # noqa: BLE001
                print(f"REGION SYNC skipped {name}: {e}")
