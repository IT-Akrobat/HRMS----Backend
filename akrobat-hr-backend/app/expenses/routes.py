from fastapi import APIRouter, Depends

from app.expenses.schemas import (
    CreateExpenseRequest,
    UpdateExpenseRequest,
    ExpenseApprovalRequest,
)

from app.expenses.services import (
    create_expense,
    get_expenses,
    get_my_expenses,
    get_expense,
    update_expense,
    approve_expense,
    reject_expense,
    delete_expense,
    get_pending_expenses,
    get_approved_expenses,
    get_rejected_expenses,
    get_employee_expenses,
    get_expenses_by_date,
)

from app.core.security import get_current_user

router = APIRouter(prefix="/expenses", tags=["Expenses"])


# =========================
# CREATE EXPENSE
# =========================


@router.post("/")
def create(data: CreateExpenseRequest, user=Depends(get_current_user)):

    return create_expense(user.id, data)


# =========================
# GET ALL EXPENSES
# =========================


@router.get("/")
def all_expenses(user=Depends(get_current_user)):

    return get_expenses()


# =========================
# MY EXPENSES
# =========================


@router.get("/my")
def my_expenses(user=Depends(get_current_user)):

    return get_my_expenses(user.id)


# =========================
# PENDING
# =========================


@router.get("/pending")
def pending(user=Depends(get_current_user)):

    return get_pending_expenses()


# =========================
# APPROVED
# =========================


@router.get("/approved")
def approved(user=Depends(get_current_user)):

    return get_approved_expenses()


# =========================
# REJECTED
# =========================


@router.get("/rejected")
def rejected(user=Depends(get_current_user)):

    return get_rejected_expenses()


# =========================
# EMPLOYEE EXPENSES
# =========================


@router.get("/employee/{employee_id}")
def employee_expenses(employee_id: str, user=Depends(get_current_user)):

    return get_employee_expenses(employee_id)


# =========================
# DATE FILTER
# =========================


@router.get("/date/{expense_date}")
def date_filter(expense_date: str, user=Depends(get_current_user)):

    return get_expenses_by_date(expense_date)


# =========================
# GET SINGLE
# =========================


@router.get("/{expense_id}")
def get_one(expense_id: str, user=Depends(get_current_user)):

    return get_expense(expense_id)


# =========================
# UPDATE
# =========================


@router.put("/{expense_id}")
def update(expense_id: str, data: UpdateExpenseRequest, user=Depends(get_current_user)):

    return update_expense(expense_id, data.model_dump(exclude_unset=True))


# =========================
# APPROVE
# =========================


@router.put("/{expense_id}/approve")
def approve(
    expense_id: str, data: ExpenseApprovalRequest, user=Depends(get_current_user)
):

    return approve_expense(expense_id, user.id, data.remarks)


# =========================
# REJECT
# =========================


@router.put("/{expense_id}/reject")
def reject(
    expense_id: str, data: ExpenseApprovalRequest, user=Depends(get_current_user)
):

    return reject_expense(expense_id, user.id, data.remarks)


# =========================
# DELETE
# =========================


@router.delete("/{expense_id}")
def delete(expense_id: str, user=Depends(get_current_user)):

    return delete_expense(expense_id)
