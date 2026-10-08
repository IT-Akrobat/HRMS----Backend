from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from app.leaves.schemas import (
    CreateLeaveRequest,
    UpdateLeaveStatusRequest,
    AssignLeaveTierRequest,
    CreditReplacementLeaveRequest,
    GenerateYearlyBalancesRequest,
    GrantLeaveBalanceRequest,
    RecordHrManagedLeaveRequest,
    CreateLeaveTypeRequest,
)
from app.leaves.entitlement_services import (
    get_entitlement_form_types,
    get_employee_entitlement_days,
    create_leave_type,
)

from app.leaves.services import (
    apply_leave,
    get_my_leaves,
    get_all_leaves,
    get_leave_types,
    get_team_leaves,
    update_leave_status,
    record_hr_managed_leave,
)
from app.leaves.mc_services import (
    upload_medical_certificate,
    get_medical_certificate_url,
    validate_mc,
    get_mc_pending_validation,
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
    get_all_leave_balances,
)
from app.core.helpers.employee_helper import get_employee_id_for_auth_user

from app.core.security import get_current_user
from app.core.rbac import require_permission
from app.core.permissions import require_role
from app.core.constants import ADMIN, HR

HR_ROLES = [ADMIN, HR, "HR ADMIN", "HR EXECUTIVE"]

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
def team_leaves(user=Depends(get_current_user)):
    # Scoped inside get_team_leaves() to this person's reports and the
    # employees they are the assigned leave manager for.
    return get_team_leaves(user.id)


# ==========================================
# GET ALL LEAVES (HR / Admin only — company-wide view)
# ==========================================


@router.get("/")
def all_leaves(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    employee_id: str | None = Query(None),
    user=Depends(require_permission("VIEW_LEAVE_REQUESTS")),
):
    return get_all_leaves(
        page=page, limit=limit, status=status, employee_id=employee_id
    )


# ==========================================
# GET LEAVE TYPES (HR / Admin — org-wide list with default_days/allocation)
# ==========================================


@router.get("/types")
def leave_types(user=Depends(require_permission("VIEW_LEAVE_REQUESTS"))):
    return get_leave_types()


@router.post("/types")
def add_leave_type(
    data: CreateLeaveTypeRequest,
    request: Request,
    user=Depends(require_role(HR_ROLES)),
):
    """HR / Super Admin: add a new leave type (shows up as a days input on
    the Create / Edit User form straight away)."""
    return create_leave_type(
        data.leave_name,
        data.default_days,
        applies_to=data.applies_to,
        married_only=data.married_only,
        is_paid=data.is_paid,
        description=data.description,
        created_by=get_employee_id_for_auth_user(user.id),
        request=request,
    )


# ==========================================
# GET ALL LEAVE BALANCES (HR / Admin — backs the Leave Balance screen)
# Must be declared before any "/{leave_id}" route.
# ==========================================


@router.get("/balances")
def all_leave_balances(
    year: int | None = Query(None),
    user=Depends(require_permission("VIEW_LEAVE_REQUESTS")),
):
    return get_all_leave_balances(year)


# ==========================================
# APPROVE / REJECT LEAVE
# The employee's assigned leave manager (or Super Admin) decides. The
# leave-manager check lives in update_leave_status(), because it depends
# on WHICH employee the request belongs to, not just on the caller's role.
# ==========================================


@router.put("/{leave_id}")
def update_status(
    leave_id: str,
    data: UpdateLeaveStatusRequest,
    request: Request,
    user=Depends(get_current_user),
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


@router.get("/policy/entitlement-types")
def entitlement_types(user=Depends(require_permission("VIEW_LEAVE_REQUESTS"))):
    """Leave types that get a "days" input on the Create / Edit User form,
    with the gender / marital-status exclusions the form uses to hide
    e.g. Maternity for a male employee."""
    return get_entitlement_form_types()


@router.get("/policy/employee-entitlements/{employee_id}")
def employee_entitlements(
    employee_id: str, user=Depends(require_permission("VIEW_LEAVE_REQUESTS"))
):
    """{leave_type_id: days} currently set for this employee (Edit User)."""
    return get_employee_entitlement_days(employee_id)


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


# ==========================================
# MC (MEDICAL CERTIFICATE) FLOW
# ==========================================


@router.post("/{leave_id}/medical-certificate")
def upload_mc_certificate(
    leave_id: str,
    request: Request,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Step 2 of the MC flow: employee attaches the certificate. HR is notified."""
    return upload_medical_certificate(user.id, leave_id, file, request=request)


@router.get("/{leave_id}/medical-certificate")
def view_mc_certificate(leave_id: str, user=Depends(get_current_user)):
    """Short-lived link to the certificate (owner, leave manager, HR, Super Admin)."""
    return get_medical_certificate_url(user.id, leave_id)


@router.put("/{leave_id}/mc-validate")
def mc_validate(leave_id: str, request: Request, user=Depends(require_role(HR_ROLES))):
    """HR / Super Admin confirms the leave is a valid MC."""
    return validate_mc(user.id, leave_id, request=request)


# ==========================================
# HR / SUPER ADMIN: HOSPITALISATION + MATERNITY (hidden from employees)
# ==========================================


@router.post("/hr-managed")
def record_hr_leave(
    data: RecordHrManagedLeaveRequest,
    request: Request,
    user=Depends(require_role(HR_ROLES)),
):
    return record_hr_managed_leave(user.id, data, request=request)


@router.get("/mc/pending-validation")
def mc_pending_validation(user=Depends(require_role(HR_ROLES))):
    """HR / Super Admin queue: MCs not yet validated (oldest first)."""
    return get_mc_pending_validation()
