import asyncio
import sys
from types import SimpleNamespace

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.limiter import limiter
from app.core.ws_tickets import redeem_ticket

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

from app.core.config import (
    ACCESS_TOKEN_COOKIE,
    ALLOWED_ORIGINS,
    APP_NAME,
    APP_VERSION,
    ENVIRONMENT,
)
from app.core import realtime
from app.core.csrf import CSRFMiddleware
from app.core.database import supabase
from app.core.rbac import has_permission
from app.core.helpers.employee_helper import get_employee_id_for_auth_user

app = FastAPI(title=APP_NAME, version=APP_VERSION)

# Rate limiting (slowapi) — currently only applied to POST /auth/login
# via @limiter.limit("5/minute") on that route, to stop scripted
# password-guessing. app.state.limiter + this exception handler are
# required by slowapi regardless of how many routes use @limiter.limit.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS origins come from the ALLOWED_ORIGINS env var (comma-separated), so the
# same code deploys to any environment without edits. Falls back to the local
# Vite dev origins when unset so local development keeps working out of the
# box.
# Starlette makes the LAST middleware added the OUTERMOST layer. CSRF
# must be added before CORS (not after) so CORS ends up outermost --
# otherwise a request CSRFMiddleware rejects with 403 never reaches
# CORSMiddleware, the response goes out with no
# Access-Control-Allow-Origin header, and the browser hides the real 403
# behind a generic "Failed to fetch" / network-error message instead of
# the CSRF message the frontend actually needs to see.
app.add_middleware(CSRFMiddleware)

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
async def dashboard_ws(websocket: WebSocket):
    # Live push for the super-admin dashboard: instead of polling
    # GET /dashboard and GET /audit-logs on a timer, the frontend opens
    # this socket and gets a message the instant any employee checks
    # in/out or starts/ends a break (see the broadcast_threadsafe() calls
    # in app/attendance/services.py), then refetches just those two
    # endpoints itself.
    #
    # Prefer the httpOnly access-token cookie (same-origin deployments
    # send it automatically on the WS handshake, same as any other
    # request). Falls back to a short-lived ?ticket= (see
    # app/core/ws_tickets.py) for deployments where the frontend is
    # proxied through a different site -- a WS upgrade can't be proxied
    # the way a normal fetch() can, so it connects straight to this
    # API's domain, where the cookie may never have been stored (e.g.
    # iOS/Safari blocking third-party cookies). The ticket is minted by
    # GET /auth/ws-ticket over the proxied (cookie-authed) connection,
    # so the real token still never has to sit in a URL or log line.
    token = websocket.cookies.get(ACCESS_TOKEN_COOKIE)
    user = None
    try:
        if token:
            user_response = supabase.auth.get_user(token)
            user = user_response.user if user_response else None
        else:
            ticket = websocket.query_params.get("ticket")
            user_id = redeem_ticket(ticket) if ticket else None
            if user_id:
                user = SimpleNamespace(id=user_id)
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


@app.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket):
    # Real-time replacement for the frontend's old "poll GET
    # /notifications/my every few seconds" approach (see
    # src/components/layout/Header.jsx / useNotificationLiveUpdates).
    # notify_employee() in app/notifications/services.py pushes a message
    # here the instant a notification row is written, so it shows up as a
    # toast with no polling delay. Same cookie-with-ticket-fallback auth
    # as /ws/dashboard above -- see the comment there for why the
    # ?ticket= fallback exists.
    #
    # Unlike /ws/dashboard (one shared feed for anyone with
    # VIEW_ALL_ATTENDANCE), this is private per employee -- each socket is
    # registered under the connecting employee's own id, and only ever
    # receives notifications written for that id.
    token = websocket.cookies.get(ACCESS_TOKEN_COOKIE)
    user = None
    try:
        if token:
            user_response = supabase.auth.get_user(token)
            user = user_response.user if user_response else None
        else:
            ticket = websocket.query_params.get("ticket")
            user_id = redeem_ticket(ticket) if ticket else None
            if user_id:
                user = SimpleNamespace(id=user_id)
    except Exception:
        user = None

    if not user:
        await websocket.close(code=4401)
        return

    employee_id = get_employee_id_for_auth_user(user.id)
    if not employee_id:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await realtime.register_notification_socket(employee_id, websocket)
    try:
        while True:
            # Client never sends anything meaningful -- this just blocks
            # until the tab closes/reloads/loses connection, which raises
            # WebSocketDisconnect below so we can clean up.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.unregister_notification_socket(employee_id, websocket)


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
