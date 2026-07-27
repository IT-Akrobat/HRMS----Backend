from datetime import datetime

from fastapi import HTTPException

from app.core.database import supabase_admin

# =========================
# CREATE EXPENSE
# =========================


def create_expense(employee_id: str, data):

    try:

        response = (
            supabase_admin.table("expenses")
            .insert(
                {
                    "employee_id": employee_id,
                    "expense_date": str(data.expense_date),
                    "category": data.category,
                    "amount": float(data.amount),
                    "description": data.description,
                    "receipt_url": data.receipt_url,
                }
            )
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# GET ALL EXPENSES
# =========================


def get_expenses():

    try:

        response = supabase_admin.table("expenses").select("""
            *,
            employees!expenses_employee_id_fkey(
                full_name,
                employee_id
            )
            """).order("created_at", desc=True).execute()

        return response.data

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# MY EXPENSES
# =========================


def get_my_expenses(employee_id: str):

    try:

        response = (
            supabase_admin.table("expenses")
            .select("*")
            .eq("employee_id", employee_id)
            .order("created_at", desc=True)
            .execute()
        )

        return response.data

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# GET SINGLE
# =========================


def get_expense(expense_id: str):

    try:

        response = (
            supabase_admin.table("expenses")
            .select("*")
            .eq("id", expense_id)
            .single()
            .execute()
        )

        return response.data

    except Exception as e:

        raise HTTPException(404, str(e))


# =========================
# UPDATE
# =========================


def update_expense(expense_id: str, data: dict):

    try:

        expense = (
            supabase_admin.table("expenses")
            .select("status")
            .eq("id", expense_id)
            .single()
            .execute()
        )

        if expense.data["status"] != "PENDING":

            raise HTTPException(400, "Only pending expenses can be updated")

        data["updated_at"] = datetime.utcnow().isoformat()

        response = (
            supabase_admin.table("expenses").update(data).eq("id", expense_id).execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# APPROVE
# =========================


def approve_expense(expense_id: str, approver_id: str, remarks: str = None):

    try:

        response = (
            supabase_admin.table("expenses")
            .update(
                {
                    "status": "APPROVED",
                    "approved_by": approver_id,
                    "approved_at": datetime.utcnow().isoformat(),
                    "remarks": remarks,
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            .eq("id", expense_id)
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(500, str(e))

        # =========================


# REJECT EXPENSE
# =========================


def reject_expense(expense_id: str, approver_id: str, remarks: str = None):

    try:

        response = (
            supabase_admin.table("expenses")
            .update(
                {
                    "status": "REJECTED",
                    "approved_by": approver_id,
                    "approved_at": datetime.utcnow().isoformat(),
                    "remarks": remarks,
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            .eq("id", expense_id)
            .execute()
        )

        return response.data[0]

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# DELETE EXPENSE
# =========================


def delete_expense(expense_id: str):

    try:

        expense = (
            supabase_admin.table("expenses")
            .select("status")
            .eq("id", expense_id)
            .single()
            .execute()
        )

        if expense.data["status"] != "PENDING":

            raise HTTPException(400, "Only pending expenses can be deleted")

        supabase_admin.table("expenses").delete().eq("id", expense_id).execute()

        return {"message": "Expense deleted successfully"}

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# PENDING EXPENSES
# =========================


def get_pending_expenses():

    try:

        response = supabase_admin.table("expenses").select("""
            *,
            employees!expenses_employee_id_fkey(
                full_name,
                employee_id
            )
            """).eq("status", "PENDING").order("created_at", desc=True).execute()

        return response.data

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# APPROVED EXPENSES
# =========================


def get_approved_expenses():

    try:

        response = supabase_admin.table("expenses").select("""
            *,
            employees!expenses_employee_id_fkey(
                full_name,
                employee_id
            )
            """).eq("status", "APPROVED").order("created_at", desc=True).execute()

        return response.data

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# REJECTED EXPENSES
# =========================


def get_rejected_expenses():

    try:

        response = supabase_admin.table("expenses").select("""
            *,
            employees!expenses_employee_id_fkey(
                full_name,
                employee_id
            )
            """).eq("status", "REJECTED").order("created_at", desc=True).execute()

        return response.data

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# EMPLOYEE EXPENSES
# =========================


def get_employee_expenses(employee_id: str):

    try:

        response = (
            supabase_admin.table("expenses")
            .select("*")
            .eq("employee_id", employee_id)
            .order("created_at", desc=True)
            .execute()
        )

        return response.data

    except Exception as e:

        raise HTTPException(500, str(e))


# =========================
# DATE FILTER
# =========================


def get_expenses_by_date(expense_date: str):

    try:

        response = (
            supabase_admin.table("expenses")
            .select("""
            *,
            employees!expenses_employee_id_fkey(
                full_name,
                employee_id
            )
            """)
            .eq("expense_date", expense_date)
            .order("created_at", desc=True)
            .execute()
        )

        return response.data

    except Exception as e:

        raise HTTPException(500, str(e))
