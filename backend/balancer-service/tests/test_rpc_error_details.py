"""The balancer's dict-detail errors reach clients as structure, not as a string.

A limit rejection carries the cap that was hit (``max_players``) and the code
that named it. Those used to be ``json.dumps``-ed into ``error.message``, so a
client had to parse JSON back out of a human-readable field to act on them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from src.rpc import _common as rpc_common  # noqa: E402


class _Logger:
    def exception(self, *args, **kwargs) -> None:
        raise AssertionError("mapped errors must not reach the defensive guard")


def _map(exc: Exception) -> dict:
    return rpc_common._map_error(_Logger(), "test", exc)["error"]


def test_module_no_longer_stringifies_details() -> None:
    # The old dict branch did a local ``import json`` purely to dump the detail
    # into the message; nothing here should need a JSON encoder any more.
    assert not hasattr(rpc_common, "json")


def test_dict_detail_keeps_the_keys_the_client_acts_on() -> None:
    # The shape ``_enforce_player_limit`` raises in services/balancer/jobs.py.
    exc = HTTPException(
        status_code=400,
        detail={"code": "balancer_player_limit_exceeded", "max_players": 500},
    )

    error = _map(exc)
    assert error["code"] == "bad_request"
    # The specific code and the cap the request blew past survive as a fields
    # entry. NOT merged at the top of details: the gateway lets the envelope's
    # own `code` win there, so a merged specific code would be dropped.
    assert error["details"]["fields"] == [
        {
            "field": None,
            "msg": "balancer player limit exceeded",
            "code": "balancer_player_limit_exceeded",
            "max_players": 500,
        }
    ]
    assert error["message"] == "balancer player limit exceeded"
    assert "{" not in error["message"]


def test_item_shaped_dict_detail_becomes_a_fields_entry() -> None:
    exc = HTTPException(status_code=409, detail={"msg": "team is full", "code": "team_full", "field": "roster"})
    error = _map(exc)
    assert error["message"] == "team is full"
    assert error["details"]["fields"] == [{"field": "roster", "msg": "team is full", "code": "team_full"}]


def test_rate_limit_headers_become_retry_after() -> None:
    exc = HTTPException(
        status_code=429,
        detail="Balancer rate limit exceeded: requests_per_minute",
        headers={"Retry-After": "30"},
    )
    error = _map(exc)
    assert error["code"] == "rate_limited"
    assert error["details"] == {"retry_after": 30}


def test_list_detail_still_carries_item_codes() -> None:
    exc = ApiHTTPException(status_code=422, detail=[ApiExc(msg="bad roster", code="roster_invalid")])
    error = _map(exc)
    assert error["message"] == "bad roster"
    assert error["details"]["fields"][0]["code"] == "roster_invalid"


def test_plain_string_detail_carries_no_details_key() -> None:
    assert "details" not in _map(HTTPException(status_code=404, detail="Job not found"))
