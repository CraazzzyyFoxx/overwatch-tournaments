from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException, RequestValidationError
from starlette.responses import JSONResponse
from loguru import logger
from pydantic import ValidationError
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from shared.core.errors import ApiHTTPException

__all__ = ("ExceptionMiddleware", "RequestSizeLimitMiddleware")


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds a configurable limit.

    Usage::

        app.add_middleware(RequestSizeLimitMiddleware, max_content_length=10 * 1024 * 1024)
    """

    def __init__(self, app, *, max_content_length: int = 10 * 1024 * 1024) -> None:
        super().__init__(app)
        self.max_content_length = max_content_length

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "detail": [{"msg": "Invalid Content-Length header", "code": "invalid_header"}]
                    },
                )
            if length > self.max_content_length:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "detail": [{"msg": "Request body too large", "code": "request_too_large"}]
                    },
                )
        return await call_next(request)


class ExceptionMiddleware(BaseHTTPMiddleware):
    """Unified exception handling middleware for all services.

    Usage::

        app.add_middleware(
            ExceptionMiddleware,
            is_development=settings.environment == "development",
        )
    """

    def __init__(self, app, *, is_development: bool = False) -> None:
        super().__init__(app)
        self.is_development = is_development

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            response = await call_next(request)
        except RequestValidationError as e:
            logger.warning(
                "Request validation error",
                exc_info=self.is_development,
            )
            validation_errors = jsonable_encoder(
                e.errors(),
                exclude={"url", "ctx", "input"},
            )
            response = JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "detail": [
                        {
                            "msg": validation_errors,
                            "code": "unprocessable_entity",
                        }
                    ]
                },
            )
        except ValidationError as e:
            logger.exception("Pydantic model validation error (internal)")
            response = JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=jsonable_encoder({
                    "detail": [
                        {
                            "msg": e.errors(include_url=False),
                            "code": "unprocessable_entity",
                        }
                    ]
                }),
            )
        except ApiHTTPException as e:
            if e.status_code >= 500:
                logger.error(f"ApiHTTPException {e.status_code}: {e.detail}")
            else:
                logger.bind(status_code=e.status_code).debug(f"ApiHTTPException: {e.detail}")
            response = JSONResponse(content=jsonable_encoder({"detail": e.detail}), status_code=e.status_code)
        except HTTPException as e:
            if e.status_code >= 500:
                logger.error(f"HTTPException {e.status_code}: {e.detail}")
            else:
                logger.bind(status_code=e.status_code).debug(f"HTTPException: {e.detail}")
            response = JSONResponse(content=jsonable_encoder({"detail": [e.detail]}), status_code=e.status_code)
        except Exception as e:
            logger.exception(e)
            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": [{"msg": "Unknown", "code": "Unknown"}]},
            )

        return response
