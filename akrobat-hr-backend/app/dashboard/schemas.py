# # # from typing import Any, Optional

# # from pydantic import BaseModel, EmailStr


# # class LoginRequest(BaseModel):

# #     email: EmailStr

# #     password: str


# # class SidebarItem(BaseModel):
# #     key: str
# #     label: str
# #     icon: str
# #     route: str


# # class MeProfile(BaseModel):
# #     """Employee-facing profile fields. None for accounts with no linked
# #     employee record (e.g. a Vendor login) rather than erroring out."""

# #     employee_id: Optional[str] = None
# #     full_name: Optional[str] = None
# #     phone: Optional[str] = None
# #     profile_photo: Optional[str] = None
# #     joining_date: Optional[str] = None
# #     employment_status: Optional[str] = None


# # class MeResponse(BaseModel):
# #     id: str
# #     name: str
# #     email: Optional[EmailStr] = None

# #     role: str
# #     role_id: str

# #     # Multi-tenant org isolation isn't built yet (single-company schema
# #     # today — see REFACTOR_NOTES.md "Suggested order for the next pass").
# #     # These are returned now, as null, so the frontend contract doesn't
# #     # change shape once Organization/Branch/Team land; it just starts
# #     # getting populated.
# #     organization: Optional[Any] = None
# #     branch: Optional[Any] = None
# #     department: Optional[Any] = None

# #     permissions: list[str]
# #     allowed_modules: list[str]
# #     sidebar: list[SidebarItem]

# #     redirect_path: str

# #     theme: str = "light"
# #     profile: MeProfile


# # class MeEnvelope(BaseModel):
# #     success: bool = True
# #     message: str
# #     data: MeResponse
# from typing import Any, Optional

# from pydantic import BaseModel, EmailStr


# class LoginRequest(BaseModel):

#     email: EmailStr

#     password: str


# class RefreshRequest(BaseModel):

#     refresh_token: str


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
#     designation: Optional[Any] = None
#     work_location: Optional[str] = None
#     manager: Optional[Any] = None
#     shift: Optional[Any] = None


# class DashboardStats(BaseModel):

#     total_employees: int

#     present_today: int

#     absent_today: int

#     on_leave: int

#     late_today: int

#     total_departments: int

#     total_locations: int

#     total_shifts: int


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
# # from typing import Any, Optional

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

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):

    email: EmailStr

    password: str


class RefreshRequest(BaseModel):

    refresh_token: str


class SidebarItem(BaseModel):
    key: str
    label: str
    icon: str
    route: str


class MeProfile(BaseModel):
    """Employee-facing profile fields. None for accounts with no linked
    employee record (e.g. a Vendor login) rather than erroring out."""

    employee_id: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    profile_photo: Optional[str] = None
    joining_date: Optional[str] = None
    employment_status: Optional[str] = None
    designation: Optional[Any] = None
    work_location: Optional[str] = None
    manager: Optional[Any] = None
    shift: Optional[Any] = None


class DashboardStats(BaseModel):

    total_employees: int

    present_today: int

    absent_today: int

    on_leave: int

    late_today: int

    total_departments: int

    total_locations: int

    total_shifts: int


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


class QuoteOfDayResponse(BaseModel):
    """Response for GET /dashboard/quote-of-day (wrapped in the usual
    success_response envelope — see app/core/responses.py)."""

    id: Optional[str] = None
    date: str
    quote: str
    author: str
    background_url: str
    # 'cached'   -> today's row already existed, no external call made
    # 'api'      -> freshly fetched from the external quote/image APIs
    # 'fallback' -> external APIs failed; reused the most recent stored
    #               quote (or the hardcoded default if the table is empty)
    source: str
