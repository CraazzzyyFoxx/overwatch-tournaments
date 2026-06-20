"""FastAPI-free HTTP status constants.

Drop-in replacement for ``fastapi.status`` (which only re-exports
``starlette.status``): the same ``HTTP_<code>_<NAME>`` integer constants, so
RPC-path modules can ``from shared.core import http_status as status`` and keep
``status.HTTP_403_FORBIDDEN`` usages unchanged — without importing FastAPI.
"""

# 2xx
HTTP_200_OK = 200
HTTP_201_CREATED = 201
HTTP_202_ACCEPTED = 202
HTTP_204_NO_CONTENT = 204

# 3xx
HTTP_304_NOT_MODIFIED = 304

# 4xx
HTTP_400_BAD_REQUEST = 400
HTTP_401_UNAUTHORIZED = 401
HTTP_403_FORBIDDEN = 403
HTTP_404_NOT_FOUND = 404
HTTP_405_METHOD_NOT_ALLOWED = 405
HTTP_409_CONFLICT = 409
HTTP_410_GONE = 410
HTTP_413_REQUEST_ENTITY_TOO_LARGE = 413
HTTP_422_UNPROCESSABLE_ENTITY = 422
HTTP_422_UNPROCESSABLE_CONTENT = 422  # fastapi.status alias for 422
HTTP_429_TOO_MANY_REQUESTS = 429

# 5xx
HTTP_500_INTERNAL_SERVER_ERROR = 500
HTTP_502_BAD_GATEWAY = 502
HTTP_503_SERVICE_UNAVAILABLE = 503
HTTP_504_GATEWAY_TIMEOUT = 504
