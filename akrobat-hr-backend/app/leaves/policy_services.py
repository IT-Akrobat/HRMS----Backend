"""
Leave Policy Engine.

Everything to do with WHO gets HOW MUCH leave, as opposed to
app/leaves/services.py which is about individual leave *requests*
(apply / approve / reject). Covers:

  - leave_policy_tiers   (Annual Leave 21/20/14/11/10, Childcare 6/2)
  - employee_leave_tier  (HR's per-employee tier assignment)
  - leave_eligibility_rules (nationality / marital_status / gender /
    employee_type exclusions)
  - leave_replacement_credits (manual, event-based, Replacement Leave)
  - the yearly leave_balances generator
  - the Annual Leave 10-day tenure recompute job

NS Leave has no table of its own here: it goes through the normal
leave_requests flow with entitlement_mode = 'event', an eligibility
check, and no balance / no cap (see validate_event_leave_request below
and app/leaves/services.py apply_leave()).
"""

from datetime import date, datetime, timezone
from typing import Optional

from app.core.database import supabase_admin
from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import bad_request, internal_server_error, not_found
from app.core.audit import record_audit_log
from app.core.helpers.employee_helper import (
    is_field_employee,
    get_employee_id_for_auth_user,
)

leave_type_repo = SupabaseRepository("leave_types")
tier_repo = SupabaseRepository("leave_policy_tiers")
employee_tier_repo = SupabaseRepository("employee_leave_tier")
leave_override_repo = SupabaseRepository("employee_leave_overrides")
eligibility_repo = SupabaseRepository("leave_eligibility_rules")
balance_repo = SupabaseRepository("leave_balances")
replacement_credit_repo = SupabaseRepository("leave_replacement_credits")
employee_repo = SupabaseRepository("employees")

ANNUAL_LEAVE = "ANNUAL LEAVE"
CHILDCARE_LEAVE = "CHILDCARE LEAVE"
REPLACEMENT_LEAVE = "REPLACEMENT LEAVE"
NATIONAL_SERVICE_LEAVE = "NATIONAL SERVICE LEAVE"
UNPAID_LEAVE = "UNPAID LEAVE"
SICK_LEAVE = "SICK LEAVE"  # shown to staff as "MC (Medical Leave)"

# employees.leave_scheme values (sql/034_sg_leave_rules.sql)
SCHEME_SG_LIST = "SG_LIST"  # on the Singapore leave sheet
SCHEME_MC_ONLY = "MC_ONLY"  # everyone else in Singapore: MC only, no balances
SCHEME_STANDARD = "STANDARD"  # previous behaviour (Chennai etc.)
SCHEME_FOREIGN_WORKER = "FOREIGN_WORKER"  # MC + Home Leave (+ Unpaid for extra days)

HOME_LEAVE = "HOME LEAVE"
# Leave types a FOREIGN_WORKER employee may apply for themselves. Unpaid
# Leave covers any days beyond the Home Leave cap.
FOREIGN_WORKER_LEAVE_TYPES = (SICK_LEAVE, HOME_LEAVE, UNPAID_LEAVE)

# Leave types a SG_LIST employee may apply for themselves.
SG_LIST_LEAVE_TYPES = (ANNUAL_LEAVE, SICK_LEAVE, REPLACEMENT_LEAVE, CHILDCARE_LEAVE)

TENURE_TIER_NAME = "10 DAYS"
TENURE_TIER_BASE_DAYS = 10
TENURE_TIER_CAP_DAYS = 14
TENURE_QUALIFYING_YEARS = 3

# ==========================================
# LOOKUPS
# ==========================================


def _get_leave_type_by_name(leave_name: str) -> Optional[dict]:
    return leave_type_repo.find_one(
        {"leave_name": leave_name.strip().upper()},
        select="id, leave_name, default_days, entitlement_mode, is_paid",
    )


def get_leave_type_or_404(leave_name: str) -> dict:
    leave_type = _get_leave_type_by_name(leave_name)
    if not leave_type:
        not_found(f"Leave type '{leave_name}' not found.")
    return leave_type


# ==========================================
# GET TIERS FOR A LEAVE TYPE (Employee create/edit form dropdowns)
# ==========================================


def _get_employee_leave_override_days(
    employee_id: str, leave_type_id: str
) -> Optional[int]:
    """
    Per-employee override for a 'fixed' leave type's day count (e.g.
    the Chennai Leave Default). Returns None when no override row
    exists, in which case callers fall back to the normal
    leave_types.default_days / tier logic unchanged.
    """
    override = leave_override_repo.find_one(
        {"employee_id": employee_id, "leave_type_id": leave_type_id},
        select="days",
    )
    if override and override.get("days") is not None:
        return override["days"]
    return None


def get_tiers_for_leave_type(leave_name: str):
    try:
        leave_type = get_leave_type_or_404(leave_name)

        tiers, _total = tier_repo.list(
            select="id, tier_name, days",
            filters={"leave_type_id": leave_type["id"]},
            order_by="days",
            ascending=False,
        )

        return success_response(
            message="Leave policy tiers fetched successfully.", data=tiers
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch leave policy tiers.")


# ==========================================
# ASSIGN AN EMPLOYEE'S TIER FOR A TIERED LEAVE TYPE
# (called directly by HR, and internally from employee create/update)
# ==========================================


def assign_employee_leave_tier(
    employee_id: str,
    leave_name: str,
    tier_id: Optional[str],
    assigned_by: Optional[str] = None,
):
    if not tier_id:
        return None

    leave_type = get_leave_type_or_404(leave_name)

    if leave_type.get("entitlement_mode") != "tiered":
        bad_request(f"{leave_name} is not a tiered leave type.")

    # NOTE: select now also pulls tier_name/days -- needed below to push
    # the new day count into this year's leave_balances row.
    tier = tier_repo.get_by_id(
        str(tier_id), select="id, leave_type_id, tier_name, days"
    )
    if not tier or str(tier.get("leave_type_id")) != str(leave_type["id"]):
        bad_request(f"Invalid tier for {leave_name}.")

    existing = employee_tier_repo.find_one(
        {"employee_id": employee_id, "leave_type_id": leave_type["id"]}
    )

    payload = {
        "employee_id": employee_id,
        "leave_type_id": leave_type["id"],
        "tier_id": str(tier_id),
        "assigned_by": assigned_by,
    }

    if existing:
        result = employee_tier_repo.update(existing["id"], payload)
    else:
        result = employee_tier_repo.create(payload)

    # A tier assigned explicitly replaces any day count typed on the user
    # form (otherwise the override would keep winning over the tier).
    stale_override = leave_override_repo.find_one(
        {"employee_id": employee_id, "leave_type_id": leave_type["id"]},
        select="id",
    )
    if stale_override:
        leave_override_repo.delete(stale_override["id"])

    # Keep THIS YEAR's leave_balances row in sync with the tier change.
    # Previously this function only upserted employee_leave_tier, so
    # editing an employee's Annual/Childcare Leave tier (e.g. Childcare
    # 6 -> 2 days) never touched their existing leave_balances row --
    # the employee kept seeing the OLD tier's total/remaining days
    # (and requests kept validating against it) until someone re-ran
    # the yearly generate-balances job company-wide. That's the "edit
    # it, doesn't update" bug: sync it here so the change is immediate.
    _sync_leave_balance_for_tier(employee_id, leave_type, tier)

    return result


def _sync_leave_balance_for_tier(employee_id: str, leave_type: dict, tier: dict):
    """
    Push a (re)assigned tier's day count into the employee's current
    year leave_balances row immediately, instead of waiting for the
    next generate_yearly_leave_balances() run. Preserves used_days so
    remaining_days is simply recomputed from the new total.
    """

    leave_name = (leave_type.get("leave_name") or "").strip().upper()

    if leave_name == ANNUAL_LEAVE and tier.get("tier_name") == TENURE_TIER_NAME:
        employee = employee_repo.get_by_id(employee_id, select="joining_date")
        new_days = compute_annual_leave_10_day_days(
            employee.get("joining_date") if employee else None
        )
    else:
        new_days = tier.get("days") or 0

    current_year = datetime.now(timezone.utc).year

    existing_balance = balance_repo.find_one(
        {
            "employee_id": employee_id,
            "leave_type_id": leave_type["id"],
            "year": current_year,
        },
        select="id, used_days",
    )

    if existing_balance:
        used = existing_balance.get("used_days") or 0
        balance_repo.update(
            existing_balance["id"],
            {"total_days": new_days, "remaining_days": new_days - used},
        )
    else:
        balance_repo.create(
            {
                "employee_id": employee_id,
                "leave_type_id": leave_type["id"],
                "year": current_year,
                "total_days": new_days,
                "used_days": 0,
                "remaining_days": new_days,
            }
        )


def get_employee_leave_tier(employee_id: str, leave_type_id: str) -> Optional[dict]:
    return employee_tier_repo.find_one(
        {"employee_id": employee_id, "leave_type_id": leave_type_id},
        select="id, tier_id, leave_policy_tiers(id, tier_name, days)",
    )


# ==========================================
# ELIGIBILITY
# ==========================================


def _employee_field_value(employee: dict, field: str) -> Optional[str]:
    if field == "nationality":
        # employees.nationality now stores a real country name (the
        # create/edit form is a full country picker), not a
        # Singaporean/Foreigner category. The only rule seeded against
        # this field is nationality='Foreigner' -> not eligible (NS
        # Leave), so normalize here: Singapore nationals stay
        # "Singapore" (never matches that rule), everyone else
        # collapses to "Foreigner" so the existing rule still catches
        # them regardless of which country they actually picked.
        raw = employee.get("nationality")
        if raw is None:
            return None
        return "Singapore" if raw.strip().lower() == "singapore" else "Foreigner"
    if field == "marital_status":
        return employee.get("marital_status")
    if field == "gender":
        return employee.get("gender")
    if field == "employee_type":
        return "field" if is_field_employee(employee.get("id")) else "office"
    return None


def evaluate_leave_eligibility(
    employee: dict, leave_type_id: str
) -> tuple[bool, Optional[str]]:
    """
    Returns (eligible, reason_if_not_eligible).

    An employee is ineligible only if there's a rule whose (field, value)
    matches the employee AND eligible=false. No matching rule (or no
    rules at all for this leave type) means eligible by default.
    """

    rules, _total = eligibility_repo.list(
        select="field, value, eligible", filters={"leave_type_id": leave_type_id}
    )

    for rule in rules:
        employee_value = _employee_field_value(employee, rule["field"])

        if employee_value is None:
            continue

        if (
            str(employee_value).strip().lower() == str(rule["value"]).strip().lower()
            and rule["eligible"] is False
        ):
            return False, (
                f"Not eligible: {rule['field'].replace('_', ' ')} "
                f"'{employee_value}' is excluded from this leave type."
            )

    return True, None


def check_leave_eligibility(employee_id: str, leave_name: str):
    try:
        employee = employee_repo.get_by_id_or_404(employee_id, "Employee not found.")
        leave_type = get_leave_type_or_404(leave_name)

        eligible, reason = evaluate_leave_eligibility(employee, leave_type["id"])

        return success_response(
            message="Eligibility checked.",
            data={"eligible": eligible, "reason": reason},
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to check leave eligibility.")


# ==========================================
# REPLACEMENT LEAVE — manual HR credit
# ==========================================


def credit_replacement_leave(
    employee_id: str,
    public_holiday_date: date,
    credited_by: Optional[str] = None,
    request=None,
):
    try:
        employee = employee_repo.get_by_id_or_404(employee_id, "Employee not found.")

        leave_type = get_leave_type_or_404(REPLACEMENT_LEAVE)
        eligible, reason = evaluate_leave_eligibility(employee, leave_type["id"])

        if not eligible:
            # Replacement Leave is gated to office staff only — this is
            # the concrete case that trips: field employees.
            bad_request(reason or "Employee is not eligible for Replacement Leave.")

        credited_date = date.today()
        try:
            expiry_date = credited_date.replace(year=credited_date.year + 1)
        except ValueError:
            # Feb 29 credited_date in a leap year -> Feb 28 next year.
            expiry_date = credited_date.replace(year=credited_date.year + 1, day=28)

        credit = replacement_credit_repo.create(
            {
                "employee_id": employee_id,
                "public_holiday_date": str(public_holiday_date),
                "credited_by": credited_by,
                "credited_date": str(credited_date),
                "expiry_date": str(expiry_date),
                "used": False,
            }
        )

        record_audit_log(
            module="LEAVE",
            action="CREDIT_REPLACEMENT_LEAVE",
            performed_by=credited_by,
            target_employee_id=employee_id,
            record_id=credit.get("id"),
            description=(
                f"Replacement leave credited for public holiday "
                f"{public_holiday_date} (expires {expiry_date})"
            ),
            new_values=credit,
            request=request,
        )

        return success_response(
            message="Replacement leave credited successfully.", data=credit
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to credit replacement leave.")


def get_replacement_leave_credits(employee_id: str):
    try:
        credits, _total = replacement_credit_repo.list(
            select="*",
            filters={"employee_id": employee_id},
            order_by="credited_date",
            ascending=False,
        )
        return success_response(
            message="Replacement leave credits fetched successfully.", data=credits
        )
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch replacement leave credits.")


def _unused_credit_rows(employee_id: str) -> list:
    today = date.today().isoformat()
    response = (
        supabase_admin.table("leave_replacement_credits")
        .select("id, days, used_days, expiry_date")
        .eq("employee_id", employee_id)
        .eq("used", False)
        .gte("expiry_date", today)
        .order("expiry_date")
        .execute()
    )
    return response.data or []


def get_unused_replacement_credit_days(employee_id: str) -> float:
    """Unused, unexpired Replacement Leave days available today (half days allowed)."""
    return sum(
        float(r.get("days") or 1) - float(r.get("used_days") or 0)
        for r in _unused_credit_rows(employee_id)
    )


def consume_replacement_credits(
    employee_id: str, days_needed: float, leave_request_id: str
) -> list:
    """
    Takes `days_needed` (may be 0.5) from the oldest-expiring credits (FIFO).
    Returns the allocation [{credit_id, days}] so a rejection can give the
    days back exactly (see release_replacement_credits).
    """
    remaining_needed = float(days_needed)
    allocation = []

    for row in _unused_credit_rows(employee_id):
        if remaining_needed <= 0:
            break
        free = float(row.get("days") or 1) - float(row.get("used_days") or 0)
        take = min(free, remaining_needed)
        if take <= 0:
            continue
        new_used = float(row.get("used_days") or 0) + take
        replacement_credit_repo.update(
            row["id"],
            {
                "used_days": new_used,
                "used": new_used >= float(row.get("days") or 1),
                "used_leave_request_id": leave_request_id,
            },
        )
        allocation.append({"credit_id": row["id"], "days": take})
        remaining_needed -= take

    if remaining_needed > 0:
        # roll back whatever was taken before failing
        release_replacement_credits(allocation)
        bad_request("Not enough unused Replacement Leave credits available.")

    return allocation


def release_replacement_credits(allocation: Optional[list]):
    """Gives held Replacement Leave days back (leave rejected)."""
    for item in allocation or []:
        credit = replacement_credit_repo.get_by_id(
            item["credit_id"], select="id, days, used_days"
        )
        if not credit:
            continue
        new_used = max(float(credit.get("used_days") or 0) - float(item["days"]), 0)
        replacement_credit_repo.update(
            credit["id"], {"used_days": new_used, "used": False}
        )


# ==========================================
# LEAVE SCHEME ACCESS (who may apply for what, who sees balances)
# ==========================================


def get_leave_scheme(employee: dict) -> str:
    return (employee or {}).get("leave_scheme") or SCHEME_MC_ONLY


def tracks_balance(employee: dict, leave_type: dict) -> bool:
    """
    Every scheme tracks a balance. MC-only staff have a real MC balance too
    (14 days, or whatever HR set) -- it is only HIDDEN from them (see
    get_my_leave_entitlements) so HR can still see how much MC they used.
    """
    return True


def evaluate_self_apply_access(
    employee: dict, leave_type: dict
) -> tuple[bool, Optional[str]]:
    """
    Can this employee apply for this leave type themselves?

    - Hospitalisation / Maternity (leave_types.hr_managed): never -- HR and
      Super Admin record these.
    - MC_ONLY (not on the Singapore sheet): MC (Sick Leave) only.
    - SG_LIST: Annual, MC, Replacement, Childcare only (the sheet is the
      source of truth, so the generic nationality/field rules are skipped).
    - FOREIGN_WORKER: MC, Home Leave and Unpaid Leave only.
    - STANDARD: previous eligibility rules.
    """

    leave_name = (leave_type.get("leave_name") or "").strip().upper()

    if leave_type.get("hr_managed"):
        return (
            False,
            f"{leave_name.title()} is managed by HR and cannot be applied for.",
        )

    scheme = get_leave_scheme(employee)

    if scheme == SCHEME_MC_ONLY:
        if leave_name != SICK_LEAVE:
            return False, "You can only apply for MC (Medical Leave)."
        return True, None

    if scheme == SCHEME_FOREIGN_WORKER:
        if leave_name in FOREIGN_WORKER_LEAVE_TYPES:
            return True, None
        return False, f"{leave_name.title()} is not available for you."

    if scheme == SCHEME_SG_LIST:
        if leave_name in SG_LIST_LEAVE_TYPES:
            return True, None

        # Paternity / HR-added leave types: available only once HR has set
        # a number of days for this employee (user form -> Leave days),
        # and still subject to the normal eligibility rules.
        granted = leave_override_repo.find_one(
            {"employee_id": employee.get("id"), "leave_type_id": leave_type["id"]},
            select="days",
        )
        if granted and (granted.get("days") or 0) > 0:
            return evaluate_leave_eligibility(employee, leave_type["id"])

        return False, f"{leave_name.title()} is not available for you."

    return evaluate_leave_eligibility(employee, leave_type["id"])


# ==========================================
# LEAVE REQUEST VALIDATION HOOK
# (called from app/leaves/services.py apply_leave)
# ==========================================


def _get_or_create_leave_balance(employee: dict, leave_type: dict, year: int):
    """
    Fetches this employee's leave_balances row for (leave_type, year),
    lazily creating it on first use if it doesn't exist yet.

    Why this exists: get_my_leave_entitlements() (the "Apply Leave"
    entitlements panel) already shows a 'fixed' leave type's
    default_days to the employee even before a balance row exists in
    the DB -- every eligible employee gets the exact same number for a
    'fixed' type, so there's nothing per-person to guess. But this
    validation used to require an actual leave_balances row and reject
    with "No X balance found for <year>. Contact HR." the instant
    someone tried to apply -- so an employee could SEE "2 days of
    Casual Leave" on screen and still get blocked applying for it,
    just because nobody had run generate_yearly_leave_balances() for
    the year yet.

    This makes apply-time match what's already displayed: create the
    row on demand (same eligibility + day-resolution logic as the
    yearly generator) instead of erroring, so a missed/late yearly run
    no longer blocks anyone. Safe to call every time -- find_one runs
    first and short-circuits once the row exists.

    'tiered' types with no tier assigned still return None (there's no
    correct number to grant without a tier), and the caller keeps its
    own "Contact HR" error for that specific case.
    """

    balance = balance_repo.find_one(
        {
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "year": year,
        },
        select="id, total_days, used_days, remaining_days",
    )
    if balance:
        return balance

    days = _resolve_days_for_employee(employee, leave_type)
    if days is None:
        return None

    return balance_repo.create(
        {
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "year": year,
            "total_days": days,
            "used_days": 0,
            "remaining_days": days,
        }
    )


def validate_leave_request_against_entitlement(
    employee: dict, leave_type: dict, total_days: float
):
    """
    Raises a 400 if the request can't be honoured. Called after
    eligibility has already passed.

    - event (NS Leave): no balance, no cap — always fine.
    - event (Replacement Leave): must have enough unused, unexpired
      leave_replacement_credits.
    - not_a_balance (Unpaid Leave): never blocked here — payroll deducts
      via employees.working_days_per_week, not a balance row.
    - fixed / tiered: must have a leave_balances row for the current
      year with enough remaining_days.
    """

    mode = leave_type.get("entitlement_mode")
    leave_name = (leave_type.get("leave_name") or "").strip().upper()

    # MC-only staff: MC is tracked against their 14 days (so HR can see it)
    # but never blocked and never shown to them -- no balance or "insufficient"
    # message ever reaches the employee. Make sure the balance row exists so
    # deduct_entitlement() has something to deduct from.
    if get_leave_scheme(employee) == SCHEME_MC_ONLY:
        if mode == "fixed":
            _get_or_create_leave_balance(
                employee, leave_type, datetime.now(timezone.utc).year
            )
        return

    if mode == "not_a_balance":
        return

    if mode == "event":
        if leave_name == NATIONAL_SERVICE_LEAVE:
            return

        if leave_name == REPLACEMENT_LEAVE:
            available = get_unused_replacement_credit_days(employee["id"])
            if available < total_days:
                bad_request(
                    f"Insufficient Replacement Leave credit: {available} day(s) "
                    f"available, {total_days} requested."
                )
            return

        # Any other event-based type: no balance model defined, allow.
        return

    # fixed / tiered
    current_year = datetime.now(timezone.utc).year
    balance = _get_or_create_leave_balance(employee, leave_type, current_year)

    if not balance:
        # Only reachable for 'tiered' types with no tier assigned yet --
        # there's genuinely no correct day count to grant (could be 21,
        # 14, 11, 10... for Annual Leave), so this can't self-heal like
        # 'fixed' types do. HR needs to assign a tier first.
        bad_request(
            f"No {leave_name.title()} entitlement configured for {current_year}. "
            "Contact HR."
        )

    if (balance.get("remaining_days") or 0) < total_days:
        bad_request(
            f"Insufficient {leave_name.title()} balance: "
            f"{balance.get('remaining_days')} day(s) remaining, "
            f"{total_days} requested."
        )


def deduct_entitlement(
    employee_id: str, leave_type: dict, total_days: float, leave_request_id: str
) -> dict:
    """
    Takes the days out of the entitlement that backs this leave type.
    Called when the employee APPLIES (so the balance they see drops
    straight away). Returns {"balance_deducted": bool,
    "replacement_allocation": list|None} to store on the leave request.
    """

    employee = employee_repo.get_by_id(employee_id, select="id, leave_scheme") or {}
    if not tracks_balance(employee, leave_type):
        return {"balance_deducted": False, "replacement_allocation": None}

    mode = leave_type.get("entitlement_mode")
    leave_name = (leave_type.get("leave_name") or "").strip().upper()

    if mode == "not_a_balance":
        return {"balance_deducted": False, "replacement_allocation": None}

    if mode == "event":
        if leave_name == REPLACEMENT_LEAVE:
            allocation = consume_replacement_credits(
                employee_id, total_days, leave_request_id
            )
            return {"balance_deducted": True, "replacement_allocation": allocation}
        # NS Leave: nothing to deduct, no cap.
        return {"balance_deducted": False, "replacement_allocation": None}

    current_year = datetime.now(timezone.utc).year
    balance = balance_repo.find_one(
        {
            "employee_id": employee_id,
            "leave_type_id": leave_type["id"],
            "year": current_year,
        },
        select="id, used_days, total_days",
    )

    if not balance:
        logger.error(
            f"No leave_balances row for employee {employee_id}, "
            f"leave_type {leave_type['id']}, year {current_year} at deduction time."
        )
        return {"balance_deducted": False, "replacement_allocation": None}

    new_used = float(balance.get("used_days") or 0) + float(total_days)
    new_remaining = float(balance.get("total_days") or 0) - new_used

    balance_repo.update(
        balance["id"], {"used_days": new_used, "remaining_days": new_remaining}
    )
    return {"balance_deducted": True, "replacement_allocation": None}


def release_entitlement(leave_request: dict, leave_type: dict):
    """Gives the held days back (leave rejected). No-op if nothing was held."""

    if not leave_request.get("balance_deducted"):
        return

    mode = leave_type.get("entitlement_mode")
    leave_name = (leave_type.get("leave_name") or "").strip().upper()

    if mode == "event" and leave_name == REPLACEMENT_LEAVE:
        release_replacement_credits(leave_request.get("replacement_allocation"))
        return

    balance = balance_repo.find_one(
        {
            "employee_id": leave_request["employee_id"],
            "leave_type_id": leave_type["id"],
            "year": datetime.now(timezone.utc).year,
        },
        select="id, used_days, total_days",
    )
    if not balance:
        return

    new_used = max(
        float(balance.get("used_days") or 0)
        - float(leave_request.get("total_days") or 0),
        0,
    )
    balance_repo.update(
        balance["id"],
        {
            "used_days": new_used,
            "remaining_days": float(balance.get("total_days") or 0) - new_used,
        },
    )


# ==========================================
# ANNUAL LEAVE 10-DAY TENURE BONUS
# ==========================================


def compute_annual_leave_10_day_days(joining_date: Optional[str]) -> int:
    """
    Base 10 days. Past 3 years of tenure, +1 day per year, capped at 14.
    e.g. tenure 3y -> 10, 4y -> 11, 5y -> 12, 7y+ -> 14 (cap).
    """

    if not joining_date:
        return TENURE_TIER_BASE_DAYS

    if isinstance(joining_date, str):
        joining = datetime.fromisoformat(joining_date).date()
    else:
        joining = joining_date

    today = date.today()
    tenure_years = (
        today.year
        - joining.year
        - (1 if (today.month, today.day) < (joining.month, joining.day) else 0)
    )

    if tenure_years <= TENURE_QUALIFYING_YEARS:
        return TENURE_TIER_BASE_DAYS

    bonus_years = tenure_years - TENURE_QUALIFYING_YEARS
    return min(TENURE_TIER_BASE_DAYS + bonus_years, TENURE_TIER_CAP_DAYS)


def recompute_annual_leave_tenure_tiers(year: Optional[int] = None, current_user=None):
    """
    HR-triggered (or scheduled) job: for every employee on the Annual
    Leave 10-day tier, recompute their day count from tenure and update
    THIS YEAR's leave_balances row (total_days, remaining_days). Does
    not touch employees on the 21/20/14/11-day tiers.
    """

    try:
        target_year = year or datetime.now(timezone.utc).year

        annual_leave = get_leave_type_or_404(ANNUAL_LEAVE)
        tenure_tier = tier_repo.find_one(
            {"leave_type_id": annual_leave["id"], "tier_name": TENURE_TIER_NAME},
            select="id",
        )

        if not tenure_tier:
            not_found("Annual Leave 10-day tier not configured.")

        assignments, _total = employee_tier_repo.list(
            select="employee_id",
            filters={
                "leave_type_id": annual_leave["id"],
                "tier_id": tenure_tier["id"],
            },
        )

        updated = 0
        skipped = 0

        for assignment in assignments:
            employee_id = assignment["employee_id"]
            employee = employee_repo.get_by_id(employee_id, select="joining_date")

            if not employee:
                skipped += 1
                continue

            new_days = compute_annual_leave_10_day_days(employee.get("joining_date"))

            existing_balance = balance_repo.find_one(
                {
                    "employee_id": employee_id,
                    "leave_type_id": annual_leave["id"],
                    "year": target_year,
                },
                select="id, used_days",
            )

            if existing_balance:
                used = existing_balance.get("used_days") or 0
                balance_repo.update(
                    existing_balance["id"],
                    {"total_days": new_days, "remaining_days": new_days - used},
                )
            else:
                balance_repo.create(
                    {
                        "employee_id": employee_id,
                        "leave_type_id": annual_leave["id"],
                        "year": target_year,
                        "total_days": new_days,
                        "used_days": 0,
                        "remaining_days": new_days,
                    }
                )

            updated += 1

        record_audit_log(
            module="LEAVE",
            action="RECOMPUTE_ANNUAL_LEAVE_TENURE",
            performed_by=getattr(current_user, "id", None),
            description=f"Recomputed Annual Leave 10-day tier for {target_year}: "
            f"{updated} updated, {skipped} skipped.",
        )

        return success_response(
            message="Annual Leave 10-day tier recomputed.",
            data={"year": target_year, "updated": updated, "skipped": skipped},
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to recompute Annual Leave tenure tiers.")


# ==========================================
# AD HOC LEAVE BALANCE GRANTS — Compassionate Leave (boss's discretion)
# ==========================================
# Compassionate Leave has no company-wide default_days (it's 0 in
# leave_types) because, per the client, it isn't a policy number at
# all -- "compassionate leave, this is based on Boss, how many he will
# give to employee" -- it's decided case by case, per employee, by
# whoever approves it. There was previously no way to actually act on
# that decision: HR had no way to grant a specific employee a specific
# number of Compassionate Leave days, so the balance stayed 0/0
# forever. This adds that grant, modelled the same way as
# credit_replacement_leave (an explicit, audited HR action) but adding
# straight to a leave_balances row rather than to an event-credit
# table, since Compassionate Leave is consumed like any other
# fixed-mode balance once granted.
#
# Generic by design (works for any 'fixed' mode leave type, not only
# Compassionate Leave) in case another ad hoc/discretionary leave type
# is added later -- but tiered/event/not_a_balance types have their own
# dedicated mechanisms (tier assignment / replacement credits / no
# balance at all) and are rejected here on purpose.


def grant_leave_balance_days(
    employee_id: str,
    leave_name: str,
    days: int,
    granted_by: Optional[str] = None,
    year: Optional[int] = None,
    request=None,
):
    try:
        if days <= 0:
            bad_request("Days granted must be a positive number.")

        employee = employee_repo.get_by_id_or_404(employee_id, "Employee not found.")
        leave_type = get_leave_type_or_404(leave_name)

        if leave_type.get("entitlement_mode") != "fixed":
            bad_request(
                f"{leave_name} isn't a manually-granted leave type. "
                "Tiered types use tier assignment, event types use their "
                "own credit mechanism."
            )

        eligible, reason = evaluate_leave_eligibility(employee, leave_type["id"])
        if not eligible:
            bad_request(reason or f"Employee is not eligible for {leave_name}.")

        target_year = year or datetime.now(timezone.utc).year

        existing = balance_repo.find_one(
            {
                "employee_id": employee_id,
                "leave_type_id": leave_type["id"],
                "year": target_year,
            },
            select="id, total_days, used_days, remaining_days",
        )

        if existing:
            new_total = (existing.get("total_days") or 0) + days
            new_remaining = (existing.get("remaining_days") or 0) + days
            balance = balance_repo.update(
                existing["id"],
                {"total_days": new_total, "remaining_days": new_remaining},
            )
        else:
            balance = balance_repo.create(
                {
                    "employee_id": employee_id,
                    "leave_type_id": leave_type["id"],
                    "year": target_year,
                    "total_days": days,
                    "used_days": 0,
                    "remaining_days": days,
                }
            )

        record_audit_log(
            module="LEAVE",
            action="GRANT_LEAVE_BALANCE",
            performed_by=granted_by,
            target_employee_id=employee_id,
            record_id=balance.get("id"),
            description=(
                f"Granted {days} day(s) of {leave_name.title()} for "
                f"{target_year} (discretionary)."
            ),
            new_values=balance,
            request=request,
        )

        return success_response(
            message=f"{days} day(s) of {leave_name.title()} granted.", data=balance
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to grant leave balance.")


# ==========================================
# MY LEAVE ENTITLEMENTS (self-service — "Apply Leave" screen)
# ==========================================
# This is what actually backs the "Leave Type Entitlements" panel on the
# employee Apply Leave page. It replaces the old frontend approach of a
# hardcoded LEAVE_TYPES list applied identically to every employee
# (which is why Maternity Leave used to show up for male employees —
# the UI never asked the backend who was eligible for what, it just
# rendered the same static array for everyone). Every number here comes
# from the real policy engine: leave_eligibility_rules decides *whether*
# an employee sees a leave type at all, and leave_balances / tier /
# replacement-credit tables decide *how many* days.


def get_all_leave_balances(year: Optional[int] = None):
    """
    Company-wide leave balances for the HR Leave Balance screen.

    Returns { balances: [{employee_id, leave_type_id, leave_name, total_days,
    used_days, remaining_days, year}] } -- the same numbers employees see on
    Apply Leave: leave_balances rows for the year, plus Replacement Leave
    built from unused, unexpired credits. Leave types with no balance
    (Unpaid, NS, MC...) have no row and are omitted.
    """
    try:
        year = year or datetime.now(timezone.utc).year

        leave_types, _ = leave_type_repo.list(select="id, leave_name")
        name_by_id = {lt["id"]: lt.get("leave_name") for lt in leave_types}

        rows = []
        page_size = 1000
        start = 0
        while True:
            chunk, _total = balance_repo.list(
                select="employee_id, leave_type_id, total_days, used_days, remaining_days, year",
                filters={"year": year},
                start=start,
                end=start + page_size - 1,
            )
            rows.extend(chunk)
            if len(chunk) < page_size:
                break
            start += page_size

        balances = []
        for r in rows:
            leave_name = name_by_id.get(r.get("leave_type_id"))
            if not leave_name:
                continue
            balances.append(
                {
                    "employee_id": r["employee_id"],
                    "leave_type_id": r["leave_type_id"],
                    "leave_name": leave_name,
                    "total_days": r.get("total_days") or 0,
                    "used_days": r.get("used_days") or 0,
                    "remaining_days": r.get("remaining_days") or 0,
                    "year": r.get("year"),
                }
            )

        # Replacement Leave lives in credits, not leave_balances.
        replacement_type_id = next(
            (
                lt["id"]
                for lt in leave_types
                if (lt.get("leave_name") or "").strip().upper() == REPLACEMENT_LEAVE
            ),
            None,
        )
        if replacement_type_id:
            today = date.today().isoformat()
            credits = (
                supabase_admin.table("leave_replacement_credits")
                .select("employee_id, days, used_days")
                .eq("used", False)
                .gte("expiry_date", today)
                .execute()
                .data
                or []
            )
            by_employee = {}
            for c in credits:
                total = float(c.get("days") or 1)
                used = float(c.get("used_days") or 0)
                agg = by_employee.setdefault(c["employee_id"], [0.0, 0.0])
                agg[0] += total
                agg[1] += used
            for employee_id, (total, used) in by_employee.items():
                balances.append(
                    {
                        "employee_id": employee_id,
                        "leave_type_id": replacement_type_id,
                        "leave_name": name_by_id[replacement_type_id],
                        "total_days": total,
                        "used_days": used,
                        "remaining_days": total - used,
                        "year": year,
                    }
                )

        # MC-only staff: show their MC balance (default 14 days, or HR's
        # override) even before they have a leave_balances row, so HR's Leave
        # Balance screen isn't empty for them. Nothing is written here; used
        # days are counted from their pending / approved MC requests.
        sick_type = next(
            (
                lt
                for lt in leave_types
                if (lt.get("leave_name") or "").strip().upper() == SICK_LEAVE
            ),
            None,
        )
        if sick_type:
            sick_default = (
                leave_type_repo.get_by_id(sick_type["id"], select="default_days") or {}
            ).get("default_days") or 0
            have_sick = {
                b["employee_id"]
                for b in balances
                if b["leave_type_id"] == sick_type["id"]
            }
            mc_only_staff, _ = employee_repo.list(
                select="id",
                filters={"employment_status": "Active", "leave_scheme": SCHEME_MC_ONLY},
            )
            used_by_employee = {}
            for lr in (
                supabase_admin.table("leave_requests")
                .select("employee_id, total_days, status, start_date")
                .eq("leave_type_id", sick_type["id"])
                .in_("status", ["Pending", "Approved"])
                .gte("start_date", f"{year}-01-01")
                .lte("start_date", f"{year}-12-31")
                .execute()
                .data
                or []
            ):
                used_by_employee[lr["employee_id"]] = used_by_employee.get(
                    lr["employee_id"], 0.0
                ) + float(lr.get("total_days") or 0)

            for emp in mc_only_staff:
                if emp["id"] in have_sick:
                    continue
                override = _get_employee_leave_override_days(emp["id"], sick_type["id"])
                total = float(override if override is not None else sick_default)
                used = used_by_employee.get(emp["id"], 0.0)
                balances.append(
                    {
                        "employee_id": emp["id"],
                        "leave_type_id": sick_type["id"],
                        "leave_name": name_by_id[sick_type["id"]],
                        "total_days": total,
                        "used_days": used,
                        "remaining_days": total - used,
                        "year": year,
                    }
                )

        return success_response(
            message="Leave balances fetched successfully.",
            data={"balances": balances},
        )
    except Exception as e:
        logger.error(f"get_all_leave_balances failed: {e}")
        if hasattr(e, "status_code"):
            raise
        internal_server_error("Failed to fetch leave balances.")


def get_my_leave_entitlements(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            return success_response(
                message="Leave entitlements fetched successfully.", data=[]
            )

        employee = employee_repo.get_by_id_or_404(employee_id, "Employee not found.")

        leave_types, _total = leave_type_repo.list(
            select="id, leave_name, default_days, entitlement_mode, is_paid, hr_managed",
            order_by="leave_name",
        )

        current_year = datetime.now(timezone.utc).year
        entitlements = []
        scheme = get_leave_scheme(employee)

        for leave_type in leave_types:
            leave_type_id = leave_type["id"]
            leave_name = (leave_type.get("leave_name") or "").strip().upper()
            mode = leave_type.get("entitlement_mode")

            # Gate on eligibility first (gender / marital_status /
            # nationality / employee_type). An employee who isn't
            # eligible for a leave type never sees it here, full stop —
            # this is the fix for e.g. Maternity Leave rendering for a
            # male employee.
            # Who sees what (Singapore leave rules): Hospitalisation and
            # Maternity are HR-only; MC-only staff see just MC and no
            # balance; the Singapore list sees Annual / MC / Replacement /
            # Childcare (Childcare only where HR has set it up).
            eligible, reason = evaluate_self_apply_access(employee, leave_type)
            if not eligible:
                continue

            if scheme == SCHEME_SG_LIST and leave_name == CHILDCARE_LEAVE:
                has_childcare = balance_repo.find_one(
                    {
                        "employee_id": employee_id,
                        "leave_type_id": leave_type_id,
                        "year": current_year,
                    },
                    select="id",
                )
                if not has_childcare:
                    continue

            entry = {
                "leave_type_id": leave_type_id,
                "leave_name": leave_type.get("leave_name"),
                "entitlement_mode": mode,
                "is_paid": leave_type.get("is_paid"),
                "total_days": None,
                "used_days": None,
                "remaining_days": None,
                "unlimited": False,
                "tier_not_assigned": False,
                "show_balance": True,
            }

            if mode == "not_a_balance":
                # Unpaid Leave — no balance, no cap.
                entry["unlimited"] = True

            elif mode == "event" and leave_name == NATIONAL_SERVICE_LEAVE:
                # NS Leave — no pre-set balance, no cap.
                entry["unlimited"] = True

            elif mode == "event" and leave_name == REPLACEMENT_LEAVE:
                available = get_unused_replacement_credit_days(employee_id)
                entry["total_days"] = available
                entry["used_days"] = 0
                entry["remaining_days"] = available

            elif mode == "event":
                entry["unlimited"] = True

            else:
                # fixed / tiered — this employee's real, per-person
                # balance row for the current year, not a generic
                # leave_types.default_days constant.
                balance = balance_repo.find_one(
                    {
                        "employee_id": employee_id,
                        "leave_type_id": leave_type_id,
                        "year": current_year,
                    },
                    select="total_days, used_days, remaining_days",
                )
                if balance:
                    entry["total_days"] = balance.get("total_days") or 0
                    entry["used_days"] = balance.get("used_days") or 0
                    entry["remaining_days"] = balance.get("remaining_days") or 0
                elif mode == "fixed":
                    # No balance row yet (HR hasn't run the yearly
                    # generator). Every eligible employee gets
                    # default_days, UNLESS this specific employee has a
                    # Chennai Leave Default (or other) override row —
                    # checked first so the preview matches what
                    # _resolve_days_for_employee will actually grant.
                    override_days = _get_employee_leave_override_days(
                        employee_id, leave_type_id
                    )
                    default_days = (
                        override_days
                        if override_days is not None
                        else (leave_type.get("default_days") or 0)
                    )
                    entry["total_days"] = default_days
                    entry["used_days"] = 0
                    entry["remaining_days"] = default_days
                else:
                    # tiered, no tier assigned / no balance yet — we
                    # genuinely don't know this employee's number (could
                    # be 21, 20, 14, 11, or 10 days for Annual Leave), so
                    # show 0 rather than guessing, and let generate the
                    # balances / assign a tier fix it properly.
                    entry["total_days"] = 0
                    entry["used_days"] = 0
                    entry["remaining_days"] = 0
                    entry["tier_not_assigned"] = True

            entitlements.append(entry)

        return success_response(
            message="Leave entitlements fetched successfully.", data=entitlements
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch leave entitlements.")


# ==========================================
# YEARLY LEAVE BALANCE GENERATOR
# ==========================================


def _resolve_days_for_employee(employee: dict, leave_type: dict) -> Optional[int]:
    """
    Returns the number of days to grant this employee for this leave
    type this year, or None if it should be skipped (tiered type with
    no tier assigned).
    """

    mode = leave_type.get("entitlement_mode")
    leave_name = (leave_type.get("leave_name") or "").strip().upper()

    if mode == "fixed":
        override_days = _get_employee_leave_override_days(
            employee["id"], leave_type["id"]
        )
        if override_days is not None:
            return override_days
        return leave_type.get("default_days") or 0

    if mode == "tiered":
        # A number typed on the user form (employee_leave_overrides) wins
        # over the tier; assigning a tier later clears it again.
        override_days = _get_employee_leave_override_days(
            employee["id"], leave_type["id"]
        )
        if override_days is not None:
            return override_days

        assignment = get_employee_leave_tier(employee["id"], leave_type["id"])

        if not assignment or not assignment.get("leave_policy_tiers"):
            return None

        tier = assignment["leave_policy_tiers"]

        if leave_name == ANNUAL_LEAVE and tier.get("tier_name") == TENURE_TIER_NAME:
            return compute_annual_leave_10_day_days(employee.get("joining_date"))

        return tier.get("days") or 0

    # event / not_a_balance never get a leave_balances row.
    return None


def generate_yearly_leave_balances(year: Optional[int] = None, current_user=None):
    """
    For every employee, for every fixed/tiered leave type: check
    eligibility, resolve the day count (tier or default_days), and
    upsert leave_balances. event/not_a_balance types are skipped
    entirely — they're never represented as a balance row.
    """

    try:
        target_year = year or datetime.now(timezone.utc).year

        leave_types, _total = leave_type_repo.list(
            select="id, leave_name, default_days, entitlement_mode",
        )
        applicable_types = [
            lt
            for lt in leave_types
            if lt.get("entitlement_mode") in ("fixed", "tiered")
        ]

        employees, _total = employee_repo.list(
            select="id, joining_date, nationality, marital_status, gender, employment_status, leave_scheme",
            filters={"employment_status": "Active"},
        )

        created = 0
        updated = 0
        skipped_ineligible = 0
        skipped_no_tier = 0

        for employee in employees:
            for leave_type in applicable_types:
                # MC-only staff get an MC balance (hidden from them) and
                # nothing else.
                if (
                    get_leave_scheme(employee) == SCHEME_MC_ONLY
                    and (leave_type.get("leave_name") or "").strip().upper()
                    != SICK_LEAVE
                ):
                    continue

                eligible, _reason = evaluate_leave_eligibility(
                    employee, leave_type["id"]
                )

                if not eligible:
                    skipped_ineligible += 1
                    continue

                days = _resolve_days_for_employee(employee, leave_type)

                if days is None:
                    skipped_no_tier += 1
                    continue

                existing = balance_repo.find_one(
                    {
                        "employee_id": employee["id"],
                        "leave_type_id": leave_type["id"],
                        "year": target_year,
                    },
                    select="id, used_days",
                )

                if existing:
                    used = existing.get("used_days") or 0
                    balance_repo.update(
                        existing["id"],
                        {"total_days": days, "remaining_days": days - used},
                    )
                    updated += 1
                else:
                    balance_repo.create(
                        {
                            "employee_id": employee["id"],
                            "leave_type_id": leave_type["id"],
                            "year": target_year,
                            "total_days": days,
                            "used_days": 0,
                            "remaining_days": days,
                        }
                    )
                    created += 1

        record_audit_log(
            module="LEAVE",
            action="GENERATE_YEARLY_BALANCES",
            performed_by=getattr(current_user, "id", None),
            description=(
                f"Generated {target_year} leave balances: {created} created, "
                f"{updated} updated, {skipped_ineligible} skipped (ineligible), "
                f"{skipped_no_tier} skipped (no tier assigned)."
            ),
        )

        return success_response(
            message="Yearly leave balances generated.",
            data={
                "year": target_year,
                "created": created,
                "updated": updated,
                "skipped_ineligible": skipped_ineligible,
                "skipped_no_tier": skipped_no_tier,
            },
        )

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to generate yearly leave balances.")
