"""``rpc.tournament.admin_pick_ban_config_upsert`` accepts slot-mode configs.

Ported from the legacy ``test_veto_admin_upsert_slots.py`` (deleted alongside
``veto_admin.py``'s config CRUD when it moved to the generic, kind-partitioned
``pick_ban_admin.py``). Same rationale, translated vocabulary: ``MapVetoConfig``
-> ``PickBanConfig`` (+ ``kind``), ``MapVetoConfigMap``/``MapVetoConfigSlotMap``
-> ``PickBanConfigItem``/``PickBanConfigSlotItem`` (``map_id`` -> ``item_id``),
``map_ids`` -> ``item_ids``, ``reserve_map_id`` -> ``reserve_item_id``,
``veto_sequence_json`` -> ``sequence_json``.

This endpoint is the first and only writer of a slot-mode config, so every
guard the rest of the feature added becomes reachable here for the first time:
``validate_pick_ban_slot_config``'s guards, the
``ck_pick_ban_config_slots_not_custom`` CHECK, and the two cross-mode clears
that keep a converted config from leaving the other mode's rows behind.

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

Every body in this file is ``kind: "map"``: it ports the MAP-mode-focused
legacy suite, not the (untested here) hero-kind path.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from tests._rpc_fakes import CapturingBroker, make_identity

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from shared.tests import eager_loading  # noqa: E402

pick_ban_admin = importlib.import_module("src.rpc.pick_ban_admin")
helpers = importlib.import_module("src.rpc._helpers")
models = importlib.import_module("src.models")
enums = importlib.import_module("shared.core.enums")
# Referenced only for CUSTOM_PRESET/BRACKET_PRESET below: pick_ban_session.py
# does not re-export or redefine them (confirmed by reading its imports), and
# pick_ban_admin.py never references them either -- see
# CustomPresetIsUnstorableInSlotMode's docstring for why.
veto_session_service = importlib.import_module("src.services.encounter.veto_session")
pick_ban_models = importlib.import_module("shared.models.tournament.pick_ban")

UPSERT = "rpc.tournament.admin_pick_ban_config_upsert"
LIST = "rpc.tournament.admin_pick_ban_config_list"

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

#: Candidate counts 4/2/3: unequal to each other, to the slot count and to every
#: position, and listed in an id order that is neither ascending nor descending.
CANDIDATES = [[51, 12, 33, 24], [77, 15], [88, 42, 66]]
#: Only the MIDDLE slot carries a reserve, and 99 is not a candidate anywhere, so
#: neither "the first slot's" nor "any slot's" reserve is interchangeable with it.
RESERVES: list[int | None] = [None, 99, None]

FLAT_SEQUENCE = ["ban_first", "ban_second", "pick_first", "pick_second", "decider"]
#: Six items for five steps, none of them shared with the slot fixture, so a pool
#: that leaked into slot mode (or the reverse) is visible by value alone.
FLAT_ITEM_IDS = [101, 102, 103, 104, 105, 106]

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
        "preset": "bracket",
        "turn_timer_seconds": 45,
        "no_repeat_scope": enums.PickBanNoRepeatScope.NONE.value,
        "unique_attribute_per_side_per_round": None,
        "allow_protect": False,
        "sequence": [],
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
        "preset": "bo5",
        "turn_timer_seconds": 30,
        "no_repeat_scope": enums.PickBanNoRepeatScope.NONE.value,
        "unique_attribute_per_side_per_round": None,
        "allow_protect": False,
        "sequence": list(FLAT_SEQUENCE),
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
        preset="bo3",
        turn_timer_seconds=15,
        sequence_json=[],
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

    Mirrors what ``ensure_pick_ban_session`` itself reads off ``config.slots``
    (``pick_ban_session.py``'s ``slots = [[item.item_id for item in
    slot.items] for slot in ordered]``). There is no public accessor for this
    on ``pick_ban_session`` the way legacy ``veto_session.slot_candidates`` is
    one for ``MapVetoConfigSlot`` -- that legacy helper reads ``.maps``/
    ``.map_id`` and so raises ``AttributeError`` against a
    ``PickBanConfigSlot``'s ``.items``/``.item_id`` -- so this reimplements the
    one expression rather than reaching for the wrong-shaped legacy helper.
    """
    return [[item.item_id for item in slot.items] for slot in sorted(slots, key=lambda s: s.position)]


def _slot_reserves(slots) -> dict[str, int]:
    """String-keyed reserve snapshot in ``position`` order, mirroring
    ``ensure_pick_ban_session``'s own derivation (same contract as legacy
    ``veto_session.slot_reserves``, generalized to ``reserve_item_id``)."""
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

    def __init__(self, *, existing=None, configs: list | None = None, stage_tournament_id=TOURNAMENT_ID) -> None:
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
        if entity is pick_ban_models.PickBanConfig:
            return self._existing
        raise AssertionError(f"the handler queried an unexpected entity: {entity!r}")

    async def execute(self, query):
        entity = self._record(query)
        if entity is pick_ban_models.PickBanConfig:
            return _Result(self._configs)
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


class _UpsertCase(IsolatedAsyncioTestCase):
    async def invoke(self, body: dict, *, existing=None, stage_tournament_id=TOURNAMENT_ID):
        broker = CapturingBroker()
        pick_ban_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(UPSERT, broker.handlers, "subject is not registered")

        session = _FakeSession(existing=existing, stage_tournament_id=stage_tournament_id)

        async def _workspace_id(_session, tournament_id):
            self.assertEqual(TOURNAMENT_ID, tournament_id)
            return WORKSPACE_ID

        self.enterContext(patch.object(helpers.db, "async_session_maker", session))
        self.enterContext(patch.object(pick_ban_admin.auth, "get_tournament_workspace_id", _workspace_id))

        envelope = await broker.handlers[UPSERT]({"identity": IDENTITY, "id": TOURNAMENT_ID, "payload": body}, None)
        return envelope, session

    def assert_unprocessable(self, envelope: dict, *fragments: str) -> str:
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("unprocessable", envelope["error"]["code"], envelope)
        message = envelope["error"]["message"]
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

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
        # ``type=missing`` rather than a bare "mode" match: a defaulted ``mode``
        # would send this same body down the pool branch, where the message
        # "sequence must be empty in pool mode" contains "mode" too and would
        # let the mutant pass. Pydantic's own error type is what separates them.
        body = slot_body()
        del body["mode"]

        envelope, session = await self.invoke(body)

        self.assert_unprocessable(envelope, "mode", "type=missing")
        self.assertEqual(0, session.commits)

    async def test_an_unknown_mode_is_rejected_rather_than_read_as_flat(self) -> None:
        # ``mode`` is an enum precisely so a typo cannot fall silently into
        # flat mode. Same substring hazard as above, so this pins the enum
        # error rather than the word.
        envelope, session = await self.invoke(slot_body(mode="slot"))

        self.assert_unprocessable(envelope, "mode", "type=enum")
        self.assertEqual(0, session.commits)

    async def test_first_ban_rotation_defaults_to_fixed_when_omitted(self) -> None:
        body = slot_body()
        del body["first_ban_rotation"]

        envelope, session = await self.invoke(body)

        config = self.written_config(envelope, session)
        self.assertEqual(FIXED, config.first_ban_rotation)


# ── the cross-field 422s ─────────────────────────────────────────────────────


class ModeContradictions(_UpsertCase):
    async def test_each_contradiction_is_refused_and_names_what_it_got_instead(self) -> None:
        # Three payloads that pick one pool shape and then carry the other's
        # data -- same hazard as the legacy suite's ModeContradictions.
        #
        # ``pick_ban_admin._reject_other_modes_field`` phrases its 422
        # differently from ``veto_admin``'s legacy
        # ``f"{name} must be empty in {mode.value} mode; send {name}: []"``:
        # it is ``f"{name} must be empty in {mode.value} mode (got {other}
        # instead)"``, read verbatim from the real source rather than assumed
        # to match the legacy wording.
        cases = {
            "item_ids": (slot_body(item_ids=[101, 102]), "slots", "item_ids/sequence"),
            "sequence": (slot_body(sequence=["ban_first"]), "slots", "item_ids/sequence"),
            "slots": (flat_body(slots=slot_payload()), "pool", "slots"),
        }
        for field, (body, mode_word, other) in cases.items():
            with self.subTest(field=field):
                envelope, session = await self.invoke(body)
                message = self.assert_unprocessable(envelope, field)
                self.assertIn(f"{field} must be empty in {mode_word} mode (got {other} instead)", message)
                self.assertEqual(0, session.commits)


class CustomPresetIsUnstorableInSlotMode(_UpsertCase):
    """``pick_ban_admin._admin_pick_ban_config_upsert`` 422s a custom preset
    in slot mode itself, right before ``validate_pick_ban_slot_config``,
    rather than leaving it to ``ck_pick_ban_config_slots_not_custom``'s
    IntegrityError (which ``_run`` would map to an opaque 500). Ported from
    ``veto_admin``'s legacy guard -- the generic engine's upsert originally
    shipped without this check (a genuine regression found while porting this
    suite), since fixed directly in ``pick_ban_admin.py``.
    """

    async def test_a_custom_preset_is_refused_rather_than_left_to_the_check(self) -> None:
        envelope, session = await self.invoke(slot_body(preset=veto_session_service.CUSTOM_PRESET))

        self.assert_unprocessable(
            envelope,
            "preset",
            "custom",
            f"send preset: '{veto_session_service.BRACKET_PRESET}' or null",
        )
        self.assertEqual(0, session.commits)

    async def test_a_custom_preset_is_still_accepted_in_pool_mode(self) -> None:
        # The (missing or present) slot-mode CHECK is irrelevant here; flat
        # mode's hand-authored order is exactly what ``custom`` is for.
        envelope, session = await self.invoke(flat_body(preset=veto_session_service.CUSTOM_PRESET))

        config = self.written_config(envelope, session)
        self.assertEqual("custom", config.preset)

    async def test_a_non_custom_preset_survives_a_slot_upsert(self) -> None:
        envelope, session = await self.invoke(slot_body(preset="bracket"))

        config = self.written_config(envelope, session)
        self.assertEqual("bracket", config.preset)


# ── validate_pick_ban_slot_config, reached through the endpoint ─────────────


class SlotValidationGuards(_UpsertCase):
    async def test_an_empty_slot_list_is_kept_as_a_rules_template(self) -> None:
        """No groups is no pool, which is a rules TEMPLATE: rotation, timer and
        the rest, saved at a wide scope for narrower ones to inherit. It opens no
        room (`PickBanSessionService.has_pool`), so the group-shaped rules have
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

        # ``validate_pick_ban_slot_config`` stayed a module-level function on
        # ``pick_ban_session`` (it takes already-built lists and no session), and
        # the handler calls it through that module -- not through the singleton.
        self.enterContext(patch.object(pick_ban_admin.pick_ban_session, "validate_pick_ban_slot_config", _spy))
        await self.invoke(slot_body())

        self.assertEqual([(CANDIDATES, RESERVES)], seen)


# ── the round trip ───────────────────────────────────────────────────────────


class SlotRoundTrip(_UpsertCase):
    async def test_a_slot_config_comes_back_exactly_as_it_was_sent(self) -> None:
        envelope, session = await self.invoke(slot_body())

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(
            {
                "mode": SLOTS,
                "first_ban_rotation": ALTERNATE,
                "sequence": [],
                "item_ids": [],
                "slots": [
                    {"position": 1, "candidates": [51, 12, 33, 24], "reserve_item_id": None},
                    {"position": 2, "candidates": [77, 15], "reserve_item_id": 99},
                    {"position": 3, "candidates": [88, 42, 66], "reserve_item_id": None},
                ],
            },
            {key: envelope["data"][key] for key in ("mode", "first_ban_rotation", "sequence", "item_ids", "slots")},
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
        # The consumers' own reading shape (see ``_slot_candidates``/
        # ``_slot_reserves`` above), not a re-implementation of unrelated
        # logic.
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
        self.assertEqual([], list(config.sequence_json))


# ── flat mode is untouched ───────────────────────────────────────────────────


class FlatModeIsUnchanged(_UpsertCase):
    async def test_a_payload_that_never_mentions_slots_still_works(self) -> None:
        envelope, session = await self.invoke(flat_body())

        config = self.written_config(envelope, session)
        self.assertEqual(POOL, config.mode)
        self.assertEqual(FLAT_ITEM_IDS, [entry.item_id for entry in config.items])
        self.assertEqual(list(range(len(FLAT_ITEM_IDS))), [entry.sort_order for entry in config.items])
        self.assertEqual(FLAT_SEQUENCE, config.sequence_json)
        self.assertEqual([], list(config.slots))

    async def test_the_flat_validator_still_runs(self) -> None:
        envelope, session = await self.invoke(flat_body(sequence=["decider", "ban_first"]))

        self.assert_unprocessable(envelope, "decider must be the last step of the sequence")
        self.assertEqual(0, session.commits)

    async def test_an_empty_pool_is_kept_as_a_rules_template(self) -> None:
        """The rules and the pool share one row, so "author the rotation and the
        timer once for the whole tournament, pick the maps per stage" needs a
        pool-less row to exist. It plays nothing, so the pool-shaped rules (a
        sequence that fits inside the pool, a pick or a decider to end on) are
        not applied to it."""
        envelope, session = await self.invoke(flat_body(item_ids=[]))

        config = self.written_config(envelope, session)
        self.assertEqual([], config.items)

    async def test_a_template_is_still_held_to_the_step_vocabulary(self) -> None:
        envelope, session = await self.invoke(
            flat_body(item_ids=[], sequence=["ban_first", "nonsense"], preset="custom")
        )

        self.assert_unprocessable(envelope, "Invalid sequence token(s): nonsense")
        self.assertEqual(0, session.commits)

    async def test_omitting_the_sequence_of_a_config_with_a_pool_is_still_refused(self) -> None:
        # ``sequence`` and ``item_ids`` default to empty so that slot mode has
        # one spelling of "this mode does not use it". A flat config that DOES
        # carry a pool must not become laxer for it: the refusal moves from the
        # schema to ``validate_pick_ban_config``, but it still refuses.
        body = flat_body()
        del body["sequence"]

        envelope, session = await self.invoke(body)

        self.assert_unprocessable(envelope, "sequence must not be empty")
        self.assertEqual(0, session.commits)

    async def test_a_hero_sequence_may_be_bans_only(self) -> None:
        # A hero sequence is ONE round's steps, replayed per map of the series,
        # and it bans out of a pool that stays playable — the map rule "must end
        # in a pick or a decider" would make a hero config unauthorable.
        envelope, session = await self.invoke(
            flat_body(kind="hero", sequence=["ban_first", "ban_second"], preset="custom")
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(1, session.commits)

    async def test_a_hero_sequence_may_not_carry_a_decider(self) -> None:
        envelope, session = await self.invoke(
            flat_body(kind="hero", sequence=["ban_first", "decider"], preset="custom")
        )

        self.assert_unprocessable(envelope, "a hero sequence must not contain a decider step")
        self.assertEqual(0, session.commits)

    async def test_a_map_sequence_still_needs_a_pick_or_a_decider(self) -> None:
        envelope, session = await self.invoke(flat_body(sequence=["ban_first", "ban_second"]))

        self.assert_unprocessable(envelope, "sequence must contain at least one pick or a decider")
        self.assertEqual(0, session.commits)


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
    async def test_the_handler_reads_and_writes_only_config_rows(self) -> None:
        # A session carries its own sequence and reserve snapshots and must
        # not follow a config edit. The fake raises on any other entity, so
        # this pins both halves -- nothing queried, and the only row added
        # besides the config itself (untouched here, this is an update) is the
        # admin audit entry.
        existing = _config(SLOTS, slots=CANDIDATES)

        envelope, session = await self.invoke(slot_body(), existing=existing)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(["PickBanConfig"], sorted(session.statements))
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
        broker = CapturingBroker()
        pick_ban_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        session = _FakeSession(configs=[_config(SLOTS, slots=CANDIDATES)])

        async def _workspace_id(_session, _tournament_id):
            return WORKSPACE_ID

        self.enterContext(patch.object(helpers.db, "async_session_maker", session))
        self.enterContext(patch.object(pick_ban_admin.auth, "get_tournament_workspace_id", _workspace_id))

        envelope = await broker.handlers[LIST]({"identity": IDENTITY, "id": TOURNAMENT_ID}, None)

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
    this sweep exists to prevent. ``Session.refresh`` takes no loader options
    (SQLAlchemy 2.0.45), so it can never express ``slots -> items``: if this
    site ever does need re-reading, it takes a fresh SELECT carrying the
    two-level chain, never a wider refresh.
    """

    async def test_the_response_carries_the_slots_across_the_commit(self) -> None:
        envelope, _ = await self.invoke(slot_body(), existing=_config(POOL, item_ids=FLAT_ITEM_IDS))

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(CANDIDATES, [slot["candidates"] for slot in envelope["data"]["slots"]])
        self.assertEqual([], envelope["data"]["item_ids"])


class SerializeOrdersSlotsByPosition(TestCase):
    """``pick_ban_session.serialize_pick_ban_config`` sorts slots by
    ``position`` rather than trusting row order -- fixed directly (a genuine
    regression found while porting this suite: the generic engine's
    serializer originally iterated ``config.slots`` in whatever order the
    collection held them, unlike ``map_veto.serialize_veto_config``, which
    always ran ``ordered_slots(config.slots)`` first for exactly this reason).
    Everything this endpoint itself writes is already in position order, so
    the upsert's own round trip cannot pin this -- slot rows reach the
    serializer from elsewhere too (the stage-merge copier builds them
    directly), and play order is what the room labels its slots by.
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
