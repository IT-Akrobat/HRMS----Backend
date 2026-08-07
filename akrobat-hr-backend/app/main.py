import asyncio
import sys

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
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
from app.push_subscriptions.routes import router as push_subscriptions_router
from app.notification_preferences.routes import (
    router as notification_preferences_router,
)
from app.announcements.routes import router as announcement_router
from app.reports.routes import router as report_router
from app.settings.routes import router as settings_router
from app.access_control.routes import router as access_control_router
from app.expenses.routes import router as expense_router

from app.audit_logs.routes import router as audit_log_router

from app.core.config import APP_NAME, APP_VERSION, ENVIRONMENT, ALLOWED_ORIGINS
from app.core import realtime
from app.core.database import supabase
from app.core.rbac import has_permission

app = FastAPI(title=APP_NAME, version=APP_VERSION)

# CORS origins come from the ALLOWED_ORIGINS env var (comma-separated), so the
# same code deploys to any environment without edits. Falls back to the local
# Vite dev origins when unset so local development keeps working out of the
# box.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Health"])
def root():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
    }


@app.get("/health", tags=["Health"])
def health():
    # Deliberately does not call Supabase here — health checks should be
    # fast and not fail the whole app/load-balancer probe due to a
    # transient upstream blip. Add a separate /health/db check if you want
    # DB connectivity verified explicitly.
    return {"status": "healthy"}


@app.on_event("startup")
async def _capture_event_loop():
    # attendance/services.py broadcasts to /ws/dashboard from sync worker
    # threads (see app/core/realtime.py) — it needs a reference to *this*
    # loop to hop back onto it.
    realtime.set_main_loop(asyncio.get_running_loop())


@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket, token: str = Query(...)):
    # Live push for the super-admin dashboard: instead of polling
    # GET /dashboard and GET /audit-logs on a timer, the frontend opens
    # this socket and gets a message the instant any employee checks
    # in/out or starts/ends a break (see the broadcast_threadsafe() calls
    # in app/attendance/services.py), then refetches just those two
    # endpoints itself.
    #
    # Browsers can't attach an Authorization header to a WebSocket
    # handshake, so the Supabase access token travels as a query param
    # instead — same token apiClient.js already holds in sessionStorage,
    # just appended to the ws:// URL rather than sent as a header.
    try:
        user_response = supabase.auth.get_user(token)
        user = user_response.user if user_response else None
    except Exception:
        user = None

    if not user:
        await websocket.close(code=4401)
        return

    try:
        allowed = has_permission(user.id, "VIEW_ALL_ATTENDANCE")
    except Exception:
        allowed = False

    if not allowed:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await realtime.register(websocket)
    try:
        while True:
            # The client never sends anything meaningful here — this just
            # blocks until the tab closes/reloads/loses connection, which
            # raises WebSocketDisconnect below so we can clean up.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.unregister(websocket)


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
app.include_router(push_subscriptions_router)

app.include_router(notification_preferences_router)

app.include_router(announcement_router)

app.include_router(report_router)
app.include_router(settings_router)
app.include_router(access_control_router)

app.include_router(expense_router)
app.include_router(audit_log_router)
