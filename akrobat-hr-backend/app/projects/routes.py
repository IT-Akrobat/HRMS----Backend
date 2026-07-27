from fastapi import APIRouter, Depends

from app.projects.schemas import CreateProjectRequest, UpdateProjectRequest

from app.projects.services import (
    create_project,
    get_projects,
    get_project,
    update_project,
    delete_project,
)

from app.core.security import get_current_user

router = APIRouter(prefix="/projects", tags=["Projects"])


# =========================
# CREATE PROJECT
# =========================


@router.post("/")
def create(data: CreateProjectRequest, user=Depends(get_current_user)):

    return create_project(data)


# =========================
# GET ALL PROJECTS
# =========================


@router.get("/")
def all_projects(user=Depends(get_current_user)):

    return get_projects()


# =========================
# GET PROJECT BY ID
# =========================


@router.get("/{project_id}")
def one_project(project_id: str, user=Depends(get_current_user)):

    return get_project(project_id)


# =========================
# UPDATE PROJECT
# =========================


@router.put("/{project_id}")
def update(project_id: str, data: UpdateProjectRequest, user=Depends(get_current_user)):

    return update_project(project_id, data)


# =========================
# DELETE PROJECT
# =========================


@router.delete("/{project_id}")
def delete(project_id: str, user=Depends(get_current_user)):

    return delete_project(project_id)
