"""Resilient HTTP client with connection pooling, retries, and circuit breaker."""

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .circuit_breaker import CircuitBreaker

# Import correlation ID function (optional dependency)
try:
    from shared.observability.correlation import get_correlation_id
except ImportError:
    get_correlation_id = None


class ResilientHttpClient:
    """HTTP client with connection pooling, retry logic, and circuit breaker.

    Features:
    - Persistent connection pooling for better performance
    - Automatic retries with exponential backoff
    - Circuit breaker to prevent cascading failures
    - Configurable timeouts

    Example:
        ```python
        client = ResilientHttpClient(
            base_url="http://auth:8001",
            timeout=5.0,
            max_retries=3,
        )

        await client.start()
        try:
            response = await client.get("/validate")
            data = response.json()
        finally:
            await client.close()
        ```
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        max_retries: int = 3,
        circuit_breaker: CircuitBreaker | None = None,
        headers: dict[str, str] | None = None,
    ):
        """Initialize the resilient HTTP client.

        Args:
            base_url: Base URL for all requests
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            circuit_breaker: Optional circuit breaker instance (creates default if None)
            headers: Optional default headers to include in all requests
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.default_headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ResilientHttpClient":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()

    async def start(self) -> None:
        """Initialize the HTTP client with connection pooling.

        Should be called during application startup.
        """
        if self._client is None:
            limits = httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            )
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                limits=limits,
                headers=self.default_headers,
            )

    async def close(self) -> None:
        """Close the HTTP client and clean up connections.

        Should be called during application shutdown.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with retry logic and circuit breaker.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path (will be appended to base_url)
            **kwargs: Additional arguments to pass to httpx

        Returns:
            HTTP response

        Raises:
            CircuitBreakerOpen: If circuit breaker is open
            httpx.HTTPError: For HTTP errors after retries exhausted
        """
        if self._client is None:
            raise RuntimeError("Client not started. Call start() first.")

        # Add correlation ID to outbound requests for distributed tracing
        if get_correlation_id is not None:
            correlation_id = get_correlation_id()
            if correlation_id:
                kwargs.setdefault("headers", {})
                if isinstance(kwargs["headers"], dict):
                    kwargs["headers"]["X-Request-ID"] = correlation_id

        # Create a retry decorator for this specific request
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        )
        async def _make_request() -> httpx.Response:
            return await self._client.request(method, path, **kwargs)

        # Wrap the request in the circuit breaker
        return await self.circuit_breaker.call(_make_request())

    async def get(self, path: str, **kwargs) -> httpx.Response:
        """Make a GET request."""
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> httpx.Response:
        """Make a POST request."""
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> httpx.Response:
        """Make a PUT request."""
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs) -> httpx.Response:
        """Make a PATCH request."""
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> httpx.Response:
        """Make a DELETE request."""
        return await self.request("DELETE", path, **kwargs)
