"""Regression: resolving a Challonge group to its stage must not touch ``tournament.groups``.

``_stage_for_challonge_group`` links a Challonge group id to a stage through
``stage.challonge_group_id``. It used to fall back to the legacy
``tournament.group`` table (iterating ``tournament.groups`` and matching
``group.challonge_id``) when no stage carried the marker. That table and its ORM
model were dropped, and ``Tournament`` declares no ``groups`` relationship at all,
so the fallback raised ``AttributeError`` rather than returning ``None``.

The fallback ran on exactly the case the caller cares about: the FIRST import of a
grouped bracket, when no stage carries the marker yet and
``_ensure_stage_structure_for_matches`` is about to create the missing group stage
(``if stage is None: await self._create_group_with_stage(...)``). So a "no stage
for this group yet" lookup crashed instead of reporting the miss.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest import TestCase

os.environ.setdefault("DEBUG", "true")

from src import models  # noqa: E402
from src.core import enums  # noqa: E402
from src.services.challonge import sync  # noqa: E402


def _stage(stage_id: int, challonge_group_id: int | None) -> models.Stage:
    return models.Stage(
        id=stage_id,
        created_at=datetime.now(UTC),
        updated_at=None,
        tournament_id=7,
        name=f"Stage {stage_id}",
        description=None,
        stage_type=enums.StageType.ROUND_ROBIN,
        max_rounds=1,
        advance_count=None,
        split_lower_bracket=False,
        order=stage_id,
        is_active=False,
        is_published=False,
        is_completed=False,
        challonge_group_id=challonge_group_id,
    )


def _tournament(stages: list[models.Stage]) -> models.Tournament:
    tournament = models.Tournament(
        id=7,
        created_at=datetime.now(UTC),
        updated_at=None,
        workspace_id=1,
        name="Grouped",
        slug="grouped",
        status=enums.TournamentStatus.LIVE,
        start_date=datetime.now(UTC),
        end_date=datetime.now(UTC),
    )
    tournament.stages = stages
    return tournament


class StageForChallongeGroupTests(TestCase):
    def test_the_marker_column_resolves_the_stage(self) -> None:
        wanted = _stage(2, 555)
        tournament = _tournament([_stage(1, None), wanted])

        self.assertIs(wanted, sync._stage_for_challonge_group(tournament, 555))

    def test_an_unknown_group_reports_a_miss_instead_of_raising(self) -> None:
        # The first import of a grouped bracket: no stage carries the marker yet.
        # This must be a plain None so the caller creates the group stage; reaching
        # for the dropped `tournament.groups` raised AttributeError here.
        tournament = _tournament([_stage(1, 111)])

        self.assertIsNone(sync._stage_for_challonge_group(tournament, 555))

    def test_no_stages_at_all_reports_a_miss(self) -> None:
        self.assertIsNone(sync._stage_for_challonge_group(_tournament([]), 555))

    def test_tournament_declares_no_groups_relationship(self) -> None:
        # Pins WHY the fallback had to go: there is nothing to fall back to.
        self.assertFalse(hasattr(models.Tournament, "groups"))
