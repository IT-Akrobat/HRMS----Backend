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
eligibility_repo = SupabaseRepository("leave_eligibility_rules")
balance_repo = SupabaseRepository("leave_balances")
replacement_credit_repo = SupabaseRepository("leave_replacement_credits")
employee_repo = SupabaseRepository("employees")

ANNUAL_LEAVE = "ANNUAL LEAVE"
CHILDCARE_LEAVE = "CHILDCARE LEAVE"
REPLACEMENT_LEAVE = "REPLACEMENT LEAVE"
NATIONAL_SERVICE_LEAVE = "NATIONAL SERVICE LEAVE"
UNPAID_LEAVE = "UNPAID LEAVE"

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

    tier = tier_repo.get_by_id(str(tier_id), select="id, leave_type_id")
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
        return employee_tier_repo.update(existing["id"], payload)

    return employee_tier_repo.create(payload)


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


def get_unused_replacement_credit_days(employee_id: str) -> int:
    """Unused, unexpired Replacement Leave credits available today."""

    today = date.today().isoformat()

    response = (
        supabase_admin.table("leave_replacement_credits")
        .select("id, expiry_date")
        .eq("employee_id", employee_id)
        .eq("used", False)
        .gte("expiry_date", today)
        .execute()
    )

    return len(response.data or [])


def consume_replacement_credits(
    employee_id: str, days_needed: int, leave_request_id: str
):
    """
    Marks the oldest-expiring `days_needed` unused, unexpired credits as
    used against this leave request. One credit = one day, so this is a
    straight FIFO-by-expiry consumption.
    """

    today = date.today().isoformat()

    response = (
        supabase_admin.table("leave_replacement_credits")
        .select("id")
        .eq("employee_id", employee_id)
        .eq("used", False)
        .gte("expiry_date", today)
        .order("expiry_date")
        .limit(days_needed)
        .execute()
    )

    credit_ids = [row["id"] for row in (response.data or [])]

    if len(credit_ids) < days_needed:
        bad_request("Not enough unused Replacement Leave credits available.")

    for credit_id in credit_ids:
        replacement_credit_repo.update(
            credit_id, {"used": True, "used_leave_request_id": leave_request_id}
        )


# ==========================================
# LEAVE REQUEST VALIDATION HOOK
# (called from app/leaves/services.py apply_leave)
# ==========================================


def validate_leave_request_against_entitlement(
    employee: dict, leave_type: dict, total_days: int
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
    balance = balance_repo.find_one(
        {
            "employee_id": employee["id"],
            "leave_type_id": leave_type["id"],
            "year": current_year,
        },
        select="id, remaining_days",
    )

    if not balance:
        bad_request(
            f"No {leave_name.title()} balance found for {current_year}. " "Contact HR."
        )

    if (balance.get("remaining_days") or 0) < total_days:
        bad_request(
            f"Insufficient {leave_name.title()} balance: "
            f"{balance.get('remaining_days')} day(s) remaining, "
            f"{total_days} requested."
        )


def apply_entitlement_on_approval(
    employee_id: str, leave_type: dict, total_days: int, leave_request_id: str
):
    """
    Called when a leave request is approved (see
    app/leaves/services.py update_leave_status). Deducts from whichever
    entitlement backs this leave type.
    """

    mode = leave_type.get("entitlement_mode")
    leave_name = (leave_type.get("leave_name") or "").strip().upper()

    if mode == "not_a_balance":
        return

    if mode == "event":
        if leave_name == REPLACEMENT_LEAVE:
            consume_replacement_credits(employee_id, total_days, leave_request_id)
        # NS Leave: nothing to deduct, no cap.
        return

    # fixed / tiered — decrement the current year's leave_balances row.
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
        # Shouldn't happen if validate_leave_request_against_entitlement
        # ran at apply time, but don't hard-fail an approval over it.
        logger.error(
            f"No leave_balances row for employee {employee_id}, "
            f"leave_type {leave_type['id']}, year {current_year} at approval time."
        )
        return

    new_used = (balance.get("used_days") or 0) + total_days
    new_remaining = (balance.get("total_days") or 0) - new_used

    balance_repo.update(
        balance["id"], {"used_days": new_used, "remaining_days": new_remaining}
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


def get_my_leave_entitlements(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)
        if not employee_id:
            return success_response(
                message="Leave entitlements fetched successfully.", data=[]
            )

        employee = employee_repo.get_by_id_or_404(employee_id, "Employee not found.")

        leave_types, _total = leave_type_repo.list(
            select="id, leave_name, default_days, entitlement_mode, is_paid",
            order_by="leave_name",
        )

        current_year = datetime.now(timezone.utc).year
        entitlements = []

        for leave_type in leave_types:
            leave_type_id = leave_type["id"]
            leave_name = (leave_type.get("leave_name") or "").strip().upper()
            mode = leave_type.get("entitlement_mode")

            # Gate on eligibility first (gender / marital_status /
            # nationality / employee_type). An employee who isn't
            # eligible for a leave type never sees it here, full stop —
            # this is the fix for e.g. Maternity Leave rendering for a
            # male employee.
            eligible, reason = evaluate_leave_eligibility(employee, leave_type_id)
            if not eligible:
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
                    # generator), but "fixed" means every eligible
                    # employee gets the exact same default_days — there's
                    # no per-person ambiguity to guess at, unlike tiered.
                    # Safe to show default_days as the entitlement even
                    # before a leave_balances row exists.
                    default_days = leave_type.get("default_days") or 0
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
        return leave_type.get("default_days") or 0

    if mode == "tiered":
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
            select="id, joining_date, nationality, marital_status, gender, employment_status",
            filters={"employment_status": "Active"},
        )

        created = 0
        updated = 0
        skipped_ineligible = 0
        skipped_no_tier = 0

        for employee in employees:
            for leave_type in applicable_types:
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
