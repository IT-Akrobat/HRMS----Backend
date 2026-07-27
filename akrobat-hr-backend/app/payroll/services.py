from typing import Optional

from fastapi import HTTPException, Request

from app.core.repository import SupabaseRepository
from app.core.responses import success_response
from app.core.logger import logger
from app.core.exceptions import internal_server_error, forbidden
from app.core.messages import PAYROLL_GENERATED, PAYROLL_UPDATED, DELETED
from app.core.audit import record_audit_log
from app.core.rbac import has_permission
from app.core.helpers.employee_helper import get_employee_id_for_auth_user

payroll_repo = SupabaseRepository("payroll")

PAYROLL_SELECT = "*, employees(full_name, employee_id)"


def _net_salary(basic, allowance, overtime_amount, bonus, deduction, leave_deduction, tax):
    return basic + allowance + overtime_amount + bonus - deduction - leave_deduction - tax


# ==========================================
# CREATE PAYROLL
# ==========================================


def create_payroll(data, current_user=None, request: Optional[Request] = None):
    try:
        net_salary = _net_salary(
            data.basic_salary,
            data.allowance,
            data.overtime_amount,
            data.bonus,
            data.deduction,
            data.leave_deduction,
            data.tax,
        )

        payroll_data = payroll_repo.create(
            {
                "employee_id": str(data.employee_id),
                "payroll_month": data.payroll_month,
                "payroll_year": data.payroll_year,
                "basic_salary": data.basic_salary,
                "allowance": data.allowance,
                "overtime_amount": data.overtime_amount,
                "bonus": data.bonus,
                "deduction": data.deduction,
                "leave_deduction": data.leave_deduction,
                "tax": data.tax,
                "net_salary": net_salary,
                "remarks": data.remarks,
            }
        )

        record_audit_log(
            module="PAYROLL",
            action="CREATE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=payroll_data.get("employee_id"),
            record_id=payroll_data.get("id"),
            description=f"Payroll generated for {data.payroll_month}/{data.payroll_year}",
            new_values=payroll_data,
            request=request,
        )

        return success_response(message=PAYROLL_GENERATED, data=payroll_data)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to generate payroll.")


# ==========================================
# GET ALL PAYROLL (HR / Admin — requires VIEW_PAYROLL)
# ==========================================


def get_payrolls(page: int = 1, limit: int = 20):
    try:
        start = (max(page, 1) - 1) * max(min(limit, 100), 1)
        end = start + max(min(limit, 100), 1) - 1

        records, total = payroll_repo.list(
            select=PAYROLL_SELECT,
            order_by="payroll_year",
            ascending=False,
            start=start,
            end=end,
        )

        return success_response(
            message="Payroll records fetched successfully.",
            data={"records": records, "total": total, "page": page, "limit": limit},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch payroll records.")


# ==========================================
# GET MY PAYROLL (self-service — new endpoint, additive)
# ==========================================


def get_my_payrolls(auth_user_id: str):
    try:
        employee_id = get_employee_id_for_auth_user(auth_user_id)

        if not employee_id:
            return success_response(message="Payroll records fetched successfully.", data=[])

        records, _total = payroll_repo.list(
            select=PAYROLL_SELECT,
            filters={"employee_id": employee_id},
            order_by="payroll_year",
            ascending=False,
        )

        return success_response(message="Payroll records fetched successfully.", data=records)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch payroll records.")


# ==========================================
# GET ONE PAYROLL (HR/Admin via VIEW_PAYROLL, or the owning employee)
# ==========================================


def get_payroll(payroll_id: str, auth_user_id: str):
    try:
        record = payroll_repo.get_by_id_or_404(
            payroll_id, "Payroll record not found.", select=PAYROLL_SELECT
        )

        if not has_permission(auth_user_id, "VIEW_PAYROLL"):
            own_employee_id = get_employee_id_for_auth_user(auth_user_id)

            if not own_employee_id or record.get("employee_id") != own_employee_id:
                forbidden("You don't have permission to view this payroll record.")

        return success_response(message="Payroll record fetched successfully.", data=record)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to fetch payroll record.")


# ==========================================
# UPDATE PAYROLL
# ==========================================


def update_payroll(
    payroll_id: str,
    data,
    current_user=None,
    request: Optional[Request] = None,
):
    try:
        existing = payroll_repo.get_by_id_or_404(payroll_id, "Payroll record not found.")

        values = data.model_dump(exclude_unset=True)

        if any(k in values for k in (
            "basic_salary", "allowance", "overtime_amount", "bonus", "deduction", "leave_deduction", "tax"
        )):
            values["net_salary"] = _net_salary(
                values.get("basic_salary", existing.get("basic_salary", 0)),
                values.get("allowance", existing.get("allowance", 0)),
                values.get("overtime_amount", existing.get("overtime_amount", 0)),
                values.get("bonus", existing.get("bonus", 0)),
                values.get("deduction", existing.get("deduction", 0)),
                values.get("leave_deduction", existing.get("leave_deduction", 0)),
                values.get("tax", existing.get("tax", 0)),
            )

        updated = payroll_repo.update(payroll_id, values)

        record_audit_log(
            module="PAYROLL",
            action="UPDATE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=updated.get("employee_id"),
            record_id=payroll_id,
            description="Payroll record updated",
            old_values=existing,
            new_values=updated,
            request=request,
        )

        return success_response(message=PAYROLL_UPDATED, data=updated)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to update payroll record.")


# ==========================================
# DELETE PAYROLL
# ==========================================


def delete_payroll(payroll_id: str, current_user=None, request: Optional[Request] = None):
    try:
        existing = payroll_repo.get_by_id_or_404(payroll_id, "Payroll record not found.")

        payroll_repo.delete(payroll_id)

        record_audit_log(
            module="PAYROLL",
            action="DELETE",
            performed_by=getattr(current_user, "id", None),
            target_employee_id=existing.get("employee_id"),
            record_id=payroll_id,
            description="Payroll record deleted",
            old_values=existing,
            request=request,
        )

        return success_response(message=DELETED)

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to delete payroll record.")
