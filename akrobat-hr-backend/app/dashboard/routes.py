# from fastapi import APIRouter, Depends, Query

# from app.dashboard.schemas import DashboardStats

# from app.dashboard.services import (
#     get_admin_dashboard,
#     get_attendance_trend,
#     get_celebrations,
#     get_department_distribution,
#     get_on_leave_today,
# )

# from app.core.security import get_current_user

# router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# @router.get("/", response_model=DashboardStats)
# def dashboard(user=Depends(get_current_user)):

#     return get_admin_dashboard()


# @router.get("/attendance-trend")
# def attendance_trend(
#     days: int = Query(7, ge=2, le=30),
#     user=Depends(get_current_user),
# ):

#     return get_attendance_trend(days=days)


# @router.get("/department-distribution")
# def department_distribution(user=Depends(get_current_user)):

#     return get_department_distribution()


# @router.get("/celebrations")
# def celebrations(
#     days: int = Query(30, ge=1, le=90),
#     user=Depends(get_current_user),
# ):
#     """Upcoming birthdays + work anniversaries, company-wide. Every
#     signed-in role can see this (no VIEW_EMPLOYEE gate) — it's a
#     lightweight "who's celebrating soon" widget, not an employee
#     management view.
#     """

#     return get_celebrations(days=days)


# @router.get("/on-leave-today")
# def on_leave_today(user=Depends(get_current_user)):
#     """Employees on approved leave that covers today — a shared
#     "who's out today" widget, same no-extra-permission-gate rationale as
#     /dashboard/celebrations above.
#     """

#     return get_on_leave_today()
from fastapi import APIRouter, Depends, Query

from app.dashboard.schemas import DashboardStats

from app.dashboard.services import (
    get_admin_dashboard,
    get_attendance_trend,
    get_celebrations,
    get_department_distribution,
    get_on_leave_today,
    get_quote_of_day,
    get_top_performers,
)

from app.core.security import get_current_user
from app.core.responses import success_response

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/", response_model=DashboardStats)
def dashboard(user=Depends(get_current_user)):

    return get_admin_dashboard()


@router.get("/attendance-trend")
def attendance_trend(
    days: int = Query(7, ge=2, le=30),
    user=Depends(get_current_user),
):

    return get_attendance_trend(days=days)


@router.get("/department-distribution")
def department_distribution(user=Depends(get_current_user)):

    return get_department_distribution()


@router.get("/celebrations")
def celebrations(
    days: int = Query(30, ge=1, le=90),
    user=Depends(get_current_user),
):
    """Upcoming birthdays + work anniversaries, company-wide. Every
    signed-in role can see this (no VIEW_EMPLOYEE gate) — it's a
    lightweight "who's celebrating soon" widget, not an employee
    management view.
    """

    return get_celebrations(days=days)


@router.get("/on-leave-today")
def on_leave_today(user=Depends(get_current_user)):
    """Employees on approved leave that covers today — a shared
    "who's out today" widget, same no-extra-permission-gate rationale as
    /dashboard/celebrations above.
    """

    return get_on_leave_today()


@router.get("/top-performers")
def top_performers(
    days: int = Query(30, ge=7, le=90),
    limit: int = Query(5, ge=1, le=20),
    user=Depends(get_current_user),
):
    """Top employees by attendance punctuality over the last `days` days,
    company-wide — same no-extra-permission-gate rationale as the other
    shared dashboard widgets above (on-leave-today, celebrations).
    """

    return get_top_performers(days=days, limit=limit)


@router.get("/quote-of-day")
def quote_of_day(user=Depends(get_current_user)):
    """Today's Quote of the Day card. Backed by the `daily_quotes` table
    (see sql/014_daily_quotes.sql) — the first request each day fetches
    a quote + background from external APIs and caches it there; every
    request after that for the rest of the day reads the cached row, so
    every employee sees the same quote and the external APIs are called
    at most once per day (see app/dashboard/services.get_quote_of_day
    for the full fallback chain).
    """

    return success_response("Quote of the day fetched successfully", get_quote_of_day())
