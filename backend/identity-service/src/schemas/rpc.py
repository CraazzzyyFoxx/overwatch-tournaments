"""RPC reply envelope — now lives in shared (reused by every headless service).

Kept as a re-export so existing ``from src.schemas.rpc import ...`` imports in
identity-svc keep working.
"""

from shared.schemas.rpc import ERROR_CODES, rpc_error, rpc_ok, status_to_code

__all__ = ("ERROR_CODES", "rpc_ok", "rpc_error", "status_to_code")
