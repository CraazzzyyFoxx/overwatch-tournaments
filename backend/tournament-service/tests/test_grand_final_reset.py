"""The Grand Final Reset is decided by advancement LINKS, not round numbers.

Review items 2/3/4c: the old rule ("highest positive round in the item" plus
``away_team_id == winner``) mis-answered every interesting case — a pre-created
reset made itself the highest round, a legal home/away swap hid the LB champion,
and the lazily created reset could spawn a second one because nothing said it
was already a reset. The rule pinned here is structural: an encounter is the
Grand Final iff a WINNER link from a NEGATIVE (lower-bracket) round feeds it,
and that link's slot is where the LB champion plays.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

advancement = importlib.import_module("shared.services.bracket.advancement")
enums = importlib.import_module("shared.core.enums")
Stage = importlib.import_module("shared.models.tournament.stage").Stage
EncounterLink = importlib.import_module("shared.models.tournament.encounter_link").EncounterLink

UB_CHAMPION = 2069
LB_CHAMPION = 2071
GF_ID = 500
LEFTOVER_RESET_ID = 77


class _Result:
    """Minimal stand-in for a SQLAlchemy ``Result``."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list:
        return list(self._rows)


def _incoming(role, slot, source_round: int) -> SimpleNamespace:
    return SimpleNamespace(role=role, target_slot=slot, source_round=source_round)


def _outgoing(target_id: int, role, slot) -> SimpleNamespace:
    return SimpleNamespace(source_encounter_id=GF_ID, target_encounter_id=target_id, role=role, target_slot=slot)


def _gf(*, home_team_id: int, away_team_id: int, encounter_id: int = GF_ID, round_number: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        id=encounter_id,
        tournament_id=72,
        stage_id=175,
        stage_item_id=176,
        round=round_number,
        best_of=5,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )


def _reset_row(**overrides) -> SimpleNamespace:
    row = SimpleNamespace(
        id=LEFTOVER_RESET_ID,
        status=enums.EncounterStatus.OPEN,
        home_score=0,
        away_score=0,
        result_status=enums.EncounterResultStatus.NONE,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class _FakeSession:
    """Answers exactly the four reads ``_maybe_create_grand_final_reset`` makes:
    the stage, the incoming-link scalar, the outgoing links and a target row."""

    def __init__(
        self,
        *,
        incoming: list[SimpleNamespace] | None = None,
        outgoing: list[SimpleNamespace] | None = None,
        encounters: dict[int, SimpleNamespace] | None = None,
        grand_final_type: str = "with_reset",
    ) -> None:
        self.stage = SimpleNamespace(
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            de_grand_final_type=grand_final_type,
        )
        self.incoming = incoming or []
        self.outgoing = outgoing or []
        self.encounters = encounters or {}
        self.added: list = []
        self.deleted: list = []

    async def get(self, model, pk, **_kwargs):
        if model is Stage:
            return self.stage
        return self.encounters.get(pk)

    async def scalar(self, _statement):
        # The only scalar() read: the LB-champion slot of the incoming WINNER
        # link whose source sits in a negative round.
        for link in self.incoming:
            if link.role == enums.EncounterLinkRole.WINNER and link.source_round < 0:
                return link.target_slot
        return None

    async def execute(self, statement):
        if "encounter_link" in str(statement):
            return _Result(self.outgoing)
        return _Result([(UB_CHAMPION, "Averet"), (LB_CHAMPION, "litnik")])

    def add(self, obj) -> None:
        self.added.append(obj)

    async def delete(self, obj) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 900 + len(self.added)

    def links(self) -> list:
        return [obj for obj in self.added if isinstance(obj, EncounterLink)]

    def encounters_added(self) -> list:
        return [obj for obj in self.added if type(obj).__name__ == "Encounter"]


class GrandFinalResetTests(IsolatedAsyncioTestCase):
    async def test_lb_champion_in_away_slot_creates_a_linked_reset(self) -> None:
        session = _FakeSession(
            incoming=[_incoming(enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY, source_round=-3)]
        )
        gf = _gf(home_team_id=UB_CHAMPION, away_team_id=LB_CHAMPION)

        reset, dropped = await advancement._maybe_create_grand_final_reset(session, gf, LB_CHAMPION)

        self.assertIsNotNone(reset)
        self.assertEqual([], dropped)
        self.assertEqual(4, reset.round)
        self.assertEqual(5, reset.best_of)
        self.assertEqual((UB_CHAMPION, LB_CHAMPION), (reset.home_team_id, reset.away_team_id))
        self.assertEqual(
            {
                (enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY),
                (enums.EncounterLinkRole.LOSER, enums.EncounterLinkSlot.HOME),
            },
            {(link.role, link.target_slot) for link in session.links()},
        )
        self.assertTrue(
            all(link.source_encounter_id == GF_ID and link.target_encounter_id == reset.id for link in session.links())
        )

    async def test_lb_champion_in_home_slot_still_creates_the_reset(self) -> None:
        """A home/away swap moves the link with the team. The old
        ``away_team_id == winner`` rule returned None here and silently skipped a
        mandatory reset (review item 4)."""
        session = _FakeSession(
            incoming=[_incoming(enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.HOME, source_round=-3)]
        )
        gf = _gf(home_team_id=LB_CHAMPION, away_team_id=UB_CHAMPION)

        reset, _ = await advancement._maybe_create_grand_final_reset(session, gf, LB_CHAMPION)

        self.assertIsNotNone(reset)
        self.assertEqual(
            {
                (enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.HOME),
                (enums.EncounterLinkRole.LOSER, enums.EncounterLinkSlot.AWAY),
            },
            {(link.role, link.target_slot) for link in session.links()},
        )

    async def test_the_created_reset_never_spawns_a_second_reset(self) -> None:
        """Play the reset the first case created: its own incoming links come
        from the GF, a POSITIVE round, so it is not a Grand Final."""
        first = _FakeSession(
            incoming=[_incoming(enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY, source_round=-3)]
        )
        gf = _gf(home_team_id=UB_CHAMPION, away_team_id=LB_CHAMPION)
        reset, _ = await advancement._maybe_create_grand_final_reset(first, gf, LB_CHAMPION)

        second = _FakeSession(
            incoming=[_incoming(link.role, link.target_slot, source_round=gf.round) for link in first.links()]
        )

        self.assertEqual((None, []), await advancement._maybe_create_grand_final_reset(second, reset, LB_CHAMPION))
        self.assertEqual([], second.encounters_added())

    async def test_ub_champion_win_deletes_an_untouched_leftover_reset(self) -> None:
        leftover = _reset_row()
        session = _FakeSession(
            incoming=[_incoming(enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY, source_round=-3)],
            outgoing=[
                _outgoing(LEFTOVER_RESET_ID, enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY),
                _outgoing(LEFTOVER_RESET_ID, enums.EncounterLinkRole.LOSER, enums.EncounterLinkSlot.HOME),
            ],
            encounters={LEFTOVER_RESET_ID: leftover},
        )
        gf = _gf(home_team_id=UB_CHAMPION, away_team_id=LB_CHAMPION)

        self.assertEqual(
            (None, [leftover]), await advancement._maybe_create_grand_final_reset(session, gf, UB_CHAMPION)
        )
        self.assertEqual([leftover], session.deleted)
        self.assertEqual([], session.encounters_added())

    async def test_ub_champion_win_keeps_a_played_reset_for_an_admin(self) -> None:
        played = _reset_row(
            status=enums.EncounterStatus.COMPLETED,
            home_score=3,
            away_score=1,
            result_status=enums.EncounterResultStatus.CONFIRMED,
        )
        session = _FakeSession(
            incoming=[_incoming(enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY, source_round=-3)],
            outgoing=[_outgoing(LEFTOVER_RESET_ID, enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY)],
            encounters={LEFTOVER_RESET_ID: played},
        )
        gf = _gf(home_team_id=UB_CHAMPION, away_team_id=LB_CHAMPION)

        self.assertEqual((None, []), await advancement._maybe_create_grand_final_reset(session, gf, UB_CHAMPION))
        self.assertEqual([], session.deleted)

    async def test_only_positive_round_sources_means_never_a_grand_final(self) -> None:
        """A UB Final (or the reset itself) is fed only from positive rounds —
        it creates nothing even when it is the highest round materialised."""
        session = _FakeSession(
            incoming=[
                _incoming(enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.HOME, source_round=2),
                _incoming(enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY, source_round=2),
            ]
        )
        gf = _gf(home_team_id=UB_CHAMPION, away_team_id=LB_CHAMPION, round_number=9)

        self.assertEqual((None, []), await advancement._maybe_create_grand_final_reset(session, gf, LB_CHAMPION))
        self.assertEqual([], session.added)

    async def test_no_reset_stage_creates_nothing(self) -> None:
        session = _FakeSession(
            incoming=[_incoming(enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY, source_round=-3)],
            grand_final_type="no_reset",
        )
        gf = _gf(home_team_id=UB_CHAMPION, away_team_id=LB_CHAMPION)

        self.assertEqual((None, []), await advancement._maybe_create_grand_final_reset(session, gf, LB_CHAMPION))
        self.assertEqual([], session.added)


Encounter = importlib.import_module("shared.models.tournament.encounter").Encounter
persist_skeleton = importlib.import_module("shared.services.bracket.persist").persist_skeleton
resolve_seeds = importlib.import_module("src.domain.stage.seeds").resolve_seeds
placeholder_seeds = importlib.import_module("shared.services.bracket.engine").placeholder_seeds
bracket_template = importlib.import_module("shared.services.bracket.template")

from tests.test_bracket_template import _sketch  # noqa: E402


def _where_value(statement, key: str):
    """The value a statement's WHERE clause compares ``key`` to."""
    stack = [statement.whereclause]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        clauses = getattr(node, "clauses", None)
        if clauses is not None:
            stack.extend(clauses)
            continue
        if getattr(getattr(node, "left", None), "key", None) == key:
            return node.right.value
    return None


class _BracketSession:
    """A whole bracket in memory: enough of an ``AsyncSession`` for
    ``persist_skeleton`` to write one and ``advance_winner`` to play it out."""

    def __init__(self, stage: SimpleNamespace, team_ids: range) -> None:
        self.stage = stage
        self.encounters: dict[int, object] = {}
        self.links: list = []
        self.teams = {team_id: f"Team {team_id}" for team_id in team_ids}
        self._pending: list = []
        self._next_id = 1000

    def add(self, obj) -> None:
        self._pending.append(obj)

    def add_all(self, objs) -> None:
        self._pending.extend(objs)

    async def flush(self) -> None:
        while self._pending:
            obj = self._pending.pop(0)
            if getattr(obj, "id", None) is None:
                self._next_id += 1
                obj.id = self._next_id
            if isinstance(obj, Encounter):
                # The column defaults the INSERT would have applied.
                if obj.result_status is None:
                    obj.result_status = enums.EncounterResultStatus.NONE
                self.encounters[obj.id] = obj
            elif isinstance(obj, EncounterLink):
                self.links.append(obj)

    async def get(self, model, primary_key, with_for_update=False):
        if model is Stage:
            return self.stage
        return self.encounters.get(primary_key)

    async def scalar(self, statement):
        # The Grand Final probe: the slot of the WINNER link fed by a negative round.
        target_id = _where_value(statement, "target_encounter_id")
        for link in self.links:
            if (
                link.target_encounter_id == target_id
                and link.role == enums.EncounterLinkRole.WINNER
                and self.encounters[link.source_encounter_id].round < 0
            ):
                return link.target_slot
        return None

    async def execute(self, statement):
        entity = (statement.column_descriptions or [{}])[0].get("entity")
        if entity is EncounterLink:
            source_id = _where_value(statement, "source_encounter_id")
            return _Result([link for link in self.links if link.source_encounter_id == source_id])
        return _Result(list(self.teams.items()))

    async def delete(self, obj) -> None:
        self.encounters.pop(obj.id, None)


class CustomTemplateBracketPlaythroughTests(IsolatedAsyncioTestCase):
    """A hand-drawn template is a real bracket: persisted, its advancement links
    carry every result to the Grand Final, and the Reset still fires off them."""

    async def test_the_sketch_template_plays_through_to_a_grand_final_reset(self) -> None:
        stage = SimpleNamespace(
            id=175,
            tournament_id=72,
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            de_grand_final_type="with_reset",
        )
        session = _BracketSession(stage, range(1, 9))
        template = bracket_template.BracketTemplate.model_validate(_sketch())
        skeleton = resolve_seeds(
            bracket_template.template_to_skeleton(template),
            dict(zip(placeholder_seeds(8), range(1, 9), strict=True)),
        )

        encounters = await persist_skeleton(
            session,
            stage=stage,
            skeleton=skeleton,
            stage_item_id=176,
            team_names_by_id=session.teams,
            best_of_for_round=lambda round_number, *, is_final: 5 if is_final else 3,
            is_elimination=True,
        )

        self.assertEqual(10, len(encounters))
        # Seeds only; every other slot waits on a link.
        self.assertEqual(
            [(1, 4), (2, 3), (None, None), (5, 8), (6, 7)],
            [(e.home_team_id, e.away_team_id) for e in encounters[:5]],
        )

        # The upper seeds win their halves; team 5 runs the whole lower bracket
        # and takes the Grand Final from the LB side.
        for index, winner in ((0, 1), (1, 2), (2, 1), (3, 5), (4, 6), (5, 5), (6, 6), (7, 5), (8, 5)):
            await self._play(session, encounters[index], winner)

        grand_final = encounters[9]
        self.assertEqual((1, 5), (grand_final.home_team_id, grand_final.away_team_id))
        created = await self._play(session, grand_final, 5)

        reset = next(encounter for encounter in created if encounter.round == grand_final.round + 1)
        self.assertEqual((1, 5), (reset.home_team_id, reset.away_team_id))
        self.assertEqual(5, reset.best_of)
        self.assertEqual(
            {
                (enums.EncounterLinkRole.WINNER, enums.EncounterLinkSlot.AWAY),
                (enums.EncounterLinkRole.LOSER, enums.EncounterLinkSlot.HOME),
            },
            {
                (link.role, link.target_slot)
                for link in session.links
                if link.source_encounter_id == grand_final.id and link.target_encounter_id == reset.id
            },
        )

    @staticmethod
    async def _play(session: _BracketSession, encounter, winner_id: int) -> list:
        home_wins = encounter.home_team_id == winner_id
        encounter.home_score, encounter.away_score = (2, 0) if home_wins else (0, 2)
        encounter.status = enums.EncounterStatus.COMPLETED
        return await advancement.advance_winner(session, encounter)
