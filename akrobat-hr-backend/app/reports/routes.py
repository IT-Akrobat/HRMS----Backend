from fastapi import APIRouter, Depends

from app.core.security import get_current_user

from app.reports.services import (
    employee_report,
    attendance_report,
    today_attendance,
    leave_report,
    payroll_report,
    project_report,
    dashboard_report,
    employee_full_report,
    employee_monthly_attendance_report,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/employees")
def employees(user=Depends(get_current_user)):

    return employee_report()


@router.get("/employees/{employee_id}/full")
def employee_full(employee_id: str, user=Depends(get_current_user)):
    """Everything about one employee: profile, manager, sites worked
    (with hours per site), and lifetime attendance totals — for the
    "download this employee's full report" action."""

    return employee_full_report(employee_id)


@router.get("/attendance/employee/{employee_id}")
def attendance_employee_monthly(
    employee_id: str, month: str, user=Depends(get_current_user)
):
    """One employee's attendance for one calendar month (?month=YYYY-MM),
    plus the month's totals (working hours, break time, overtime,
    lates) — for the "download this employee's monthly attendance"
    action."""

    return employee_monthly_attendance_report(employee_id, month)


@router.get("/attendance")
def attendance(user=Depends(get_current_user)):

    return attendance_report()


@router.get("/attendance/today")
def attendance_today(user=Depends(get_current_user)):

    return today_attendance()


@router.get("/leaves")
def leaves(user=Depends(get_current_user)):

    return leave_report()


@router.get("/payroll")
def payroll(user=Depends(get_current_user)):

    return payroll_report()


@router.get("/projects")
def projects(user=Depends(get_current_user)):

    return project_report()


@router.get("/dashboard")
def dashboard(user=Depends(get_current_user)):

    return dashboard_report()
