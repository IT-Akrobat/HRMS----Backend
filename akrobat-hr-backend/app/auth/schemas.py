# from typing import Any, Optional

# from pydantic import BaseModel, EmailStr


# class LoginRequest(BaseModel):

#     email: EmailStr

#     password: str


# class SidebarItem(BaseModel):
#     key: str
#     label: str
#     icon: str
#     route: str


# class MeProfile(BaseModel):
#     """Employee-facing profile fields. None for accounts with no linked
#     employee record (e.g. a Vendor login) rather than erroring out."""

#     employee_id: Optional[str] = None
#     full_name: Optional[str] = None
#     phone: Optional[str] = None
#     profile_photo: Optional[str] = None
#     joining_date: Optional[str] = None
#     employment_status: Optional[str] = None


# class MeResponse(BaseModel):
#     id: str
#     name: str
#     email: Optional[EmailStr] = None

#     role: str
#     role_id: str

#     # Multi-tenant org isolation isn't built yet (single-company schema
#     # today — see REFACTOR_NOTES.md "Suggested order for the next pass").
#     # These are returned now, as null, so the frontend contract doesn't
#     # change shape once Organization/Branch/Team land; it just starts
#     # getting populated.
#     organization: Optional[Any] = None
#     branch: Optional[Any] = None
#     department: Optional[Any] = None

#     permissions: list[str]
#     allowed_modules: list[str]
#     sidebar: list[SidebarItem]

#     redirect_path: str

#     theme: str = "light"
#     profile: MeProfile


# class MeEnvelope(BaseModel):
#     success: bool = True
#     message: str
#     data: MeResponse
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):

    # Employees now sign in with their employee code (e.g. HR-0001)
    # instead of an email address -- see app/auth/services.login_user,
    # which resolves this to the email on file and authenticates
    # against Supabase underneath.
    employee_code: str = Field(..., min_length=1, max_length=50)

    password: str


class RefreshRequest(BaseModel):

    # The refresh token now normally travels as an httpOnly cookie (see
    # app/core/cookies.py) rather than in the request body -- the
    # frontend doesn't hold it in JS anymore, so it has nothing to put
    # here. This field is optional and kept only so the endpoint doesn't
    # break for any non-browser client that still wants to pass a
    # refresh token explicitly (e.g. a script/mobile client not using
    # cookies); POST /auth/refresh prefers the cookie when both are
    # present. See app/auth/routes.py::refresh.
    refresh_token: Optional[str] = None


class ChangePasswordRequest(BaseModel):

    current_password: str

    # Mirrors the frontend's client-side check (Settings.jsx), but the
    # backend can't trust that check ran — enforce it here too.
    new_password: str = Field(min_length=8)


class SidebarItem(BaseModel):
    key: str
    label: str
    icon: str
    route: str


class MeProfile(BaseModel):
    """Employee-facing profile fields. None for accounts with no linked
    employee record (e.g. a Vendor login) rather than erroring out.

    IMPORTANT: FastAPI's `response_model=MeEnvelope` on GET /auth/me
    validates the dict get_me() builds against this model and drops
    ANY key not declared here -- silently, no error. Designation,
    Reporting Manager, Shift, Work Location, and every Personal Details
    field (date_of_birth, gender, marital_status, nationality,
    blood_group, religion, address) were all being computed correctly
    in get_me() but stripped out right here before ever reaching the
    frontend. If you add a field to the profile dict in
    app/auth/services.py::get_me(), it MUST be declared below too, or
    it will silently vanish from the response again.
    """

    id: Optional[str] = None  # employees.id (internal UUID) — needed by the
    # frontend to call employee-scoped endpoints for the logged-in user,
    # e.g. GET /reports/employees/{id}/full ("My Profile" full report
    # download). Not to be confused with employee_id, the human-readable
    # code (e.g. EMP-0042).
    employee_id: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    profile_photo: Optional[str] = None
    joining_date: Optional[str] = None
    employment_status: Optional[str] = None

    designation: Optional[Any] = None
    manager: Optional[Any] = None
    shift: Optional[Any] = None
    work_location: Optional[str] = None

    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    nationality: Optional[str] = None
    blood_group: Optional[str] = None
    religion: Optional[str] = None
    address: Optional[str] = None


class MeResponse(BaseModel):
    id: str
    name: str
    email: Optional[EmailStr] = None

    role: str
    role_id: str

    # Multi-tenant org isolation isn't built yet (single-company schema
    # today — see REFACTOR_NOTES.md "Suggested order for the next pass").
    # These are returned now, as null, so the frontend contract doesn't
    # change shape once Organization/Branch/Team land; it just starts
    # getting populated.
    organization: Optional[Any] = None
    branch: Optional[Any] = None
    department: Optional[Any] = None

    permissions: list[str]
    allowed_modules: list[str]
    sidebar: list[SidebarItem]

    redirect_path: str

    theme: str = "light"
    profile: MeProfile


class MeEnvelope(BaseModel):
    success: bool = True
    message: str
    data: MeResponse
