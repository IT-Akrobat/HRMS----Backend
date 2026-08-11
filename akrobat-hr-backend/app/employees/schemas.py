# from datetime import date, datetime
# from typing import Optional
# from uuid import UUID

# from pydantic import BaseModel, ConfigDict, EmailStr, Field

# from app.core.constants import ACTIVE

# # ==========================================
# # Create Employee
# # ==========================================


# class EmployeeCreate(BaseModel):
#     model_config = ConfigDict(extra="forbid")

#     full_name: str = Field(..., min_length=2, max_length=100)

#     email: EmailStr

#     password: str = Field(..., min_length=8, max_length=100)

#     phone: Optional[str] = Field(default=None, max_length=20)

#     department_id: Optional[UUID] = None
#     designation_id: Optional[UUID] = None
#     manager_id: Optional[UUID] = None
#     shift_id: Optional[UUID] = None

#     role_id: UUID

#     joining_date: Optional[date] = None

#     employment_status: str = ACTIVE

#     work_location: Optional[str] = Field(default=None, max_length=150)

#     profile_photo: Optional[str] = None


# # ==========================================
# # Update Employee
# # ==========================================


# class EmployeeUpdate(BaseModel):
#     model_config = ConfigDict(extra="forbid")

#     full_name: Optional[str] = Field(default=None, min_length=2, max_length=100)

#     email: Optional[EmailStr] = None

#     phone: Optional[str] = Field(default=None, max_length=20)

#     department_id: Optional[UUID] = None
#     designation_id: Optional[UUID] = None
#     manager_id: Optional[UUID] = None
#     shift_id: Optional[UUID] = None

#     joining_date: Optional[date] = None

#     employment_status: Optional[str] = None

#     work_location: Optional[str] = Field(default=None, max_length=150)

#     profile_photo: Optional[str] = None


# # ==========================================
# # Employee Response
# # ==========================================


# class EmployeeResponse(BaseModel):
#     model_config = ConfigDict(from_attributes=True)

#     id: UUID
#     employee_id: str
#     full_name: str

#     email: Optional[str]
#     phone: Optional[str]

#     department_id: Optional[UUID]
#     designation_id: Optional[UUID]
#     manager_id: Optional[UUID]
#     shift_id: Optional[UUID]

#     joining_date: Optional[date]

#     employment_status: str

#     work_location: Optional[str]
#     profile_photo: Optional[str]

#     created_at: Optional[datetime]
#     updated_at: Optional[datetime]


# # ==========================================
# # Employee List Response
# # ==========================================


# class EmployeeListResponse(BaseModel):
#     employees: list[EmployeeResponse]
#     total: int


# # ==========================================
# # Employee Filter
# # ==========================================


# class EmployeeFilter(BaseModel):
#     department_id: Optional[UUID] = None
#     designation_id: Optional[UUID] = None
#     role_id: Optional[UUID] = None
#     employment_status: Optional[str] = None
#     search: Optional[str] = None
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.constants import ACTIVE

WORKING_DAYS_PER_WEEK_OPTIONS = (5, 5.5, 6)

# ==========================================
# Create Employee
# ==========================================


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=2, max_length=100)

    # Required -- no auto-generated placeholder login email anymore. HR
    # must supply a real email; the employee code is never appended to
    # build one (see app/employees/services.py create_employee()).
    email: EmailStr

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
    annual_leave_tier_id: UUID

    childcare_leave_tier_id: Optional[UUID] = None

    # Drives the Unpaid Leave payroll deduction (Unpaid Leave itself
    # never gets a leave_balances row -- see
    # app/leaves/policy_services.py). 5 / 5.5 / 6 per the Leave Info doc.
    working_days_per_week: float = Field(default=5)

    @field_validator("working_days_per_week")
    @classmethod
    def _validate_working_days_per_week(cls, v):
        if v not in WORKING_DAYS_PER_WEEK_OPTIONS:
            raise ValueError("working_days_per_week must be 5, 5.5, or 6.")
        return v


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

    profile_photo: Optional[str] = None

    gender: Optional[str] = Field(default=None, max_length=20)
    marital_status: Optional[str] = Field(default=None, max_length=20)
    nationality: Optional[str] = Field(default=None, max_length=100)

    annual_leave_tier_id: Optional[UUID] = None
    childcare_leave_tier_id: Optional[UUID] = None

    working_days_per_week: Optional[float] = None

    @field_validator("working_days_per_week")
    @classmethod
    def _validate_working_days_per_week(cls, v):
        if v is not None and v not in WORKING_DAYS_PER_WEEK_OPTIONS:
            raise ValueError("working_days_per_week must be 5, 5.5, or 6.")
        return v


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
    shift_id: Optional[UUID]

    joining_date: Optional[date]

    date_of_birth: Optional[date] = None

    employment_status: str

    work_location: Optional[str]
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
