from fastapi import APIRouter, Depends


from app.designations.schemas import CreateDesignationRequest


from app.designations.services import (
    create_designation,
    get_designations,
    get_department_designations,
    update_designation,
    delete_designation,
)


from app.core.permissions import require_role

router = APIRouter(prefix="/designations", tags=["Designations"])


# CREATE


@router.post("/")
def create(
    data: CreateDesignationRequest,
    user=Depends(require_role(["SUPER ADMIN", "HR"])),
):

    return create_designation(data)


# GET ALL


@router.get("/")
def get_all(user=Depends(require_role(["SUPER ADMIN", "HR"]))):

    return get_designations()


# GET SPECIFIC


@router.get("/{designation_id}")
def get_one(designation_id: str, user=Depends(require_role(["SUPER ADMIN", "HR"]))):

    return get_designations(designation_id)


# GET BY DEPARTMENT


@router.get("/department/{department_id}")
def by_department(
    department_id: str,
    user=Depends(require_role(["SUPER ADMIN", "HR"])),
):

    return get_department_designations(department_id)


# UPDATE


@router.put("/{designation_id}")
def update(
    designation_id: str,
    data: dict,
    user=Depends(require_role(["SUPER ADMIN", "HR"])),
):

    return update_designation(designation_id, data)


# DELETE


@router.delete("/{designation_id}")
def delete(designation_id: str, user=Depends(require_role(["SUPER ADMIN", "HR"]))):

    return delete_designation(designation_id)
