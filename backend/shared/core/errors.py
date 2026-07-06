from pydantic import BaseModel, ValidationError

__all__ = (
    "ApiExc",
    "BaseAPIException",
    "ApiHTTPException",
    "ValidationErrorDetail",
    "APIValidationError",
)


class ApiExc(BaseModel):
    msg: str
    code: str


class BaseAPIException(Exception):
    """Framework-neutral HTTP-ish error raised across the RPC + service layers.

    Mirrors the ``fastapi.HTTPException`` constructor (``status_code`` / ``detail``
    / ``headers``) so the RPC envelope helpers can map ``status_code`` to an error
    code (``status_to_code``) and flatten ``detail`` to a message — without the
    codebase importing FastAPI. RPC-path modules import this as ``HTTPException``
    (``from shared.core.errors import BaseAPIException as HTTPException``) so the
    existing ``raise HTTPException(...)`` / ``except HTTPException`` sites are
    drop-in unchanged.
    """

    def __init__(
        self,
        status_code: int,
        detail: object = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
        super().__init__(detail)


class ApiHTTPException(BaseAPIException):
    def __init__(
        self,
        status_code: int,
        detail: list[ApiExc],
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=[e.model_dump(mode="json") for e in detail],
            headers=headers,
        )


class ValidationErrorDetail(BaseModel):
    location: str
    message: str
    error_type: str


class APIValidationError(BaseModel):
    errors: list[ValidationErrorDetail]

    @classmethod
    def from_pydantic(cls, exc: ValidationError) -> "APIValidationError":
        return cls(
            errors=[
                ValidationErrorDetail(
                    location=" -> ".join(map(str, err["loc"])),
                    message=str(err["msg"]),
                    error_type=str(err["type"]),
                )
                for err in exc.errors()
            ],
        )
