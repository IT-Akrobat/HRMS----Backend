from fastapi import HTTPException

from app.core.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)


def bad_request(message: str):
    raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=message)


def unauthorized(message: str = "Unauthorized"):
    raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=message)


def forbidden(message: str = "Access denied"):
    raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail=message)


def not_found(message: str = "Resource not found"):
    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=message)


def conflict(message: str = "Resource already exists"):
    raise HTTPException(status_code=HTTP_409_CONFLICT, detail=message)


def internal_server_error(message: str = "Internal server error"):
    raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=message)
