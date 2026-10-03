"""``rpc.tournament.admin_pick_ban_config_upsert`` — the organizer's config write.

Ported from the legacy ``test_veto_admin_upsert_slots.py`` and then rewritten
onto ruleset v2 (``docs/plans/2026-09-28-pick-ban-constructor.md``): the flat
token ``sequence`` and the ``preset``/``no_repeat_scope``/``allow_protect``/
``unique_attribute_per_side_per_round``/``turn_timer_seconds`` columns are gone,
replaced by one ``ruleset`` document the pure engine validates. What did NOT
change is the POOL: slots, candidates, reserves and the cascade key are still
this endpoint's own business, so their guards are still pinned here.

This endpoint is the only writer of a slot-mode config, so every pool guard the
feature added becomes reachable here for the first time:
``validate_pick_ban_slot_config``'s checks and the two cross-mode clears that
keep a converted config from leaving the other mode's rows behind.

Everything below drives the real subscriber through the real permission path
against a session fake that answers by the entity each query targets, so a
handler that asked for the wrong thing gets an ``AssertionError`` rather than a
conveniently correct answer. The configs are real ORM objects -- transient, so
no database is touched -- because the relationship collections are what the
handler actually assigns to and what ``serialize_pick_ban_config`` reads back.

The fixture's numbers are deliberately all different from one another: three
slots with 4/2/3 candidates, positions 1..3 against indices 0..2, one reserve on
the MIDDLE slot, and candidates listed in an order that is neither ascending nor
descending by id. A handler that confused a position with an index, took the
first or last slot for the reserved one, or re-sorted candidates cannot pass by
coincidence.
"""

from __future__ import annotations

import importlib
import os
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from tests._rpc_fakes import CapturingBroker, make_identity

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from shared.domain import pick_ban_rules as pbr  # noqa: E402
from shared.tests import eager_loading  # noqa: E402

pick_ban_admin = importlib.import_module("src.rpc.pick_ban_admin")
helpers = importlib.import_module("src.rpc._helpers")
models = importlib.import_module("src.models")
enums = importlib.import_module("shared.core.enums")
catalog_models = importlib.import_module("shared.models.catalog")
pick_ban_config = importlib.import_module("src.services.encounter.pick_ban_config")
pick_ban_models = importlib.import_module("shared.models.tournament.pick_ban")

UPSERT = "rpc.tournament.admin_pick_ban_config_upsert"
LIST = "rpc.tournament.admin_pick_ban_config_list"
VALIDATE = "rpc.tournament.admin_pick_ban_rules_validate"
PREVIEW = "rpc.tournament.admin_pick_ban_rules_preview"

TOURNAMENT_ID = 7
#: Unequal to ``TOURNAMENT_ID`` and to ``ROUND``: a handler that mixed any two of
#: the three up would still land on a row if they shared a value.
STAGE_ID = 8
ROUND = 3
CONFIG_ID = 500
WORKSPACE_ID = 1

MAP_KIND = enums.PickBanKind.MAP
SLOTS = enums.MapVetoMode.SLOTS
POOL = enums.MapVetoMode.POOL
FIXED = enums.FirstBanRotation.FIXED
ALTERNATE = enums.FirstBanRotation.ALTERNATE

#: The gamemode slugs the map kind's ``item_group`` vocabulary is read from.
GAMEMODE_SLUGS = ["control", "escort", "flashpoint", "hybrid", "push"]

#: Candidate counts 4/2/3: unequal to each other, to the slot count and to every
#: position, and listed in an id order that is neither ascending nor descending.
CANDIDATES = [[51, 12, 33, 24], [77, 15], [88, 42, 66]]
#: Only the MIDDLE slot carries a reserve, and 99 is not a candidate anywhere, so
#: neither "the first slot's" nor "any slot's" reserve is interchangeable with it.
RESERVES: list[int | None] = [None, 99, None]

#: Six items for a five-step map phase, none of them shared with the slot
#: fixture, so a pool that leaked into slot mode (or the reverse) is visible by
#: value alone.
FLAT_ITEM_IDS = [101, 102, 103, 104, 105, 106]


def _v1(*, mode: str, sequence: list[str], kind: str = "map", timer: int | None = 30) -> dict:
    """A v2 ruleset built from the v1 tokens it converts from.

    Spelling the fixtures as tokens keeps them readable AND pins the migration's
    own converter: every config the 2026-10-03 tournament runs on came through
    exactly this function inside the migration.
    """
    return pbr.ruleset_from_v1(
        kind=kind,
        mode=mode,
        preset="bracket" if mode == "slots" else "custom",
        sequence=sequence,
        no_repeat_scope="none",
        unique_attribute=None,
        turn_timer_seconds=timer,
    ).to_json()


FLAT_TOKENS = ["ban_first", "ban_second", "pick_first", "pick_second", "decider"]
FLAT_RULESET = _v1(mode="pool", sequence=FLAT_TOKENS)
SLOT_RULESET = _v1(mode="slots", sequence=[], timer=45)
HERO_RULESET = _v1(kind="hero", mode="pool", sequence=["ban_first", "ban_second"])
#: Well-formed as a document, but says nothing: the engine's cheapest error.
_EMPTY_RULESET = {"version": 2, "timer_seconds": 90, "on_timeout": "random_fill", "phases": []}

#: Grants exactly the gate this subject checks (``match.update``) and nothing
#: else, and is not a superuser, so the real permission path runs.
IDENTITY = make_identity(
    workspaces=[
        {
            "workspace_id": WORKSPACE_ID,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "match", "action": "update"}],
        }
    ]
)


def slot_payload(
    candidates: list[list[int]] | None = None,
    reserves: list[int | None] | None = None,
) -> list[dict]:
    """The ``slots`` body fragment, defaulting to the module fixture."""
    cands = CANDIDATES if candidates is None else candidates
    res = RESERVES if reserves is None else reserves
    return [{"candidates": list(c), "reserve_item_id": r} for c, r in zip(cands, res, strict=True)]


def slot_body(**overrides) -> dict:
    body = {
        "kind": MAP_KIND.value,
        "mode": SLOTS.value,
        "first_pick_rule": enums.FirstPickRule.HIGHER_SEED.value,
        "first_ban_rotation": ALTERNATE.value,
        "ruleset": deepcopy(SLOT_RULESET),
        "item_ids": [],
        "slots": slot_payload(),
    }
    body.update(overrides)
    return body


def flat_body(**overrides) -> dict:
    body = {
        "kind": MAP_KIND.value,
        "mode": POOL.value,
        "first_pick_rule": enums.FirstPickRule.HIGHER_SEED.value,
        "ruleset": deepcopy(FLAT_RULESET),
        "item_ids": list(FLAT_ITEM_IDS),
    }
    body.update(overrides)
    return body


def _config(mode, *, slots: list[list[int]] | None = None, item_ids: list[int] | None = None):
    """A persisted-looking config. Transient, so its collections need no DB."""
    config = pick_ban_models.PickBanConfig(
        tournament_id=TOURNAMENT_ID,
        kind=MAP_KIND,
        stage_id=None,
        round=None,
        mode=mode,
        first_ban_rotation=FIXED,
        ruleset_json=deepcopy(FLAT_RULESET),
    )
    config.id = CONFIG_ID
    config.items = [
        pick_ban_models.PickBanConfigItem(item_id=item_id, sort_order=index)
        for index, item_id in enumerate(item_ids or [])
    ]
    config.slots = [
        pick_ban_models.PickBanConfigSlot(
            position=index + 1,
            reserve_item_id=None,
            items=[pick_ban_models.PickBanConfigSlotItem(item_id=m, sort_order=i) for i, m in enumerate(candidates)],
        )
        for index, candidates in enumerate(slots or [])
    ]
    return config


def _slot_candidates(slots) -> list[list[int]]:
    """Candidate item ids per slot, in ``position`` order.

    Mirrors what ``ensure_pick_ban_session`` itself reads off ``config.slots``,
    rather than reaching for a legacy helper shaped for ``MapVetoConfigSlot``.
    """
    return [[item.item_id for item in slot.items] for slot in sorted(slots, key=lambda s: s.position)]


def _slot_reserves(slots) -> dict[str, int]:
    """String-keyed reserve snapshot in ``position`` order, mirroring
    ``ensure_pick_ban_session``'s own derivation."""
    return {str(slot.position): slot.reserve_item_id for slot in slots if slot.reserve_item_id is not None}


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def unique(self):
        return self

    def all(self):
        return list(self._rows)

    def __iter__(self):
        # ``session.scalars(...)`` is consumed by iteration (the item-group
        # vocabulary read), not through ``.all()``.
        return iter(self._rows)

    def first(self):
        # ``PickBanConfigRepository.find_for_stage_round`` (the upsert's scope
        # lookup) and ``BaseRepository.get`` (the delete's load) read a single
        # row through ``.unique().scalars().first()``.
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Answers each query by the entity it targets, and records every statement.

    Dispatching on ``column_descriptions`` rather than on call order is what
    makes the fixture unable to flatter a wrong query: asking for anything the
    handler has no business asking for -- a ``PickBanSession``, say -- raises
    instead of returning a row.
    """

    def __init__(
        self,
        *,
        existing=None,
        configs: list | None = None,
        stage_tournament_id=TOURNAMENT_ID,
        roster_slots: dict | None = None,
        hero_types: list[str] | None = None,
    ) -> None:
        self._roster_slots = roster_slots
        self._hero_types = hero_types or []
        self._existing = existing
        # One table described two ways: ``existing`` is the single row already
        # sitting at the scope the upsert targets, ``configs`` the tournament's
        # whole list. Both the scope lookup and the list read go through
        # ``execute`` now, so an ``existing`` row has to be visible there too --
        # otherwise the upsert would find nothing and insert a duplicate.
        self._configs = configs if configs is not None else ([] if existing is None else [existing])
        self._stage_tournament_id = stage_tournament_id
        self.statements: dict[str, list] = {}
        self.added: list = []
        self.commits = 0
        self.refreshes: list[tuple[object, list[str]]] = []
        self.flushes: list[dict[str, list[int]]] = []

    def _record(self, query):
        entity = query.column_descriptions[0]["entity"]
        self.statements.setdefault(entity.__name__, []).append(query)
        return entity

    async def scalar(self, query):
        entity = self._record(query)
        if entity is models.Stage:
            return self._stage_tournament_id
        if entity is models.Tournament:
            return self._roster_slots
        if entity is pick_ban_models.PickBanConfig:
            return self._existing
        raise AssertionError(f"the handler queried an unexpected entity: {entity!r}")

    async def execute(self, query):
        entity = self._record(query)
        if entity is pick_ban_models.PickBanConfig:
            return _Result(self._configs)
        if entity is catalog_models.Gamemode:
            return _Result(list(GAMEMODE_SLUGS))
        if entity is catalog_models.Hero:
            return _Result(list(self._hero_types))
        raise AssertionError(f"the handler queried an unexpected entity: {entity!r}")

    async def scalars(self, query):
        return await self.execute(query)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj, names):
        self.refreshes.append((obj, list(names)))

    async def flush(self):
        # Snapshots the config's two child collections AS THEY STAND, which is
        # the only thing a fake can see about flush ordering: whether the
        # handler emitted the clear on its own or bundled it with the rebuild.
        # A real database distinguishes the two by rejecting the second, since
        # SQLAlchemy sends child INSERTs before child DELETEs.
        config = self._existing
        if config is None:
            configs = [obj for obj in self.added if isinstance(obj, pick_ban_models.PickBanConfig)]
            config = configs[0] if configs else None
        if config is None:
            self.flushes.append({"items": [], "slots": []})
            return
        self.flushes.append(
            {
                "items": [entry.item_id for entry in config.items],
                "slots": [slot.position for slot in config.slots],
            }
        )

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _SubjectCase(IsolatedAsyncioTestCase):
    """Drives one tournament-scoped subject through the real permission path."""

    async def call(self, subject: str, data: dict, *, session: _FakeSession | None = None):
        broker = CapturingBroker()
        pick_ban_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")
        session = session if session is not None else _FakeSession()

        async def _workspace_id(_session, tournament_id):
            self.assertEqual(TOURNAMENT_ID, tournament_id)
            return WORKSPACE_ID

        self.enterContext(patch.object(helpers.db, "async_session_maker", session))
        self.enterContext(patch.object(pick_ban_admin.auth, "get_tournament_workspace_id", _workspace_id))
        return await broker.handlers[subject](data, None), session


class _UpsertCase(_SubjectCase):
    async def invoke(self, body: dict, *, existing=None, stage_tournament_id=TOURNAMENT_ID):
        session = _FakeSession(existing=existing, stage_tournament_id=stage_tournament_id)
        return await self.call(UPSERT, {"identity": IDENTITY, "id": TOURNAMENT_ID, "payload": body}, session=session)

    def assert_unprocessable(self, envelope: dict, *fragments: str) -> str:
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"], envelope)
        message = envelope["error"]["message"]
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    def assert_ruleset_issue(self, envelope: dict, code: str) -> list[dict]:
        """A ruleset rejection, asserted where the constructor reads it.

        ``pick_ban_config.validate_config_payload`` raises 422 with an attribute
        BAG (no ``msg`` key), which is the only ``http_error`` branch that
        carries extra keys through untouched -- so the issue list survives into
        ``details.fields[0].issues`` instead of being flattened away.
        """
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"], envelope)
        entry = envelope["error"]["details"]["fields"][0]
        self.assertEqual(pick_ban_config.RULESET_INVALID, entry["code"], entry)
        issues = entry["issues"]
        self.assertIn(code, [issue["code"] for issue in issues], issues)
        return issues

    def assert_field_error(self, envelope: dict, field: str, code: str) -> None:
        """A pydantic rejection, asserted where the client reads it.

        ``_run`` maps a ``ValidationError`` through
        ``shared.rpc.common.validation_error``: the message is a one-line human
        summary and pydantic's own error type rides ``details["fields"]``. That
        is the only place a machine code survives, so a guard that has to
        distinguish "``mode`` is missing" from a *different* 422 whose prose
        merely contains "mode" pins it here rather than in the message.
        """
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"], envelope)
        entries = envelope["error"]["details"]["fields"]
        self.assertIn({"field": field, "code": code}, [{"field": e["field"], "code": e["code"]} for e in entries])

    def written_config(self, envelope: dict, session: _FakeSession):
        """The config the handler wrote, with the response asserted successful."""
        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(1, session.commits, "the handler did not commit exactly once")
        configs = [obj for obj in session.added if isinstance(obj, pick_ban_models.PickBanConfig)]
        self.assertEqual(1, len(configs), session.added)
        return configs[0]


# ── the body shape itself ────────────────────────────────────────────────────


class ModeIsRequired(_UpsertCase):
    async def test_omitting_mode_is_rejected(self) -> None:
        # Decision 17 (veto_admin): the endpoint replaces the pool wholesale,
        # so a default would let a stale admin tab convert a slot config to
        # flat in silence. Applies identically here.
        #
        # The error CODE rather than a bare "mode" match: a defaulted ``mode``
        # would send this same body down the pool branch, where the message
        # "slots must be empty in pool mode" contains "mode" too and would let
        # the mutant pass. Pydantic's own error type is what separates them.
        body = slot_body()
        del body["mode"]

        envelope, session = await self.invoke(body)

        self.assert_field_error(envelope, "mode", "missing")
        self.assertEqual(0, session.commits)

    async def test_an_unknown_mode_is_rejected_rather_than_read_as_flat(self) -> None:
        # ``mode`` is an enum precisely so a typo cannot fall silently into
        # flat mode. Same substring hazard as above, so this pins the enum
        # code rather than the word.
        envelope, session = await self.invoke(slot_body(mode="slot"))

        self.assert_field_error(envelope, "mode", "enum")
        self.assertEqual(0, session.commits)

    async def test_the_ruleset_is_required(self) -> None:
        # The rules and the pool share one row, and an omitted ruleset would
        # otherwise default to "{}" and silently blank a tournament's rules.
        body = flat_body()
        del body["ruleset"]

        envelope, session = await self.invoke(body)

        self.assert_field_error(envelope, "ruleset", "missing")
        self.assertEqual(0, session.commits)

    async def test_first_ban_rotation_defaults_to_fixed_when_omitted(self) -> None:
        body = slot_body()
        del body["first_ban_rotation"]

        envelope, session = await self.invoke(body)

        config = self.written_config(envelope, session)
        self.assertEqual(FIXED, config.first_ban_rotation)


# ── the cross-field 422s ─────────────────────────────────────────────────────


class ModeContradictions(_UpsertCase):
    async def test_each_contradiction_is_refused(self) -> None:
        # Two payloads that pick one pool shape and then carry the other's
        # data -- same hazard as the legacy suite's ModeContradictions, minus
        # the v1 ``sequence`` field that no longer exists.
        cases = {
            "item_ids": (slot_body(item_ids=[101, 102]), "item_ids must be empty in slots mode"),
            "slots": (flat_body(slots=slot_payload()), "slots must be empty in pool mode"),
        }
        for field, (body, message) in cases.items():
            with self.subTest(field=field):
                envelope, session = await self.invoke(body)
                self.assert_unprocessable(envelope, message)
                self.assertEqual(0, session.commits)

    async def test_a_round_without_a_stage_is_refused(self) -> None:
        envelope, session = await self.invoke(flat_body(round=ROUND))

        self.assert_unprocessable(envelope, "round requires stage_id")
        self.assertEqual(0, session.commits)


# ── the ruleset engine, reached through the endpoint ─────────────────────────


class RulesetValidationBlocksTheWrite(_UpsertCase):
    async def test_a_ruleset_with_no_phases_is_refused_with_its_issues(self) -> None:
        envelope, session = await self.invoke(flat_body(ruleset=_EMPTY_RULESET))

        issues = self.assert_ruleset_issue(envelope, "phases_empty")
        self.assertEqual("phases", issues[0]["path"])
        self.assertEqual(0, session.commits)

    async def test_a_hero_ruleset_may_not_carry_a_decider(self) -> None:
        # A hero phase bans out of a pool that stays playable: there is no
        # survivor for a decider to resolve to.
        ruleset = deepcopy(HERO_RULESET)
        ruleset["phases"][0]["steps"].append(
            {
                "id": "dec",
                "action": "decider",
                "actors": "system",
                "count": 1,
                "min": None,
                "blind": False,
                "target": None,
                "lifetime": None,
                "timer_seconds": None,
                "on_timeout": None,
                "dispute": {"enabled": False, "max": 0},
                "eligible": {},
                "constraints": [],
            }
        )

        envelope, session = await self.invoke(flat_body(kind="hero", ruleset=ruleset))

        self.assert_ruleset_issue(envelope, "decider_map_only")
        self.assertEqual(0, session.commits)

    async def test_a_map_phase_must_settle_a_map(self) -> None:
        envelope, session = await self.invoke(flat_body(ruleset=_v1(mode="pool", sequence=["ban_first", "ban_second"])))

        self.assert_ruleset_issue(envelope, "map_phase_without_pick")
        self.assertEqual(0, session.commits)

    async def test_an_unknown_item_group_is_refused_against_the_catalog_vocabulary(self) -> None:
        # The engine cannot know a map's groups -- they are gamemode slugs an
        # admin edits -- so the handler feeds it the real vocabulary. A leaf
        # naming a gamemode that does not exist would otherwise be saved and
        # then silently match nothing in the room.
        ruleset = deepcopy(FLAT_RULESET)
        ruleset["phases"][0]["pool_filter"] = {"type": "item_group", "params": {"groups": ["bananamode"]}}

        envelope, session = await self.invoke(flat_body(ruleset=ruleset))

        self.assert_ruleset_issue(envelope, "unknown_group")
        self.assertEqual(0, session.commits)

    async def test_a_template_is_still_held_to_the_ruleset(self) -> None:
        # A pool-less row is a rules TEMPLATE, but it is still rules: a broken
        # document saved at a wide scope would break every scope inheriting it.
        envelope, session = await self.invoke(flat_body(item_ids=[], ruleset=_EMPTY_RULESET))

        self.assert_ruleset_issue(envelope, "phases_empty")
        self.assertEqual(0, session.commits)

    async def test_the_stored_ruleset_is_the_engines_normalized_form(self) -> None:
        # Sent without the optional keys the schema defaults; what lands in the
        # column must be the full document, or the stage-merge signature and the
        # session snapshot compare two spellings of the same rules as different.
        terse = {
            "version": 2,
            "phases": [
                {
                    "id": "main",
                    "when": {},
                    "steps": [
                        {"id": "b1", "action": "ban", "actors": "first"},
                        {"id": "p1", "action": "pick", "actors": "first"},
                    ],
                }
            ],
        }

        envelope, session = await self.invoke(flat_body(ruleset=terse))

        config = self.written_config(envelope, session)
        self.assertEqual(pbr.parse_ruleset(terse).to_json(), config.ruleset_json)
        step = config.ruleset_json["phases"][0]["steps"][0]
        self.assertEqual({"enabled": False, "max": 0}, step["dispute"])
        self.assertEqual(1, step["count"])
        self.assertIs(False, step["blind"])
        # The response carries exactly what was stored, not what was sent.
        self.assertEqual(config.ruleset_json, envelope["data"]["ruleset"])


class PoolCapacityGuard(_UpsertCase):
    async def test_a_map_phase_that_outgrows_its_pool_is_refused(self) -> None:
        # Five steps against four maps: the room would run out of candidates
        # mid-series and strand both captains.
        envelope, session = await self.invoke(flat_body(item_ids=[101, 102, 103, 104]))

        self.assert_unprocessable(envelope, "consumes 5 items per map but the pool has only 4")
        self.assertEqual(0, session.commits)

    async def test_a_simultaneous_step_counts_once_per_acting_side(self) -> None:
        # ``actors: both`` spends ``count`` items on EACH side, so a 3+3 ban
        # phase needs six items before the pick that follows it.
        ruleset = deepcopy(FLAT_RULESET)
        ruleset["phases"][0]["steps"] = [
            {
                "id": "b",
                "action": "ban",
                "actors": "both",
                "count": 3,
                "min": None,
                "blind": True,
                "target": None,
                "lifetime": 1,
                "timer_seconds": None,
                "on_timeout": None,
                "dispute": {"enabled": False, "max": 0},
                "eligible": {},
                "constraints": [],
            },
            {
                "id": "p",
                "action": "pick",
                "actors": "first",
                "count": 1,
                "min": None,
                "blind": False,
                "target": None,
                "lifetime": None,
                "timer_seconds": None,
                "on_timeout": None,
                "dispute": {"enabled": False, "max": 0},
                "eligible": {},
                "constraints": [],
            },
        ]

        envelope, session = await self.invoke(flat_body(ruleset=ruleset, item_ids=[1, 2, 3, 4, 5, 6]))
        self.assert_unprocessable(envelope, "consumes 7 items per map but the pool has only 6")
        self.assertEqual(0, session.commits)

        envelope, session = await self.invoke(flat_body(ruleset=ruleset, item_ids=[1, 2, 3, 4, 5, 6, 7]))
        self.assertTrue(envelope["ok"], envelope)

    async def test_a_hero_pool_is_not_spent_by_its_steps(self) -> None:
        # A hero phase replays per map against a pool that stays playable, so
        # "more steps than items" is not a contradiction there.
        envelope, session = await self.invoke(flat_body(kind="hero", ruleset=HERO_RULESET, item_ids=[1]))

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(1, session.commits)

    async def test_a_generator_phase_sizes_itself_to_the_pool(self) -> None:
        # A bracket/slot generator derives its steps FROM the pool, so it can
        # never outgrow it and must not be measured against it.
        bracket = _v1(mode="pool", sequence=[]) | {
            "phases": [{"id": "main", "when": {}, "generator": "bracket", "steps": []}]
        }

        envelope, session = await self.invoke(flat_body(ruleset=bracket, item_ids=[101, 102]))

        self.assertTrue(envelope["ok"], envelope)


# ── the pool guards (unchanged by v2) ────────────────────────────────────────


class SlotValidationGuards(_UpsertCase):
    async def test_an_empty_slot_list_is_kept_as_a_rules_template(self) -> None:
        """No groups is no pool, which is a rules TEMPLATE: rotation, timer and
        the rest, saved at a wide scope for narrower ones to inherit. It opens no
        room (`pick_ban_config.has_pool`), so the group-shaped rules have
        nothing to hold and are not applied."""
        envelope, session = await self.invoke(slot_body(slots=[]))

        config = self.written_config(envelope, session)
        self.assertEqual([], config.slots)

    async def test_an_underfilled_slot_is_named_by_its_one_based_position(self) -> None:
        # The offender is the SECOND slot, so an ordinal taken from a 0-based
        # index would say "slot 1" and an off-by-one would say "slot 3".
        envelope, session = await self.invoke(
            slot_body(slots=slot_payload([[51, 12, 33, 24], [77], [88, 42, 66]], RESERVES))
        )

        self.assert_unprocessable(envelope, "slot 2 must have at least two candidate items")
        self.assertEqual(0, session.commits)

    async def test_a_slot_repeating_a_candidate_is_refused(self) -> None:
        envelope, session = await self.invoke(
            slot_body(slots=slot_payload([[51, 12, 33, 24], [77, 15], [88, 42, 88]], RESERVES))
        )

        self.assert_unprocessable(envelope, "slot 3 must not repeat candidate item(s): 88")
        self.assertEqual(0, session.commits)

    async def test_a_reserve_that_is_its_own_slots_candidate_is_refused(self) -> None:
        envelope, session = await self.invoke(slot_body(slots=slot_payload(CANDIDATES, [None, 15, None])))

        self.assert_unprocessable(envelope, "slot 2 reserve must not be one of its own candidates")
        self.assertEqual(0, session.commits)

    async def test_a_reserve_may_be_another_slots_candidate(self) -> None:
        # Uniqueness is per slot: only within-slot duplication is meaningless.
        envelope, session = await self.invoke(slot_body(slots=slot_payload(CANDIDATES, [None, 88, None])))

        config = self.written_config(envelope, session)
        self.assertEqual([None, 88, None], [slot.reserve_item_id for slot in config.slots])

    async def test_an_item_may_be_a_candidate_in_several_slots(self) -> None:
        shared = [[51, 12, 33, 24], [51, 15], [88, 51, 66]]

        envelope, session = await self.invoke(slot_body(slots=slot_payload(shared, RESERVES)))

        config = self.written_config(envelope, session)
        self.assertEqual(shared, [[entry.item_id for entry in slot.items] for slot in config.slots])

    async def test_the_reserve_list_the_handler_derives_is_parallel_to_the_slots(self) -> None:
        # ``validate_pick_ban_slot_config``'s length-mismatch guard cannot be
        # tripped from here -- both lists are comprehended from the same
        # payload -- so what is worth pinning is that the derivation stays
        # parallel and in payload order, which is what makes every OTHER guard
        # report the right ordinal.
        seen: list[tuple[list[list[int]], list[int | None]]] = []

        def _spy(slots, *, reserves):
            seen.append((slots, list(reserves)))

        self.enterContext(patch.object(pick_ban_config, "validate_pick_ban_slot_config", _spy))
        await self.invoke(slot_body())

        self.assertEqual([(CANDIDATES, RESERVES)], seen)

    async def test_a_flat_pool_may_not_repeat_an_item(self) -> None:
        envelope, session = await self.invoke(flat_body(item_ids=[101, 102, 103, 104, 105, 101]))

        self.assert_unprocessable(envelope, "item_ids must be unique")
        self.assertEqual(0, session.commits)


# ── the round trip ───────────────────────────────────────────────────────────


class SlotRoundTrip(_UpsertCase):
    async def test_a_slot_config_comes_back_exactly_as_it_was_sent(self) -> None:
        envelope, session = await self.invoke(slot_body())

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(
            {
                "mode": SLOTS,
                "first_ban_rotation": ALTERNATE,
                "ruleset": SLOT_RULESET,
                "item_ids": [],
                "slots": [
                    {"position": 1, "candidates": [51, 12, 33, 24], "reserve_item_id": None},
                    {"position": 2, "candidates": [77, 15], "reserve_item_id": 99},
                    {"position": 3, "candidates": [88, 42, 66], "reserve_item_id": None},
                ],
            },
            {key: envelope["data"][key] for key in ("mode", "first_ban_rotation", "ruleset", "item_ids", "slots")},
        )

    async def test_positions_are_one_based_and_follow_payload_order(self) -> None:
        envelope, session = await self.invoke(slot_body())

        config = self.written_config(envelope, session)
        # Positions 1..3 against indices 0..2: an ``enumerate`` left at its
        # default start would violate ``ck_pick_ban_config_slot_position_positive``
        # and shift every ordinal ``validate_pick_ban_slot_config`` reports.
        self.assertEqual([1, 2, 3], [slot.position for slot in config.slots])

    async def test_reordering_the_payload_moves_the_positions_with_it(self) -> None:
        reordered = list(reversed(CANDIDATES))
        reordered_reserves = list(reversed(RESERVES))

        envelope, session = await self.invoke(slot_body(slots=slot_payload(reordered, reordered_reserves)))

        config = self.written_config(envelope, session)
        self.assertEqual(
            [(1, [88, 42, 66]), (2, [77, 15]), (3, [51, 12, 33, 24])],
            [(slot.position, [entry.item_id for entry in slot.items]) for slot in config.slots],
        )

    async def test_candidate_sort_order_is_the_payload_order_not_the_id_order(self) -> None:
        # Asserting the stored ``sort_order`` values, not just the in-memory
        # list: reading ``items`` back through the relationship's
        # ``order_by`` means a handler that wrote every candidate at
        # sort_order 0 would look right here and shuffle after a reload.
        envelope, session = await self.invoke(slot_body())

        config = self.written_config(envelope, session)
        self.assertEqual(
            [[(0, 51), (1, 12), (2, 33), (3, 24)], [(0, 77), (1, 15)], [(0, 88), (1, 42), (2, 66)]],
            [[(entry.sort_order, entry.item_id) for entry in slot.items] for slot in config.slots],
        )

    async def test_the_written_slots_are_what_the_session_builder_would_read(self) -> None:
        envelope, session = await self.invoke(slot_body())

        config = self.written_config(envelope, session)
        self.assertEqual(CANDIDATES, _slot_candidates(config.slots))
        self.assertEqual({"2": 99}, _slot_reserves(config.slots))

    async def test_slot_mode_writes_no_flat_pool_rows(self) -> None:
        # No union mirror: a mirror would turn a dead room into a plausible
        # flat pick-ban over every slot's candidates.
        envelope, session = await self.invoke(slot_body())

        config = self.written_config(envelope, session)
        self.assertEqual([], list(config.items))


class FlatModeIsUnchanged(_UpsertCase):
    async def test_a_payload_that_never_mentions_slots_still_works(self) -> None:
        envelope, session = await self.invoke(flat_body())

        config = self.written_config(envelope, session)
        self.assertEqual(POOL, config.mode)
        self.assertEqual(FLAT_ITEM_IDS, [entry.item_id for entry in config.items])
        self.assertEqual(list(range(len(FLAT_ITEM_IDS))), [entry.sort_order for entry in config.items])
        self.assertEqual(FLAT_RULESET, config.ruleset_json)
        self.assertEqual([], list(config.slots))

    async def test_an_empty_pool_is_kept_as_a_rules_template(self) -> None:
        """The rules and the pool share one row, so "author the rotation and the
        timer once for the whole tournament, pick the maps per stage" needs a
        pool-less row to exist. It plays nothing, so the pool-shaped rules (a
        pool big enough for one map's steps, unique ids) are not applied to it."""
        envelope, session = await self.invoke(flat_body(item_ids=[]))

        config = self.written_config(envelope, session)
        self.assertEqual([], config.items)


# ── converting between the modes ─────────────────────────────────────────────


class CrossModeClearing(_UpsertCase):
    async def test_switching_a_slot_config_to_flat_empties_its_slots(self) -> None:
        existing = _config(SLOTS, slots=CANDIDATES)

        envelope, session = await self.invoke(flat_body(), existing=existing)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(1, session.commits)
        self.assertEqual([], list(existing.slots), "slot rows survived the conversion to flat")
        self.assertEqual(FLAT_ITEM_IDS, [entry.item_id for entry in existing.items])
        self.assertEqual(POOL, existing.mode)
        self.assertEqual([], envelope["data"]["slots"])

    async def test_switching_a_flat_config_to_slots_empties_its_pool(self) -> None:
        existing = _config(POOL, item_ids=FLAT_ITEM_IDS)

        envelope, session = await self.invoke(slot_body(), existing=existing)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(1, session.commits)
        self.assertEqual([], list(existing.items), "pool rows survived the conversion to slots")
        self.assertEqual(CANDIDATES, [[entry.item_id for entry in slot.items] for slot in existing.slots])
        self.assertEqual(SLOTS, existing.mode)
        self.assertEqual([], envelope["data"]["item_ids"])
        self.assertEqual(SLOT_RULESET, existing.ruleset_json)

    async def test_editing_a_slot_config_replaces_its_slots_wholesale(self) -> None:
        existing = _config(SLOTS, slots=[[1, 2], [3, 4], [5, 6], [7, 8]])
        stale = list(existing.slots)

        envelope, session = await self.invoke(slot_body(), existing=existing)

        self.assertTrue(envelope["ok"], envelope)
        # Four slots in, three out: a handler that reconciled by position would
        # leave the fourth behind.
        self.assertEqual(3, len(existing.slots))
        self.assertEqual(CANDIDATES, [[entry.item_id for entry in slot.items] for slot in existing.slots])
        self.assertTrue(all(slot not in existing.slots for slot in stale))

    async def test_an_edit_adds_no_second_config_row(self) -> None:
        existing = _config(POOL, item_ids=FLAT_ITEM_IDS)

        _, session = await self.invoke(slot_body(), existing=existing)

        self.assertEqual([], [obj for obj in session.added if isinstance(obj, pick_ban_models.PickBanConfig)])

    async def test_converting_out_and_back_leaves_neither_shape_behind(self) -> None:
        # Executable documentation, not a gap-closer. No mutant kills this test
        # alone -- every candidate is already caught by one of the two
        # directional tests above or by the wholesale-replace one. It is kept
        # because the compound case is what an organizer actually does, and a
        # reader should not have to assemble it from three others.
        existing = _config(SLOTS, slots=[[1, 2], [3, 4], [5, 6], [7, 8]])

        await self.invoke(flat_body(), existing=existing)
        self.assertEqual(([], FLAT_ITEM_IDS), (list(existing.slots), [e.item_id for e in existing.items]))

        envelope, _ = await self.invoke(slot_body(), existing=existing)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual([], list(existing.items))
        self.assertEqual(SLOTS, existing.mode)
        self.assertEqual(CANDIDATES, _slot_candidates(existing.slots))
        self.assertEqual([1, 2, 3], [slot.position for slot in existing.slots])


# ── the clear must reach the database before the replacements do ─────────────


class ReplacementRowsAreFlushedAfterTheClear(_UpsertCase):
    """The one failure only a real database shows, so it is pinned structurally.

    SQLAlchemy's unit of work emits a mapper's child INSERTs before its child
    DELETEs. Replacing either collection in a single step therefore sends the
    new rows while the old ones are still present, and both child tables carry a
    plain non-deferrable UNIQUE the new rows land on:
    ``uq_pick_ban_config_slot_position`` always, because positions are
    re-derived as 1..N, and ``uq_pick_ban_config_item`` whenever the new item
    set overlaps the old. Postgres rejects the INSERT and the IntegrityError
    reaches ``_run``'s bare ``except Exception`` as an opaque 500.

    A fake session cannot reproduce that -- it has no constraints and no unit of
    work -- so what is pinned instead is the shape that avoids it: the handler
    empties both collections and flushes THAT, before building any replacement.
    """

    async def test_the_clear_is_flushed_before_the_replacements_are_built(self) -> None:
        existing = _config(SLOTS, slots=[[1, 2], [3, 4], [5, 6], [7, 8]])

        envelope, session = await self.invoke(slot_body(), existing=existing)

        self.assertTrue(envelope["ok"], envelope)
        # Exactly one flush, and both collections were empty at that moment.
        self.assertEqual([{"items": [], "slots": []}], session.flushes)

    async def test_a_flat_edit_flushes_its_cleared_pool_too(self) -> None:
        # ``uq_pick_ban_config_item`` is the same hazard on the flat side:
        # FLAT_ITEM_IDS resent over itself is a total overlap.
        existing = _config(POOL, item_ids=FLAT_ITEM_IDS)

        envelope, session = await self.invoke(flat_body(), existing=existing)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual([{"items": [], "slots": []}], session.flushes)

    async def test_the_flush_lands_before_the_commit(self) -> None:
        # A flush emitted after the rebuild would snapshot the new rows, and one
        # emitted after the commit would not help at all.
        existing = _config(SLOTS, slots=CANDIDATES)

        _, session = await self.invoke(slot_body(), existing=existing)

        self.assertEqual(1, len(session.flushes))
        self.assertEqual({"items": [], "slots": []}, session.flushes[0])
        self.assertEqual(1, session.commits)


# ── a running session is nobody's business here ──────────────────────────────


class RunningSessionsAreUntouched(_UpsertCase):
    async def test_the_handler_reads_and_writes_only_config_and_catalog_rows(self) -> None:
        # A session carries its own ruleset snapshot and resolved steps and must
        # not follow a config edit. The fake raises on any other entity, so
        # this pins both halves -- the only reads are the config itself and the
        # gamemode vocabulary the ruleset validator needs, and the only row
        # added besides the config (untouched here, this is an update) is the
        # admin audit entry.
        existing = _config(SLOTS, slots=CANDIDATES)

        envelope, session = await self.invoke(slot_body(), existing=existing)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(["Gamemode", "PickBanConfig"], sorted(session.statements))
        self.assertEqual(["AuditLog"], [type(obj).__name__ for obj in session.added])


# ── the eager loads serialize_pick_ban_config now depends on ────────────────


class SerializeNeedsTheSlotChain(_UpsertCase):
    async def test_the_upsert_lookup_loads_the_slot_chain(self) -> None:
        # Two reasons, either sufficient: assigning over a lazy ``slots``
        # collection loads it to compute the orphans, and
        # ``serialize_pick_ban_config`` reads it back. Both happen outside the
        # async greenlet.
        existing = _config(POOL, item_ids=FLAT_ITEM_IDS)

        _, session = await self.invoke(slot_body(), existing=existing)

        statement = session.statements["PickBanConfig"][0]
        eager_loading.assert_eager_loads(self, statement, "PickBanConfig.slots", "PickBanConfigSlot.items")
        eager_loading.assert_eager_loads(self, statement, "PickBanConfig.items")

    async def test_the_admin_list_loads_the_slot_chain(self) -> None:
        session = _FakeSession(configs=[_config(SLOTS, slots=CANDIDATES)])

        envelope, session = await self.call(LIST, {"identity": IDENTITY, "id": TOURNAMENT_ID}, session=session)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(CANDIDATES, [slot["candidates"] for slot in envelope["data"]["configs"][0]["slots"]])
        eager_loading.assert_eager_loads(
            self, session.statements["PickBanConfig"][0], "PickBanConfig.slots", "PickBanConfigSlot.items"
        )

    # Public list (`rpc.tournament.get_pick_ban_configs`) uses the same
    # `list_configs` + `serialize_pick_ban_config` path as the admin list above.


class SerializedSlotsSurviveTheCommit(_UpsertCase):
    """The upsert serializes BEFORE it commits, and reloads nothing.

    ``config.slots`` and each slot's ``items`` are already loaded here -- they
    were assigned above -- so the response is built from them directly. The
    handler used to ``session.refresh(config, ["items"])`` first; a refresh that
    also named ``slots`` would have expired a correct collection and reloaded it
    with every slot's ``items`` lazy, i.e. the ``MissingGreenlet`` the rest of
    this sweep exists to prevent.
    """

    async def test_the_response_carries_the_slots_across_the_commit(self) -> None:
        envelope, _ = await self.invoke(slot_body(), existing=_config(POOL, item_ids=FLAT_ITEM_IDS))

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(CANDIDATES, [slot["candidates"] for slot in envelope["data"]["slots"]])
        self.assertEqual([], envelope["data"]["item_ids"])


class SerializeOrdersSlotsByPosition(TestCase):
    """``serialize_pick_ban_config`` sorts slots by ``position`` rather than
    trusting row order. Everything this endpoint itself writes is already in
    position order, so the upsert's own round trip cannot pin this -- slot rows
    reach the serializer from elsewhere too (the stage-merge copier and the
    scrim cloner build them directly), and play order is what the room labels
    its slots by.
    """

    def test_row_order_does_not_decide_play_order(self) -> None:
        config = _config(SLOTS)
        # Arrival order reversed against position, and positions deliberately
        # non-contiguous: a deleted middle slot leaves a gap, so a position is
        # not an index into this list.
        config.slots = [
            pick_ban_models.PickBanConfigSlot(
                position=7,
                reserve_item_id=99,
                items=[
                    pick_ban_models.PickBanConfigSlotItem(item_id=m, sort_order=i) for i, m in enumerate([88, 42, 66])
                ],
            ),
            pick_ban_models.PickBanConfigSlot(
                position=2,
                reserve_item_id=None,
                items=[pick_ban_models.PickBanConfigSlotItem(item_id=m, sort_order=i) for i, m in enumerate([77, 15])],
            ),
        ]

        self.assertEqual(
            [
                {"position": 2, "candidates": [77, 15], "reserve_item_id": None},
                {"position": 7, "candidates": [88, 42, 66], "reserve_item_id": 99},
            ],
            pick_ban_admin._serialize_config(config)["slots"],
        )


# ── the constructor's two read-only probes ───────────────────────────────────


class RulesValidateOp(_SubjectCase):
    async def _validate(self, body: dict) -> dict:
        envelope, _ = await self.call(VALIDATE, {"identity": IDENTITY, "id": TOURNAMENT_ID, "payload": body})
        self.assertTrue(envelope["ok"], envelope)
        return envelope["data"]

    async def test_a_valid_ruleset_reports_no_errors(self) -> None:
        data = await self._validate({"kind": "map", "mode": "pool", "ruleset": FLAT_RULESET})

        self.assertTrue(data["valid"])
        self.assertEqual([], [issue for issue in data["issues"] if issue["severity"] == "error"])

    async def test_a_broken_ruleset_is_reported_rather_than_raised(self) -> None:
        # The whole point of this op: the editor gets the issue list while the
        # document is still being typed, instead of a 422 per keystroke.
        data = await self._validate(
            {"kind": "map", "mode": "pool", "ruleset": {"version": 2, "phases": [{"id": "a", "when": {}, "steps": []}]}}
        )

        self.assertFalse(data["valid"])
        self.assertIn("phase_without_steps", [issue["code"] for issue in data["issues"]])
        self.assertEqual(
            ["code", "message", "path", "severity"], sorted(data["issues"][0]), "issue shape changed under the editor"
        )

    async def test_the_map_group_vocabulary_comes_from_the_catalog(self) -> None:
        ruleset = deepcopy(FLAT_RULESET)
        ruleset["phases"][0]["pool_filter"] = {"type": "item_group", "params": {"groups": [GAMEMODE_SLUGS[0]]}}

        self.assertTrue((await self._validate({"kind": "map", "mode": "pool", "ruleset": ruleset}))["valid"])

        ruleset["phases"][0]["pool_filter"]["params"]["groups"] = ["not-a-gamemode"]
        data = await self._validate({"kind": "map", "mode": "pool", "ruleset": ruleset})

        self.assertFalse(data["valid"])
        self.assertIn("unknown_group", [issue["code"] for issue in data["issues"]])


#: A hero pool big enough that every role survives a Bo5 of the anti-one-trick
#: rules, and with three different sizes so a role read off the wrong key shows.
HERO_POOL = {"Tank": 8, "Damage": 14, "Support": 12}
HERO_TYPES = [role for role, count in HERO_POOL.items() for _ in range(count)]
#: The 5v5 shape the 2026-10-03 tournament runs: one tank, two of each other
#: role. All three numbers differ, so a preview that mixed two roles up cannot
#: land on the right answer.
ROSTER_SLOTS = {"tank": 1, "damage": 2, "support": 2, "flex": 0}


class RulesPreviewOp(_SubjectCase):
    async def _preview(self, session: _FakeSession, **payload) -> dict:
        body = {
            "kind": "hero",
            "mode": "pool",
            "ruleset": pbr.PRESETS_BY_ID["hero_anti_one_trick"].ruleset.to_json(),
            "best_of": 5,
            "item_ids": [],
        }
        body.update(payload)
        envelope, _ = await self.call(
            PREVIEW, {"identity": IDENTITY, "id": TOURNAMENT_ID, "payload": body}, session=session
        )
        self.assertTrue(envelope["ok"], envelope)
        return envelope["data"]

    async def test_the_anti_one_trick_preset_reaches_twenty_active_bans(self) -> None:
        # The tournament these rules were written for: 2+2 blind bans on map 1
        # (lifetime 1), then 5+5 per-player bans with lifetime 2 from map 2 on.
        # 4 / 10 / 20 / 20 / 20 is the whole point of the preview — an organizer
        # has to see that a Bo5 takes 20 heroes off the table before they run it.
        maps = (await self._preview(_FakeSession()))["maps"]

        self.assertEqual([1, 2, 3, 4, 5], [m["map_index"] for m in maps])
        self.assertEqual([4, 10, 20, 20, 20], [m["max_active_bans"] for m in maps])
        self.assertEqual(["map1", *["map2plus"] * 4], [m["phase_id"] for m in maps])

    async def test_the_roster_shape_bounds_the_per_player_bans_per_role(self) -> None:
        # A per-player ban names ONE opponent player and must match their role,
        # so a 1/2/2 roster absorbs at most 1/2/2 bans per side per round -- 2/4/4
        # across both sides. With lifetime 2 the map-3 board carries maps 2 and 3,
        # i.e. 4 tank / 8 damage / 8 support bans, NOT the 20-on-one-role worst
        # case the preview has to assume when the roster is unknown.
        data = await self._preview(
            _FakeSession(roster_slots=ROSTER_SLOTS, hero_types=HERO_TYPES),
            item_ids=list(range(1, sum(HERO_POOL.values()) + 1)),
        )

        self.assertEqual(
            {"tank": HERO_POOL["Tank"] - 4, "damage": HERO_POOL["Damage"] - 8, "support": HERO_POOL["Support"] - 8},
            data["maps"][2]["worst_case_remaining"],
        )

    async def test_without_a_roster_shape_the_preview_assumes_the_worst(self) -> None:
        # The refusal to guess: an organizer who never set a roster shape is
        # shown the bleakest board the rules permit, not a flattering one.
        unbounded = await self._preview(
            _FakeSession(hero_types=HERO_TYPES), item_ids=list(range(1, sum(HERO_POOL.values()) + 1))
        )
        bounded = await self._preview(
            _FakeSession(roster_slots=ROSTER_SLOTS, hero_types=HERO_TYPES),
            item_ids=list(range(1, sum(HERO_POOL.values()) + 1)),
        )

        self.assertLess(
            unbounded["maps"][2]["worst_case_remaining"]["support"],
            bounded["maps"][2]["worst_case_remaining"]["support"],
        )

    async def test_a_flex_player_raises_every_roles_ban_ceiling(self) -> None:
        # A role-less player matches EVERY hero under ``target_role_match``, so
        # their per-player bans can land on any role. The roster map is handed to
        # the engine raw for exactly this reason: filtering ``flex`` out here
        # would make the preview optimistic and swallow a real warning.
        ids = list(range(1, sum(HERO_POOL.values()) + 1))
        strict = await self._preview(_FakeSession(roster_slots=ROSTER_SLOTS, hero_types=HERO_TYPES), item_ids=ids)
        flexed = await self._preview(
            _FakeSession(roster_slots={**ROSTER_SLOTS, "flex": 1}, hero_types=HERO_TYPES), item_ids=ids
        )

        self.assertLess(
            flexed["maps"][2]["worst_case_remaining"]["tank"],
            strict["maps"][2]["worst_case_remaining"]["tank"],
        )


# ── the public catalog read ──────────────────────────────────────────────────


class CatalogOp(IsolatedAsyncioTestCase):
    """``rpc.tournament.pick_ban_rules_catalog`` — the constructor's grammar.

    Registered in ``reads.py`` rather than here because it is public: it
    describes the ENGINE, not any tournament, and the editor loads it before a
    config exists to attach it to.
    """

    async def test_the_catalog_carries_the_leaves_constraints_presets_and_both_group_vocabularies(self) -> None:
        reads = importlib.import_module("src.rpc.reads")
        broker = CapturingBroker()
        reads.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        session = _FakeSession()

        with patch.object(helpers.db, "async_session_maker", session):
            envelope = await broker.handlers["rpc.tournament.pick_ban_rules_catalog"]({}, None)

        self.assertTrue(envelope["ok"], envelope)
        data = envelope["data"]
        self.assertEqual(sorted(pbr.LEAVES), sorted(leaf["type"] for leaf in data["leaves"]))
        self.assertEqual(sorted(pbr.CONSTRAINTS), sorted(c["type"] for c in data["constraints"]))
        self.assertEqual([preset.id for preset in pbr.PRESETS], [preset["id"] for preset in data["presets"]])
        self.assertEqual(list(pbr.HERO_GROUPS), data["groups"]["hero"])
        self.assertEqual(GAMEMODE_SLUGS, data["groups"]["map"])
