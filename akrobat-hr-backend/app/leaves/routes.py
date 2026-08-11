from fastapi import APIRouter, Depends, Query, Request

from app.leaves.schemas import (
    CreateLeaveRequest,
    UpdateLeaveStatusRequest,
    AssignLeaveTierRequest,
    CreditReplacementLeaveRequest,
    GenerateYearlyBalancesRequest,
    GrantLeaveBalanceRequest,
)

from app.leaves.services import (
    apply_leave,
    get_my_leaves,
    get_all_leaves,
    get_leave_types,
    get_team_leaves,
    update_leave_status,
)
from app.leaves.policy_services import (
    get_tiers_for_leave_type,
    assign_employee_leave_tier,
    check_leave_eligibility,
    credit_replacement_leave,
    get_replacement_leave_credits,
    generate_yearly_leave_balances,
    recompute_annual_leave_tenure_tiers,
    get_my_leave_entitlements,
    grant_leave_balance_days,
)
from app.core.helpers.employee_helper import get_employee_id_for_auth_user

from app.core.security import get_current_user
from app.core.rbac import require_permission
from app.core.permissions import require_role
from app.core.constants import ADMIN, HR

router = APIRouter(prefix="/leaves", tags=["Leaves"])


# ==========================================
# APPLY LEAVE (self-service — any authenticated employee)
# ==========================================


@router.post("/")
def create_leave(
    data: CreateLeaveRequest, request: Request, user=Depends(get_current_user)
):
    return apply_leave(user.id, data, request=request)


# ==========================================
# GET MY LEAVES (self-service — own records only)
# ==========================================


@router.get("/my")
def my_leaves(user=Depends(get_current_user)):
    return get_my_leaves(user.id)


# ==========================================
# GET MY LEAVE ENTITLEMENTS (self-service — own eligibility + balances)
# ==========================================
# Backs the "Leave Type Entitlements" panel on the Apply Leave screen.
# Only returns leave types this employee is actually eligible for
# (leave_eligibility_rules), with each type's real total/used/remaining
# days pulled from their own leave_balances / tier / replacement-credit
# records — never a one-size-fits-all constant.


@router.get("/my-entitlements")
def my_leave_entitlements(user=Depends(get_current_user)):
    return get_my_leave_entitlements(user.id)


# ==========================================
# GET TEAM LEAVES (Manager / HR — view only, direct + indirect reports)
# ==========================================


@router.get("/team")
def team_leaves(user=Depends(require_permission("VIEW_LEAVE_REQUESTS"))):
    return get_team_leaves(user.id)


# ==========================================
# GET ALL LEAVES (HR / Admin only — company-wide view)
# ==========================================


@router.get("/")
def all_leaves(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    user=Depends(require_permission("VIEW_LEAVE_REQUESTS")),
):
    return get_all_leaves(page=page, limit=limit, status=status)


# ==========================================
# GET LEAVE TYPES (HR / Admin — org-wide list with default_days/allocation)
# ==========================================


@router.get("/types")
def leave_types(user=Depends(require_permission("VIEW_LEAVE_REQUESTS"))):
    return get_leave_types()


# ==========================================
# APPROVE / REJECT LEAVE
# (SUPER ADMIN only — company policy: no other role may approve/reject
#  leave, regardless of what's granted in role_permissions)
# ==========================================


@router.put("/{leave_id}")
def update_status(
    leave_id: str,
    data: UpdateLeaveStatusRequest,
    request: Request,
    user=Depends(require_role([ADMIN])),
):
    return update_leave_status(leave_id, data, auth_user_id=user.id, request=request)


# ==========================================
# LEAVE POLICY ENGINE (HR / Admin)
# ==========================================


@router.get("/policy/tiers/{leave_name}")
def leave_policy_tiers(
    leave_name: str, user=Depends(require_permission("VIEW_LEAVE_REQUESTS"))
):
    """Tier options for a tiered leave type, e.g. ANNUAL LEAVE / CHILDCARE LEAVE.
    Used to populate the Annual Leave / Childcare Leave tier dropdowns on
    the Employee create/edit form."""
    return get_tiers_for_leave_type(leave_name)


@router.post("/policy/assign-tier")
def assign_tier(
    data: AssignLeaveTierRequest,
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    return assign_employee_leave_tier(
        str(data.employee_id),
        data.leave_type,
        str(data.tier_id),
        assigned_by=get_employee_id_for_auth_user(user.id),
    )


@router.get("/policy/eligibility/{employee_id}/{leave_name}")
def leave_eligibility(
    employee_id: str,
    leave_name: str,
    user=Depends(require_permission("VIEW_LEAVE_REQUESTS")),
):
    return check_leave_eligibility(employee_id, leave_name)


@router.post("/policy/replacement-credits")
def credit_replacement(
    data: CreditReplacementLeaveRequest,
    request: Request,
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    """HR: credit one Replacement Leave day for a public holiday that
    fell on a Saturday. Gated to office employees — field employees are
    excluded via leave_eligibility_rules."""
    return credit_replacement_leave(
        str(data.employee_id),
        data.public_holiday_date,
        credited_by=get_employee_id_for_auth_user(user.id),
        request=request,
    )


@router.get("/policy/replacement-credits/{employee_id}")
def replacement_credits(
    employee_id: str, user=Depends(require_permission("VIEW_LEAVE_REQUESTS"))
):
    return get_replacement_leave_credits(employee_id)


@router.post("/policy/grant-balance")
def grant_balance(
    data: GrantLeaveBalanceRequest,
    request: Request,
    user=Depends(require_permission("EDIT_EMPLOYEE")),
):
    """HR/boss: grant an employee a specific number of days for a
    discretionary 'fixed' leave type — e.g. Compassionate Leave, which
    per company policy has no set company-wide amount and is decided
    case by case ("based on Boss, how many he will give to employee").
    Not for Annual/Childcare Leave (use tier assignment) or
    Replacement/NS Leave (their own event mechanisms)."""
    return grant_leave_balance_days(
        str(data.employee_id),
        data.leave_type,
        data.days,
        granted_by=get_employee_id_for_auth_user(user.id),
        year=data.year,
        request=request,
    )


@router.post("/policy/generate-yearly-balances")
def generate_yearly_balances(
    data: GenerateYearlyBalancesRequest,
    user=Depends(require_role([ADMIN, HR])),
):
    """HR/Admin-triggered batch job — run once a year (or re-run safely
    any time) to (re)populate leave_balances for every active employee
    across all fixed/tiered leave types."""
    return generate_yearly_leave_balances(data.year, current_user=user)


@router.post("/policy/recompute-annual-tenure")
def recompute_annual_tenure(
    data: GenerateYearlyBalancesRequest,
    user=Depends(require_role([ADMIN, HR])),
):
    """HR/Admin-triggered — recompute the +1 day/year (capped at 14)
    tenure bonus for employees on the Annual Leave 10-day tier."""
    return recompute_annual_leave_tenure_tiers(data.year, current_user=user)
