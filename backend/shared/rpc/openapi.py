"""Declarative request/response model map for OpenAPI schema export.

The Go gateway owns the HTTP routes but the response/request *types* live here in
Python (Pydantic). Each service declares an ``OPERATIONS`` table mapping an RPC
subject (the same string the gateway dispatches to) to the Pydantic models it
consumes/produces. ``scripts/export_openapi_schemas.py`` turns these into a
JSON-Schema manifest the gateway embeds (see ``gateway/internal/openapi``).

This module imports nothing heavy — services declare ``OPERATIONS`` in a
schemas-only module so the export stays import-light (no broker/DB).

Subject key convention (must match the gateway's lookup):
  - bespoke handler:        the subject, e.g. ``"rpc.tournament.get_tournament"``
  - generic CRUD engine:    ``"<subject>#<entity>"`` (one subject, many entities),
                            e.g. ``"rpc.app.read.get#hero"``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QueryParam:
    """One explicitly-declared query parameter, for handlers that read ad-hoc
    query keys via ``_q1(data, "key", cast)`` instead of a Pydantic query model.

    ``type`` is an OpenAPI scalar (``string``/``integer``/``number``/``boolean``);
    ``array=True`` wraps it as an array of that scalar.
    """

    name: str
    type: str = "string"
    required: bool = False
    array: bool = False
    description: str = ""


@dataclass(frozen=True)
class Op:
    """Request/response models + query parameters for one RPC subject.

    ``response``/``request`` are Pydantic model classes (or a generic alias such
    as ``Paginated[TournamentRead]``, which is itself a model). ``response_array``
    marks a raw ``list[Model]`` return — rendered as an OpenAPI array of the
    referenced model (a ``Paginated[...]`` wrapper is NOT an array; it is a model).

    ``query`` is a Pydantic query-param model (incl. a generic alias such as
    ``PaginationSortSearchQueryParams[Literal[...]]``); its fields become
    ``in:query`` parameters. ``query_params`` declares params explicitly for
    handlers without a query model. Use one or the other (or neither).
    """

    response: Any = None
    response_array: bool = False
    request: Any = None
    query: Any = None
    query_params: tuple[QueryParam, ...] = field(default_factory=tuple)
