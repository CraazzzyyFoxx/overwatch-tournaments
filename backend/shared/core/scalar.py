from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from scalar_fastapi import AgentScalarConfig, get_scalar_api_reference


def _prefix_root_path(root_path: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path

    normalized_path = path if path.startswith("/") else f"/{path}"
    normalized_root = root_path.strip().rstrip("/")

    if not normalized_root:
        return normalized_path

    if not normalized_root.startswith("/"):
        normalized_root = f"/{normalized_root}"

    return f"{normalized_root}{normalized_path}"


def register_scalar_docs(app: FastAPI, *, path: str = "/scalar", title: str | None = None) -> None:
    @app.get(path, include_in_schema=False)
    async def scalar_docs(request: Request) -> HTMLResponse:
        root_path = request.scope.get("root_path", "")
        openapi_url = _prefix_root_path(str(root_path), app.openapi_url or "/openapi.json")

        return get_scalar_api_reference(
            openapi_url=openapi_url,
            title=title or f"{app.title} API Reference",
            agent=AgentScalarConfig(disabled=True),
            telemetry=False,
        )
