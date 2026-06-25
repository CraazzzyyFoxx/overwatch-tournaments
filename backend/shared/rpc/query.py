"""Reconstruct FastAPI query-params Pydantic models from gateway-forwarded query.

The gateway forwards query params as ``{key: [values]}`` (always lists, so repeated
params survive). This rebuilds the route's query-params model: list-typed fields
keep the list, scalar fields take the first value, and Pydantic coerces types —
so an RPC handler can call the same ``Params.from_query_params(...)`` the route did.

Routes declare params as ``Field(Query(default=X))``. Under direct ``model_validate``
(no FastAPI dependency resolution) an absent such field would keep the raw
``fastapi.params.Query`` marker as its value — not iterable, wrong type. So for any
absent field we resolve the marker's real default (``[]`` for lists).
"""

from __future__ import annotations

import types
import typing
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

T = TypeVar("T", bound=BaseModel)

_UNION_ORIGINS = (typing.Union, getattr(types, "UnionType", typing.Union))


def _is_list_field(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    if origin in (list, set, tuple, frozenset):
        return True
    if origin in _UNION_ORIGINS:
        return any(_is_list_field(arg) for arg in typing.get_args(annotation))
    return False


def _absent_default(field: Any, is_list: bool) -> tuple[bool, Any]:
    """Return (should_set, value) for a field missing from the query.

    For FastAPI Query/Param markers, use the marker's real default; otherwise let
    Pydantic apply the field's own default (return should_set=False).
    """
    default = field.default
    if type(default).__module__.split(".")[0] == "fastapi":
        real = getattr(default, "default", None)
        if real is Ellipsis or real is PydanticUndefined:
            real = None
        if real is None and is_list:
            real = []
        return True, real
    return False, None


def build_query_model(model: type[T], query: dict[str, Any] | None) -> T:
    """Build ``model`` from the forwarded query dict (values are lists of strings)."""
    query = query or {}
    data: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        is_list = _is_list_field(field.annotation)
        vals = query.get(field.alias or name)
        if vals is None and field.alias:
            vals = query.get(name)
        if vals is None:
            should_set, value = _absent_default(field, is_list)
            if should_set:
                data[name] = value
            continue
        if not isinstance(vals, list):
            vals = [vals]
        data[name] = vals if is_list else (vals[0] if vals else None)
    return model.model_validate(data)
