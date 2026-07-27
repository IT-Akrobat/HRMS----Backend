from fastapi import APIRouter, Depends


from app.roles.services import get_roles, get_role_by_id


from app.core.permissions import require_role

router = APIRouter(prefix="/roles", tags=["Roles"])


# =========================
# ALL ROLES
# =========================


@router.get("/")
def all_roles(user=Depends(require_role(["SUPER ADMIN", "HR"]))):

    return get_roles()


# =========================
# SPECIFIC ROLE
# =========================


@router.get("/{role_id}")
def specific_role(role_id: str, user=Depends(require_role(["SUPER ADMIN", "HR"]))):

    return get_role_by_id(role_id)
