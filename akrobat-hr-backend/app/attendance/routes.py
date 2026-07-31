from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from app.attendance.schemas import (
    CheckInRequest,
    CheckOutRequest,
    RegularizationRequest,
    RegularizationDecisionRequest,
    AdminUpdateAttendanceRequest,
    SiteVisitArriveRequest,
    SiteVisitDepartRequest,
    SiteVisitPingRequest,
)

from app.attendance.services import (
    check_in,
    check_out,
    get_attendance_reminder_status,
    start_break,
    end_break,
    get_my_attendance,
    get_attendance_timeline,
    submit_regularization,
    get_my_regularizations,
    get_team_regularizations,
    decide_regularization,
    get_team_attendance,
    get_team_attendance_report,
    get_all_attendance,
    get_employee_attendance,
    get_attendance_analytics,
    admin_update_attendance,
    arrive_at_site,
    depart_site,
    ping_site_visit,
    get_site_visits_for_attendance,
    get_my_site_visits_today,
    get_team_site_visits_today,
    get_org_site_visits_today,
    get_org_site_visits_history,
    get_employee_site_visits_history,
)

from app.core.security import get_current_user
from app.core.rbac import require_permission, require_any_permission

router = APIRouter(prefix="/attendance", tags=["Attendance"])


# ==========================================
# CHECK IN / CHECK OUT / BREAKS (self-service)
# ==========================================


@router.post("/check-in")
def employee_check_in(
    data: CheckInRequest, request: Request, user=Depends(get_current_user)
):
    return check_in(user.id, data, request=request)


# Self-service "have I forgotten to check in today?" check -- polled
# periodically by the frontend (see Header.jsx) while the employee is
# logged in. Fires a real "ATTENDANCE_REMINDER" notification (picked up
# by the existing NotificationBell poll/toast) the first time it detects
# the employee is late-and-unchecked-in for the day; a no-op every other
# time it's called. See get_attendance_reminder_status() docstring for
# the full set of conditions.
@router.get("/reminder-check")
def attendance_reminder_check(user=Depends(get_current_user)):
    return get_attendance_reminder_status(user.id)


@router.post("/check-out")
def employee_check_out(
    data: CheckOutRequest, request: Request, user=Depends(get_current_user)
):
    return check_out(user.id, data, request=request)


@router.post("/break-start")
def employee_break_start(request: Request, user=Depends(get_current_user)):
    return start_break(user.id, request=request)


@router.post("/break-end")
def employee_break_end(request: Request, user=Depends(get_current_user)):
    return end_break(user.id, request=request)


# ==========================================
# SITE VISITS (multi-location field staff — Inspection / Operation)
# ==========================================


@router.post("/site-visit/arrive")
def site_visit_arrive(
    data: SiteVisitArriveRequest, request: Request, user=Depends(get_current_user)
):
    return arrive_at_site(user.id, data, request=request)


@router.post("/site-visit/depart")
def site_visit_depart(
    data: SiteVisitDepartRequest, request: Request, user=Depends(get_current_user)
):
    return depart_site(user.id, data, request=request)


@router.post("/site-visit/ping")
def site_visit_ping(
    data: SiteVisitPingRequest, request: Request, user=Depends(get_current_user)
):
    """Live presence check, fired every ~60s by the frontend while a site visit is open."""
    return ping_site_visit(user.id, data, request=request)


@router.get("/site-visit/today")
def site_visit_today(user=Depends(get_current_user)):
    return get_my_site_visits_today(user.id)


@router.get("/team/site-visits")
def team_site_visits_today(user=Depends(require_permission("VIEW_ATTENDANCE"))):
    """Manager's live view: which of their field-staff reports are on-site right now."""
    return get_team_site_visits_today(user.id)


@router.get("/org/site-visits")
def org_site_visits_today(user=Depends(require_permission("VIEW_ALL_ATTENDANCE"))):
    """
    Super Admin / HR "Live Tracking" view: every field-staff employee in
    the company (not scoped to one manager's reports) — who's currently
    on site, at which site, and their site-visit trail for today.
    """
    return get_org_site_visits_today(user.id)


@router.get("/org/site-visits/history")
def org_site_visits_history(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    user=Depends(require_permission("VIEW_ALL_ATTENDANCE")),
):
    """
    Super Admin / HR "Live Tracking" -> History: past site visits for
    every field employee (separate from /org/site-visits, which is
    today-only). Defaults to the trailing 30 days ending yesterday.
    """
    return get_org_site_visits_history(user.id, from_date=from_date, to_date=to_date)


@router.get("/employee/{employee_id}/site-visits")
def employee_site_visits_history(
    employee_id: str,
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    user=Depends(get_current_user),
):
    return get_employee_site_visits_history(
        employee_id, auth_user_id=user.id, from_date=from_date, to_date=to_date
    )


# NOTE: registered AFTER /team/site-visits and /employee/{id}/site-visits
# above — this generic /{attendance_id}/site-visits pattern would otherwise
# swallow those two routes first (Starlette matches path params against
# literal segments like "team"/"employee" too, in registration order).
@router.get("/{attendance_id}/site-visits")
def site_visits_for_day(
    attendance_id: str,
    user=Depends(require_permission("VIEW_ATTENDANCE")),
):
    return get_site_visits_for_attendance(attendance_id)


# ==========================================
# HISTORY / TIMELINE (self-service)
# ==========================================


@router.get("/my")
def my_attendance(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    user=Depends(get_current_user),
):
    return get_my_attendance(user.id, from_date=from_date, to_date=to_date)


@router.get("/timeline/{target_date}")
def attendance_timeline(target_date: date, user=Depends(get_current_user)):
    return get_attendance_timeline(user.id, target_date)


# ==========================================
# REGULARIZATION
# ==========================================


@router.post("/regularization")
def create_regularization(
    data: RegularizationRequest, request: Request, user=Depends(get_current_user)
):
    return submit_regularization(user.id, data, request=request)


@router.get("/regularization/my")
def my_regularizations(user=Depends(get_current_user)):
    return get_my_regularizations(user.id)


@router.get("/regularization/team")
def team_regularizations(user=Depends(require_permission("VIEW_ATTENDANCE"))):
    return get_team_regularizations(user.id)


@router.put("/regularization/{correction_id}")
def decide_regularization_route(
    correction_id: str,
    data: RegularizationDecisionRequest,
    request: Request,
    user=Depends(
        require_any_permission(["EDIT_ATTENDANCE", "APPROVE_ATTENDANCE_CORRECTION"])
    ),
):
    return decide_regularization(
        correction_id, data, auth_user_id=user.id, request=request
    )


# ==========================================
# TEAM / COMPANY-WIDE VIEWS
# ==========================================


@router.get("/team")
def team_attendance(
    target_date: date | None = Query(None),
    user=Depends(require_permission("VIEW_ATTENDANCE")),
):
    return get_team_attendance(user.id, target_date=target_date)


@router.get("/team/report")
def team_attendance_report(
    from_date: date = Query(...),
    to_date: date = Query(...),
    user=Depends(require_permission("VIEW_ATTENDANCE")),
):
    return get_team_attendance_report(user.id, from_date=from_date, to_date=to_date)


@router.get("/analytics")
def attendance_analytics(
    from_date: date = Query(...),
    to_date: date = Query(...),
    user=Depends(require_permission("VIEW_ALL_ATTENDANCE")),
):
    return get_attendance_analytics(from_date, to_date)


@router.get("/employee/{employee_id}")
def employee_attendance(
    employee_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
):
    return get_employee_attendance(
        employee_id, auth_user_id=user.id, page=page, limit=limit
    )


@router.get("/")
def all_attendance(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    target_date: date | None = Query(None),
    user=Depends(require_permission("VIEW_ALL_ATTENDANCE")),
):
    return get_all_attendance(page=page, limit=limit, target_date=target_date)


# ==========================================
# HR / ADMIN DIRECT EDIT
# ==========================================


@router.put("/{attendance_id}")
def update_attendance(
    attendance_id: str,
    data: AdminUpdateAttendanceRequest,
    request: Request,
    user=Depends(require_permission("EDIT_ATTENDANCE")),
):
    return admin_update_attendance(
        attendance_id, data, current_user=user, request=request
    )
