"""Unit tests for scrim-room provisioning (``docs/plans/2026-08-12-scrim-rooms.md``).

Scope is the decidable half of ``services/scrim/service.py`` — the invariants the
module OWNS, because nothing downstream can enforce them: workspace membership,
the per-creator open-room cap, one-captain-per-person, and the fidelity of a
copied pool. Row assembly in ``create_room`` is deliberately not faked; a fake
session deep enough to prove six inserts would mostly be testing itself.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import (  # noqa: E402
    FirstBanRotation,
    FirstPickRule,
    MapVetoMode,
    PickBanKind,
)
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.domain import pick_ban_rules as pbr  # noqa: E402
from src.services.scrim import service as scrim  # noqa: E402

#: Gamemode slugs the map kind's ``item_group`` vocabulary is read from; the
#: custom-pool validator asks the catalog for them before it trusts a ruleset.
GAMEMODE_SLUGS = ["control", "escort", "hybrid", "push"]


def _ruleset(tokens: list[str], *, mode: str = "pool", kind: str = "map") -> dict:
    """A v2 ruleset spelled as the v1 tokens it converts from."""
    return pbr.ruleset_from_v1(
        kind=kind,
        mode=mode,
        preset="bracket" if mode == "slots" else "custom",
        sequence=tokens,
        no_repeat_scope="none",
        unique_attribute=None,
        turn_timer_seconds=45,
    ).to_json()


MAP_RULESET = _ruleset(["ban_first", "ban_second", "decider"])

WORKSPACE_ID = 5


def _user(
    *,
    id: int = 1,
    workspaces: list[int] | None = None,
    superuser: bool = False,
    staff_of: list[int] | None = None,
) -> Any:
    """``staff_of`` names the workspaces where this user holds ``match.result``
    — the grant that makes someone a scrim room's referee."""
    staff = list(staff_of or [])
    return SimpleNamespace(
        id=id,
        username=f"user{id}",
        email=f"user{id}@example.com",
        is_superuser=superuser,
        get_workspace_ids=lambda: list(workspaces if workspaces is not None else [WORKSPACE_ID]),
        # Mirrors the real method, which answers True for a superuser before it
        # looks at any grant.
        has_workspace_permission=lambda workspace_id, resource, action: superuser or workspace_id in staff,
    )


def _team(id: int, *, captain_id: int | None) -> Any:
    return SimpleNamespace(id=id, name=f"team{id}", captain_id=captain_id)


def _room(
    *,
    home_captain: int | None = 100,
    away_captain: int | None = None,
    closed_at: Any = None,
    workspace_id: int = WORKSPACE_ID,
) -> Any:
    encounter = SimpleNamespace(
        id=500,
        best_of=3,
        home_team=_team(700, captain_id=home_captain),
        away_team=_team(701, captain_id=away_captain),
    )
    return SimpleNamespace(
        id=1,
        token="tok",
        label="A vs B",
        workspace_id=workspace_id,
        tournament_id=99,
        stage_id=140,
        encounter_id=500,
        created_by_auth_user_id=1,
        created_at="2026-08-12T00:00:00Z",
        closed_at=closed_at,
        encounter=encounter,
    )


class _ScalarSession:
    """An ``AsyncSession`` stand-in that answers ``scalar`` from a queue.

    Every helper under test issues its scalars in a fixed order, named in each
    test, so a queue is enough — and a reordering of those reads shows up as a
    failure here rather than as a wrong answer in production.
    """

    def __init__(self, *scalars: Any) -> None:
        self._scalars = list(scalars)
        self.added: list[Any] = []
        self.flushes = 0
        self.commits = 0

    async def scalar(self, _statement: Any) -> Any:
        return self._scalars.pop(0) if self._scalars else None

    async def execute(self, _statement: Any) -> Any:
        """Only the advisory lock goes through ``execute``; its result is unread."""
        return None

    async def scalars(self, _statement: Any) -> Any:
        """The item-group vocabulary read (``pick_ban_config.group_vocabulary``),
        which is iterated rather than popped from the scalar queue."""
        return list(GAMEMODE_SLUGS)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    def add(self, obj: Any) -> None:
        self.added.append(obj)


class MembershipIsTheCreateGate(IsolatedAsyncioTestCase):
    """Creating a scrim is a player action, not an organizer one.

    Pinned because the obvious "reuse the admin gate" mistake
    (``match``/``update``) would silently turn scrims into an admin-only
    feature, which is the opposite of the point.
    """

    def test_a_member_passes(self) -> None:
        scrim.require_workspace_member(_user(workspaces=[WORKSPACE_ID]), WORKSPACE_ID)

    def test_a_superuser_passes_without_membership(self) -> None:
        scrim.require_workspace_member(_user(workspaces=[], superuser=True), WORKSPACE_ID)

    def test_a_non_member_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            scrim.require_workspace_member(_user(workspaces=[42]), WORKSPACE_ID)
        self.assertEqual(403, ctx.exception.status_code)


class TheOpenRoomCapIsEnforced(IsolatedAsyncioTestCase):
    """Room creation writes six rows and is reachable by any member."""

    async def test_under_the_cap_is_allowed(self) -> None:
        await scrim.scrim_service._assert_under_cap(_ScalarSession(0), _user(), 1)

    async def test_at_the_cap_is_refused_with_the_cap_named(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await scrim.scrim_service._assert_under_cap(_ScalarSession(1), _user(), 1)
        self.assertEqual(409, ctx.exception.status_code)
        # The message has to say what the limit is: a bare "conflict" leaves the
        # captain with no idea that closing a room is the fix.
        self.assertIn("1", str(ctx.exception.detail))

    async def test_a_raised_cap_admits_more(self) -> None:
        """The cap is a ``Settings`` value precisely so it can be raised."""
        await scrim.scrim_service._assert_under_cap(_ScalarSession(2), _user(), 3)
        with self.assertRaises(HTTPException):
            await scrim.scrim_service._assert_under_cap(_ScalarSession(3), _user(), 3)

    async def test_a_null_count_is_treated_as_zero(self) -> None:
        await scrim.scrim_service._assert_under_cap(_ScalarSession(None), _user(), 1)


def _source_config(*, mode: MapVetoMode = MapVetoMode.POOL) -> Any:
    return SimpleNamespace(
        id=42,
        kind=PickBanKind.MAP,
        stage_id=4,
        round=2,
        mode=mode,
        first_pick_rule=FirstPickRule.HIGHER_SEED,
        first_ban_rotation=FirstBanRotation.FIXED,
        ruleset_json=_ruleset(["ban_first", "ban_second", "decider"]),
        items=[
            SimpleNamespace(item_id=30, sort_order=2),
            SimpleNamespace(item_id=10, sort_order=0),
            SimpleNamespace(item_id=20, sort_order=1),
        ],
        slots=[
            SimpleNamespace(
                position=2,
                reserve_item_id=99,
                items=[SimpleNamespace(item_id=6, sort_order=1), SimpleNamespace(item_id=5, sort_order=0)],
            ),
            SimpleNamespace(position=1, reserve_item_id=None, items=[SimpleNamespace(item_id=1, sort_order=0)]),
        ],
    )


class CopyingARoundReproducesItsPool(IsolatedAsyncioTestCase):
    """A copied pool must play identically to the round it came from.

    Every rule the engine reads off a config is checked field by field: a silent
    omission here (the ruleset, the rotation) produces a room that looks right
    and plays by different rules than the round it advertises.
    """

    def setUp(self) -> None:
        self.source = _source_config()
        self.clone = scrim._clone_config(self.source, tournament_id=99, stage_id=140)

    def test_it_is_retargeted_at_the_room_not_the_source_level(self) -> None:
        self.assertEqual(99, self.clone.tournament_id)
        self.assertEqual(140, self.clone.stage_id)
        # Round-less on purpose: a room has one pool, and a round-scoped clone
        # would resolve at rank 2 only for an encounter whose round matched.
        self.assertIsNone(self.clone.round)

    def test_every_rule_field_is_carried(self) -> None:
        for field in ("kind", "mode", "first_pick_rule", "first_ban_rotation"):
            self.assertEqual(getattr(self.source, field), getattr(self.clone, field), field)
        self.assertEqual(self.source.ruleset_json, self.clone.ruleset_json)

    def test_the_ruleset_is_deep_copied_not_shared(self) -> None:
        """A room editing its own rules must not rewrite the tournament's, and a
        shallow copy would still share every phase and step dict."""
        self.clone.ruleset_json["phases"][0]["steps"].append({"id": "x", "action": "ban", "actors": "first"})
        self.clone.ruleset_json["timer_seconds"] = 5

        self.assertEqual(3, len(self.source.ruleset_json["phases"][0]["steps"]))
        self.assertEqual(45, self.source.ruleset_json["timer_seconds"])

    def test_items_arrive_in_sort_order(self) -> None:
        self.assertEqual([10, 20, 30], [item.item_id for item in self.clone.items])
        self.assertEqual([0, 1, 2], [item.sort_order for item in self.clone.items])

    def test_slots_and_their_candidates_arrive_in_position_order(self) -> None:
        self.assertEqual([1, 2], [slot.position for slot in self.clone.slots])
        self.assertEqual([None, 99], [slot.reserve_item_id for slot in self.clone.slots])
        self.assertEqual([[1], [5, 6]], [[i.item_id for i in slot.items] for slot in self.clone.slots])


class ACustomPoolIsValidatedBeforeItIsProvisioned(IsolatedAsyncioTestCase):
    """A room provisioned into an invalid config would strand its captains.

    The engine refuses to open a session for a bad config, and a scrim has no
    organizer to fix it — so the refusal has to happen at create time, through
    the SAME validator the organizer's config editor runs.
    """

    async def _build(self, payload: dict) -> Any:
        return await scrim._config_from_input(_ScalarSession(), payload, tournament_id=99, stage_id=140)

    async def test_pool_mode_rejects_slots(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._build(
                {"kind": "map", "mode": "pool", "ruleset": MAP_RULESET, "slots": [{"candidates": [1, 2]}]}
            )
        self.assertEqual(422, ctx.exception.status_code)

    async def test_slots_mode_rejects_a_flat_pool(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._build(
                {
                    "kind": "map",
                    "mode": "slots",
                    "ruleset": _ruleset([], mode="slots"),
                    "item_ids": [1, 2],
                    "slots": [{"candidates": [1, 2]}],
                }
            )
        self.assertEqual(422, ctx.exception.status_code)

    async def test_an_unplayable_ruleset_is_refused(self) -> None:
        """Delegated to the engine's own validator, not re-implemented here: a
        map phase that never picks or deciders settles no map."""
        with self.assertRaises(HTTPException) as ctx:
            await self._build(
                {
                    "kind": "map",
                    "mode": "pool",
                    "ruleset": _ruleset(["ban_first", "ban_second"]),
                    "item_ids": [1, 2, 3],
                }
            )
        self.assertEqual(422, ctx.exception.status_code)
        self.assertIn("map_phase_without_pick", [issue["code"] for issue in ctx.exception.detail["issues"]])

    async def test_the_stored_ruleset_is_normalized(self) -> None:
        config = await self._build(
            {
                "kind": "map",
                "mode": "pool",
                "ruleset": {
                    "version": 2,
                    "phases": [{"id": "m", "when": {}, "steps": [{"id": "p", "action": "pick", "actors": "first"}]}],
                },
                "item_ids": [1, 2, 3],
            }
        )
        self.assertEqual("random_fill", config.ruleset_json["on_timeout"])
        self.assertEqual(1, config.ruleset_json["phases"][0]["steps"][0]["count"])

    async def test_absent_fields_leave_server_defaults_alone(self) -> None:
        """Writing ``None`` over ``first_pick_rule``/``first_ban_rotation`` would
        violate their NOT NULL, so a payload that omits them must not touch
        them."""
        config = await self._build({"kind": "map", "mode": "pool", "ruleset": MAP_RULESET, "item_ids": [1, 2, 3]})
        self.assertIsNone(config.first_pick_rule)
        self.assertIsNone(config.first_ban_rotation)

    async def test_a_supplied_rule_is_applied(self) -> None:
        config = await self._build(
            {
                "kind": "map",
                "mode": "pool",
                "ruleset": MAP_RULESET,
                "item_ids": [1, 2, 3],
                "first_ban_rotation": FirstBanRotation.ALTERNATE.value,
            }
        )
        self.assertEqual(FirstBanRotation.ALTERNATE.value, config.first_ban_rotation)

    async def test_items_are_numbered_in_submitted_order(self) -> None:
        config = await self._build({"kind": "map", "mode": "pool", "ruleset": MAP_RULESET, "item_ids": [7, 3, 5]})
        self.assertEqual([(7, 0), (3, 1), (5, 2)], [(i.item_id, i.sort_order) for i in config.items])


class TheCustomPoolEnvelopeIsChecked(IsolatedAsyncioTestCase):
    async def test_an_unknown_source_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await scrim.scrim_service._build_configs(
                _ScalarSession(), _user(), {"source": "whatever"}, tournament_id=99, stage_id=140
            )
        self.assertEqual(422, ctx.exception.status_code)

    async def test_an_empty_custom_pool_is_refused(self) -> None:
        with self.assertRaises(HTTPException):
            await scrim.scrim_service._build_configs(
                _ScalarSession(), _user(), {"source": "custom", "configs": []}, tournament_id=99, stage_id=140
            )

    async def test_two_configs_of_one_kind_are_refused(self) -> None:
        """``uq_pick_ban_config_level`` would reject the second row with an
        IntegrityError, which the RPC envelope maps to an opaque 500."""
        payload = {
            "source": "custom",
            "configs": [
                {"kind": "map", "mode": "pool", "sequence": ["decider"], "item_ids": [1]},
                {"kind": "map", "mode": "pool", "sequence": ["decider"], "item_ids": [2]},
            ],
        }
        with self.assertRaises(HTTPException) as ctx:
            await scrim.scrim_service._build_configs(_ScalarSession(), _user(), payload, tournament_id=99, stage_id=140)
        self.assertEqual(422, ctx.exception.status_code)


class SideClaiming(IsolatedAsyncioTestCase):
    def test_the_free_side_is_the_one_without_a_captain(self) -> None:
        self.assertEqual("away", scrim._free_side(_room().encounter))
        self.assertEqual("home", scrim._free_side(_room(home_captain=None, away_captain=200).encounter))
        self.assertIsNone(scrim._free_side(_room(home_captain=100, away_captain=200).encounter))

    async def test_a_captain_of_one_side_cannot_claim_the_other(self) -> None:
        """The engine reads authority straight off ``Team.captain_id``, so one
        user holding both sides could ban for both halves of their own veto."""
        room = _room(home_captain=100)
        # One scalar: `_viewer_side`'s player-id lookup, answering with the home
        # captain's own player id.
        session = _ScalarSession(100)
        side = await scrim.scrim_service._viewer_side(session, room, _user())
        self.assertEqual("home", side)


class RoomSerialization(IsolatedAsyncioTestCase):
    async def _serialize(self, room: Any, user: Any, player_id: Any) -> dict:
        return await scrim.scrim_service.serialize_room(_ScalarSession(player_id), room, user)

    async def test_a_member_spectator_may_claim_the_free_side(self) -> None:
        payload = await self._serialize(_room(), _user(), 999)
        self.assertIsNone(payload["viewer_side"])
        self.assertTrue(payload["can_claim"])
        self.assertEqual({"id": 701, "name": "team701", "captain_claimed": False}, payload["away_team"])

    async def test_a_captain_may_not_claim(self) -> None:
        payload = await self._serialize(_room(), _user(), 100)
        self.assertEqual("home", payload["viewer_side"])
        self.assertFalse(payload["can_claim"])

    async def test_a_non_member_may_not_claim(self) -> None:
        payload = await self._serialize(_room(), _user(workspaces=[42]), 999)
        self.assertFalse(payload["can_claim"])

    async def test_an_anonymous_viewer_may_not_claim(self) -> None:
        payload = await self._serialize(_room(), None, None)
        self.assertIsNone(payload["viewer_side"])
        self.assertFalse(payload["can_claim"])

    async def test_a_closed_room_may_not_be_claimed(self) -> None:
        payload = await self._serialize(_room(closed_at="2026-08-12T01:00:00Z"), _user(), 999)
        self.assertFalse(payload["can_claim"])

    async def test_a_full_room_may_not_be_claimed(self) -> None:
        payload = await self._serialize(_room(away_captain=200), _user(), 999)
        self.assertFalse(payload["can_claim"])

    async def test_the_creator_may_close_a_room_they_play_no_side_of(self) -> None:
        """The bug ``can_close`` fixes: the page keyed Close off ``viewer_side``,
        so a creator who handed both sides away lost the button the endpoint has
        always honoured."""
        payload = await self._serialize(_room(), _user(), 999)
        self.assertIsNone(payload["viewer_side"])
        self.assertTrue(payload["can_close"])

    async def test_workspace_staff_may_close_a_room_they_are_no_part_of(self) -> None:
        payload = await self._serialize(_room(), _user(id=42, staff_of=[WORKSPACE_ID]), 999)
        self.assertTrue(payload["can_close"])

    async def test_a_plain_member_may_not_close_someone_elses_room(self) -> None:
        payload = await self._serialize(_room(), _user(id=42), 999)
        self.assertFalse(payload["can_close"])

    async def test_staff_of_another_workspace_may_not_close(self) -> None:
        payload = await self._serialize(_room(), _user(id=42, staff_of=[WORKSPACE_ID + 1]), 999)
        self.assertFalse(payload["can_close"])

    async def test_a_closed_room_offers_nobody_a_close(self) -> None:
        payload = await self._serialize(_room(closed_at="2026-08-12T01:00:00Z"), _user(), 100)
        self.assertFalse(payload["can_close"])

    async def test_an_anonymous_viewer_may_not_close(self) -> None:
        payload = await self._serialize(_room(), None, None)
        self.assertFalse(payload["can_close"])


class ClosingARoom(IsolatedAsyncioTestCase):
    """``close_room`` end to end over a fake session.

    The room itself comes back from ``execute`` (the repository's
    ``unique().scalars().first()``), and so does the visibility gate's column row
    (``one_or_none()``); the scalar queue is the rest of the call's read order:
    the caller's player id, then — after the write — what the re-read
    ``get_room_by_token`` needs (the scrim-container probe, the player id again).
    """

    def _session(self, room: Any, *, player_id: int | None) -> Any:
        container = SimpleNamespace(
            id=room.tournament_id,
            workspace_id=room.workspace_id,
            is_hidden=True,
            workspace_is_hidden=False,
        )

        class _RoomSession(_ScalarSession):
            async def execute(self, _statement: Any) -> Any:
                scalars = SimpleNamespace(first=lambda: room)
                return SimpleNamespace(
                    unique=lambda: SimpleNamespace(scalars=lambda: scalars),
                    one_or_none=lambda: container,
                )

        return _RoomSession(player_id, room.id, player_id)

    async def test_staff_close_a_room_they_neither_created_nor_play(self) -> None:
        room = _room(away_captain=200)
        session = self._session(room, player_id=999)
        payload = await scrim.scrim_service.close_room(session, _user(id=42, staff_of=[WORKSPACE_ID]), "tok")
        self.assertIsNotNone(room.closed_at)
        self.assertEqual(1, session.commits)
        self.assertIsNotNone(payload["closed_at"])
        # The room they just retired cannot be retired again.
        self.assertFalse(payload["can_close"])

    async def test_an_uninvolved_member_is_refused(self) -> None:
        room = _room(away_captain=200)
        session = self._session(room, player_id=999)
        with self.assertRaises(HTTPException) as ctx:
            await scrim.scrim_service.close_room(session, _user(id=42), "tok")
        self.assertEqual(403, ctx.exception.status_code)
        self.assertIsNone(room.closed_at)
        self.assertEqual(0, session.commits)

    async def test_a_captain_who_did_not_create_it_may_close(self) -> None:
        room = _room(away_captain=200)
        session = self._session(room, player_id=200)
        await scrim.scrim_service.close_room(session, _user(id=42), "tok")
        self.assertIsNotNone(room.closed_at)


class TheSerializerMatchesTheWireSchema(IsolatedAsyncioTestCase):
    """``rpc/scrim.py`` validates every response through ``ScrimRoomRead``.

    So a field the serializer renames, drops or leaves nullable while the schema
    requires it is a 500 on a route that "works" in every unit test above. This
    is the seam that catches it — a mismatch was introduced and only found by
    hand while wiring the client.
    """

    async def test_a_serialized_room_validates(self) -> None:
        from src import schemas

        payload = await scrim.scrim_service.serialize_room(_ScalarSession(100), _room(), _user())
        room = schemas.ScrimRoomRead.model_validate(payload)
        self.assertEqual("home", room.viewer_side)
        self.assertEqual(500, room.encounter_id)
        self.assertEqual(3, room.best_of)
        self.assertTrue(room.home_team.captain_claimed)
        self.assertFalse(room.away_team.captain_claimed)

    async def test_the_schema_carries_no_field_the_serializer_omits(self) -> None:
        from src import schemas

        payload = await scrim.scrim_service.serialize_room(_ScalarSession(None), _room(), None)
        self.assertEqual(set(schemas.ScrimRoomRead.model_fields), set(payload))


class TheContainerSatisfiesTheTournamentReadContract(IsolatedAsyncioTestCase):
    """The container is a real ``Tournament`` row, so every reader of one must
    survive it — including the admin tournament list, the one list that shows
    hidden rows.

    ``Tournament.start_date``/``end_date`` are nullable and drive nothing, but
    ``TournamentRead`` declares both NOT NULL and ~15 render sites read them
    unguarded. That contract held only because the admin create form requires
    both; the container shipped without them and 500'd the list with
    ``2 validation errors for TournamentRead``. Pinned against the FIELDS the
    schema requires, so a future reader-visible column with the same shape fails
    here rather than in production.
    """

    async def test_a_new_container_fills_every_non_nullable_read_field(self) -> None:
        """Every ``TournamentRead`` field whose type rejects ``None`` and that
        nothing fills for us must be set here.

        The three exemptions are what makes this a contract check rather than a
        snapshot: a primary key arrives on flush, and a column with a Python-side
        or server default fills itself. Everything left is the container's own
        responsibility -- which is exactly the class ``start_date``/``end_date``
        fall into, being nullable columns with no default.
        """
        from src import models, schemas

        session = _ScalarSession(None)  # one scalar: "no container yet"
        container = await scrim.scrim_service._ensure_container(session, WORKSPACE_ID)
        self.assertIs(container, session.added[0])

        columns = models.Tournament.__table__.columns
        gaps: list[str] = []
        for name, field in schemas.TournamentRead.model_fields.items():
            if type(None) in get_args(field.annotation):
                continue
            column = columns.get(name)
            if column is None or column.primary_key:
                continue
            if column.default is not None or column.server_default is not None:
                continue
            if getattr(container, name) is None:
                gaps.append(name)

        self.assertEqual([], sorted(gaps), f"NULL where TournamentRead rejects it: {sorted(gaps)}")

    async def test_both_dates_are_the_creation_instant(self) -> None:
        """Named explicitly, not just covered by the sweep above: these two are
        the fields the shipped version left NULL."""
        container = await scrim.scrim_service._ensure_container(_ScalarSession(None), WORKSPACE_ID)
        self.assertIsNotNone(container.start_date)
        self.assertEqual(container.start_date, container.end_date)

    async def test_the_container_is_hidden_and_never_auto_advanced(self) -> None:
        session = _ScalarSession(None)
        container = await scrim.scrim_service._ensure_container(session, WORKSPACE_ID)
        self.assertTrue(container.is_hidden)
        self.assertFalse(container.auto_transitions_enabled)
        self.assertEqual(scrim.CONTAINER_NAME, container.name)

    async def test_an_existing_container_is_reused_not_duplicated(self) -> None:
        """One per workspace forever: ``Tournament.id`` is an ordinal ML timeline."""
        existing = SimpleNamespace(id=99, name=scrim.CONTAINER_NAME)
        session = _ScalarSession(existing)
        self.assertIs(existing, await scrim.scrim_service._ensure_container(session, WORKSPACE_ID))
        self.assertEqual([], session.added)
