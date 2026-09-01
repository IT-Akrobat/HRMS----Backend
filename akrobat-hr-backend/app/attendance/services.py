import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import bad_request, forbidden, internal_server_error
from app.core.audit import record_audit_log
from app.core.rbac import has_permission
from app.core.request_ip import get_client_ip
from app.core.helpers.employee_helper import (
    get_employee_id_for_auth_user,
    is_manager_of,
    get_all_report_ids,
    get_employee_ids_for_role,
    get_field_employee_ids,
)
from app.core.constants import ADMIN
from app.core.database import supabase_admin
from app.core import realtime
from app.notifications.services import notify_employee

attendance_repo = SupabaseRepository("attendance")
correction_repo = SupabaseRepository("attendance_corrections")

ATTENDANCE_SELECT = "*, employees(employee_id, full_name)"
CORRECTION_SELECT = "*, employees(employee_id, full_name)"

# ==========================================================================
# TIMEZONE — shift start_time / grace_period in attendance_rules & shifts
# are entered as company-local wall-clock (e.g. "09:00:00" means 9 AM at
# whichever office the company has configured in Settings, not 9 AM UTC).
# But every stored/returned timestamp in this app (check_in_time,
# check_out_time, audit log created_at, notification created_at, etc.) is
# UTC — that's the DB column convention (see utils/date.js's parseServerDate
# on the frontend: a bare timestamp with no "Z"/offset is always assumed to
# be UTC). So "now" must stay true UTC; what actually needs converting is
# the shift's company-local-authored start time, which has to be translated
# to UTC before it's compared against a UTC check-in time — not the other
# way around. (An earlier version of this fix anchored "now" to a fixed IST
# offset instead, which fixed the late-minutes math for India-based
# companies but broke it for every other configured timezone — e.g. a
# Singapore office (Asia/Singapore, UTC+8) checking in on time was still
# compared against a 9 AM *India* (UTC+5:30) cutoff, showing everyone as
# checking in 2h30m "late". The shift's start_time has to be localized to
# whatever `settings.timezone` actually says the company office is in, not
# a value hardcoded at write-time.)
#
# `_now_utc()` is explicit about forcing UTC rather than relying on the
# server's OS clock already being UTC (cloud hosts default to UTC, but a
# server misconfigured to local time would silently break this).
# ==========================================================================
IST = ZoneInfo("Asia/Kolkata")

# Friendly labels -> IANA zone names for the timezones Settings currently
# offers (Settings > Preferences: "Singapore Time" / "India Time"). Falls
# back to IST below if `settings.timezone` holds neither an alias here nor
# a value ZoneInfo recognizes directly, so existing India-only deployments
# that never touched this setting keep behaving exactly as before.
TIMEZONE_ALIASES = {
    "singapore": "Asia/Singapore",
    "singapore time": "Asia/Singapore",
    "india": "Asia/Kolkata",
    "india time": "Asia/Kolkata",
}


def _get_company_timezone() -> ZoneInfo:
    """
    Resolves the IANA timezone the company's shift start_time / grace
    period wall-clock values are authored in, from `settings.timezone`
    (Settings > Preferences). Looked up fresh per check-in rather than
    cached, matching `_get_attendance_rule()`'s pattern — this table is
    edited rarely, so the extra read is cheap and avoids ever serving a
    stale timezone after an admin changes it. Falls back to IST
    (`Asia/Kolkata`) if settings has no row, no timezone value, or a value
    that isn't a recognized alias or valid IANA name.
    """
    try:
        settings_row = (
            supabase_admin.table("settings").select("timezone").limit(1).execute()
        )
        raw = (settings_row.data or [{}])[0].get("timezone")
        if raw:
            key = raw.strip().lower()
            zone_name = TIMEZONE_ALIASES.get(key, raw.strip())
            return ZoneInfo(zone_name)
    except Exception as e:
        logger.error(
            f"Failed to resolve company timezone from settings, falling back to IST: {e}"
        )

    return IST


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ==========================================================================
# POLICY RESOLUTION — shift + attendance_rules drive every calculation
# below; nothing is hardcoded to a fixed 9-to-5.
# ==========================================================================


def _get_attendance_rule() -> dict:
    """
    Company-wide fallback rule (sql/001_schema.sql seeds one: "Default
    Company Rule"). Shift-level `grace_period` / `working_hours` (below)
    take precedence per-employee whenever a shift is resolved; this is
    only the fallback for employees with no shift assigned at all.
    """
    try:
        rule = (
            supabase_admin.table("attendance_rules")
            .select("*")
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        )
        if rule.data:
            return rule.data[0]
    except Exception as e:
        logger.error(f"Failed to fetch attendance_rules, using defaults: {e}")

    return {
        "late_grace_minutes": 0,
        "minimum_work_minutes": 480,
        "overtime_after_minutes": 480,
    }


def _get_employee_shift(employee_id: str, for_date: date) -> Optional[dict]:
    """
    Resolves the shift that applies to `employee_id` on `for_date`:
      1. An active `employee_shift_history` row covering that date.
      2. Else the employee's default `employees.shift_id`.
      3. If `for_date` is a Saturday and the resolved shift's name doesn't
         already say SATURDAY, look for a sibling shift named
         "<same area> ... SATURDAY" — sql/003_attendance_info_seed.sql
         models weekday vs Saturday hours as separate rows per area
         (e.g. "OFFICE - WEEKDAY (9:00-6:00)" / "OFFICE - SATURDAY").
         Best-effort match; falls back to the weekday shift's own hours
         if no Saturday sibling is found. Schema note: shift assignment
         isn't day-of-week aware, so this is a naming-convention-based
         heuristic, not a first-class model — flagged in REFACTOR_NOTES.
      4. Step 3 only applies if this employee actually works Saturdays,
         per employees.works_saturday (set via the Create/Edit User
         form's Saturday Yes/No toggle) — a column deliberately separate
         from employees.working_days_per_week, which is a payroll-only
         figure (Unpaid Leave deduction denominator) with no defined
         relationship to Saturday shift hours in the source Leave Info
         doc. works_saturday == False means this employee is off on
         Saturdays regardless of their department's area schedule, so we
         deliberately skip the SATURDAY sibling lookup below and return
         None instead of silently applying the area's Saturday hours to
         everyone.
    """

    shift = None

    try:
        history = (
            supabase_admin.table("employee_shift_history")
            .select("effective_from, effective_to, shifts(*)")
            .eq("employee_id", employee_id)
            .lte("effective_from", for_date.isoformat())
            .order("effective_from", desc=True)
            .execute()
        )

        for row in history.data or []:
            effective_to = row.get("effective_to")
            if not effective_to or effective_to >= for_date.isoformat():
                shift = row.get("shifts")
                break
    except Exception as e:
        logger.error(f"Failed to fetch employee_shift_history for {employee_id}: {e}")

    works_saturday = False
    if not shift:
        try:
            employee = (
                supabase_admin.table("employees")
                .select("shift_id, works_saturday, shifts(*)")
                .eq("id", employee_id)
                .maybe_single()
                .execute()
            )
            if employee and employee.data:
                shift = employee.data.get("shifts")
                works_saturday = bool(employee.data.get("works_saturday"))
        except Exception as e:
            logger.error(f"Failed to fetch default shift for {employee_id}: {e}")
    else:
        try:
            employee = (
                supabase_admin.table("employees")
                .select("works_saturday")
                .eq("id", employee_id)
                .maybe_single()
                .execute()
            )
            if employee and employee.data:
                works_saturday = bool(employee.data.get("works_saturday"))
        except Exception as e:
            logger.error(f"Failed to fetch works_saturday for {employee_id}: {e}")

    if not shift:
        return None

    if for_date.weekday() == 5 and not works_saturday:
        return None

    if (
        for_date.weekday() == 5
        and "SATURDAY" not in (shift.get("shift_name") or "").upper()
    ):
        try:
            area = shift["shift_name"].split(" - ")[0].strip()
            saturday_shift = (
                supabase_admin.table("shifts")
                .select("*")
                .ilike("shift_name", f"{area}%SATURDAY%")
                .limit(1)
                .execute()
            )
            if saturday_shift.data:
                shift = saturday_shift.data[0]
        except Exception as e:
            logger.error(f"Failed to resolve Saturday shift variant: {e}")

    return shift


def _late_minutes(
    check_in_time: datetime,
    for_date: date,
    shift: Optional[dict],
    rule: dict,
    tz: ZoneInfo = IST,
) -> int:
    """
    `check_in_time` is UTC (see `_now_utc()`). `shift["start_time"]` is
    authored in the company's configured local wall-clock (`tz` — resolved
    by `_get_company_timezone()` from `settings.timezone`, e.g. "09:00:00"
    means 9 AM in Singapore for a company set to Asia/Singapore), so it has
    to be localized to `tz` and converted to UTC before comparing —
    comparing it directly against a UTC check_in_time (as if "09:00" were
    already UTC) is off by exactly `tz`'s offset, which is what made
    genuinely-late check-ins show as only a few minutes late (or on-time
    check-ins show as hours late, for offices outside India). `tz` defaults
    to IST only so any other lingering caller of this helper keeps its
    previous behavior — callers wired up to Settings should always pass
    `_get_company_timezone()` explicitly.
    """
    if not shift or not shift.get("start_time"):
        return 0

    hh, mm, *_ = str(shift["start_time"]).split(":")
    scheduled_start_local = datetime.combine(
        for_date, time(int(hh), int(mm)), tzinfo=tz
    )
    scheduled_start = scheduled_start_local.astimezone(timezone.utc).replace(
        tzinfo=None
    )

    grace = shift.get("grace_period")
    if grace is None:
        grace = rule.get("late_grace_minutes", 0)

    diff_minutes = (check_in_time - scheduled_start).total_seconds() / 60

    return int(diff_minutes - grace) if diff_minutes > grace else 0


def _minimum_work_minutes(shift: Optional[dict], rule: dict) -> int:
    if shift and shift.get("working_hours"):
        return int(float(shift["working_hours"]) * 60)
    return rule.get("minimum_work_minutes") or 480


def _haversine_meters(lat1, lon1, lat2, lon2) -> float:
    r_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r_km * math.asin(math.sqrt(a)) * 1000


def _format_duration_minutes(minutes) -> str:
    """
    "240" -> "4h", "70" -> "1h 10m", "45" -> "45m" — used for the audit-log
    descriptions that Recent Activity displays (late check-ins, site-visit
    durations), so the UI never has to show a raw "240 min" count. Mirrors
    formatMinutes()/formatDuration() on the frontend (Dashboard.jsx,
    SiteVisitCard.jsx) so the wording matches wherever it's rendered.
    """
    total = max(0, round(minutes or 0))
    h, m = divmod(total, 60)
    if h == 0:
        return f"{m}m"
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"


def _validate_geofence(
    location_id: Optional[str], latitude: Optional[float], longitude: Optional[float]
):
    """
    Real, DB-driven geofence check — nothing here is hardcoded. It looks up
    the given location_id's lat/long/radius from the `locations` table at
    call time, so if a site's coordinates or radius change in the DB, this
    always uses the current values. Used by site visits (arrive_at_site),
    where staying within a client site's configured radius still matters.

    check_in intentionally does NOT call this (see check_in below) — daily
    attendance check-in is allowed from wherever the employee actually is.
    """
    if not location_id or latitude is None or longitude is None:
        return

    location = (
        supabase_admin.table("locations")
        .select("*")
        .eq("id", location_id)
        .maybe_single()
        .execute()
    )

    if not location or not location.data:
        bad_request("Invalid location_id.")

    loc = location.data

    if (
        loc.get("latitude") is None
        or loc.get("longitude") is None
        or not loc.get("radius")
    ):
        return  # location has no geofence configured — nothing to enforce

    distance_m = _haversine_meters(
        latitude, longitude, loc["latitude"], loc["longitude"]
    )

    if distance_m > loc["radius"]:
        bad_request(
            f"You are {int(distance_m)}m from {loc.get('location_name', 'the check-in location')}, "
            f"outside the allowed {loc['radius']}m radius."
        )


def _get_active_assigned_location_ids(employee_id: str) -> list[str]:
    """
    Site(s) this employee's manager has explicitly assigned them to — see
    app/site_assignments/services.py. An empty list means nobody has
    configured an assignment for this employee yet, so check-in /
    site-visit falls back to the old "any configured company location"
    behaviour (additive, not a breaking change).
    """
    response = (
        supabase_admin.table("employee_site_assignments")
        .select("location_id")
        .eq("employee_id", employee_id)
        .eq("is_active", True)
        .execute()
    )

    return [
        row["location_id"] for row in (response.data or []) if row.get("location_id")
    ]


def _enforce_assigned_site(employee_id: str, location_id: Optional[str], action: str):
    """
    The location_id sent on site-visit arrival MUST be one of the
    employee's manager-assigned sites. Raises 400 if none are assigned
    at all (previously this was a no-op, which let anyone with zero
    assignments log a visit to *any* company location — the backend
    counterpart of the "shows every site" bug in SiteVisitCard.jsx),
    and raises 400 if the given location isn't one of the assigned ones.
    """
    assigned_ids = _get_active_assigned_location_ids(employee_id)

    if not assigned_ids:
        bad_request(
            "You don't have any site assigned yet. Ask your manager to "
            "assign you a site before logging a visit."
        )

    if not location_id or location_id not in assigned_ids:
        bad_request(
            f"You can only {action} from the site your manager assigned you to."
        )


def _resolve_location_name(location_id: Optional[str]) -> Optional[str]:
    """
    Looks up `locations.location_name` for the location_id the client
    matched client-side (see CheckInOutCard.jsx's nearest-office logic).
    Used so Recent Activity / audit log descriptions can say *where* a
    check-in happened ("Checked in — 37m late — at Main Office") instead
    of just the late-duration, which is all the description carried
    before. Best-effort: returns None (and the caller just omits the
    location clause) if location_id is missing or the lookup fails —
    never blocks the check-in itself.
    """
    if not location_id:
        return None
    try:
        location = (
            supabase_admin.table("locations")
            .select("location_name")
            .eq("id", location_id)
            .maybe_single()
            .execute()
        )
        if location and location.data:
            return location.data.get("location_name")
    except Exception as e:
        logger.error(f"Failed to resolve location name for {location_id}: {e}")
    return None


# ==========================================================================
# CHECK IN / CHECK OUT (self-service)
# ==========================================================================


def check_in(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        today = date.today()

        if attendance_repo.find_one(
            {"employee_id": employee_id, "attendance_date": today.isoformat()}
        ):
            bad_request("You have already checked in today.")

        # Daily attendance check-in is intentionally NOT restricted to a
        # manager-assigned site — "did you show up for work today" can
        # happen from any configured company location. It also does NOT
        # enforce the geofence (unlike Site Visits / arrive_at_site below,
        # which still calls _validate_geofence) — check-in is allowed from
        # wherever the employee actually is. We still store the real GPS
        # fix (data.latitude/data.longitude) on the attendance row below,
        # so there's an honest record of where the check-in happened.

        check_in_time = _now_utc()
        shift = _get_employee_shift(employee_id, today)
        rule = _get_attendance_rule()
        company_tz = _get_company_timezone()
        late_minutes = _late_minutes(check_in_time, today, shift, rule, tz=company_tz)

        payload = {
            "employee_id": employee_id,
            "attendance_date": today.isoformat(),
            "check_in_time": check_in_time.isoformat(),
            "late_minutes": late_minutes,
            "status": "Present",
            "check_in_latitude": data.latitude,
            "check_in_longitude": data.longitude,
        }

        if request is not None:
            # See app/core/request_ip.py -- reads X-Forwarded-For first so
            # this logs the employee's real IP instead of the Vercel
            # proxy's, when the frontend is proxied (vercel.json).
            payload["ip_address"] = get_client_ip(request)
            payload["device_info"] = request.headers.get("user-agent")

        attendance_data = attendance_repo.create(payload)

        # Notify every SUPER ADMIN on every check-in (not managers — this
        # is deliberately scoped narrower than the leave-request fan-out
        # in app/leaves/services.apply_leave, since a per-employee ping
        # to every manager on every check-in would be noisy; Super Admin
        # is the role that owns attendance policy company-wide). Used to
        # only fire this for *late* check-ins, which meant an on-time
        # check-in never created a notification at all — nothing for the
        # Super Admin dashboard's toast poller (GET /notifications/my in
        # Header.jsx) to ever pick up. Now it always notifies, just with
        # a different title/message for late vs. on-time.
        # Best-effort: notify_employee() swallows its own errors and a
        # failed lookup here never blocks the check-in itself.
        try:
            employee = (
                supabase_admin.table("employees")
                .select("employee_id, full_name")
                .eq("id", employee_id)
                .maybe_single()
                .execute()
            )
            emp = employee.data if employee else None
            employee_code = (emp or {}).get("employee_id", "—")
            employee_name = (emp or {}).get("full_name", "An employee")

            if late_minutes > 0:
                notify_title = "Late Check-In"
                notify_message = (
                    f"{employee_name} (ID: {employee_code}) checked in "
                    f"{_format_duration_minutes(late_minutes)} late today."
                )
            else:
                notify_title = "Check-In"
                notify_message = (
                    f"{employee_name} (ID: {employee_code}) checked in "
                    f"on time today."
                )

            for recipient_id in get_employee_ids_for_role(ADMIN):
                if recipient_id == employee_id:
                    continue  # don't ping a Super Admin about their own check-in
                notify_employee(
                    recipient_id,
                    title=notify_title,
                    message=notify_message,
                    notification_type="ATTENDANCE",
                )
        except Exception as e:
            logger.error(f"Failed to send check-in notification: {e}")

        location_name = _resolve_location_name(data.location_id)

        record_audit_log(
            module="ATTENDANCE",
            action="CHECK_IN",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=attendance_data.get("id"),
            description="Checked in"
            + (
                f" — {_format_duration_minutes(late_minutes)} late"
                if late_minutes
                else ""
            )
            + (f" — at {location_name}" if location_name else ""),
            new_values=attendance_data,
            request=request,
        )

        realtime.broadcast_threadsafe(
            {
                "type": "attendance_event",
                "action": "check_in",
                "employee_id": employee_id,
            }
        )

        return success_response(
            message="Checked in successfully.", data=attendance_data
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to check in.")


def check_out(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        today = date.today()

        existing = attendance_repo.find_one(
            {"employee_id": employee_id, "attendance_date": today.isoformat()}
        )

        if not existing:
            bad_request("You haven't checked in today.")

        if existing.get("check_out_time"):
            bad_request("You have already checked out today.")

        check_in_time = datetime.fromisoformat(existing["check_in_time"])
        check_out_time = _now_utc()

        breaks_resp = (
            supabase_admin.table("attendance_breaks")
            .select("break_minutes")
            .eq("attendance_id", existing["id"])
            .execute()
        )
        total_break_minutes = sum(
            (b.get("break_minutes") or 0) for b in (breaks_resp.data or [])
        )

        gross_minutes = int((check_out_time - check_in_time).total_seconds() / 60)
        working_minutes = max(0, gross_minutes - total_break_minutes)

        # Safety net: if a field-staff employee forgot to log "Departed
        # Site" for the last location, close it out now rather than
        # leaving it open forever.
        _close_open_site_visit(
            existing["id"], check_out_time, data.latitude, data.longitude
        )

        shift = _get_employee_shift(employee_id, today)
        rule = _get_attendance_rule()
        minimum_work_minutes = _minimum_work_minutes(shift, rule)
        overtime_after_minutes = (
            rule.get("overtime_after_minutes") or minimum_work_minutes
        )

        early_checkout_minutes = max(0, minimum_work_minutes - working_minutes)
        overtime_minutes = max(0, working_minutes - overtime_after_minutes)
        status = (
            "Half Day" if working_minutes < (minimum_work_minutes / 2) else "Present"
        )

        updated = attendance_repo.update(
            existing["id"],
            {
                "check_out_time": check_out_time.isoformat(),
                "break_minutes": total_break_minutes,
                "working_minutes": working_minutes,
                "early_checkout_minutes": early_checkout_minutes,
                "overtime_minutes": overtime_minutes,
                "status": status,
                "check_out_latitude": data.latitude,
                "check_out_longitude": data.longitude,
            },
        )

        location_name = _resolve_location_name(data.location_id)

        record_audit_log(
            module="ATTENDANCE",
            action="CHECK_OUT",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=existing["id"],
            description=f"Checked out — {_format_duration_minutes(working_minutes)} worked, status: {status}"
            + (f" — at {location_name}" if location_name else ""),
            old_values=existing,
            new_values=updated,
            request=request,
        )

        realtime.broadcast_threadsafe(
            {
                "type": "attendance_event",
                "action": "check_out",
                "employee_id": employee_id,
            }
        )

        return success_response(message="Checked out successfully.", data=updated)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to check out.")


# ==========================================================================
# ATTENDANCE REMINDER (self-service "have I forgotten to check in?" check)
# ==========================================================================


def get_attendance_reminder_status(auth_user_id: str):
    """
    Self-service "have I forgotten to check in?" check.

    There's no background job scheduler anywhere in this backend (no
    APScheduler/celery/cron), so this can't run on its own at shift-start
    time the way a real reminder system would. Instead, Header.jsx polls
    this endpoint every few minutes while an employee is logged in (see
    the periodic call added next to NotificationBell's existing 20s
    /notifications/my poll) -- that's already the same "only works while
    a session is open" constraint the rest of this app's live-notification
    system runs under, so it's not adding a new limitation, just applying
    the existing one here too.

    Uses the exact same shift-resolution and late-minutes rules check_in()
    uses (_get_employee_shift / _get_attendance_rule, IST-aware), so
    "shift start" here always agrees with what a check-in would have been
    scored against. Writes ONE "ATTENDANCE_REMINDER" notification via
    notify_employee() once the employee is confirmed late-and-unchecked-in
    -- deduped per employee per day so a person who leaves the tab open
    doesn't get re-reminded every single poll. The existing NotificationBell
    poll then picks that row up and surfaces it as a toast (+ sound +
    browser notification if the tab isn't focused) within ~20s, same as
    any other notification -- no separate delivery path was needed.

    Silently no-ops (reminder_due: False) whenever: the "Attendance
    reminders" preference is off (or never set -- defaults to off), there's
    no resolved shift for today, today is a weekly off, the employee has
    already checked in, they're on approved leave, or a reminder already
    went out today. Never raises -- a broken check here should never
    surface as an error to a page that's just polling in the background.
    """
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            return success_response(
                message="No reminder due.", data={"reminder_due": False}
            )

        pref = (
            supabase_admin.table("notification_preferences")
            .select("attendance_reminders")
            .eq("employee_id", employee_id)
            .maybe_single()
            .execute()
        )
        # No row yet -- matches notification_preferences DEFAULTS
        # (attendance_reminders: False) until the employee opts in via
        # Settings -> Notifications -> Save preferences.
        if not pref or not pref.data or not pref.data.get("attendance_reminders"):
            return success_response(
                message="No reminder due.", data={"reminder_due": False}
            )

        today = date.today()

        # Sunday is the one day get_team_attendance_report() etc. treat as
        # a fixed weekly off company-wide; Saturday is handled inside
        # _get_employee_shift (falls back to a SATURDAY-named shift
        # variant, or the weekday shift's own hours if none exists).
        if today.weekday() == 6:
            return success_response(
                message="No reminder due.", data={"reminder_due": False}
            )

        rule = _get_attendance_rule()
        shift = _get_employee_shift(employee_id, today)
        if not shift or not shift.get("start_time"):
            return success_response(
                message="No reminder due.", data={"reminder_due": False}
            )

        hh, mm, *_ = str(shift["start_time"]).split(":")
        company_tz = _get_company_timezone()
        scheduled_start_local = datetime.combine(
            today, time(int(hh), int(mm)), tzinfo=company_tz
        )
        scheduled_start = scheduled_start_local.astimezone(timezone.utc).replace(
            tzinfo=None
        )

        grace = shift.get("grace_period")
        if grace is None:
            grace = rule.get("late_grace_minutes", 0)

        if _now_utc() < scheduled_start + timedelta(minutes=grace):
            return success_response(
                message="No reminder due.", data={"reminder_due": False}
            )

        already_checked_in = (
            supabase_admin.table("attendance")
            .select("id")
            .eq("employee_id", employee_id)
            .eq("attendance_date", today.isoformat())
            .maybe_single()
            .execute()
        )
        if already_checked_in and already_checked_in.data:
            return success_response(
                message="No reminder due.", data={"reminder_due": False}
            )

        on_leave = (
            supabase_admin.table("leave_requests")
            .select("id")
            .eq("employee_id", employee_id)
            .eq("status", "Approved")
            .lte("start_date", today.isoformat())
            .gte("end_date", today.isoformat())
            .limit(1)
            .execute()
        )
        if on_leave and on_leave.data:
            return success_response(
                message="No reminder due.", data={"reminder_due": False}
            )

        day_start = datetime.combine(today, time(0, 0)).isoformat()
        already_reminded = (
            supabase_admin.table("notifications")
            .select("id")
            .eq("user_id", employee_id)
            .eq("notification_type", "ATTENDANCE_REMINDER")
            .gte("created_at", day_start)
            .limit(1)
            .execute()
        )
        if already_reminded and already_reminded.data:
            return success_response(
                message="No reminder due.", data={"reminder_due": False}
            )

        shift_start_label = scheduled_start_ist.strftime("%I:%M %p").lstrip("0")

        notify_employee(
            employee_id,
            title="Attendance reminder",
            message=(
                f"You haven't checked in yet — your shift started at "
                f"{shift_start_label}."
            ),
            notification_type="ATTENDANCE_REMINDER",
        )

        return success_response(
            message="Reminder sent.",
            data={"reminder_due": True, "shift_start": shift_start_label},
        )

    except Exception as e:
        # Best-effort background check -- never let this bubble up as a
        # 500 to a page that's just polling.
        logger.error(f"Attendance reminder check failed for {auth_user_id}: {e}")
        return success_response(
            message="No reminder due.", data={"reminder_due": False}
        )


# ==========================================================================
# BREAKS (multiple breaks per day)
# ==========================================================================


def start_break(auth_user_id: str, request: Optional[Request] = None):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        today = date.today()
        attendance = attendance_repo.find_one(
            {"employee_id": employee_id, "attendance_date": today.isoformat()}
        )

        if not attendance:
            bad_request("You need to check in before starting a break.")

        if attendance.get("check_out_time"):
            bad_request("You have already checked out today.")

        open_break = (
            supabase_admin.table("attendance_breaks")
            .select("id")
            .eq("attendance_id", attendance["id"])
            .is_("break_end", "null")
            .execute()
        )

        if open_break.data:
            bad_request("A break is already in progress.")

        inserted = (
            supabase_admin.table("attendance_breaks")
            .insert(
                {
                    "attendance_id": attendance["id"],
                    "break_start": _now_utc().isoformat(),
                }
            )
            .execute()
        )
        record = inserted.data[0] if inserted.data else None

        record_audit_log(
            module="ATTENDANCE",
            action="BREAK_START",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=attendance["id"],
            description="Break started",
            request=request,
        )

        realtime.broadcast_threadsafe(
            {
                "type": "attendance_event",
                "action": "break_start",
                "employee_id": employee_id,
            }
        )

        return success_response(message="Break started.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to start break.")


def end_break(auth_user_id: str, request: Optional[Request] = None):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        today = date.today()
        attendance = attendance_repo.find_one(
            {"employee_id": employee_id, "attendance_date": today.isoformat()}
        )

        if not attendance:
            bad_request("You haven't checked in today.")

        open_break = (
            supabase_admin.table("attendance_breaks")
            .select("*")
            .eq("attendance_id", attendance["id"])
            .is_("break_end", "null")
            .order("break_start", desc=True)
            .limit(1)
            .execute()
        )

        if not open_break.data:
            bad_request("No break is currently in progress.")

        break_row = open_break.data[0]
        break_start = datetime.fromisoformat(break_row["break_start"])
        break_end = _now_utc()
        break_minutes = int((break_end - break_start).total_seconds() / 60)

        updated_break = (
            supabase_admin.table("attendance_breaks")
            .update(
                {"break_end": break_end.isoformat(), "break_minutes": break_minutes}
            )
            .eq("id", break_row["id"])
            .execute()
        )

        totals_resp = (
            supabase_admin.table("attendance_breaks")
            .select("break_minutes")
            .eq("attendance_id", attendance["id"])
            .execute()
        )
        total_break_minutes = sum(
            (b.get("break_minutes") or 0) for b in (totals_resp.data or [])
        )

        attendance_repo.update(attendance["id"], {"break_minutes": total_break_minutes})

        record_audit_log(
            module="ATTENDANCE",
            action="BREAK_END",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=attendance["id"],
            description=f"Break ended — {_format_duration_minutes(break_minutes)}",
            request=request,
        )

        realtime.broadcast_threadsafe(
            {
                "type": "attendance_event",
                "action": "break_end",
                "employee_id": employee_id,
            }
        )

        record = updated_break.data[0] if updated_break.data else None
        return success_response(message="Break ended.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to end break.")


# ==========================================================================
# SITE VISITS — multiple locations in one day (Inspection / Operation
# field staff). The day's total working_minutes/late/overtime still come
# from check_in_time -> check_out_time on `attendance` exactly as before;
# this is an additive breakdown of *where* that time was spent.
# ==========================================================================

SITE_VISIT_SELECT = "*, locations(id, location_name, location_code, address)"


def _get_open_attendance_or_400(employee_id: str) -> dict:
    today = date.today()
    attendance = attendance_repo.find_one(
        {"employee_id": employee_id, "attendance_date": today.isoformat()}
    )

    if not attendance:
        bad_request("You need to check in for the day before logging a site visit.")

    if attendance.get("check_out_time"):
        bad_request("You have already checked out today.")

    return attendance


def _close_open_site_visit(
    attendance_id: str, at_time: datetime, latitude=None, longitude=None
):
    """
    Closes whichever site-visit row (if any) is still open for this
    attendance day — used both when arriving at the *next* site (leaving
    the previous one implicitly) and as a safety net on day check-out, so
    a forgotten "depart" never leaves a visit open forever.
    """
    open_visit = (
        supabase_admin.table("attendance_site_visits")
        .select("*")
        .eq("attendance_id", attendance_id)
        .is_("departure_time", "null")
        .order("arrival_time", desc=True)
        .limit(1)
        .execute()
    )

    if not open_visit.data:
        return None

    visit = open_visit.data[0]
    arrival = datetime.fromisoformat(visit["arrival_time"])
    duration_minutes = max(0, int((at_time - arrival).total_seconds() / 60))

    updated = (
        supabase_admin.table("attendance_site_visits")
        .update(
            {
                "departure_time": at_time.isoformat(),
                "duration_minutes": duration_minutes,
                "departure_latitude": latitude,
                "departure_longitude": longitude,
                "updated_at": _now_utc().isoformat(),
            }
        )
        .eq("id", visit["id"])
        .execute()
    )

    return updated.data[0] if updated.data else None


def arrive_at_site(auth_user_id: str, data, request: Optional[Request] = None):
    """
    "Arrived at Site" — one button for field staff. If they were already
    logged in at a different site today, that visit is auto-closed with
    departure_time = now (arriving somewhere new implies leaving the last
    place), so an inspector doing 3 sites in a day just taps this each
    time they move, without a separate "depart" step in between.
    """
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        attendance = _get_open_attendance_or_400(employee_id)

        _enforce_assigned_site(employee_id, data.location_id, action="log a site visit")

        _validate_geofence(data.location_id, data.latitude, data.longitude)

        arrival_time = _now_utc()

        # Leaving the previous site, if one is still open.
        _close_open_site_visit(
            attendance["id"], arrival_time, data.latitude, data.longitude
        )

        inserted = (
            supabase_admin.table("attendance_site_visits")
            .insert(
                {
                    "attendance_id": attendance["id"],
                    "employee_id": employee_id,
                    "location_id": data.location_id,
                    "arrival_time": arrival_time.isoformat(),
                    "arrival_latitude": data.latitude,
                    "arrival_longitude": data.longitude,
                    "notes": data.notes,
                }
            )
            .execute()
        )
        record = inserted.data[0] if inserted.data else None

        # Look up the site's name for the audit-log description — Recent
        # Activity renders this description as-is, and a raw location_id
        # UUID there is meaningless to whoever's reading it. Falls back to
        # the id only if the lookup itself fails, so a broken join never
        # blocks the arrival being logged.
        site_name = data.location_id
        try:
            site_row = (
                supabase_admin.table("locations")
                .select("location_name")
                .eq("id", data.location_id)
                .maybe_single()
                .execute()
            )
            site_name = (site_row.data or {}).get("location_name", data.location_id)
        except Exception:
            pass

        record_audit_log(
            module="ATTENDANCE",
            action="SITE_VISIT_ARRIVE",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=attendance["id"],
            description=f"Arrived at site {site_name}",
            request=request,
        )

        return success_response(message="Arrival logged.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to log site arrival.")


def depart_site(auth_user_id: str, data, request: Optional[Request] = None):
    """Explicit "Departed Site" for the last site of the day (no next arrival to imply it)."""
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        attendance = _get_open_attendance_or_400(employee_id)

        record = _close_open_site_visit(
            attendance["id"], _now_utc(), data.latitude, data.longitude
        )

        if not record:
            bad_request("You haven't logged an arrival at any site yet today.")

        if data.notes:
            supabase_admin.table("attendance_site_visits").update(
                {"notes": data.notes}
            ).eq("id", record["id"]).execute()

        record_audit_log(
            module="ATTENDANCE",
            action="SITE_VISIT_DEPART",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=attendance["id"],
            description=(
                f"Departed site — "
                f"{_format_duration_minutes(record.get('duration_minutes'))} on site"
            ),
            request=request,
        )

        return success_response(message="Departure logged.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to log site departure.")


# ==========================================================================
# AD-HOC OUTDOOR / MEETING CHECK-IN
# ==========================================================================
# For employees who are NOT pre-assigned to any site (Account, HR,
# Logistics, etc.) but occasionally go straight to a client meeting or
# site survey. Gated per-employee (employees.outdoor_checkin_enabled,
# default false — sql/030.sql) rather than by role/department: most
# employees in every department never need this, so it must stay
# invisible for everyone until HR turns it on for a specific person.
# No location_id — these places aren't in the `locations` master list —
# so we log raw GPS + a free-text purpose/address instead.


def _require_outdoor_checkin_enabled(employee_id: str):
    employee = (
        supabase_admin.table("employees")
        .select("outdoor_checkin_enabled")
        .eq("id", employee_id)
        .maybe_single()
        .execute()
    )

    if not employee.data or not employee.data.get("outdoor_checkin_enabled"):
        forbidden(
            "Outdoor check-in isn't enabled for your account. Ask HR to enable it if you need it."
        )


def arrive_at_outdoor_visit(auth_user_id: str, data, request: Optional[Request] = None):
    """
    "Checking in from a meeting/site" — the ad-hoc equivalent of
    arrive_at_site(), for employees with no fixed site assignment. Same
    auto-close-previous-visit behaviour as arrive_at_site, so someone
    who goes from one meeting straight to another doesn't need a
    separate depart step in between.
    """
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        _require_outdoor_checkin_enabled(employee_id)

        attendance = _get_open_attendance_or_400(employee_id)

        arrival_time = _now_utc()

        _close_open_outdoor_visit(attendance["id"], arrival_time)

        inserted = (
            supabase_admin.table("attendance_outdoor_visits")
            .insert(
                {
                    "attendance_id": attendance["id"],
                    "employee_id": employee_id,
                    "purpose": data.purpose,
                    "address_text": data.address_text,
                    "arrival_time": arrival_time.isoformat(),
                    "arrival_latitude": data.latitude,
                    "arrival_longitude": data.longitude,
                    "notes": data.notes,
                }
            )
            .execute()
        )
        record = inserted.data[0] if inserted.data else None

        record_audit_log(
            module="ATTENDANCE",
            action="OUTDOOR_VISIT_ARRIVE",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=attendance["id"],
            description=f"Checked in from outside office{f' — {data.purpose}' if data.purpose else ''}",
            request=request,
        )

        return success_response(message="Outdoor check-in logged.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to log outdoor check-in.")


def depart_outdoor_visit(auth_user_id: str, data, request: Optional[Request] = None):
    """Explicit "Back to normal" / "Done" for the last open outdoor visit of the day."""
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        attendance = _get_open_attendance_or_400(employee_id)

        record = _close_open_outdoor_visit(
            attendance["id"], _now_utc(), data.latitude, data.longitude
        )

        if not record:
            bad_request("You don't have an open outdoor check-in today.")

        if data.notes:
            supabase_admin.table("attendance_outdoor_visits").update(
                {"notes": data.notes}
            ).eq("id", record["id"]).execute()

        record_audit_log(
            module="ATTENDANCE",
            action="OUTDOOR_VISIT_DEPART",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=attendance["id"],
            description=(
                f"Ended outdoor check-in — "
                f"{_format_duration_minutes(record.get('duration_minutes'))}"
            ),
            request=request,
        )

        return success_response(message="Outdoor check-in ended.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to end outdoor check-in.")


def _close_open_outdoor_visit(
    attendance_id: str, at_time: datetime, latitude=None, longitude=None
):
    open_visit = (
        supabase_admin.table("attendance_outdoor_visits")
        .select("*")
        .eq("attendance_id", attendance_id)
        .is_("departure_time", "null")
        .order("arrival_time", desc=True)
        .limit(1)
        .execute()
    )

    if not open_visit.data:
        return None

    visit = open_visit.data[0]
    arrival = datetime.fromisoformat(visit["arrival_time"])
    duration_minutes = max(0, int((at_time - arrival).total_seconds() / 60))

    updated = (
        supabase_admin.table("attendance_outdoor_visits")
        .update(
            {
                "departure_time": at_time.isoformat(),
                "duration_minutes": duration_minutes,
                "departure_latitude": latitude,
                "departure_longitude": longitude,
                "updated_at": _now_utc().isoformat(),
            }
        )
        .eq("id", visit["id"])
        .execute()
    )

    return updated.data[0] if updated.data else None


def get_my_outdoor_visits_today(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            return success_response(message="No employee profile linked.", data=[])

        today = date.today()
        attendance = attendance_repo.find_one(
            {"employee_id": employee_id, "attendance_date": today.isoformat()}
        )
        if not attendance:
            return success_response(message="No attendance today.", data=[])

        response = (
            supabase_admin.table("attendance_outdoor_visits")
            .select("*")
            .eq("attendance_id", attendance["id"])
            .order("arrival_time")
            .execute()
        )

        return success_response(
            message="Today's outdoor check-ins fetched.", data=response.data or []
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch outdoor check-ins.")


# How far (in meters) an open site visit's live ping can drift from the
# site's configured lat/lon before it's flagged as "left the site" and a
# manager/super-admin notification fires. Deliberately separate from a
# location's own `radius` (used by _validate_geofence at check-in time,
# and typically tighter — e.g. 300m for "were you here when you arrived")
# — this is a looser "did they wander off after arriving" threshold.
ALERT_RADIUS_M = 500


def ping_site_visit(auth_user_id: str, data, request: Optional[Request] = None):
    """
    Live presence check for an open site visit — called every ~60s by the
    frontend (see SiteVisitCard.jsx) while the employee has an active
    "Arrived" with no "Departed" yet. Records where they are right now,
    and — the first time a ping lands more than ALERT_RADIUS_M from the
    site — notifies their manager and every SUPER ADMIN with the
    distance, so someone can act instead of the app silently keeping a
    stale "on site" status all day.

    Deliberately quiet (no error) if there's no open visit right now —
    the frontend only calls this while it believes one is open, but a
    race (e.g. they just tapped Departed on another tab) shouldn't spam
    an error toast every minute.
    """
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            return success_response(message="No employee profile linked.", data=None)

        open_visit = (
            supabase_admin.table("attendance_site_visits")
            .select("*, locations(location_name, latitude, longitude)")
            .eq("employee_id", employee_id)
            .is_("departure_time", "null")
            .order("arrival_time", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        visit = open_visit.data if open_visit else None
        if not visit:
            return success_response(message="No open site visit.", data=None)

        loc = visit.get("locations") or {}
        site_lat, site_lng = loc.get("latitude"), loc.get("longitude")

        update_payload = {
            "last_ping_latitude": data.latitude,
            "last_ping_longitude": data.longitude,
            "last_ping_at": _now_utc().isoformat(),
        }

        distance_m = None
        was_outside = bool(visit.get("is_outside_radius"))
        is_now_outside = False

        if site_lat is not None and site_lng is not None:
            distance_m = _haversine_meters(
                data.latitude, data.longitude, site_lat, site_lng
            )
            is_now_outside = distance_m > ALERT_RADIUS_M
            update_payload["last_ping_distance_m"] = distance_m
            update_payload["is_outside_radius"] = is_now_outside

        supabase_admin.table("attendance_site_visits").update(update_payload).eq(
            "id", visit["id"]
        ).execute()

        # Edge-triggered: only notify the moment this flips from inside to
        # outside range, not on every ping while it stays outside — and
        # not on the way back in (a returning-then-leaving-again employee
        # will re-trigger it, since is_now_outside just went False then
        # will go True again on a later ping).
        if is_now_outside and not was_outside:
            employee = (
                supabase_admin.table("employees")
                .select("full_name, manager_id")
                .eq("id", employee_id)
                .maybe_single()
                .execute()
            )
            employee_data = employee.data if employee else None
            employee_name = (employee_data or {}).get("full_name", "An employee")
            manager_id = (employee_data or {}).get("manager_id")
            site_name = loc.get("location_name", "the site")

            message = (
                f"{employee_name} has moved {int(distance_m)}m away from "
                f"{site_name} (allowed {ALERT_RADIUS_M}m) while still marked "
                "on site."
            )

            recipient_ids = set(get_employee_ids_for_role(ADMIN))
            if manager_id:
                recipient_ids.add(manager_id)
            recipient_ids.discard(employee_id)

            for recipient_id in recipient_ids:
                notify_employee(
                    recipient_id,
                    title="Employee left site area",
                    message=message,
                    notification_type="ATTENDANCE",
                )

            record_audit_log(
                module="ATTENDANCE",
                action="SITE_VISIT_OUT_OF_RANGE",
                performed_by=auth_user_id,
                target_employee_id=employee_id,
                record_id=visit["id"],
                description=message,
                request=request,
            )

        return success_response(
            message="Presence ping recorded.",
            data={
                "distance_m": distance_m,
                "outside_radius": is_now_outside,
                "alert_radius_m": ALERT_RADIUS_M,
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to record presence ping.")


# ==========================================================================
# SITE VISIT COMPLIANCE (self-service "did I miss an assigned site today?"
# check — same "no background scheduler" constraint as
# get_attendance_reminder_status() above, so this rides along on the
# employee's own open session instead of a real cron job.)
# ==========================================================================


def get_site_visit_compliance_status(auth_user_id: str):
    """
    For the CURRENT employee: looks at every active site assignment that
    covers today (assigned_from <= today <= assigned_to, treating either
    bound as open-ended when null). Once that employee's shift has ended
    for the day (same shift-resolution rules as the attendance reminder —
    _get_employee_shift, IST-aware) and no attendance_site_visits row
    exists for that site today, the assignment counts as "missed":

      - the employee's manager (+ every SUPER ADMIN) gets a one-time
        "Site visit missed" notification, deduped per manager/site/day the
        same way get_attendance_reminder_status dedupes its own reminder
        (a notifications-table lookup instead of a real job-run flag,
        since there's nowhere else to persist that here).
      - the site's id is returned in `missed_site_ids` so the frontend
        (SiteVisitCard) can stop the employee from tapping "Arrived" for
        it for the rest of today — once the manager's been told a visit
        was missed, letting the employee quietly log one after the fact
        would just make that notification wrong.

    Polled by SiteVisitCard on load and every few minutes while it's
    mounted (mirrors the reminder-check poll on Header.jsx) — best-effort
    and silent on any failure, exactly like the reminder check, since a
    broken compliance check should never block the card from rendering.
    """
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            return success_response(
                message="No compliance check due.", data={"missed_site_ids": []}
            )

        today = date.today()

        assignments = (
            supabase_admin.table("employee_site_assignments")
            .select(
                "id, location_id, assigned_from, assigned_to, locations(location_name)"
            )
            .eq("employee_id", employee_id)
            .eq("is_active", True)
            .execute()
        )

        today_iso = today.isoformat()
        covering_today = [
            a
            for a in (assignments.data or [])
            if (not a.get("assigned_from") or a["assigned_from"] <= today_iso)
            and (not a.get("assigned_to") or a["assigned_to"] >= today_iso)
        ]

        if not covering_today:
            return success_response(
                message="No compliance check due.", data={"missed_site_ids": []}
            )

        # Only worth checking once the employee's shift for today is over
        # — flagging a "missed" visit mid-shift would just be wrong (they
        # still have time to go). Same resolution + grace period the
        # attendance reminder above uses.
        rule = _get_attendance_rule()
        shift = _get_employee_shift(employee_id, today)
        if not shift or not shift.get("end_time"):
            return success_response(
                message="No compliance check due.", data={"missed_site_ids": []}
            )

        hh, mm, *_ = str(shift["end_time"]).split(":")
        company_tz = _get_company_timezone()
        scheduled_end_local = datetime.combine(
            today, time(int(hh), int(mm)), tzinfo=company_tz
        )
        # Overnight shifts (end_time earlier than start than start_time)
        # roll to the next day, same convention used elsewhere for shift
        # math — otherwise this would fire hours too early for them.
        if shift.get("start_time") and str(shift["end_time"]) < str(
            shift["start_time"]
        ):
            scheduled_end_local += timedelta(days=1)
        scheduled_end = scheduled_end_local.astimezone(timezone.utc).replace(
            tzinfo=None
        )

        grace = shift.get("grace_period")
        if grace is None:
            grace = rule.get("late_grace_minutes", 0)

        if _now_utc() < scheduled_end + timedelta(minutes=grace):
            return success_response(
                message="No compliance check due.", data={"missed_site_ids": []}
            )

        employee = (
            supabase_admin.table("employees")
            .select("full_name, manager_id")
            .eq("id", employee_id)
            .maybe_single()
            .execute()
        )
        employee_data = (employee.data if employee else None) or {}
        employee_name = employee_data.get("full_name", "An employee")
        manager_id = employee_data.get("manager_id")

        day_start = datetime.combine(today, time(0, 0)).isoformat()
        missed_site_ids = []

        for assignment in covering_today:
            location_id = assignment.get("location_id")
            site_name = (assignment.get("locations") or {}).get(
                "location_name", "the assigned site"
            )

            visited = (
                supabase_admin.table("attendance_site_visits")
                .select("id")
                .eq("employee_id", employee_id)
                .eq("location_id", location_id)
                .gte("arrival_time", day_start)
                .limit(1)
                .execute()
            )
            if visited and visited.data:
                continue

            missed_site_ids.append(location_id)

            already_notified = (
                supabase_admin.table("notifications")
                .select("id")
                .eq("notification_type", "SITE_VISIT_MISSED")
                .gte("created_at", day_start)
                .ilike("message", f"%{employee_name}%{site_name}%")
                .limit(1)
                .execute()
            )
            if already_notified and already_notified.data:
                continue

            message = (
                f"{employee_name} did not visit their assigned site "
                f"{site_name} today."
            )

            recipient_ids = set(get_employee_ids_for_role(ADMIN))
            if manager_id:
                recipient_ids.add(manager_id)
            recipient_ids.discard(employee_id)

            for recipient_id in recipient_ids:
                notify_employee(
                    recipient_id,
                    title="Site visit missed",
                    message=message,
                    notification_type="SITE_VISIT_MISSED",
                )

            record_audit_log(
                module="ATTENDANCE",
                action="SITE_VISIT_MISSED",
                performed_by=auth_user_id,
                target_employee_id=employee_id,
                record_id=assignment.get("id"),
                description=message,
            )

        return success_response(
            message="Compliance check complete.",
            data={"missed_site_ids": missed_site_ids},
        )

    except Exception as e:
        # Best-effort background check — never let this bubble up as a
        # 500 to a page that's just polling.
        logger.error(f"Site visit compliance check failed for {auth_user_id}: {e}")
        return success_response(
            message="No compliance check due.", data={"missed_site_ids": []}
        )


def _effective_visit_minutes(visit: dict) -> int:
    """
    Minutes spent on this visit *as of right now*.

    For a closed visit this is just the stored `duration_minutes`
    (written once, at departure — see _close_open_site_visit). For a
    visit that's still open (no departure_time yet — the employee is
    on site right now), `duration_minutes` is NULL in the DB, so we
    compute the live elapsed time instead of treating it as 0. This is
    also stashed back onto the visit dict as `live_minutes` so any
    caller (e.g. the frontend "23m so far" label) doesn't have to
    redo the same arithmetic.
    """
    if visit.get("departure_time"):
        return visit.get("duration_minutes") or 0

    arrival = datetime.fromisoformat(visit["arrival_time"])
    live_minutes = max(0, int((_now_utc() - arrival).total_seconds() / 60))
    visit["live_minutes"] = live_minutes
    return live_minutes


def get_site_visits_for_attendance(attendance_id: str):
    """
    Full breakdown for one day: every site visited, arrival/departure,
    minutes spent at each, plus a per-location total (in case the same
    site was revisited twice in the day) and travel-between-sites time
    (the gaps between one departure and the next arrival).
    """
    try:
        response = (
            supabase_admin.table("attendance_site_visits")
            .select(SITE_VISIT_SELECT)
            .eq("attendance_id", attendance_id)
            .order("arrival_time", desc=False)
            .execute()
        )
        visits = response.data or []

        totals_by_location: dict = {}
        travel_minutes_total = 0
        previous_departure = None

        for visit in visits:
            loc = visit.get("locations") or {}
            key = loc.get("location_name") or visit.get("location_id") or "Unknown"
            duration = _effective_visit_minutes(visit)
            totals_by_location[key] = totals_by_location.get(key, 0) + duration

            if previous_departure and visit.get("arrival_time"):
                gap = (
                    datetime.fromisoformat(visit["arrival_time"]) - previous_departure
                ).total_seconds() / 60
                travel_minutes_total += max(0, int(gap))

            if visit.get("departure_time"):
                previous_departure = datetime.fromisoformat(visit["departure_time"])
            else:
                previous_departure = None

        return success_response(
            message="Site visits fetched successfully.",
            data={
                "visits": visits,
                "site_count": len(
                    {v.get("location_id") for v in visits if v.get("location_id")}
                ),
                "total_minutes_by_site": totals_by_location,
                "estimated_travel_minutes": travel_minutes_total,
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch site visits.")


def get_my_site_visits_today(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        today = date.today()
        attendance = attendance_repo.find_one(
            {"employee_id": employee_id, "attendance_date": today.isoformat()}
        )

        if not attendance:
            return success_response(
                message="Site visits fetched successfully.",
                data={
                    "visits": [],
                    "site_count": 0,
                    "total_minutes_by_site": {},
                    "estimated_travel_minutes": 0,
                },
            )

        return get_site_visits_for_attendance(attendance["id"])

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch today's site visits.")


# ==========================================================================
# MANAGER — TEAM SITE VISITS (live status + history)
# ==========================================================================


def get_team_site_visits_today(auth_user_id: str):
    """
    One row per report who is field staff (Inspection/Operation
    department — see get_field_employee_ids()), for the manager's "who's
    out on site right now" view:
      - not checked in yet today
      - checked in, no site visit logged yet (e.g. left home, not arrived)
      - currently AT a site (open visit — no departure_time yet)
      - checked out for the day, with a same-day visit summary

    Office staff under the same manager are intentionally left out —
    they get the ordinary Team Attendance table (GET /attendance/team),
    not this one, since "which site are they at" doesn't apply to them.
    """
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not manager_employee_id:
            return success_response(
                message="Team site visits fetched successfully.", data=[]
            )

        report_ids = get_all_report_ids(manager_employee_id)
        field_ids = get_field_employee_ids()
        target_ids = [rid for rid in report_ids if rid in field_ids]

        if not target_ids:
            return success_response(
                message="Team site visits fetched successfully.", data=[]
            )

        today = date.today()

        attendance_rows = (
            supabase_admin.table("attendance")
            .select(
                "id, employee_id, check_in_time, check_out_time, status, employees(employee_id, full_name, profile_photo)"
            )
            .in_("employee_id", target_ids)
            .eq("attendance_date", today.isoformat())
            .execute()
        ).data or []

        attendance_by_employee = {row["employee_id"]: row for row in attendance_rows}
        attendance_ids = [row["id"] for row in attendance_rows]

        visits_by_attendance: dict = {}
        if attendance_ids:
            visit_rows = (
                supabase_admin.table("attendance_site_visits")
                .select(SITE_VISIT_SELECT)
                .in_("attendance_id", attendance_ids)
                .order("arrival_time", desc=False)
                .execute()
            ).data or []
            for v in visit_rows:
                visits_by_attendance.setdefault(v["attendance_id"], []).append(v)

        results = []
        for employee_id in target_ids:
            attendance = attendance_by_employee.get(employee_id)
            employee_info = (attendance or {}).get("employees") or {}
            visits = visits_by_attendance.get((attendance or {}).get("id"), [])
            open_visit = next((v for v in visits if not v.get("departure_time")), None)

            if not attendance:
                live_status = "not_checked_in"
            elif open_visit:
                live_status = "on_site"
            elif attendance.get("check_out_time"):
                live_status = "checked_out"
            else:
                live_status = "checked_in_no_site"

            # Prefer the latest 1-min presence ping over the arrival point
            # frozen at "Arrived" time — that's what actually tells you
            # where they are *right now*, not just where they started.
            current_lat = (open_visit or {}).get("last_ping_latitude") or (
                open_visit or {}
            ).get("arrival_latitude")
            current_lng = (open_visit or {}).get("last_ping_longitude") or (
                open_visit or {}
            ).get("arrival_longitude")

            results.append(
                {
                    "employee_id": employee_id,
                    "employee": employee_info,
                    "live_status": live_status,
                    "current_site": (open_visit or {}).get("locations"),
                    "current_site_since": (open_visit or {}).get("arrival_time"),
                    "current_latitude": current_lat,
                    "current_longitude": current_lng,
                    "last_ping_at": (open_visit or {}).get("last_ping_at"),
                    "last_ping_distance_m": (open_visit or {}).get(
                        "last_ping_distance_m"
                    ),
                    "is_outside_radius": bool(
                        (open_visit or {}).get("is_outside_radius")
                    ),
                    "check_in_time": (attendance or {}).get("check_in_time"),
                    "check_out_time": (attendance or {}).get("check_out_time"),
                    "sites_visited_today": len(
                        {v.get("location_id") for v in visits if v.get("location_id")}
                    ),
                    "visits": visits,
                }
            )

        # On-site first, then checked-in-no-site, then checked-out, then absent.
        order = {
            "on_site": 0,
            "checked_in_no_site": 1,
            "checked_out": 2,
            "not_checked_in": 3,
        }
        results.sort(key=lambda r: order.get(r["live_status"], 9))

        return success_response(
            message="Team site visits fetched successfully.", data=results
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch team site visits.")


def get_org_site_visits_today(auth_user_id: str):
    """
    Company-wide version of get_team_site_visits_today() — every field
    employee (Inspection/Operation) in the organization, not just the
    caller's own reports. Backs the Super Admin / HR "Live Tracking"
    view: gated by VIEW_ALL_ATTENDANCE at the route level (see
    app/attendance/routes.py), the same permission that already governs
    the company-wide attendance list.

    Reuses the exact fields already captured by Arrive/Depart Site
    (arrival/departure latitude+longitude, timestamps) — no new tracking
    data or polling is introduced here. "Live" means "who is currently
    inside an open site visit right now", refreshed by the frontend
    polling this endpoint periodically.

    Only employees who have actually logged a site visit today are
    returned (i.e. at least one arrival recorded) — field staff who
    haven't checked in, or who checked in but haven't arrived at a site
    yet, are left out of this list. Their past visits (any day before
    today) show up separately under get_org_site_visits_history().
    """
    try:
        field_ids = sorted(get_field_employee_ids())

        if not field_ids:
            return success_response(
                message="Live site tracking fetched successfully.", data=[]
            )

        today = date.today()

        attendance_rows = (
            supabase_admin.table("attendance")
            .select(
                "id, employee_id, check_in_time, check_out_time, status, "
                "employees(employee_id, full_name, profile_photo, department_id, "
                "departments!employees_department_id_fkey(department_name))"
            )
            .in_("employee_id", field_ids)
            .eq("attendance_date", today.isoformat())
            .execute()
        ).data or []

        attendance_by_employee = {row["employee_id"]: row for row in attendance_rows}
        attendance_ids = [row["id"] for row in attendance_rows]

        visits_by_attendance: dict = {}
        if attendance_ids:
            visit_rows = (
                supabase_admin.table("attendance_site_visits")
                .select(SITE_VISIT_SELECT)
                .in_("attendance_id", attendance_ids)
                .order("arrival_time", desc=False)
                .execute()
            ).data or []
            for v in visit_rows:
                visits_by_attendance.setdefault(v["attendance_id"], []).append(v)

        results = []
        for employee_id in field_ids:
            attendance = attendance_by_employee.get(employee_id)
            employee_info = (attendance or {}).get("employees") or {}
            visits = visits_by_attendance.get((attendance or {}).get("id"), [])
            open_visit = next((v for v in visits if not v.get("departure_time")), None)

            if not attendance:
                live_status = "not_checked_in"
            elif open_visit:
                live_status = "on_site"
            elif attendance.get("check_out_time"):
                live_status = "checked_out"
            else:
                live_status = "checked_in_no_site"

            # For the map: current position is the open visit's arrival
            # point if they're on site right now, otherwise the most
            # recent visit's departure point (last known position today),
            # otherwise nothing to plot.
            last_visit = visits[-1] if visits else None
            if open_visit:
                # Prefer the latest 1-min presence ping (see
                # ping_site_visit) over the point captured once at
                # "Arrived" — that's what actually tells you where they
                # are right now, not just where they started.
                current_lat = open_visit.get("last_ping_latitude") or open_visit.get(
                    "arrival_latitude"
                )
                current_lng = open_visit.get("last_ping_longitude") or open_visit.get(
                    "arrival_longitude"
                )
            elif last_visit:
                current_lat = last_visit.get("departure_latitude")
                current_lng = last_visit.get("departure_longitude")
            else:
                current_lat = current_lng = None

            results.append(
                {
                    "employee_id": employee_id,
                    "employee": employee_info,
                    "live_status": live_status,
                    "current_site": (open_visit or {}).get("locations"),
                    "current_site_since": (open_visit or {}).get("arrival_time"),
                    "current_latitude": current_lat,
                    "current_longitude": current_lng,
                    "last_ping_at": (open_visit or {}).get("last_ping_at"),
                    "last_ping_distance_m": (open_visit or {}).get(
                        "last_ping_distance_m"
                    ),
                    "is_outside_radius": bool(
                        (open_visit or {}).get("is_outside_radius")
                    ),
                    "check_in_time": (attendance or {}).get("check_in_time"),
                    "check_out_time": (attendance or {}).get("check_out_time"),
                    "sites_visited_today": len(
                        {v.get("location_id") for v in visits if v.get("location_id")}
                    ),
                    "trail": visits,
                }
            )

        # Only keep employees who actually logged a site visit today —
        # "not checked in" / "checked in, no site yet" employees don't
        # belong on a "who visited site today" view.
        results = [r for r in results if r["sites_visited_today"] > 0]

        # On-site first, then checked-out (both imply an actual visit).
        order = {
            "on_site": 0,
            "checked_in_no_site": 1,
            "checked_out": 2,
            "not_checked_in": 3,
        }
        results.sort(key=lambda r: order.get(r["live_status"], 9))

        return success_response(
            message="Live site tracking fetched successfully.", data=results
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch live site tracking.")


def get_org_site_visits_history(
    auth_user_id: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
):
    """
    Company-wide site-visit HISTORY — every field employee's past visits,
    separate from get_org_site_visits_today()'s "today only" list. Backs
    the Super Admin "Live Tracking" -> History tab: gated the same way
    (VIEW_ALL_ATTENDANCE) as the live view.

    Defaults to the trailing 30 days ending yesterday when no range is
    given, so "today" (shown on the live tab) and "history" never
    overlap. Passing an explicit from_date/to_date can include today if
    the caller wants that.

    Returns one row per employee per day that has at least one recorded
    visit, newest day first.
    """
    try:
        field_ids = sorted(get_field_employee_ids())

        if not field_ids:
            return success_response(
                message="Site visit history fetched successfully.", data=[]
            )

        to_day = to_date or (date.today() - timedelta(days=1))
        from_day = from_date or (to_day - timedelta(days=29))

        attendance_rows = (
            supabase_admin.table("attendance")
            .select(
                "id, employee_id, attendance_date, "
                "employees(employee_id, full_name, profile_photo, department_id, "
                "departments!employees_department_id_fkey(department_name))"
            )
            .in_("employee_id", field_ids)
            .gte("attendance_date", from_day.isoformat())
            .lte("attendance_date", to_day.isoformat())
            .order("attendance_date", desc=True)
            .execute()
        ).data or []

        attendance_ids = [row["id"] for row in attendance_rows]

        visits_by_attendance: dict = {}
        if attendance_ids:
            visit_rows = (
                supabase_admin.table("attendance_site_visits")
                .select(SITE_VISIT_SELECT)
                .in_("attendance_id", attendance_ids)
                .order("arrival_time", desc=False)
                .execute()
            ).data or []
            for v in visit_rows:
                visits_by_attendance.setdefault(v["attendance_id"], []).append(v)

        days = []
        for row in attendance_rows:
            visits = visits_by_attendance.get(row["id"], [])
            if not visits:
                # No site visited that day — not part of "site visit
                # history", same rule as the today view.
                continue
            days.append(
                {
                    "employee_id": row["employee_id"],
                    "employee": row.get("employees") or {},
                    "attendance_date": row["attendance_date"],
                    "site_count": len(
                        {v.get("location_id") for v in visits if v.get("location_id")}
                    ),
                    "total_minutes": sum(_effective_visit_minutes(v) for v in visits),
                    "visits": visits,
                }
            )

        days.sort(
            key=lambda d: (d["attendance_date"], d["employee"].get("full_name") or ""),
            reverse=True,
        )

        return success_response(
            message="Site visit history fetched successfully.", data=days
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch site visit history.")


def get_employee_site_visits_history(
    employee_id: str,
    auth_user_id: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
):
    """
    Day-by-day site-visit history for one employee, for a manager (or HR)
    drilling into a single field-staff member's attendance. Same
    ownership rule as get_employee_attendance(): callers with
    VIEW_ALL_ATTENDANCE can view anyone, others only their own reports.
    """
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not has_permission(auth_user_id, "VIEW_ALL_ATTENDANCE"):
            if not manager_employee_id or not (
                manager_employee_id == employee_id
                or is_manager_of(manager_employee_id, employee_id)
            ):
                forbidden(
                    "You don't have permission to view this employee's site visits."
                )

        to_day = to_date or date.today()
        from_day = from_date or to_day

        attendance_rows = (
            supabase_admin.table("attendance")
            .select("id, attendance_date")
            .eq("employee_id", employee_id)
            .gte("attendance_date", from_day.isoformat())
            .lte("attendance_date", to_day.isoformat())
            .order("attendance_date", desc=True)
            .execute()
        ).data or []

        attendance_ids = [row["id"] for row in attendance_rows]
        date_by_attendance = {
            row["id"]: row["attendance_date"] for row in attendance_rows
        }

        visits_by_attendance: dict = {}
        if attendance_ids:
            visit_rows = (
                supabase_admin.table("attendance_site_visits")
                .select(SITE_VISIT_SELECT)
                .in_("attendance_id", attendance_ids)
                .order("arrival_time", desc=False)
                .execute()
            ).data or []
            for v in visit_rows:
                visits_by_attendance.setdefault(v["attendance_id"], []).append(v)

        days = [
            {
                "attendance_date": date_by_attendance[attendance_id],
                "visits": visits,
                "site_count": len(
                    {v.get("location_id") for v in visits if v.get("location_id")}
                ),
                "total_minutes": sum(_effective_visit_minutes(v) for v in visits),
            }
            for attendance_id, visits in visits_by_attendance.items()
        ]
        days.sort(key=lambda d: d["attendance_date"], reverse=True)

        return success_response(
            message="Employee site visit history fetched successfully.", data=days
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch employee site visit history.")


# ==========================================================================
# HISTORY / TIMELINE (self-service)
# ==========================================================================


def get_my_attendance(
    auth_user_id: str, from_date: Optional[date] = None, to_date: Optional[date] = None
):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            return success_response(
                message="Attendance history fetched successfully.", data=[]
            )

        query = (
            supabase_admin.table("attendance")
            .select("*")
            .eq("employee_id", employee_id)
        )

        if from_date:
            query = query.gte("attendance_date", from_date.isoformat())
        if to_date:
            query = query.lte("attendance_date", to_date.isoformat())

        response = query.order("attendance_date", desc=True).execute()

        # The `attendance` table's date column is `attendance_date`, but the
        # frontend (AttendanceHistory.jsx) reads `date` for display, for its
        # client-side date-range filter, and for the click-to-open day
        # summary modal. Without this alias every row's `date` was
        # `undefined`, so `r.date >= dateFrom` was always false — rows never
        # survived the filter and there was nothing to click on, regardless
        # of how much real attendance data existed.
        rows_by_date = {
            row.get("attendance_date"): {**row, "date": row.get("attendance_date")}
            for row in (response.data or [])
        }

        # A row only ever exists here for a day the employee actually
        # checked in on — days they were absent, or weekends, never get a
        # row written at all. That's why the Attendance Calendar (which
        # colors each day from this same list) only ever showed green
        # (Present) / amber (Half Day) dots and never red (Absent) or grey
        # (Weekly Off), even on days that should clearly have been one or
        # the other. We only synthesize the gaps when the caller gave us a
        # bounded range (from_date AND to_date) — that's what the calendar
        # always sends (one month at a time); AttendanceHistory.jsx's
        # "load everything" call omits both, and we don't want to
        # backfill an unbounded/all-time range back to whenever the
        # employee joined.
        if from_date and to_date:
            leave_resp = (
                supabase_admin.table("leave_requests")
                .select("start_date, end_date")
                .eq("employee_id", employee_id)
                .eq("status", "Approved")
                .lte("start_date", to_date.isoformat())
                .gte("end_date", from_date.isoformat())
                .execute()
            )
            leave_dates = set()
            for row in leave_resp.data or []:
                start = max(date.fromisoformat(row["start_date"]), from_date)
                end = min(date.fromisoformat(row["end_date"]), to_date)
                for d in _daterange(start, end):
                    leave_dates.add(d)

            today = date.today()
            last_synth_day = min(to_date, today)

            for d in _daterange(from_date, last_synth_day):
                key = d.isoformat()
                if key in rows_by_date:
                    continue
                if d.weekday() >= 5:  # Sat/Sun — see docstring note in
                    # get_team_attendance_report() re: "working day" being
                    # simplified to Mon-Fri company-wide for now.
                    rows_by_date[key] = {"date": key, "status": "Weekly Off"}
                elif d in leave_dates:
                    rows_by_date[key] = {"date": key, "status": "On Leave"}
                else:
                    rows_by_date[key] = {"date": key, "status": "Absent"}

        rows = sorted(rows_by_date.values(), key=lambda r: r["date"], reverse=True)

        return success_response(
            message="Attendance history fetched successfully.", data=rows
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch attendance history.")


def get_attendance_timeline(auth_user_id: str, target_date: date):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            return success_response(
                message="Attendance timeline fetched successfully.", data=None
            )

        attendance = attendance_repo.find_one(
            {"employee_id": employee_id, "attendance_date": target_date.isoformat()}
        )

        if not attendance:
            return success_response(
                message="No attendance record for this date.", data=None
            )

        breaks_resp = (
            supabase_admin.table("attendance_breaks")
            .select("*")
            .eq("attendance_id", attendance["id"])
            .order("break_start")
            .execute()
        )

        return success_response(
            message="Attendance timeline fetched successfully.",
            data={**attendance, "breaks": breaks_resp.data or []},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch attendance timeline.")


# ==========================================================================
# REGULARIZATION
# ==========================================================================


def submit_regularization(auth_user_id: str, data, request: Optional[Request] = None):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            forbidden("No employee profile is linked to this account.")

        attendance = attendance_repo.find_one(
            {
                "employee_id": employee_id,
                "attendance_date": data.attendance_date.isoformat(),
            }
        )

        payload = {
            "employee_id": employee_id,
            "attendance_id": attendance["id"] if attendance else None,
            "requested_check_in": data.requested_check_in.isoformat(),
            "requested_check_out": (
                data.requested_check_out.isoformat()
                if data.requested_check_out
                else None
            ),
            "reason": data.reason,
            "status": "Pending",
        }

        created = correction_repo.create(payload)

        record_audit_log(
            module="ATTENDANCE",
            action="REGULARIZATION_REQUEST",
            performed_by=auth_user_id,
            target_employee_id=employee_id,
            record_id=created.get("id"),
            description=f"Regularization requested for {data.attendance_date}: {data.reason}",
            new_values=created,
            request=request,
        )

        return success_response(
            message="Regularization request submitted.", data=created
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to submit regularization request.")


def get_my_regularizations(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            return success_response(
                message="Regularization requests fetched successfully.", data=[]
            )

        records, _total = correction_repo.list(
            filters={"employee_id": employee_id}, order_by="created_at", ascending=False
        )

        return success_response(
            message="Regularization requests fetched successfully.", data=records
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch regularization requests.")


def get_team_regularizations(auth_user_id: str):
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not manager_employee_id:
            return success_response(
                message="Team regularization requests fetched successfully.", data=[]
            )

        report_ids = get_all_report_ids(manager_employee_id)

        if not report_ids:
            return success_response(
                message="Team regularization requests fetched successfully.", data=[]
            )

        response = (
            supabase_admin.table("attendance_corrections")
            .select(CORRECTION_SELECT)
            .in_("employee_id", report_ids)
            .eq("status", "Pending")
            .order("created_at", desc=True)
            .execute()
        )

        return success_response(
            message="Team regularization requests fetched successfully.",
            data=response.data or [],
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch team regularization requests.")


def decide_regularization(
    correction_id: str, data, auth_user_id: str, request: Optional[Request] = None
):
    try:
        existing = correction_repo.get_by_id_or_404(
            correction_id, "Regularization request not found."
        )

        if existing.get("status") != "Pending":
            bad_request(
                f"This regularization request has already been {str(existing.get('status')).lower()}."
            )

        target_employee_id = existing.get("employee_id")
        approver_employee_id = get_employee_id_for_auth_user(auth_user_id)

        has_full_access = has_permission(
            auth_user_id, "EDIT_ATTENDANCE"
        ) or has_permission(auth_user_id, "VIEW_ALL_ATTENDANCE")
        is_direct_or_indirect_manager = is_manager_of(
            approver_employee_id, target_employee_id
        )

        if not has_full_access and not is_direct_or_indirect_manager:
            forbidden(
                "You don't have permission to approve or reject this regularization request."
            )

        if approver_employee_id and approver_employee_id == target_employee_id:
            forbidden("You cannot approve or reject your own regularization request.")

        updated = (
            supabase_admin.table("attendance_corrections")
            .update({"status": data.status, "approved_by": approver_employee_id})
            .eq("id", correction_id)
            .execute()
        )
        updated_row = updated.data[0] if updated.data else None

        if data.status == "Approved" and existing.get("attendance_id"):
            patch = {"status": "Present"}
            if existing.get("requested_check_in"):
                patch["check_in_time"] = existing["requested_check_in"]
            if existing.get("requested_check_out"):
                patch["check_out_time"] = existing["requested_check_out"]

            attendance_repo.update(existing["attendance_id"], patch)

        record_audit_log(
            module="ATTENDANCE",
            action=data.status.upper(),
            performed_by=auth_user_id,
            target_employee_id=target_employee_id,
            record_id=correction_id,
            description=(
                f"Regularization request {data.status.lower()}"
                + (f" — {data.comments}" if data.comments else "")
            ),
            old_values=existing,
            new_values=updated_row,
            request=request,
        )

        return success_response(
            message=f"Regularization request {data.status.lower()}.", data=updated_row
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update regularization request.")


# ==========================================================================
# TEAM / COMPANY-WIDE VIEWS
# ==========================================================================


def get_team_attendance(auth_user_id: str, target_date: Optional[date] = None):
    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not manager_employee_id:
            return success_response(
                message="Team attendance fetched successfully.", data=[]
            )

        report_ids = get_all_report_ids(manager_employee_id)

        if not report_ids:
            return success_response(
                message="Team attendance fetched successfully.", data=[]
            )

        day = target_date or date.today()

        response = (
            supabase_admin.table("attendance")
            .select(ATTENDANCE_SELECT)
            .in_("employee_id", report_ids)
            .eq("attendance_date", day.isoformat())
            .execute()
        )

        return success_response(
            message="Team attendance fetched successfully.", data=response.data or []
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch team attendance.")


def get_team_attendance_report(auth_user_id: str, from_date: date, to_date: date):
    """
    Per-employee attendance summary for the calling manager's direct +
    indirect reports over [from_date, to_date] — the data behind the
    manager-facing Attendance Reports page. There's no per-manager
    aggregate endpoint elsewhere to reuse: /attendance/team only ever
    returns a single day, and /attendance/analytics is a company-wide
    number gated behind VIEW_ALL_ATTENDANCE, which MANAGER doesn't hold
    (see sql/002_role_permissions_seed.sql) — so this is a new query,
    following the same manager-scoping pattern as get_team_attendance()
    and get_team_leaves() above/in app/leaves/services.py.

    "Working day" here is simplified to Mon-Fri in the requested range
    (shift-aware working-day calendars exist per-employee via
    _get_employee_shift(), but resolving that per employee per day for a
    whole team/date-range is a heavier query than this summary needs;
    flagged here rather than silently baked in). A working day with no
    attendance row and no overlapping Approved leave counts as Absent.
    """

    try:
        manager_employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not manager_employee_id:
            return success_response(
                message="Team attendance report fetched successfully.",
                data={
                    "from_date": from_date.isoformat(),
                    "to_date": to_date.isoformat(),
                    "employees": [],
                },
            )

        report_ids = get_all_report_ids(manager_employee_id)

        if not report_ids:
            return success_response(
                message="Team attendance report fetched successfully.",
                data={
                    "from_date": from_date.isoformat(),
                    "to_date": to_date.isoformat(),
                    "employees": [],
                },
            )

        roster_resp = (
            supabase_admin.table("employees")
            .select(
                "id, employee_id, full_name, profile_photo, "
                "departments!employees_department_id_fkey(department_name), "
                "designations(designation_name)"
            )
            .in_("id", report_ids)
            .order("full_name")
            .execute()
        )
        roster = roster_resp.data or []

        attendance_resp = (
            supabase_admin.table("attendance")
            .select(
                "employee_id, attendance_date, status, late_minutes, "
                "working_minutes, overtime_minutes"
            )
            .in_("employee_id", report_ids)
            .gte("attendance_date", from_date.isoformat())
            .lte("attendance_date", to_date.isoformat())
            .execute()
        )
        attendance_rows = attendance_resp.data or []

        leave_resp = (
            supabase_admin.table("leave_requests")
            .select("employee_id, start_date, end_date")
            .in_("employee_id", report_ids)
            .eq("status", "Approved")
            .lte("start_date", to_date.isoformat())
            .gte("end_date", from_date.isoformat())
            .execute()
        )
        leave_rows = leave_resp.data or []

        working_days = [
            d
            for d in _daterange(from_date, to_date)
            if d.weekday() < 5  # Mon-Fri; see docstring note above
        ]

        by_employee: dict[str, dict] = {}
        for emp in roster:
            by_employee[emp["id"]] = {
                "employee_id": emp["id"],
                "employee_code": emp.get("employee_id"),
                "full_name": emp.get("full_name"),
                "profile_photo": emp.get("profile_photo"),
                "department": (emp.get("departments") or {}).get("department_name"),
                "designation": (emp.get("designations") or {}).get("designation_name"),
                "working_days": len(working_days),
                "present_days": 0,
                "half_days": 0,
                "leave_days": 0,
                "absent_days": 0,
                "late_days": 0,
                "total_working_minutes": 0,
                "total_overtime_minutes": 0,
            }

        attendance_by_key: dict[tuple, dict] = {
            (row["employee_id"], row["attendance_date"]): row for row in attendance_rows
        }

        leave_dates_by_employee: dict[str, set] = {}
        for row in leave_rows:
            start = max(date.fromisoformat(row["start_date"]), from_date)
            end = min(date.fromisoformat(row["end_date"]), to_date)
            dates = leave_dates_by_employee.setdefault(row["employee_id"], set())
            for d in _daterange(start, end):
                dates.add(d)

        for emp_id, summary in by_employee.items():
            leave_dates = leave_dates_by_employee.get(emp_id, set())
            for d in working_days:
                key = (emp_id, d.isoformat())
                record = attendance_by_key.get(key)

                if record:
                    if record.get("status") == "Half Day":
                        summary["half_days"] += 1
                    else:
                        summary["present_days"] += 1
                    if (record.get("late_minutes") or 0) > 0:
                        summary["late_days"] += 1
                    summary["total_working_minutes"] += (
                        record.get("working_minutes") or 0
                    )
                    summary["total_overtime_minutes"] += (
                        record.get("overtime_minutes") or 0
                    )
                elif d in leave_dates:
                    summary["leave_days"] += 1
                else:
                    summary["absent_days"] += 1

            attended = summary["present_days"] + summary["half_days"]
            summary["attendance_percentage"] = (
                round((attended / summary["working_days"]) * 100, 1)
                if summary["working_days"]
                else 0
            )

        return success_response(
            message="Team attendance report fetched successfully.",
            data={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "working_days": len(working_days),
                "employees": list(by_employee.values()),
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch team attendance report.")


def _daterange(start: date, end: date):
    days = (end - start).days
    for offset in range(days + 1):
        yield start + timedelta(days=offset)


# NEW: powers the HR-facing Attendance Reports page
# (src/pages/hr-admin/AttendanceReports.jsx) — GET /attendance/org/report.
#
# Unlike get_team_attendance_report() above (scoped to one manager's
# reports), this covers the whole organization and is gated on
# VIEW_ALL_ATTENDANCE. Optional department_id/employee_id/status let the
# frontend's filter bar narrow the result without re-fetching everything.
#
# Returns both:
#  - "employees": one summary row per employee (present/absent/late/leave
#    counts + attendance %) — used for the "By employee" / "By department"
#    views and the per-employee CSV export.
#  - "daily_records": one row per employee per working day in range — used
#    for the "Daily log" table and the "export everything" CSV, since that
#    needs actual check-in/check-out times, not just the summary counts.
def get_org_attendance_report(
    from_date: date,
    to_date: date,
    department_id: Optional[str] = None,
    employee_id: Optional[str] = None,
    status: Optional[str] = None,
):
    try:
        roster_query = supabase_admin.table("employees").select(
            "id, employee_id, full_name, profile_photo, department_id, "
            "departments!employees_department_id_fkey(department_name), "
            "designations(designation_name)"
        )
        if department_id:
            roster_query = roster_query.eq("department_id", department_id)
        if employee_id:
            roster_query = roster_query.eq("id", employee_id)

        roster = (roster_query.order("full_name").execute()).data or []

        if not roster:
            return success_response(
                message="Attendance report fetched successfully.",
                data={
                    "from_date": from_date.isoformat(),
                    "to_date": to_date.isoformat(),
                    "employees": [],
                    "daily_records": [],
                },
            )

        roster_ids = [emp["id"] for emp in roster]
        roster_by_id = {emp["id"]: emp for emp in roster}

        attendance_resp = (
            supabase_admin.table("attendance")
            .select(
                "employee_id, attendance_date, status, check_in_time, "
                "check_out_time, late_minutes, working_minutes, "
                "overtime_minutes"
            )
            .in_("employee_id", roster_ids)
            .gte("attendance_date", from_date.isoformat())
            .lte("attendance_date", to_date.isoformat())
            .execute()
        )
        attendance_rows = attendance_resp.data or []

        leave_resp = (
            supabase_admin.table("leave_requests")
            .select("employee_id, start_date, end_date")
            .in_("employee_id", roster_ids)
            .eq("status", "Approved")
            .lte("start_date", to_date.isoformat())
            .gte("end_date", from_date.isoformat())
            .execute()
        )
        leave_rows = leave_resp.data or []

        working_days = [d for d in _daterange(from_date, to_date) if d.weekday() < 5]

        attendance_by_key = {
            (row["employee_id"], row["attendance_date"]): row for row in attendance_rows
        }

        leave_dates_by_employee: dict[str, set] = {}
        for row in leave_rows:
            start = max(date.fromisoformat(row["start_date"]), from_date)
            end = min(date.fromisoformat(row["end_date"]), to_date)
            dates = leave_dates_by_employee.setdefault(row["employee_id"], set())
            for d in _daterange(start, end):
                dates.add(d)

        by_employee: dict[str, dict] = {}
        daily_records: list[dict] = []

        for emp_id in roster_ids:
            emp = roster_by_id[emp_id]
            summary = {
                "employee_id": emp_id,
                "employee_code": emp.get("employee_id"),
                "full_name": emp.get("full_name"),
                "department": (emp.get("departments") or {}).get("department_name"),
                "designation": (emp.get("designations") or {}).get("designation_name"),
                "working_days": len(working_days),
                "present_days": 0,
                "half_days": 0,
                "leave_days": 0,
                "absent_days": 0,
                "late_days": 0,
                "total_working_minutes": 0,
                "total_overtime_minutes": 0,
            }
            leave_dates = leave_dates_by_employee.get(emp_id, set())

            for d in working_days:
                record = attendance_by_key.get((emp_id, d.isoformat()))
                day_status = None

                if record:
                    day_status = (
                        "Half Day" if record.get("status") == "Half Day" else "Present"
                    )
                    if day_status == "Half Day":
                        summary["half_days"] += 1
                    else:
                        summary["present_days"] += 1
                    if (record.get("late_minutes") or 0) > 0:
                        summary["late_days"] += 1
                        day_status = "Late"
                    summary["total_working_minutes"] += (
                        record.get("working_minutes") or 0
                    )
                    summary["total_overtime_minutes"] += (
                        record.get("overtime_minutes") or 0
                    )
                elif d in leave_dates:
                    summary["leave_days"] += 1
                    day_status = "On Leave"
                else:
                    summary["absent_days"] += 1
                    day_status = "Absent"

                if status and day_status != status:
                    continue

                working_minutes = record.get("working_minutes") if record else 0
                daily_records.append(
                    {
                        "employee_id": emp_id,
                        "employee_code": emp.get("employee_id"),
                        "full_name": emp.get("full_name"),
                        "department": summary["department"],
                        "date": d.isoformat(),
                        "check_in_time": (
                            record.get("check_in_time") if record else None
                        ),
                        "check_out_time": (
                            record.get("check_out_time") if record else None
                        ),
                        "working_hours": round((working_minutes or 0) / 60, 1),
                        "status": day_status,
                    }
                )

            attended = summary["present_days"] + summary["half_days"]
            summary["attendance_percentage"] = (
                round((attended / summary["working_days"]) * 100, 1)
                if summary["working_days"]
                else 0
            )
            by_employee[emp_id] = summary

        return success_response(
            message="Attendance report fetched successfully.",
            data={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "working_days": len(working_days),
                "employees": list(by_employee.values()),
                "daily_records": daily_records,
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch attendance report.")


def get_all_attendance(
    page: int = 1, limit: int = 50, target_date: Optional[date] = None
):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 200), 1)
        end = start + max(min(limit, 200), 1) - 1

        filters = {"attendance_date": target_date.isoformat()} if target_date else None

        records, total = attendance_repo.list(
            select=ATTENDANCE_SELECT,
            filters=filters,
            order_by="attendance_date",
            ascending=False,
            start=start,
            end=end,
        )

        return success_response(
            message="Attendance fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch attendance.")


def get_employee_attendance(
    employee_id: str, auth_user_id: str, page: int = 1, limit: int = 50
):
    try:
        if not has_permission(auth_user_id, "VIEW_ALL_ATTENDANCE"):
            own_employee_id = get_employee_id_for_auth_user(auth_user_id)

            # A manager drilling into one of their own direct/indirect
            # reports (e.g. from the Team Attendance Report) is allowed
            # even without the org-wide VIEW_ALL_ATTENDANCE permission —
            # same "is this caller the report's manager" check used to
            # gate leave/overtime approval. Everyone else falls back to
            # "must be your own record".
            if own_employee_id == employee_id:
                pass
            elif not is_manager_of(own_employee_id, employee_id):
                forbidden(
                    "You don't have permission to view this employee's attendance."
                )

        start = (max(page, 1) - 1) * max(min(limit, 200), 1)
        end = start + max(min(limit, 200), 1) - 1

        records, total = attendance_repo.list(
            select=ATTENDANCE_SELECT,
            filters={"employee_id": employee_id},
            order_by="attendance_date",
            ascending=False,
            start=start,
            end=end,
        )

        return success_response(
            message="Attendance fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch employee attendance.")


def get_attendance_analytics(from_date: date, to_date: date):
    try:
        response = (
            supabase_admin.table("attendance")
            .select("status, late_minutes, overtime_minutes, working_minutes")
            .gte("attendance_date", from_date.isoformat())
            .lte("attendance_date", to_date.isoformat())
            .execute()
        )

        rows = response.data or []
        total_records = len(rows)
        present_count = sum(1 for r in rows if r.get("status") == "Present")
        half_day_count = sum(1 for r in rows if r.get("status") == "Half Day")
        late_count = sum(1 for r in rows if (r.get("late_minutes") or 0) > 0)
        total_overtime_minutes = sum((r.get("overtime_minutes") or 0) for r in rows)
        average_working_minutes = (
            round(sum((r.get("working_minutes") or 0) for r in rows) / total_records, 1)
            if total_records
            else 0
        )

        return success_response(
            message="Attendance analytics fetched successfully.",
            data={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "total_records": total_records,
                "present_count": present_count,
                "half_day_count": half_day_count,
                "late_count": late_count,
                "average_working_minutes": average_working_minutes,
                "total_overtime_minutes": total_overtime_minutes,
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch attendance analytics.")


# ==========================================================================
# HR / ADMIN DIRECT EDIT
# ==========================================================================


def admin_update_attendance(
    attendance_id: str, data, current_user=None, request: Optional[Request] = None
):
    try:
        existing = attendance_repo.get_by_id_or_404(
            attendance_id, "Attendance record not found."
        )

        values = data.model_dump(exclude_unset=True)

        for key in ("check_in_time", "check_out_time"):
            if key in values and values[key] is not None:
                values[key] = values[key].isoformat()

        updated = attendance_repo.update(attendance_id, values)

        record_audit_log(
            module="ATTENDANCE",
            action="ADMIN_UPDATE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=updated.get("employee_id"),
            record_id=attendance_id,
            description="Attendance record manually updated by HR/Admin",
            old_values=existing,
            new_values=updated,
            request=request,
        )

        return success_response(message="Attendance record updated.", data=updated)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update attendance record.")
