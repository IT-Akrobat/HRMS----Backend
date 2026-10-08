import re
from datetime import date, datetime
from typing import List, Optional, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.constants import ACTIVE
from app.leaves.schemas import LeaveEntitlementInput

WORKING_DAYS_PER_WEEK_OPTIONS = (5, 5.5, 6)

# "Working Location" -- where the employee works from. Distinct from the
# free-text `work_location` (city/office name used for timezone + holiday
# detection). Stored in employees.working_location (see sql/035.sql).
WORKING_LOCATION_OPTIONS = ("Office", "Site", "Office and Site")


def _clean_working_location(v):
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    # Case-insensitive match, stored in canonical casing.
    for option in WORKING_LOCATION_OPTIONS:
        if v.lower() == option.lower():
            return option
    raise ValueError(
        "working_location must be one of: " + ", ".join(WORKING_LOCATION_OPTIONS)
    )


# ==========================================
# Create Employee
# ==========================================


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=2, max_length=100)

    # Optional login username given by the company (e.g. "SAKTHI"). When
    # blank the employee's full name is still used to log in.
    username: Optional[str] = Field(default=None, max_length=50)

    @field_validator("username", mode="before")
    @classmethod
    def _clean_username(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        if not v:
            return None
        if not re.fullmatch(r"[A-Za-z0-9._-]{2,50}", v):
            raise ValueError(
                "Username must be 2-50 characters: letters, numbers, dot, "
                "underscore or hyphen (no spaces)."
            )
        return v

    # Optional. If left blank the employee is created with no email on
    # file (employees.email = NULL) and can log in with the employee code
    # + generated password as usual; HR can add the real email later via
    # Edit User (see app/employees/services.py create_employee()).
    email: Optional[EmailStr] = None

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # No longer accepted from the client -- see app/employees/services.py
    # create_employee(). The employee_id (code) is auto-generated from
    # the department and the login password is auto-generated too, both
    # via app/core/helpers/employee_helper.py, and the generated password
    # is returned once in the create response for HR to share.

    phone: Optional[str] = Field(default=None, max_length=20)

    department_id: Optional[UUID] = None
    designation_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    shift_id: Optional[UUID] = None

    role_id: UUID

    joining_date: Optional[date] = None

    date_of_birth: Optional[date] = None

    employment_status: str = ACTIVE

    work_location: Optional[str] = Field(default=None, max_length=150)

    working_location: Optional[str] = None

    @field_validator("working_location", mode="before")
    @classmethod
    def _validate_working_location(cls, v):
        return _clean_working_location(v)

    profile_photo: Optional[str] = None

    # Eligibility inputs for the leave policy engine (nationality/
    # marital_status/gender feed leave_eligibility_rules — e.g.
    # foreigners aren't eligible for NS Leave, single employees aren't
    # eligible for Paternity/Maternity/Childcare). Previously only
    # settable via the employee's own "My Profile" self-update; HR can
    # now set them at creation time too, since eligibility needs to be
    # known from day one, not just after the employee logs in once.
    gender: Optional[str] = Field(default=None, max_length=20)
    marital_status: Optional[str] = Field(default=None, max_length=20)
    nationality: Optional[str] = Field(default=None, max_length=100)

    # Tiered leave entitlement assignment. Annual Leave tier is
    # required -- every employee must be on one of the 21/20/14/11/10
    # day tiers. Childcare Leave tier is optional and only meaningful if
    # the employee passes the CHILDCARE LEAVE eligibility rules
    # (married); the create flow silently ignores it otherwise rather
    # than erroring, since the UI only shows the field when eligible.
    annual_leave_tier_id: Optional[UUID] = None

    childcare_leave_tier_id: Optional[UUID] = None

    # Days typed into the "Leave days" inputs on the Create User form
    # (Annual, Medical, Replacement, Childcare, Maternity, Paternity and any
    # HR-added leave type). See app/leaves/entitlement_services.py.
    # Only entries HR actually filled in are sent.
    leave_entitlements: Optional[List[LeaveEntitlementInput]] = None

    # Drives the Unpaid Leave payroll deduction (Unpaid Leave itself
    # never gets a leave_balances row -- see
    # app/leaves/policy_services.py). 5 / 5.5 / 6 per the Leave Info doc.
    # Deliberately independent of `works_saturday` below -- the payroll
    # doc doesn't tie 5.5-vs-6 to whether this employee's *shift*
    # actually includes Saturday hours, so HR sets this on its own.
    working_days_per_week: float = Field(default=5)

    @field_validator("working_days_per_week")
    @classmethod
    def _validate_working_days_per_week(cls, v):
        if v not in WORKING_DAYS_PER_WEEK_OPTIONS:
            raise ValueError("working_days_per_week must be 5, 5.5, or 6.")
        return v

    # Whether this employee's shift includes Saturday hours -- purely an
    # attendance concept (gates the Saturday-sibling-shift lookup in
    # app/attendance/services.py _get_employee_shift), unrelated to the
    # payroll working_days_per_week figure above.
    works_saturday: bool = Field(default=False)

    # Alternate Saturday schedule (works only the 2nd & 4th Saturday of
    # the month) -- a second, independent flag alongside works_saturday
    # rather than a redesign of it, so the existing Yes/No toggle and
    # its downstream logic stay exactly as they were. Only meaningful
    # when works_saturday is also true; see app/attendance/services.py
    # _get_employee_shift.
    alternate_saturday: bool = Field(default=False)

    # Office-hours staff only: which Saturday timing applies (9:00-12:00 or
    # 8:30-12:30). Optional -- omitted/None keeps the old default Office
    # Saturday. See sql/034.sql and app/attendance/services.py.
    saturday_shift_id: Optional[UUID] = None

    # Leave setup (sql/034_sg_leave_rules.sql)
    leave_manager_id: Optional[UUID] = None
    leave_scheme: Literal["SG_LIST", "MC_ONLY", "STANDARD"] = "MC_ONLY"


# ==========================================
# Update Employee
# ==========================================


# ==========================================
# Self-Update Personal Details ("My Profile")
# ==========================================
# Deliberately a SEPARATE, narrower model from EmployeeUpdate — this is
# what PUT /employees/me accepts, and it must never include job/role
# fields (department_id, designation_id, manager_id, employment_status,
# etc.). Any employee can call that endpoint for their OWN record with
# no special permission, so if this model included those fields, every
# employee could promote/reassign themselves. Personal-detail-only, by
# construction, not by convention.


class EmployeeSelfUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: Optional[str] = Field(default=None, max_length=20)

    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(default=None, max_length=20)
    marital_status: Optional[str] = Field(default=None, max_length=20)
    nationality: Optional[str] = Field(default=None, max_length=100)
    blood_group: Optional[str] = Field(default=None, max_length=5)
    religion: Optional[str] = Field(default=None, max_length=100)
    address: Optional[str] = Field(default=None, max_length=500)

    # Profile photo (base64 data URL, resized/compressed client-side).
    # Without this field, PUT /employees/me silently dropped it (extra
    # fields are forbidden), which is why the photo only ever lived in
    # localStorage on the device that uploaded it and never showed up
    # anywhere else the employee record is displayed (dashboards, team
    # views, other employees' screens, etc).
    profile_photo: Optional[str] = None


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=100)

    # Optional login username given by the company (e.g. "SAKTHI"). When
    # blank the employee's full name is still used to log in.
    username: Optional[str] = Field(default=None, max_length=50)

    @field_validator("username", mode="before")
    @classmethod
    def _clean_username(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        if not v:
            return None
        if not re.fullmatch(r"[A-Za-z0-9._-]{2,50}", v):
            raise ValueError(
                "Username must be 2-50 characters: letters, numbers, dot, "
                "underscore or hyphen (no spaces)."
            )
        return v

    email: Optional[EmailStr] = None

    phone: Optional[str] = Field(default=None, max_length=20)

    department_id: Optional[UUID] = None
    designation_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    shift_id: Optional[UUID] = None

    joining_date: Optional[date] = None

    date_of_birth: Optional[date] = None

    employment_status: Optional[str] = None

    work_location: Optional[str] = Field(default=None, max_length=150)

    working_location: Optional[str] = None

    @field_validator("working_location", mode="before")
    @classmethod
    def _validate_working_location(cls, v):
        return _clean_working_location(v)

    profile_photo: Optional[str] = None

    gender: Optional[str] = Field(default=None, max_length=20)
    marital_status: Optional[str] = Field(default=None, max_length=20)
    nationality: Optional[str] = Field(default=None, max_length=100)

    annual_leave_tier_id: Optional[UUID] = None
    childcare_leave_tier_id: Optional[UUID] = None

    # Only the days HR changed on the Edit User form.
    leave_entitlements: Optional[List[LeaveEntitlementInput]] = None

    working_days_per_week: Optional[float] = None

    @field_validator("working_days_per_week")
    @classmethod
    def _validate_working_days_per_week(cls, v):
        if v is not None and v not in WORKING_DAYS_PER_WEEK_OPTIONS:
            raise ValueError("working_days_per_week must be 5, 5.5, or 6.")
        return v

    works_saturday: Optional[bool] = None

    alternate_saturday: Optional[bool] = None

    saturday_shift_id: Optional[UUID] = None

    leave_manager_id: Optional[UUID] = None
    leave_scheme: Optional[Literal["SG_LIST", "MC_ONLY", "STANDARD"]] = None

    # Ad-hoc outdoor/meeting check-in (sql/030.sql). Off by default for
    # every employee -- HR/Admin flips this per-person for whoever
    # occasionally needs to check in from a meeting/site instead of the
    # office. Deliberately not tied to department/role: even within
    # Account/HR/Logistics only some staff, sometimes, need this.
    outdoor_checkin_enabled: Optional[bool] = None


# ==========================================
# Employee Response
# ==========================================


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: str
    full_name: str

    email: Optional[str]
    phone: Optional[str]

    department_id: Optional[UUID]
    designation_id: Optional[UUID]
    manager_id: Optional[UUID]
    leave_manager_id: Optional[UUID] = None
    leave_scheme: Optional[str] = None
    shift_id: Optional[UUID]

    joining_date: Optional[date]

    date_of_birth: Optional[date] = None

    employment_status: str

    work_location: Optional[str]
    working_location: Optional[str] = None
    profile_photo: Optional[str]

    created_at: Optional[datetime]
    updated_at: Optional[datetime]


# ==========================================
# Employee List Response
# ==========================================


class EmployeeListResponse(BaseModel):
    employees: list[EmployeeResponse]
    total: int


# ==========================================
# Employee Filter
# ==========================================


class EmployeeFilter(BaseModel):
    department_id: Optional[UUID] = None
    designation_id: Optional[UUID] = None
    role_id: Optional[UUID] = None
    employment_status: Optional[str] = None
    search: Optional[str] = None
