from typing import Any, Optional


def success_response(message: str, data: Any = None, status_code: int = 200):
    return {
        "success": True,
        "status_code": status_code,
        "message": message,
        "data": data,
    }


def error_response(message: str, errors: Optional[Any] = None, status_code: int = 400):
    return {
        "success": False,
        "status_code": status_code,
        "message": message,
        "errors": errors,
    }


def paginated_response(
    data: list,
    total: int,
    page: int,
    limit: int,
    message: str = "Data fetched successfully",
):
    return {
        "success": True,
        "message": message,
        "data": data,
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit,
        },
    }
