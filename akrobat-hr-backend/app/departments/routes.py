from fastapi import APIRouter, Depends

from app.departments.services import get_departments, create_department

from app.departments.schemas import CreateDepartmentRequest

from app.core.permissions import require_role

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.post("/")
def create(
    data: CreateDepartmentRequest,
    user=Depends(require_role(["SUPER ADMIN", "HR"])),
):

    return create_department(data)


# ALL DEPARTMENTS


@router.get("/")
def get_all(user=Depends(require_role(["SUPER ADMIN", "HR"]))):

    return get_departments()


# SPECIFIC DEPARTMENT


@router.get("/{department_id}")
def get_one(
    department_id: str,
    user=Depends(require_role(["SUPER ADMIN", "HR"])),
):

    return get_departments(department_id)
