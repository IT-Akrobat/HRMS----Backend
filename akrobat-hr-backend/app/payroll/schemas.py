from pydantic import BaseModel


class CreatePayrollRequest(BaseModel):

    employee_id: str

    payroll_month: int

    payroll_year: int

    basic_salary: float

    allowance: float = 0

    overtime_amount: float = 0

    bonus: float = 0

    deduction: float = 0

    leave_deduction: float = 0

    tax: float = 0

    remarks: str | None = None


class UpdatePayrollRequest(BaseModel):

    basic_salary: float | None = None

    allowance: float | None = None

    overtime_amount: float | None = None

    bonus: float | None = None

    deduction: float | None = None

    leave_deduction: float | None = None

    tax: float | None = None

    payment_status: str | None = None

    payment_date: str | None = None

    remarks: str | None = None
