from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import ENVIRONMENT
from app.core.responses import error_response
from app.core.status_codes import (
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
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
    # Full exception always goes to the server log (exc_info=True below),
    # regardless of environment -- this is only about what goes back to
    # the CALLER in the HTTP response body.
    logger.error(
        f"UnhandledException | {request.method} {request.url.path} | {exc}",
        exc_info=True,
    )

    # Raw exception text (str(exc)) can include DB column/table names,
    # file paths, or other internals -- fine for local debugging, not
    # fine to hand to whoever sent the request once this is live. Only
    # include it when ENVIRONMENT=development; production callers get a
    # generic message and should check the server log instead.
    exposed_error = str(exc) if ENVIRONMENT == "development" else None

    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response(
            message="Internal server error",
            errors=exposed_error,
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        ),
    )
