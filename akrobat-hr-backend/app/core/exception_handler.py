from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.responses import error_response
from app.core.status_codes import HTTP_422_UNPROCESSABLE_ENTITY, HTTP_500_INTERNAL_SERVER_ERROR
from app.core.logger import logger


async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(
        f"HTTPException | {request.method} {request.url.path} | "
        f"status={exc.status_code} | detail={exc.detail}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            message=str(exc.detail),
            errors=None,
            status_code=exc.status_code,
        ),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(
        f"ValidationError | {request.method} {request.url.path} | errors={exc.errors()}"
    )
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response(
            message="Validation failed",
            errors=exc.errors(),
            status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"UnhandledException | {request.method} {request.url.path} | {exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response(
            message="Internal server error",
            errors=str(exc),
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        ),
    )
