"""
Swagger "Try it out" examples for POST /employees, one per role.

There are 4 roles: SUPER ADMIN, HR, MANAGER, EMPLOYEE. Their
role ids were created with a random uuid_generate_v4() in the seed, so
there's no way to know them ahead of time here — those fields are left
as an obvious REPLACE_WITH_... placeholder naming exactly what to look
up and from which GET endpoint, so it's a copy/paste job in Swagger
rather than a guessing game.
"""

CREATE_EMPLOYEE_EXAMPLES = {
    "super_admin_creates_super_admin": {
        "summary": "1. Owner creates another SUPER ADMIN",
        "description": (
            "Called by IT@akrobat.com.sg (or any existing Super Admin). "
            "Get the real role_id first: GET /roles -> find role_name == 'SUPER ADMIN'."
        ),
        "value": {
            "full_name": "Aarav Krishnan",
            "email": "aarav.krishnan@akrobat.com.sg",
            "password": "StrongPass123!",
            "role_id": "REPLACE_WITH_SUPER_ADMIN_ROLE_ID_FROM_GET_/roles",
            "employment_status": "Active",
        },
    },
    "super_admin_creates_hr": {
        "summary": "2. Super Admin creates an HR user",
        "description": (
            "role_id: GET /roles -> role_name == 'HR'. "
            "department_id: GET /departments -> department_name == 'HUMAN RESOURCE'. "
            "designation_id: GET /designations -> designation_name == 'ACCOUNTING PROGRAMMER' "
            "(the only HR-linked designation seeded so far)."
        ),
        "value": {
            "full_name": "Sarah Williams",
            "email": "sarah.williams@akrobat.com.sg",
            "password": "StrongPass123!",
            "department_id": "REPLACE_WITH_HUMAN_RESOURCE_DEPARTMENT_ID_FROM_GET_/departments",
            "designation_id": "REPLACE_WITH_ACCOUNTING_PROGRAMMER_DESIGNATION_ID_FROM_GET_/designations",
            "role_id": "REPLACE_WITH_HR_ROLE_ID_FROM_GET_/roles",
            "joining_date": "2026-07-08",
            "employment_status": "Active",
        },
    },
    "super_admin_or_hr_creates_manager": {
        "summary": "3. Super Admin / HR creates a MANAGER",
        "description": (
            "role_id: GET /roles -> role_name == 'MANAGER'. "
            "department_id: GET /departments -> department_name == 'OPERATIONS'. "
            "designation_id: GET /designations -> designation_name == 'PROJECT MANAGER'."
        ),
        "value": {
            "full_name": "Priya Nair",
            "email": "priya.nair@akrobat.com.sg",
            "password": "StrongPass123!",
            "department_id": "REPLACE_WITH_OPERATIONS_DEPARTMENT_ID_FROM_GET_/departments",
            "designation_id": "REPLACE_WITH_PROJECT_MANAGER_DESIGNATION_ID_FROM_GET_/designations",
            "role_id": "REPLACE_WITH_MANAGER_ROLE_ID_FROM_GET_/roles",
            "joining_date": "2026-07-08",
            "employment_status": "Active",
        },
    },
    "manager_or_hr_creates_employee": {
        "summary": "4. Manager / HR creates an EMPLOYEE",
        "description": (
            "role_id: GET /roles -> role_name == 'EMPLOYEE'. "
            "department_id: GET /departments -> department_name == 'PROCUREMENT AND LOGISTICS'. "
            "designation_id: GET /designations -> designation_name == "
            "'PROCUREMENT AND LOGISTICS EXECUTIVE'."
        ),
        "value": {
            "full_name": "John Doe",
            "email": "john.doe@akrobat.com.sg",
            "password": "StrongPass123!",
            "department_id": "REPLACE_WITH_PROCUREMENT_AND_LOGISTICS_DEPARTMENT_ID_FROM_GET_/departments",
            "designation_id": "REPLACE_WITH_PROCUREMENT_AND_LOGISTICS_EXECUTIVE_DESIGNATION_ID_FROM_GET_/designations",
            "role_id": "REPLACE_WITH_EMPLOYEE_ROLE_ID_FROM_GET_/roles",
            "joining_date": "2026-07-08",
            "employment_status": "Active",
        },
    },
}
