from dataclasses import dataclass


@dataclass(frozen=True)
class UploadResult:
    success: bool
    key: str
    public_url: str | None = None
    error: str | None = None
