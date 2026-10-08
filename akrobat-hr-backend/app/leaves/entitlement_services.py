"""
Leave entitlements as plain "days" inputs (Create / Edit User form) and
HR-defined leave types.

How the numbers are stored (no new tables):

  fixed / tiered types (Annual, Medical/MC, Childcare, Maternity, Paternity,
  and any custom type)
      -> employee_leave_overrides(employee_id, leave_type_id, days)   [the
         per-employee number the yearly generator will keep using]
      -> leave_balances (current year) is updated immediately so the
         employee sees the number straight away.

  Replacement Leave (event type, credit based)
      -> a leave_replacement_credits row for the days entered
         (expires in 1 year like every other credit). Can only be
         increased from the form; reducing credits isn't supported here.

An employee's tier (employee_leave_tier) is left alone. While an override
exists it wins over the tier; assigning a tier later through
assign_employee_leave_tier() removes the override again.
"""

from datetime import date, datetime, timezone
from typing import Any, Optional

from app.core.audit import record_audit_log
from app.core.exceptions import bad_request, internal_server_error
from app.core.logger import logger
from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from fastapi import HTTPException

from app.leaves.policy_services import (
    REPLACEMENT_LEAVE,
    ANNUAL_LEAVE,
    SICK_LEAVE,
    CHILDCARE_LEAVE,
    balance_repo,
    employee_repo,
    employee_tier_repo,
    eligibility_repo,
    evaluate_leave_eligibility,
    get_unused_replacement_credit_days,
    leave_override_repo,
    leave_type_repo,
    replacement_credit_repo,
    tier_repo,
)

MAX_DAYS = 365

# Order + friendly labels for the compact form. Anything not listed here
# (i.e. HR-added types) comes after, alphabetically.
FORM_ORDER = [
    ANNUAL_LEAVE,
    SICK_LEAVE,
    "CASUAL LEAVE",
    REPLACEMENT_LEAVE,
    CHILDCARE_LEAVE,
    "MATERNITY LEAVE",
    "PATERNITY LEAVE",
]
FORM_LABELS = {
    SICK_LEAVE: "Medical Leave (MC)",
}


def _label(leave_name: str) -> str:
    name = (leave_name or "").strip().upper()
    return FORM_LABELS.get(name, name.title())


def _clean_days(value: Any, leave_name: str = "") -> float:
    try:
        days = float(value)
    except (TypeError, ValueError):
        bad_request(f"Invalid number of days for {_label(leave_name) or 'leave'}.")
    if days < 0 or days > MAX_DAYS:
        bad_request(f"Days must be between 0 and {MAX_DAYS}.")
    if round(days * 2) != days * 2:
        bad_request("Days can only be whole or half days (e.g. 7 or 7.5).")
    return days


def _item(entry: Any) -> tuple[str, Any]:
    """Accepts a dict or a pydantic model."""
    if isinstance(entry, dict):
        return str(entry.get("leave_type_id")), entry.get("days")
    return str(getattr(entry, "leave_type_id")), getattr(entry, "days")


# ==========================================
# FORM CONFIG — which leave types the form shows
# ==========================================


def get_entitlement_form_types():
    try:
        leave_types, _ = leave_type_repo.list(
            select="id, leave_name, description, default_days, entitlement_mode, "
            "is_paid, hr_managed, show_in_user_form",
            filters={"show_in_user_form": True},
        )

        # Casual Leave is part of the Standard (Chennai) scheme -- 12 Sick /
        # 12 Casual / 12 Annual -- so it always gets a days box, whatever
        # show_in_user_form says.
        if not any(
            (lt.get("leave_name") or "").strip().upper() == "CASUAL LEAVE"
            for lt in leave_types
        ):
            casual, _ = leave_type_repo.list(
                select="id, leave_name, description, default_days, entitlement_mode, "
                "is_paid, hr_managed, show_in_user_form",
                filters={"leave_name": "CASUAL LEAVE"},
            )
            leave_types = list(leave_types) + list(casual or [])

        rules, _ = eligibility_repo.list(select="leave_type_id, field, value, eligible")
        excluded: dict[str, list] = {}
        for rule in rules:
            # Only the fields the form itself knows about (gender / marital
            # status). nationality / employee_type are decided server-side.
            if rule.get("eligible") is False and rule.get("field") in (
                "gender",
                "marital_status",
            ):
                excluded.setdefault(str(rule["leave_type_id"]), []).append(
                    {"field": rule["field"], "value": rule["value"]}
                )

        def sort_key(lt):
            name = (lt.get("leave_name") or "").strip().upper()
            if name in FORM_ORDER:
                return (0, FORM_ORDER.index(name), "")
            return (1, 0, name)

        data = []
        for lt in sorted(leave_types, key=sort_key):
            name = (lt.get("leave_name") or "").strip().upper()
            data.append(
                {
                    "id": lt["id"],
                    "leave_name": name,
                    "label": _label(name),
                    "default_days": lt.get("default_days") or 0,
                    "entitlement_mode": lt.get("entitlement_mode"),
                    "hr_managed": bool(lt.get("hr_managed")),
                    "excluded_when": excluded.get(str(lt["id"]), []),
                }
            )

        return success_response(message="Leave types fetched.", data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch leave types for the form.")


# ==========================================
# CURRENT VALUES (Edit User)
# ==========================================


def get_employee_entitlement_days(employee_id: str):
    """{leave_type_id: days} — what this employee currently has this year."""
    try:
        year = datetime.now(timezone.utc).year
        result: dict[str, Optional[float]] = {}

        leave_types, _ = leave_type_repo.list(
            select="id, leave_name, entitlement_mode",
            filters={"show_in_user_form": True},
        )

        for lt in leave_types:
            lt_id = str(lt["id"])
            name = (lt.get("leave_name") or "").strip().upper()

            if name == REPLACEMENT_LEAVE:
                result[lt_id] = get_unused_replacement_credit_days(employee_id)
                continue

            balance = balance_repo.find_one(
                {"employee_id": employee_id, "leave_type_id": lt_id, "year": year},
                select="total_days",
            )
            if balance and balance.get("total_days") is not None:
                result[lt_id] = float(balance["total_days"])
                continue

            override = leave_override_repo.find_one(
                {"employee_id": employee_id, "leave_type_id": lt_id}, select="days"
            )
            if override and override.get("days") is not None:
                result[lt_id] = float(override["days"])
                continue

            assignment = employee_tier_repo.find_one(
                {"employee_id": employee_id, "leave_type_id": lt_id}, select="tier_id"
            )
            if assignment:
                tier = tier_repo.get_by_id(str(assignment["tier_id"]), select="days")
                if tier and tier.get("days") is not None:
                    result[lt_id] = float(tier["days"])

        return success_response(message="Entitlements fetched.", data=result)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch leave entitlements.")


# ==========================================
# VALIDATE (before anything is saved) + APPLY
# ==========================================


def validate_leave_entitlements(employee_id: Optional[str], entries: list) -> list:
    """
    Raises 400 on bad input. Returns normalised [(leave_type, days)].
    Called BEFORE the employee row is touched on edit, so a rejected
    value never leaves a half-saved employee behind.
    """
    normalised = []
    seen = set()

    for entry in entries or []:
        lt_id, raw_days = _item(entry)
        if lt_id in seen:
            bad_request("The same leave type was sent twice.")
        seen.add(lt_id)

        leave_type = leave_type_repo.get_by_id(
            lt_id, select="id, leave_name, entitlement_mode"
        )
        if not leave_type:
            bad_request("Unknown leave type.")

        name = (leave_type.get("leave_name") or "").strip().upper()
        days = _clean_days(raw_days, name)
        mode = leave_type.get("entitlement_mode")

        if mode in ("not_a_balance",) or (
            mode == "event" and name != REPLACEMENT_LEAVE
        ):
            bad_request(f"{_label(name)} doesn't take a days entitlement.")

        if name == REPLACEMENT_LEAVE and employee_id:
            current = get_unused_replacement_credit_days(employee_id)
            if days < current:
                bad_request(
                    f"Replacement Leave can't be reduced here (currently "
                    f"{current:g} day(s) available). You can only add more."
                )

        normalised.append((leave_type, days))

    return normalised


def apply_leave_entitlements(
    employee: dict,
    entries: list,
    assigned_by: Optional[str] = None,
    normalised: Optional[list] = None,
):
    """
    Writes the entered days for one employee. `employee` is the saved
    employees row (needed for the eligibility check). Ineligible leave
    types (e.g. Maternity for a male employee) are skipped, not errors.
    """
    employee_id = str(employee["id"])
    normalised = (
        normalised
        if normalised is not None
        else validate_leave_entitlements(employee_id, entries)
    )
    year = datetime.now(timezone.utc).year
    applied, skipped = [], []

    for leave_type, days in normalised:
        name = (leave_type.get("leave_name") or "").strip().upper()

        eligible, _reason = evaluate_leave_eligibility(employee, leave_type["id"])
        if not eligible:
            skipped.append(name)
            logger.info(f"Skipped {name} entitlement for {employee_id}: not eligible.")
            continue

        # ---- Replacement Leave: credit rows -------------------------
        if name == REPLACEMENT_LEAVE:
            diff = days - get_unused_replacement_credit_days(employee_id)
            if diff > 0:
                today = date.today()
                try:
                    expiry = today.replace(year=today.year + 1)
                except ValueError:
                    expiry = today.replace(year=today.year + 1, day=28)
                replacement_credit_repo.create(
                    {
                        "employee_id": employee_id,
                        "public_holiday_date": str(today),
                        "credited_by": assigned_by,
                        "credited_date": str(today),
                        "expiry_date": str(expiry),
                        "days": diff,
                        "used": False,
                    }
                )
            applied.append(name)
            continue

        # ---- fixed / tiered: override + this year's balance ----------
        existing_override = leave_override_repo.find_one(
            {"employee_id": employee_id, "leave_type_id": leave_type["id"]},
            select="id",
        )
        if existing_override:
            leave_override_repo.update(existing_override["id"], {"days": days})
        else:
            leave_override_repo.create(
                {
                    "employee_id": employee_id,
                    "leave_type_id": leave_type["id"],
                    "days": days,
                }
            )

        balance = balance_repo.find_one(
            {
                "employee_id": employee_id,
                "leave_type_id": leave_type["id"],
                "year": year,
            },
            select="id, used_days",
        )
        if balance:
            used = float(balance.get("used_days") or 0)
            balance_repo.update(
                balance["id"], {"total_days": days, "remaining_days": days - used}
            )
        else:
            balance_repo.create(
                {
                    "employee_id": employee_id,
                    "leave_type_id": leave_type["id"],
                    "year": year,
                    "total_days": days,
                    "used_days": 0,
                    "remaining_days": days,
                }
            )
        applied.append(name)

    if applied:
        record_audit_log(
            module="LEAVE",
            action="SET_LEAVE_ENTITLEMENTS",
            performed_by=assigned_by,
            target_employee_id=employee_id,
            description="Leave days set from user form: " + ", ".join(applied),
            new_values={
                (lt.get("leave_name") or "").strip().upper(): d
                for lt, d in normalised
                if (lt.get("leave_name") or "").strip().upper() in applied
            },
        )

    return {"applied": applied, "skipped": skipped}


# ==========================================
# NEW LEAVE TYPE (HR / Super Admin)
# ==========================================

APPLIES_TO = ("ALL", "MALE", "FEMALE")


def create_leave_type(
    leave_name: str,
    default_days: float,
    applies_to: str = "ALL",
    married_only: bool = False,
    is_paid: bool = True,
    description: Optional[str] = None,
    created_by: Optional[str] = None,
    request=None,
):
    try:
        name = " ".join((leave_name or "").split()).upper()
        if len(name) < 2 or len(name) > 60:
            bad_request("Leave name must be 2–60 characters.")

        applies_to = (applies_to or "ALL").upper()
        if applies_to not in APPLIES_TO:
            bad_request("applies_to must be ALL, MALE or FEMALE.")

        days = _clean_days(default_days, name)

        if leave_type_repo.find_one({"leave_name": name}, select="id"):
            bad_request(f"'{name.title()}' already exists.")

        created = leave_type_repo.create(
            {
                "leave_name": name,
                "description": description or f"{name.title()} (added by HR)",
                "default_days": int(
                    days
                ),  # leave_types.default_days is an integer column
                "entitlement_mode": "fixed",
                "is_paid": bool(is_paid),
                "hr_managed": False,
                "show_in_user_form": True,
            }
        )

        # Eligibility is expressed with the same leave_eligibility_rules the
        # rest of the policy engine already uses.
        rules = []
        if applies_to == "MALE":
            rules.append(("gender", "Female"))
        elif applies_to == "FEMALE":
            rules.append(("gender", "Male"))
        if married_only:
            rules.append(("marital_status", "Single"))

        for field, value in rules:
            eligibility_repo.create(
                {
                    "leave_type_id": created["id"],
                    "field": field,
                    "value": value,
                    "eligible": False,
                }
            )

        record_audit_log(
            module="LEAVE",
            action="CREATE_LEAVE_TYPE",
            performed_by=created_by,
            record_id=created.get("id"),
            description=f"Leave type '{name}' created ({days:g} default days).",
            new_values=created,
            request=request,
        )

        return success_response(
            message=f"{name.title()} added.",
            data={
                "id": created["id"],
                "leave_name": name,
                "label": _label(name),
                "default_days": created.get("default_days") or 0,
                "entitlement_mode": "fixed",
                "hr_managed": False,
                "excluded_when": [{"field": f, "value": v} for f, v in rules],
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to create leave type.")
