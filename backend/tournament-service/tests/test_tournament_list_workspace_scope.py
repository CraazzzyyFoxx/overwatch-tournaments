"""``workspace_id=all`` is the public cross-workspace opt-in; the tournament list
and its facets must read it as "every workspace", not reject it with a 422."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ.setdefault("DEBUG", "true")

from shared.rpc.query import build_query_model  # noqa: E402
from src import schemas  # noqa: E402

MODELS = (schemas.TournamentPaginationSortSearchQueryParams, schemas.TournamentFacetsQueryParams)


@pytest.mark.parametrize("model", MODELS)
def test_all_is_every_workspace_and_an_id_still_narrows(model: type) -> None:
    assert build_query_model(model, {"workspace_id": ["all"]}).workspace_id is None
    assert build_query_model(model, {"workspace_id": ["7"]}).workspace_id == 7


@pytest.mark.parametrize("model", MODELS)
def test_junk_is_still_rejected(model: type) -> None:
    with pytest.raises(ValidationError):
        build_query_model(model, {"workspace_id": ["everything"]})
