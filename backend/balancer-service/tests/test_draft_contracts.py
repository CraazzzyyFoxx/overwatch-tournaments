from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.core.enums import (  # noqa: E402
    DraftAutopickStrategy,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftPoolSource,
    DraftStatus,
    HeroClass,
)
from shared.domain.roster_shape import DEFAULT_ROSTER_SHAPE, parse_roster_slots  # noqa: E402
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession  # noqa: E402
from src import (  # noqa: E402
    openapi_docs,
    openapi_schemas,
    schemas,  # noqa: E402
)
from src.domain.draft import rules  # noqa: E402
from src.domain.draft.entities import DraftPickOption  # noqa: E402
from src.rpc import draft as draft_rpc  # noqa: E402
from src.services.draft import board, lifecycle  # noqa: E402
from src.services.draft.feasibility import feasibility_service  # noqa: E402
from tests.factories import roster  # noqa: E402


class _FakeBroker:
    def __init__(self) -> None:
        self.subjects: set[str] = set()

    def subscriber(self, subject: str):
        self.subjects.add(subject)

        def decorator(function):
            return function

        return decorator


class _FakeLogger:
    def warning(self, *args, **kwargs) -> None:
        return None


def test_feasibility_and_pick_options_have_typed_public_contracts() -> None:
    feasibility = schemas.DraftFeasibilityResponse(
        is_feasible=False,
        total_open_slots=2,
        matched_slots=1,
        unmatched_slots=[{"team_id": 10, "slot_code": "support", "ordinal": 0}],
        slot_deficits=[{"slot_code": "support", "unmatched_slots": 1, "eligible_players": 0}],
        blocking_player_ids=[],
        reason_code="role_shortage",
    )
    options = schemas.DraftPickOptionsResponse(
        pick_id=30,
        pick_version=4,
        draft_team_id=10,
        options=[
            {
                "player_id": 20,
                "role": "support",
                "is_safe": False,
                "reason_code": "role_shortage",
                "unmatched_slots": feasibility.unmatched_slots,
                "blocking_player_ids": [],
                "suggestion_score": None,
            }
        ],
    )

    assert feasibility.unmatched_slots[0].slot_code == "support"
    assert options.pick_version == 4
    assert options.options[0].is_safe is False


def test_read_models_and_handlers_cross_the_role_vocabulary_both_ways() -> None:
    # domain -> wire: the option/suggestion/role-edit reads are fed straight
    # from `domain/draft`, which speaks HeroClass. A read model that only took
    # the slot code raised a ValidationError and 500'd the whole response, so
    # the captain's pool showed no safe pick at all.
    option = DraftPickOption(
        player_id=20,
        role=HeroClass.damage,
        is_safe=True,
        reason_code=None,
    )
    assert schemas.DraftPickOptionRead.model_validate(option).role == "damage"
    assert schemas.DraftSuggestion(player_id=20, role=HeroClass.tank, fit_score=1.0).role == "tank"

    # wire -> domain: the reverse crossing, which the pick/override/role-edit
    # handlers own. Passing the raw string down reached `role.slot_code` on a
    # `str`.
    assert draft_rpc._to_role("damage") is HeroClass.damage
    assert draft_rpc._to_role(None) is None
    shape = DEFAULT_ROSTER_SHAPE
    decision = rules.resolve_pick_slot(
        shape,
        dict.fromkeys(shape.slots, 0),
        roster(101, ranks={"damage": 4000}),
        draft_rpc._to_role("damage"),
    )
    assert decision.recorded_role == "damage"


def test_role_edit_contract_requires_a_reason_and_a_positive_rank() -> None:
    # ``rank_absence_confirmed`` is gone with the draft's roles snapshot: a role
    # without a rank is not playable, so "add it and confirm the rank is
    # missing" added a role nobody could ever be drafted on.
    for invalid in (
        {"role": "support", "rank_value": 2500, "reason": "  ", "expected_version": 2},
        {"role": "support", "rank_value": None, "reason": "Missing role", "expected_version": 2},
        {"role": "support", "rank_value": 0, "reason": "Missing role", "expected_version": 2},
        {"role": "support", "reason": "Missing role", "expected_version": 2},
    ):
        with pytest.raises(ValidationError):
            schemas.DraftRoleEditRequest(**invalid)

    request = schemas.DraftRoleEditRequest(
        role="support",
        rank_value=2500,
        reason="Role was missing from registration",
        expected_version=2,
        preview_only=True,
    )
    assert request.role == "support"
    assert request.rank_value == 2500
    assert request.preview_only is True


def test_seed_contract_supports_dry_run_and_optimistic_version() -> None:
    request = schemas.DraftSeedRequest(preview_only=True, expected_version=7)

    assert request.preview_only is True
    assert request.expected_version == 7

    diff = schemas.DraftSeedDiff(
        teams_before=3,
        teams_after=4,
        players_before=15,
        players_after=20,
        picks_before=12,
        picks_after=16,
        session_version_before=7,
        session_version_after=8,
    )
    assert diff.session_version_after == 8


def test_player_read_carries_registration_notes_and_never_the_organizer_ones() -> None:
    # ``board.public_additional_info`` is gone: there is no metadata bag to
    # filter any more. The projection itself is the boundary -- ``notes`` is
    # what captains read in the Player Inspector, ``admin_notes`` has no field
    # on the wire at all, and answers only arrive through the opt-in
    # ``custom_fields`` list.
    read = schemas.DraftPlayerRead.from_seat(
        DraftPlayer(id=20, session_id=1, registration_id=120, status="available", is_captain=False, version=1),
        roster(
            120,
            ranks={"support": 2800},
            public_notes="registration note shown to captains",
            admin_notes="organizer only",
            custom_fields={"phone": "+70000000000"},
        ),
        shape=DEFAULT_ROSTER_SHAPE,
        custom_fields=[],
    )

    assert read.notes == "registration note shown to captains"
    assert "admin_notes" not in schemas.DraftPlayerRead.model_fields
    assert read.custom_fields == []
    assert "organizer only" not in read.model_dump_json()
    assert "+70000000000" not in read.model_dump_json()


def test_player_read_of_a_seat_with_no_roster_states_no_role_instead_of_guessing() -> None:
    # Possible mid-draft when an organizer clears every rank, or when the
    # registration is soft-deleted. The old seeder's answer was to label such a
    # player ``damage`` at rank 0; clients must render "no role" instead, and
    # feasibility reports the shortage.
    read = schemas.DraftPlayerRead.from_seat(
        DraftPlayer(id=20, session_id=1, registration_id=120, status="available", is_captain=False, version=1),
        None,
        shape=DEFAULT_ROSTER_SHAPE,
        custom_fields=[board.VisibleCustomField(key="vk", label="VK profile", type="url")],
    )

    assert read.registration_id == 120
    assert read.primary_role is None
    assert read.sub_role is None
    assert read.battle_tag is None
    assert read.is_flex is False
    assert read.secondary_roles == []
    assert read.role_ranks == {}
    assert read.role_sources == {}
    assert read.role_top_heroes == {}
    assert read.notes is None
    assert read.effective_rank is None
    assert read.custom_fields == []


def test_pick_event_payload_contains_resolved_role_rank_and_version() -> None:
    draft = DraftSession(id=1, tournament_id=2, workspace_id=3, current_pick_id=31)
    pick = DraftPick(
        id=30,
        session_id=1,
        overall_no=5,
        round_no=2,
        pick_in_round=1,
        draft_team_id=10,
        picked_player_id=20,
        target_role=HeroClass.support.slot_code,
        target_rank_value=2875,
        status=DraftPickStatus.COMPLETED.value,
        version=4,
    )

    payload = draft_rpc._pick_event_payload(draft, pick)

    assert payload["target_role"] == "support"
    assert payload["target_rank_value"] == 2875
    assert payload["pick_version"] == 4


def test_role_edit_result_serializes_before_and_after_feasibility() -> None:
    response = schemas.DraftRoleEditResponse(
        player_id=20,
        role="support",
        player_version=3,
        committed=False,
        before={
            "is_feasible": False,
            "total_open_slots": 1,
            "matched_slots": 0,
            "unmatched_slots": [{"team_id": 10, "slot_code": "support", "ordinal": 0}],
            "slot_deficits": [{"slot_code": "support", "unmatched_slots": 1, "eligible_players": 0}],
            "blocking_player_ids": [],
            "reason_code": "role_shortage",
        },
        after={
            "is_feasible": True,
            "total_open_slots": 1,
            "matched_slots": 1,
            "unmatched_slots": [],
            "slot_deficits": [],
            "blocking_player_ids": [],
            "reason_code": None,
        },
    )

    assert response.before.is_feasible is False
    assert response.after.is_feasible is True


def test_rpc_registers_feasibility_options_and_role_edit_subjects() -> None:
    broker = _FakeBroker()

    draft_rpc.register(broker, _FakeLogger())

    assert {
        "rpc.balancer.draft.feasibility",
        "rpc.balancer.draft.pick_options",
        "rpc.balancer.draft.player_role_edit",
        "rpc.balancer.draft.session_list",
        "rpc.balancer.draft.session_delete",
    } <= broker.subjects


def test_player_updated_event_does_not_expose_private_reason() -> None:
    payload = draft_rpc._player_updated_payload(
        session_id=1,
        player_id=20,
        role=HeroClass.support,
        player_version=3,
        is_feasible=True,
    )

    assert payload == {
        "session_id": 1,
        "player_id": 20,
        "role": "support",
        "player_version": 3,
        "is_feasible": True,
    }


def test_admin_override_builds_private_audit_event() -> None:
    event = draft_rpc._override_audit_event(
        session_id=7,
        pick_id=9,
        actor_auth_user_id=11,
        reason=" Captain disconnected ",
        before={"player_id": None, "role": None},
        after={"player_id": 22, "role": "support"},
    )

    assert event.session_id == 7
    assert event.entity_id == 9
    assert event.actor_auth_user_id == 11
    assert event.reason == "Captain disconnected"
    assert event.before_json == {"player_id": None, "role": None}
    assert event.after_json == {"player_id": 22, "role": "support"}


def test_openapi_maps_all_new_draft_contracts() -> None:
    expected = {
        "rpc.balancer.draft.feasibility": (None, schemas.DraftFeasibilityResponse),
        "rpc.balancer.draft.pick_options": (None, schemas.DraftPickOptionsResponse),
        "rpc.balancer.draft.player_role_edit": (schemas.DraftRoleEditRequest, schemas.DraftRoleEditResponse),
    }

    for subject, (request, response) in expected.items():
        operation = openapi_schemas.OPERATIONS[subject]
        assert operation.request is request
        assert operation.response is response
        assert subject in openapi_docs.DOCS

    assert openapi_schemas.OPERATIONS["rpc.balancer.draft.seed"].response is schemas.DraftSeedResponse
    # session_delete answers 204 with no body, so it is documented but carries no
    # response model (see openapi_schemas' module docstring).
    assert "rpc.balancer.draft.session_delete" in openapi_docs.DOCS
    assert "rpc.balancer.draft.session_delete" not in openapi_schemas.OPERATIONS
    session_list = openapi_schemas.OPERATIONS["rpc.balancer.draft.session_list"]
    assert session_list.response is schemas.DraftSessionRead
    assert session_list.response_array is True
    assert "rpc.balancer.draft.session_list" in openapi_docs.DOCS


@pytest.mark.parametrize("status", [DraftStatus.LIVE, DraftStatus.PAUSED])
def test_delete_session_refuses_an_in_flight_draft(status: DraftStatus) -> None:
    # The guard fires before the session is ever touched, so no DB is needed —
    # passing None also proves nothing is written on the rejected path.
    draft = DraftSession(id=1, tournament_id=2, workspace_id=3, status=status.value)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(lifecycle.lifecycle_service.delete_session(None, draft))  # type: ignore[arg-type]

    assert exc_info.value.detail[0]["code"] == "draft_in_flight"


@pytest.mark.parametrize(
    "status",
    [DraftStatus.SETUP, DraftStatus.READY, DraftStatus.COMPLETED, DraftStatus.CANCELLED],
)
def test_delete_session_accepts_every_status_that_is_not_in_flight(status: DraftStatus) -> None:
    assert status.value in rules.DELETABLE_STATUSES


def test_seed_version_guard_rejects_stale_preview_and_bumps_on_materialization() -> None:
    draft = DraftSession(id=1, tournament_id=2, workspace_id=3, version=7)

    rules.validate_seed_version(draft, expected_version=7)
    rules.bump_seed_version(draft)

    assert draft.version == 8
    with pytest.raises(Exception) as exc_info:
        rules.validate_seed_version(draft, expected_version=7)
    assert exc_info.value.detail[0]["code"] == "draft_session_stale"


def test_seed_diff_builder_reports_before_and_after_counts() -> None:
    diff = draft_rpc._seed_diff(
        before=(3, 15, 12),
        after=(4, 20, 16),
        version_before=7,
        version_after=8,
    )

    assert diff == schemas.DraftSeedDiff(
        teams_before=3,
        teams_after=4,
        players_before=15,
        players_after=20,
        picks_before=12,
        picks_after=16,
        session_version_before=7,
        session_version_after=8,
    )


def _schema(*fields: dict) -> dict:
    """A form-version ``schema_json`` holding ``fields`` in one section."""
    return {"schema_version": 1, "sections": [{"key": "extra", "fields": list(fields)}]}


class _FormSession:
    """Answers the single ``schema_json`` scalar read the board makes."""

    def __init__(self, schema_json: dict | None) -> None:
        self._schema_json = schema_json

    async def scalar(self, _statement) -> dict | None:
        return self._schema_json


def test_visible_custom_fields_takes_every_public_custom_definition_in_form_order() -> None:
    session = _FormSession(
        _schema(
            {"key": "vk", "label": "VK profile", "kind": "url", "visibility": "public"},
            # No opt-in flag exists any more: public custom questions all reach the board.
            {"key": "age", "label": "Age", "kind": "number", "visibility": "public"},
            {"key": "rules", "label": "", "kind": "checkbox", "visibility": "public"},
            # A builtin never reaches the custom-answer strip: its answer is not in
            # ``custom_fields_json`` at all.
            {"key": "battle_tag", "kind": "builtin", "visibility": "public"},
            # An organizers-only question must not leak.
            {"key": "phone", "label": "Phone", "kind": "text", "visibility": "organizers"},
            "not a definition",
        )
    )

    fields = asyncio.run(board.board_service.visible_custom_fields(session, 7))  # type: ignore[arg-type]

    assert fields == [
        board.VisibleCustomField(key="vk", label="VK profile", type="url"),
        board.VisibleCustomField(key="age", label="Age", type="number"),
        # A missing label falls back to the key.
        board.VisibleCustomField(key="rules", label="rules", type="checkbox"),
    ]


def test_player_custom_fields_renders_answers_and_drops_the_unanswered() -> None:
    fields = [
        board.VisibleCustomField(key="vk", label="VK profile", type="url"),
        board.VisibleCustomField(key="rules", label="Rules read", type="checkbox"),
        board.VisibleCustomField(key="bio", label="Bio", type="text"),
    ]

    # The answers ARE the registration's ``custom_fields_json``, read live off
    # the roster -- the draft keeps no copy, so which answers a spectator may
    # see is decided by the CURRENT form against the CURRENT answers.
    projected = board.player_custom_fields({"vk": "vk.com/p", "rules": False, "bio": ""}, fields)

    # "rules": False is an ANSWER (a rendered "No"), unlike the blank bio.
    assert [(f.key, f.label, f.type, f.value) for f in projected] == [
        ("vk", "VK profile", "url", "vk.com/p"),
        ("rules", "Rules read", "checkbox", False),
    ]
    # A registration that answered nothing, and a seat with no roster at all.
    assert board.player_custom_fields({"unrelated": "x"}, fields) == []
    assert board.player_custom_fields(None, fields) == []


class _ScalarsResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _ExecuteResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def unique(self) -> _ExecuteResult:
        return self

    def scalars(self) -> _ScalarsResult:
        return _ScalarsResult(self._rows)


class _BoardSession:
    """Answers ``build_board``'s reads in call order, with no DB behind them.

    ``scalar``: max(WorkspaceEvent.id) over the draft AND bracket topics, then
    the form version's ``schema_json`` (read only when some registration
    actually answered one).
    ``execute``: teams, picks, players (repository ``list_by_session`` reads).
    """

    def __init__(self, *, schema_json: dict | None, players: list) -> None:
        self._scalar = [None, schema_json]
        self._results = [[], [], players]

    async def scalar(self, _statement):
        return self._scalar.pop(0)

    async def execute(self, _statement) -> _ExecuteResult:
        return _ExecuteResult(self._results.pop(0))


class _FakeRosters:
    """``DraftRosterService`` stand-in: the engine's answer per seat."""

    def __init__(self, rosters: dict[int, object]) -> None:
        self._rosters = rosters

    async def load(self, _session, _draft_session, players) -> dict:
        return {player.id: self._rosters[player.id] for player in players if player.id in self._rosters}


def _seat(player_id: int) -> DraftPlayer:
    return DraftPlayer(
        id=player_id,
        session_id=1,
        registration_id=100 + player_id,
        status=DraftPlayerStatus.AVAILABLE.value,
        is_captain=False,
        drafted_by_team_id=None,
        version=1,
    )


def _live_draft(session_id: int = 1) -> DraftSession:
    """The one row ``build_board`` reads a session's own fields from.

    ``session_id`` is a parameter because ``build_board`` caches its snapshot per
    session: two tests sharing an id would read each other's board.
    """
    return DraftSession(
        id=session_id,
        tournament_id=2,
        workspace_id=3,
        status=DraftStatus.LIVE.value,
        blocked_reason=None,
        format=DraftFormat.SNAKE.value,
        rounds=4,
        pick_time_seconds=45,
        overtime_seconds=0,
        current_pick_id=None,
        pool_source=DraftPoolSource.MANUAL.value,
        source_balance_id=None,
        autopick_strategy=DraftAutopickStrategy.BEST_FIT.value,
        allow_admin_override=True,
        exported_at=None,
        export_status=None,
        settings_json={},
        version=1,
    )


def test_board_projects_public_answers_and_never_ships_the_rest(monkeypatch) -> None:
    async def _shape(*_args, **_kwargs):
        return DEFAULT_ROSTER_SHAPE

    monkeypatch.setattr(feasibility_service, "resolve_shape", _shape)
    draft = _live_draft()
    player = _seat(20)
    monkeypatch.setattr(
        board.board_service,
        "rosters",
        _FakeRosters(
            {
                20: roster(
                    120,
                    ranks={"support": 3000},
                    battle_tag="Ana#1",
                    public_notes="prefers Ana",
                    custom_fields={"vk": "vk.com/ana", "phone": "+70000000000"},
                )
            }
        ),
    )
    session = _BoardSession(
        schema_json=_schema(
            {"key": "vk", "label": "VK profile", "kind": "url", "visibility": "public"},
            {"key": "phone", "label": "Phone", "kind": "text", "visibility": "organizers"},
        ),
        players=[player],
    )

    snapshot = asyncio.run(board.board_service.build_board(session, draft))  # type: ignore[arg-type]

    read = snapshot.players[0]
    assert [(f.key, f.label, f.type, f.value) for f in read.custom_fields] == [
        ("vk", "VK profile", "url", "vk.com/ana")
    ]
    assert read.battle_tag == "Ana#1"
    assert read.notes == "prefers Ana"
    # The organizers-only answer leaves the service in NO shape — the public
    # board carries every PUBLIC question and nothing else.
    assert "phone" not in snapshot.model_dump_json()


def test_board_ranks_a_player_on_their_own_role_under_role_slots(monkeypatch) -> None:
    # A support main rated 2800 on support and 4000 on damage: the pool card, the
    # inspector header and the shortlist all render `effective_rank`, and they
    # were showing this player as a 4000. Under a shape with role slots the
    # number that represents them is the rank of the role they actually lead
    # with; the maximum belongs to a role-less roster, where nobody is assigned
    # a role at all. Contract: DraftPlayerRead.effective_rank's docstring.
    player = _seat(21)
    resolved = roster(121, ranks={"support": 2800, "damage": 4000}, primary="support", battle_tag="Ana#2")
    monkeypatch.setattr(board.board_service, "rosters", _FakeRosters({21: resolved}))

    async def _role_shape(*_args, **_kwargs):
        return DEFAULT_ROSTER_SHAPE

    monkeypatch.setattr(feasibility_service, "resolve_shape", _role_shape)
    role_slots = asyncio.run(
        board.board_service.build_board(  # type: ignore[arg-type]
            _BoardSession(schema_json=None, players=[player]), _live_draft(session_id=91)
        )
    )
    assert role_slots.players[0].effective_rank == 2800
    # The per-role catalogue keeps every playable number beside it, so the role
    # chooser still shows the 4000 on the DPS row.
    assert role_slots.players[0].role_ranks == {"support": 2800, "damage": 4000}

    async def _flex_shape(*_args, **_kwargs):
        return parse_roster_slots({"flex": 5})

    # A role-less roster assigns nobody a role, so the best playable rank stands
    # in — the existing flex rule, unchanged.
    monkeypatch.setattr(feasibility_service, "resolve_shape", _flex_shape)
    all_flex = asyncio.run(
        board.board_service.build_board(  # type: ignore[arg-type]
            _BoardSession(schema_json=None, players=[player]), _live_draft(session_id=92)
        )
    )
    assert all_flex.players[0].effective_rank == 4000


def test_board_renders_a_seat_whose_registration_resolved_to_nothing(monkeypatch) -> None:
    # A soft-deleted registration mid-draft: the seat must still render (its
    # frozen picks stay readable) with no role and no rank rather than 500 the
    # whole board.
    async def _shape(*_args, **_kwargs):
        return DEFAULT_ROSTER_SHAPE

    monkeypatch.setattr(feasibility_service, "resolve_shape", _shape)
    monkeypatch.setattr(board.board_service, "rosters", _FakeRosters({}))

    snapshot = asyncio.run(
        board.board_service.build_board(  # type: ignore[arg-type]
            _BoardSession(schema_json=None, players=[_seat(22)]), _live_draft(session_id=93)
        )
    )

    read = snapshot.players[0]
    assert read.primary_role is None
    assert read.effective_rank is None
    assert read.role_ranks == {}
