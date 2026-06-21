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

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Op:
    """Request/response models for one RPC subject.

    ``response``/``request`` are Pydantic model classes (or a generic alias such
    as ``Paginated[TournamentRead]``, which is itself a model). ``response_array``
    marks a raw ``list[Model]`` return — rendered as an OpenAPI array of the
    referenced model (a ``Paginated[...]`` wrapper is NOT an array; it is a model).
    """

    response: Any = None
    response_array: bool = False
    request: Any = None
