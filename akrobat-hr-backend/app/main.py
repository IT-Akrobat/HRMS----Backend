# import asyncio
# import sys

# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# # Windows-only fix: uvicorn's default ProactorEventLoop on Windows has a
# # known race with httpx's connection-pooled sync client (what supabase-py
# # uses under the hood) when several requests hit the same shared client
# # at once - it surfaces as "[WinError 10035] A non-blocking socket
# # operation could not be completed immediately" (WSAEWOULDBLOCK). The
# # SelectorEventLoop doesn't have this issue. No effect on Linux/macOS,
# # where this policy simply doesn't exist.
# if sys.platform == "win32":
#     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# from app.auth.routes import router as auth_router
# from app.employees.routes import router as employee_router
# from app.departments.routes import router as department_router
# from app.designations.routes import router as designation_router
# from app.roles.routes import router as role_router
# from app.attendance.routes import router as attendance_router


# from app.shifts.routes import router as shift_router

# from app.leaves.routes import router as leave_router

# from app.locations.routes import router as location_router
# from app.holidays.routes import router as holiday_router

# from app.dashboard.routes import router as dashboard_router
# from app.payroll.routes import router as payroll_router
# from app.documents.routes import router as document_router
# from fastapi.exceptions import RequestValidationError
# from fastapi import HTTPException
# from app.projects.routes import router as project_router
# from app.core.exception_handler import (
#     http_exception_handler,
#     validation_exception_handler,
#     unhandled_exception_handler,
# )
# from app.employee_project_assignments.routes import (
#     router as employee_project_assignment_router,
# )
# from app.notifications.routes import router as notification_router
# from app.announcements.routes import router as announcement_router
# from app.reports.routes import router as report_router
# from app.settings.routes import router as settings_router
# from app.expenses.routes import router as expense_router

# from app.audit_logs.routes import router as audit_log_router

# app = FastAPI()

# # Dev CORS — Vite runs on :5173. Tighten allow_origins for production.
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=[
#         "http://localhost:5173",
#         "http://127.0.0.1:5173",
#     ],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# app.add_exception_handler(HTTPException, http_exception_handler)

# app.add_exception_handler(RequestValidationError, validation_exception_handler)

# app.add_exception_handler(Exception, unhandled_exception_handler)

# app.include_router(auth_router)

# app.include_router(employee_router)

# app.include_router(department_router)

# app.include_router(designation_router)

# app.include_router(role_router)
# app.include_router(shift_router)
# app.include_router(attendance_router)
# app.include_router(leave_router)

# app.include_router(location_router)
# app.include_router(holiday_router)
# app.include_router(dashboard_router)
# app.include_router(payroll_router)

# app.include_router(document_router)
# app.include_router(project_router)
# app.include_router(employee_project_assignment_router)

# app.include_router(notification_router)

# app.include_router(announcement_router)

# app.include_router(report_router)
# app.include_router(settings_router)

# app.include_router(expense_router)
# app.include_router(audit_log_router)

import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Windows-only fix: uvicorn's default ProactorEventLoop on Windows has a
# known race with httpx's connection-pooled sync client (what supabase-py
# uses under the hood) when several requests hit the same shared client
# at once - it surfaces as "[WinError 10035] A non-blocking socket
# operation could not be completed immediately" (WSAEWOULDBLOCK). The
# SelectorEventLoop doesn't have this issue. No effect on Linux/macOS,
# where this policy simply doesn't exist.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


from app.auth.routes import router as auth_router
from app.employees.routes import router as employee_router
from app.departments.routes import router as department_router
from app.designations.routes import router as designation_router
from app.roles.routes import router as role_router
from app.permissions.routes import router as permission_router
from app.attendance.routes import router as attendance_router


from app.shifts.routes import router as shift_router

from app.leaves.routes import router as leave_router

from app.locations.routes import router as location_router
from app.holidays.routes import router as holiday_router

from app.dashboard.routes import router as dashboard_router
from app.payroll.routes import router as payroll_router
from app.documents.routes import router as document_router
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from app.projects.routes import router as project_router
from app.core.exception_handler import (
    http_exception_handler,
    validation_exception_handler,
    unhandled_exception_handler,
)
from app.employee_project_assignments.routes import (
    router as employee_project_assignment_router,
)
from app.site_assignments.routes import router as site_assignment_router
from app.notifications.routes import router as notification_router
from app.announcements.routes import router as announcement_router
from app.reports.routes import router as report_router
from app.settings.routes import router as settings_router
from app.expenses.routes import router as expense_router

from app.audit_logs.routes import router as audit_log_router

app = FastAPI()

# Dev CORS — Vite runs on :5173. Tighten allow_origins for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)

app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(auth_router)

app.include_router(employee_router)

app.include_router(department_router)

app.include_router(designation_router)

app.include_router(role_router)
app.include_router(permission_router)
app.include_router(shift_router)
app.include_router(attendance_router)
app.include_router(leave_router)

app.include_router(location_router)
app.include_router(holiday_router)
app.include_router(dashboard_router)
app.include_router(payroll_router)

app.include_router(document_router)
app.include_router(project_router)
app.include_router(employee_project_assignment_router)
app.include_router(site_assignment_router)

app.include_router(notification_router)

app.include_router(announcement_router)

app.include_router(report_router)
app.include_router(settings_router)

app.include_router(expense_router)
app.include_router(audit_log_router)
