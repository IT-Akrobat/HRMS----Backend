from pydantic import BaseModel


class CreateDepartmentRequest(BaseModel):

    department_name: str

    department_code: str | None = None
