"""The flat-``answers`` pipeline: validate, apply, project.

Two layers, split by what actually needs a database:

* ``validate`` / ``apply`` / ``answers_of`` are pure over a ``FormSchema`` and a
  transient row, so they run against fake sessions and always execute;
* ``submit_public_registration`` is the use-case those three exist for, and it
  only means anything end to end -- the version gate, the row, its identity and
  role children, the read it returns. Those take ``db_session`` and SKIP when
  Postgres is unreachable.

The second layer is not optional coverage. ``submit_public_registration`` shipped
reading ``body.roles``/``body.battle_tag``/``body.discord_nick`` for a whole task
after the body type became ``RegistrationSubmit``, raising ``AttributeError``
behind three production entry points, because nothing in the suite ever called
it with a live body.
"""

from __future__ import annotations

import asyncio
import gc
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from shared import models  # noqa: E402
from shared.core import enums  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection  # noqa: E402
from shared.hero_catalog import HeroCatalogEntry, resolve_hero_catalog  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.social import SocialAccount  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    RegistrationForm,
    RegistrationFormVersion,
)
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament, TournamentPhaseSchedule  # noqa: E402
from shared.services.ontology import project_disciplines  # noqa: E402
from shared.testing.roles import rated_catalog, registration_role  # noqa: E402
from src.schemas import BalancerRegistrationUpdateRequest  # noqa: E402
from src.schemas.registration import RegistrationSubmit  # noqa: E402
from src.services.registration.answers import answer_service  # noqa: E402
from src.services.registration.lifecycle import lifecycle_service  # noqa: E402
from src.services.registration.read_model import _public_rosters, _reg_to_read  # noqa: E402
from src.services.registration.service import registration_service  # noqa: E402


def _schema(**overrides: Any) -> FormSchema:
    """A form that asks a required Battle.net identity, a second identity, roles,
    both notes and two custom questions."""
    fields = [
        FormField(
            key="identity_battlenet", kind="builtin", required=True, params=overrides.get("battlenet_params", {})
        ),
        FormField(key="identity_discord", kind="builtin", params=overrides.get("discord_params", {})),
        FormField(key="roles", kind="builtin"),
        FormField(key="public_notes", kind="builtin"),
        FormField(key="organizer_notes", kind="builtin", visibility="organizers"),
        FormField(key="age", kind="number", label="Age"),
        FormField(key="vk", kind="text", label="VK"),
    ]
    return FormSchema(sections=[FormSection(key="all", fields=fields)])


SCHEMA = _schema()


def test_rank_answers_reject_codes_outside_the_tournament_discipline() -> None:
    schema = FormSchema(
        sections=[FormSection(key="ranks", fields=[FormField(key="peak", kind="role_ranks", label="Peak")])]
    )

    async def validate(roles):
        return await answer_service.validate(
            None,
            schema=schema,
            answers={"peak": roles},
            partial=False,
            enforce_required=False,
            player_id=None,
            workspace_id=1,
            discipline="overwatch",
            hero_catalog=None,
        )

    assert asyncio.run(validate({"tank": "3200"}))["peak"] == {"tank": 3200}
    with pytest.raises(ApiHTTPException) as raised:
        asyncio.run(validate({"healer": "3200"}))
    assert raised.value.status_code == 422
    assert raised.value.detail[0]["field"] == "peak"
    assert raised.value.detail[0]["code"] == "invalid_option"


class _Rows:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str, str]]:
        return self._rows


class _FakeSession:
    """Answers the one projection ``validate`` makes: the registrant's verified
    ``(provider, username_normalized)`` pairs."""

    def __init__(self, rows: list[tuple[str, str]] | None = None) -> None:
        self._rows = rows or []
        self.executed = 0

    async def execute(self, _stmt: object) -> _Rows:
        self.executed += 1
        return _Rows(self._rows)


async def _no_subroles(*_args: Any, **_kwargs: Any) -> dict:
    return {}


def _validate(
    answers: dict[str, Any],
    *,
    schema: FormSchema = SCHEMA,
    session: _FakeSession | None = None,
    partial: bool = False,
    enforce_required: bool = True,
    player_id: int | None = 42,
) -> dict[str, Any]:
    import src.services.registration.answers as answers_module

    original = answers_module.resolve_subrole_catalog
    answers_module.resolve_subrole_catalog = _no_subroles
    try:
        return asyncio.run(
            answer_service.validate(
                session or _FakeSession(),
                schema=schema,
                answers=answers,
                partial=partial,
                enforce_required=enforce_required,
                player_id=player_id,
                workspace_id=1,
                discipline="overwatch",
                hero_catalog=None,
            )
        )
    finally:
        answers_module.resolve_subrole_catalog = original


def _errors(exc: ApiHTTPException) -> list[dict[str, Any]]:
    """``ApiHTTPException`` serializes its ``ApiExc`` list on construction, so the
    wire shape is what a caller actually sees."""
    return list(exc.detail)


def test_a_one_role_sign_up_plays_that_role_without_answering_a_roles_question(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deadlock shows no role step, even where the organizer marked the roles question required."""
    import src.services.registration.answers as answers_module

    monkeypatch.setattr(answers_module, "resolve_subrole_catalog", _no_subroles)
    schema = FormSchema(
        sections=[FormSection(key="all", fields=[FormField(key="roles", kind="builtin", required=True)])]
    )

    async def validate(partial: bool) -> dict[str, Any]:
        return await answer_service.validate(
            _FakeSession(),
            schema=schema,
            answers={},
            partial=partial,
            enforce_required=True,
            player_id=42,
            workspace_id=1,
            discipline="deadlock",
            hero_catalog=None,
        )

    assert asyncio.run(validate(partial=False))["roles"] == [{"role": "agent", "is_primary": True}]
    # A self-edit that does not touch roles leaves them alone.
    assert "roles" not in asyncio.run(validate(partial=True))


# ── validate: one pass, every error ─────────────────────────────────────────


def test_a_submission_is_reduced_to_typed_values() -> None:
    values = _validate(
        {
            "identity_battlenet": [" Player # 1234 "],
            "identity_discord": ["Player"],
            "age": "21",
            "roles": [{"role": "tank", "is_primary": True}],
        }
    )

    # A handle is stored in its DISPLAY form -- a BattleTag loses the spacing a
    # human types around '#', casing is kept -- and normalisation is only ever
    # the matching key.
    assert values["identity_battlenet"] == ["Player#1234"]
    assert values["identity_discord"] == ["Player"]
    assert values["age"] == 21
    assert values["roles"] == [{"role": "tank", "is_primary": True}]


def test_every_stage_reports_before_anything_is_raised() -> None:
    """Normalisation, role rules and the verified gate all contribute to ONE
    422. Raising after stage one would make the registrant resubmit to discover
    the role error waiting behind it."""
    schema = _schema(discord_params={"require_verified": True})

    with pytest.raises(ApiHTTPException) as caught:
        _validate(
            {"age": "not a number", "identity_discord": ["ghost"], "roles": [{"role": "tank", "is_primary": False}]},
            schema=schema,
            session=_FakeSession([]),
        )

    by_field = {error["field"]: error["code"] for error in _errors(caught.value)}
    assert by_field["age"] == "invalid_type"
    assert by_field["identity_battlenet"] == "required"
    assert by_field["roles"] == "roles.primary_required"
    assert by_field["identity_discord"] == "not_verified"


def test_an_unreadable_gated_answer_gets_one_verdict_not_two() -> None:
    """A handle that fails its grammar is absent from ``values`` for a reason
    already reported. The gate must not read that absence as "answered blank"
    and stack ``not_verified`` on top of ``invalid_format`` -- the old validator
    was fail-fast, so collecting every stage is exactly what made this possible."""
    schema = _schema(discord_params={"require_verified": True})

    with pytest.raises(ApiHTTPException) as caught:
        _validate(
            {"identity_battlenet": ["Player#1234"], "identity_discord": ["Bad Name!"]},
            schema=schema,
            session=_FakeSession([("discord", "bad name!")]),
        )

    assert [(e["field"], e["code"]) for e in _errors(caught.value)] == [("identity_discord", "invalid_format")]


def test_a_gated_answer_left_blank_is_still_not_verified() -> None:
    """The other half: ``require_verified`` implies the field is required, so an
    answer that carries no handle at all must keep failing the gate even though
    the field itself is optional and normalisation therefore said nothing about
    it."""
    schema = _schema(discord_params={"require_verified": True})

    with pytest.raises(ApiHTTPException) as caught:
        _validate(
            {"identity_battlenet": ["Player#1234"], "identity_discord": []},
            schema=schema,
            session=_FakeSession([]),
        )

    assert [(e["field"], e["code"]) for e in _errors(caught.value)] == [("identity_discord", "not_verified")]


def test_a_gated_identity_matching_a_verified_account_passes() -> None:
    schema = _schema(discord_params={"require_verified": True})

    values = _validate(
        {"identity_battlenet": ["Player#1234"], "identity_discord": ["Player"]},
        schema=schema,
        session=_FakeSession([("discord", "player")]),
    )

    assert values["identity_discord"] == ["Player"]


def test_a_gated_identity_with_no_linked_player_is_not_verified() -> None:
    """Ownership is provable only through OAuth, so a submission with no player
    behind it cannot satisfy the gate -- and must not reach the database."""
    schema = _schema(discord_params={"require_verified": True})
    session = _FakeSession([("discord", "player")])

    with pytest.raises(ApiHTTPException) as caught:
        _validate(
            {"identity_battlenet": ["Player#1234"], "identity_discord": ["Player"]},
            schema=schema,
            session=session,
            player_id=None,
        )

    assert _errors(caught.value) == [
        {
            "msg": "This must match an OAuth-verified account linked to your profile.",
            "code": "not_verified",
            "field": "identity_discord",
        }
    ]
    # No player, no query worth making.
    assert session.executed == 0


def test_a_gated_battle_net_identity_is_checked_against_the_battlenet_account() -> None:
    schema = _schema(battlenet_params={"require_verified": True})

    with pytest.raises(ApiHTTPException) as caught:
        _validate(
            {"identity_battlenet": ["Other#9999"]},
            schema=schema,
            session=_FakeSession([("battlenet", "player#1234")]),
        )

    assert _errors(caught.value)[0]["field"] == "identity_battlenet"
    # The same tag in another casing/spacing is the same account.
    assert _validate(
        {"identity_battlenet": [" PLAYER # 1234 "]},
        schema=schema,
        session=_FakeSession([("battlenet", "player#1234")]),
    )["identity_battlenet"] == ["PLAYER#1234"]


def test_a_gated_identity_verifies_every_handle_it_carries() -> None:
    """An identity answer is a list, and ownership is claimed for all of it: a
    smurf nobody proved is exactly what the gate exists to keep out, so it must
    not ride in beside a verified main."""
    schema = _schema(battlenet_params={"require_verified": True})

    with pytest.raises(ApiHTTPException) as caught:
        _validate(
            {"identity_battlenet": ["Player#1234", "Alt#9999"]},
            schema=schema,
            session=_FakeSession([("battlenet", "player#1234")]),
        )

    assert [(e["field"], e["code"]) for e in _errors(caught.value)] == [("identity_battlenet", "not_verified")]


def test_an_organizers_draft_neither_requires_nor_verifies() -> None:
    """``enforce_required=False`` is the organizer path: they are entering what
    they know, and nobody's OAuth proves their typing."""
    schema = _schema(discord_params={"require_verified": True})
    session = _FakeSession([])

    values = _validate(
        {"identity_discord": ["ghost"]},
        schema=schema,
        session=session,
        partial=True,
        enforce_required=False,
        player_id=None,
    )

    assert values["identity_discord"] == ["ghost"]
    assert session.executed == 0


def test_a_blank_answer_survives_validation_as_an_explicit_clear() -> None:
    """``normalize_answers`` drops a blank optional answer, which is right for
    "never mentioned" and wrong for "emptied". The writer has to tell them apart
    or a PATCH that clears a question would silently leave it stored."""
    values = _validate({"vk": ""}, partial=True, enforce_required=False)

    assert values == {"vk": None}
    assert _validate({}, partial=True, enforce_required=False) == {}


# ── apply: the one writer ───────────────────────────────────────────────────


def _registration(**kwargs: Any) -> models.Registration:
    return models.Registration(id=1, tournament_id=7, status="pending", **kwargs)


def test_role_update_preserves_rank_value_on_surviving_roles() -> None:
    """Organizer state, not registrant state: ``rank_value``/``is_active`` come
    from rank autofill and the admin editor, and the public form submits
    neither. Rebuilding the rows would blank every rank the moment a player
    reordered their roles."""
    registration = _registration()
    registration.roles = [
        registration_role(role="tank", rank_value=3200, is_active=True, is_primary=True, priority=0),
        registration_role(role="damage", rank_value=2500, is_active=True, is_primary=False, priority=1),
    ]

    answer_service.apply(
        registration,
        {"roles": [{"role": "damage", "is_primary": True}, {"role": "support", "is_primary": False}]},
        catalog_roles=rated_catalog(),
        schema=SCHEMA,
        hero_catalog=None,
    )

    by_role = {row.role: row for row in registration.roles}
    assert set(by_role) == {"damage", "support"}
    # The surviving role keeps the organizer's number and its new priority.
    assert (by_role["damage"].rank_value, by_role["damage"].is_primary, by_role["damage"].priority) == (2500, True, 0)
    # A role the registrant just added has no rank yet -- nothing to preserve.
    assert by_role["support"].rank_value is None


def test_a_role_edit_does_not_leave_a_parentless_role_row_in_the_session() -> None:
    """The surviving row is handed the freshly built hero entries, and those were
    built on a THROWAWAY ``RegistrationRole``. Handing over that row's live
    collection drags the throwaway into the session through the backref: a second
    role row with no ``registration_id``, so the next flush dies on the NOT NULL
    constraint. Every self-edit of a form with the top-heroes ask switched on was
    a 500."""
    schema = FormSchema(
        sections=[
            FormSection(
                key="all",
                fields=[
                    FormField(key="identity_battlenet", kind="builtin", required=True),
                    FormField(key="roles", kind="builtin", params={"top_heroes": {"enabled": True, "max": 3}}),
                ],
            )
        ]
    )
    catalog = {"ana": HeroCatalogEntry(id=11, slug="ana")}
    registration = _registration()
    registration.roles = [registration_role(role="tank", is_primary=True, priority=0)]
    session = sa.orm.Session()
    session.add(registration)

    answer_service.apply(
        registration,
        {"roles": [{"role": "tank", "is_primary": True, "top_heroes": ["ana"]}]},
        catalog_roles=rated_catalog(),
        schema=schema,
        hero_catalog=catalog,
    )

    pending_roles = [row for row in session.new if isinstance(row, models.RegistrationRole)]
    assert [row for row in pending_roles if row not in registration.roles] == []
    assert [entry.entity_id for entry in registration.roles[0].hero_entries] == [11]


def test_a_new_registration_of_a_one_role_game_stores_that_role_without_a_roles_answer() -> None:
    """Organizer rows and sheet rows validate partially, so nothing implied the role before ``apply``."""
    created = models.Registration(tournament_id=7, status="pending", identities=[])
    answer_service.apply(
        created, {}, catalog_roles=rated_catalog(discipline_code="deadlock"), schema=SCHEMA, hero_catalog=None
    )
    assert [(row.role, row.is_primary) for row in created.roles] == [("agent", True)]

    # A stored registration is edited, never re-seeded: its roles are not even read.
    stored = _registration()
    answer_service.apply(
        stored, {}, catalog_roles=rated_catalog(discipline_code="deadlock"), schema=SCHEMA, hero_catalog=None
    )
    assert stored.roles == []


def test_an_identity_answer_rewrites_its_rows_in_place_and_a_blank_one_deletes() -> None:
    registration = _registration()

    answer_service.apply(
        registration,
        {"identity_battlenet": ["Main#1111", "Alt#2222"]},
        catalog_roles=rated_catalog(),
        schema=SCHEMA,
        hero_catalog=None,
    )
    assert [(row.position, row.handle, row.handle_normalized) for row in registration.identities] == [
        (0, "Main#1111", "main#1111"),
        (1, "Alt#2222", "alt#2222"),
    ]

    # Promoting the smurf REWRITES the surviving row instead of re-inserting it
    # (the positional unique is deferred so the swap can happen in place), and
    # the row left over is dropped.
    primary = registration.identities[0]
    answer_service.apply(
        registration,
        {"identity_battlenet": ["Alt#2222"]},
        catalog_roles=rated_catalog(),
        schema=SCHEMA,
        hero_catalog=None,
    )
    assert [(row.position, row.handle) for row in registration.identities] == [(0, "Alt#2222")]
    assert registration.identities[0] is primary

    answer_service.apply(
        registration, {"identity_battlenet": None}, catalog_roles=rated_catalog(), schema=SCHEMA, hero_catalog=None
    )
    assert registration.identities == []


def test_an_identity_the_form_does_not_ask_about_is_not_written() -> None:
    """The schema is the authority on what a registration may carry; a client
    inventing a key must not create a row for it."""
    registration = _registration()

    answer_service.apply(
        registration,
        {"identity_twitch": ["player_tv"]},
        catalog_roles=rated_catalog(),
        schema=SCHEMA,
        hero_catalog=None,
    )

    assert registration.identities == []


def test_answers_of_projects_what_apply_wrote() -> None:
    registration = _registration()
    answer_service.apply(
        registration,
        {
            "identity_battlenet": ["Player#1234", "Alt#1111"],
            "identity_discord": ["player"],
            "stream_pov": True,
            "public_notes": "hi",
            "organizer_notes": "seed me low",
            "vk": "vk.com/player",
        },
        catalog_roles=rated_catalog(),
        schema=SCHEMA,
        hero_catalog=None,
    )

    assert answer_service.answers_of(registration) == {
        "identity_battlenet": ["Player#1234", "Alt#1111"],
        "identity_discord": ["player"],
        "stream_pov": True,
        "public_notes": "hi",
        "organizer_notes": "seed me low",
        "vk": "vk.com/player",
    }


# ── the use-case, against a real database ───────────────────────────────────


async def _seed(session: Any, *, schema: FormSchema) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"answers-{suffix}", name=f"Answers {suffix}")
    session.add(workspace)
    await session.flush()

    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Answers {suffix}",
        slug=f"answers-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    now = datetime.now(UTC)
    session.add(
        TournamentPhaseSchedule(
            tournament_id=tournament.id,
            status=enums.TournamentStatus.REGISTRATION,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1),
        )
    )

    form = RegistrationForm(tournament_id=tournament.id, workspace_id=workspace.id)
    session.add(form)
    await session.flush()
    version = RegistrationFormVersion(form_id=form.id, number=1, schema_json=schema.model_dump(mode="json"))
    form.current_version = version
    await session.flush()

    auth_user = AuthUser(email=f"answers-{suffix}@example.com", username=f"answers_{suffix}", hashed_password="x")
    session.add(auth_user)
    await session.flush()
    await session.commit()
    return {
        "workspace_id": workspace.id,
        "tournament_id": tournament.id,
        "version_id": version.id,
        "auth_user": auth_user,
    }


async def _drop(session: Any, workspace_id: int) -> None:
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_public_submit_validates_against_the_current_version_and_stamps_it(db_session) -> None:
    """The live-body end-to-end: a real ``RegistrationSubmit`` in, a real row out.
    Every column, identity row and role row below was silently unreachable while
    this function still read ``body.battle_tag``."""

    async def _run() -> tuple[Any, Any]:
        seeded = await _seed(db_session, schema=SCHEMA)
        try:
            read = await registration_service.submit_public_registration(
                db_session,
                tournament_id=seeded["tournament_id"],
                auth_user=seeded["auth_user"],
                body=RegistrationSubmit(
                    form_version_id=seeded["version_id"],
                    answers={
                        "identity_battlenet": ["Answerer#1234", "Alt#1111"],
                        "identity_discord": ["Answerer"],
                        "public_notes": "hi organizers",
                        "vk": "vk.com/answerer",
                        "roles": [{"role": "tank", "is_primary": True}],
                    },
                ),
            )
            row = await db_session.scalar(
                sa.select(models.Registration)
                .where(models.Registration.id == read.id)
                .options(
                    sa.orm.selectinload(models.Registration.identities),
                    sa.orm.selectinload(models.Registration.roles),
                )
            )
            return read, _row_image(row, seeded["version_id"])
        finally:
            await _drop(db_session, seeded["workspace_id"])

    read, image = asyncio.run(_run())

    assert image == {
        "display_name": "Answerer#1234",
        "public_notes": "hi organizers",
        "custom_fields_json": {"vk": "vk.com/answerer"},
        "identities": [
            ("battlenet", "Answerer#1234", "answerer#1234", 0),
            ("battlenet", "Alt#1111", "alt#1111", 1),
            ("discord", "Answerer", "answerer", 0),
        ],
        "roles": [("tank", True)],
        "stamped_current_version": True,
    }
    # The read model the caller gets back carries the same answers, flat.
    assert read.primary_handle == "Answerer#1234"
    assert read.answers["identity_discord"] == ["Answerer"]
    assert read.answers["vk"] == "vk.com/answerer"
    assert read.form_version_stale is False


def _row_image(row: Any, version_id: int) -> dict[str, Any]:
    return {
        "display_name": row.display_name,
        "public_notes": row.public_notes,
        "custom_fields_json": row.custom_fields_json,
        "identities": [(i.provider, i.handle, i.handle_normalized, i.position) for i in row.identities],
        "roles": [(r.role, r.is_primary) for r in row.roles],
        "stamped_current_version": row.form_version_id == version_id,
    }


def test_submit_with_stale_version_is_409_form_version_stale(db_session) -> None:
    """The server always validates against the CURRENT version: answers judged by
    rules the registrant never saw are worse than a reload."""

    async def _run() -> ApiHTTPException:
        seeded = await _seed(db_session, schema=SCHEMA)
        try:
            with pytest.raises(ApiHTTPException) as caught:
                await registration_service.submit_public_registration(
                    db_session,
                    tournament_id=seeded["tournament_id"],
                    auth_user=seeded["auth_user"],
                    body=RegistrationSubmit(
                        form_version_id=seeded["version_id"] + 1000,
                        answers={"identity_battlenet": ["Answerer#1234"]},
                    ),
                )
            return caught.value
        finally:
            await db_session.rollback()
            await _drop(db_session, seeded["workspace_id"])

    exc = asyncio.run(_run())

    assert exc.status_code == 409
    assert _errors(exc)[0]["code"] == "form_version_stale"
    assert _errors(exc)[0]["field"] == "form_version_id"


def test_a_self_edit_read_never_lazy_loads_its_tournament(db_session) -> None:
    """P8-D1: the self-edit PATCH labels ``queue_role`` with ``reg.tournament``'s rated dimension. The
    post-commit reload (``populate_existing``) put that relationship back to lazy, so the read found the
    Tournament in the identity map -- until a GC pass collected it first and the lazy load ran SQL outside
    a greenlet: ``MissingGreenlet``, a 500 on an edit that was already written."""
    suffix = uuid.uuid4().hex[:8]

    async def _run() -> Any:
        seeded = await _seed(db_session, schema=SCHEMA)
        try:
            await registration_service.submit_public_registration(
                db_session,
                tournament_id=seeded["tournament_id"],
                auth_user=seeded["auth_user"],
                body=RegistrationSubmit(
                    form_version_id=seeded["version_id"],
                    answers={"identity_battlenet": [f"E{suffix}#1234"]},
                ),
            )
            registration = await registration_service.get_registration(
                db_session, seeded["tournament_id"], seeded["auth_user"].id
            )
            updated = await registration_service.update_registration(
                db_session,
                registration,
                tournament=await registration_service.tournament_repo.get(db_session, seeded["tournament_id"]),
                values={"public_notes": "edited"},
                schema=SCHEMA,
                form_version_id=seeded["version_id"],
            )
            gc.collect()  # the intermittent half: nothing but the read itself may keep the Tournament alive
            return _reg_to_read(
                updated,
                workspace_id=seeded["workspace_id"],
                provider="battlenet",
                queue=await registration_service.queue_position(db_session, updated),
            )
        finally:
            await db_session.rollback()
            await _drop(db_session, seeded["workspace_id"])

    read = asyncio.run(_run())

    assert (read.queue_position, read.queue_total) == (1, 1)
    assert read.queue_role is None  # no role declared; the tournament was still read to label it


def test_a_new_invitee_with_no_form_answers_is_refused(db_session) -> None:
    """``RegistrationTeamAcceptRequest.registration`` is optional because an
    invitee who already registered has nothing to resend. A NEW invitee reaching
    the writer with ``None`` must be refused, not written as a blank row."""

    async def _run() -> ApiHTTPException:
        seeded = await _seed(db_session, schema=SCHEMA)
        try:
            with pytest.raises(ApiHTTPException) as caught:
                await registration_service.submit_public_registration(
                    db_session,
                    tournament_id=seeded["tournament_id"],
                    auth_user=seeded["auth_user"],
                    body=None,
                )
            return caught.value
        finally:
            await db_session.rollback()
            await _drop(db_session, seeded["workspace_id"])

    exc = asyncio.run(_run())

    assert exc.status_code == 422
    assert _errors(exc)[0]["field"] == "answers"


def test_a_gated_identity_is_refused_end_to_end(db_session) -> None:
    """The ``require_verified`` plugin against real ``social_account`` rows, so
    the query the fake session stands in for is the one that actually runs."""

    async def _run() -> tuple[ApiHTTPException, int]:
        schema = _schema(discord_params={"require_verified": True})
        seeded = await _seed(db_session, schema=schema)
        try:
            with pytest.raises(ApiHTTPException) as caught:
                await registration_service.submit_public_registration(
                    db_session,
                    tournament_id=seeded["tournament_id"],
                    auth_user=seeded["auth_user"],
                    body=RegistrationSubmit(
                        form_version_id=seeded["version_id"],
                        answers={
                            "identity_battlenet": ["Answerer#1234"],
                            "identity_discord": ["someone_else"],
                        },
                    ),
                )
            await db_session.rollback()
            written = await db_session.scalar(
                sa.select(sa.func.count())
                .select_from(models.Registration)
                .where(models.Registration.tournament_id == seeded["tournament_id"])
            )
            return caught.value, int(written)
        finally:
            await _drop(db_session, seeded["workspace_id"])

    exc, written = asyncio.run(_run())

    assert [error["code"] for error in _errors(exc)] == ["not_verified"]
    assert _errors(exc)[0]["field"] == "identity_discord"
    # Refused before any row exists.
    assert written == 0


def _heroes_schema() -> FormSchema:
    """A form whose ``roles`` question is open for editing and asks for top heroes."""
    return FormSchema(
        sections=[
            FormSection(
                key="all",
                fields=[
                    FormField(key="identity_battlenet", kind="builtin", required=True),
                    FormField(
                        key="roles",
                        kind="builtin",
                        editable=True,
                        params={"top_heroes": {"enabled": True, "max": 5}},
                    ),
                ],
            )
        ]
    )


def test_the_character_catalog_is_the_owning_disciplines_and_carries_no_role_vocabulary(db_session) -> None:
    """A pick is validated against the OWNING tournament's game only, and a character's class plays no
    part in it: League champions resolve for a League tournament, Overwatch heroes do not."""
    suffix = uuid.uuid4().hex[:8]
    ow_slug, lol_slug = f"hero-{suffix}-ow", f"hero-{suffix}-lol"

    async def _run() -> tuple[set[str], set[str]]:
        db_session.add_all(
            [
                models.CatalogEntity(
                    discipline="overwatch",
                    kind="character",
                    slug=ow_slug,
                    name=ow_slug,
                    image_path="x",
                    attrs={"class": "tank"},
                ),
                models.CatalogEntity(
                    discipline="lol",
                    kind="character",
                    slug=lol_slug,
                    name=lol_slug,
                    image_path="x",
                    attrs={"class": "mage"},
                ),
            ]
        )
        await db_session.commit()
        try:
            ow = await resolve_hero_catalog(db_session, discipline="overwatch")
            lol = await resolve_hero_catalog(db_session, discipline="lol")
            return {slug for slug in ow if slug in (ow_slug, lol_slug)}, {
                slug for slug in lol if slug in (ow_slug, lol_slug)
            }
        finally:
            await db_session.execute(
                sa.delete(models.CatalogEntity).where(models.CatalogEntity.slug.in_([ow_slug, lol_slug]))
            )
            await db_session.commit()

    ow, lol = asyncio.run(_run())

    assert ow == {ow_slug}
    assert lol == {lol_slug}


def test_a_role_top_hero_list_survives_being_replaced_in_place(db_session) -> None:
    """A self-edit replaces the role's whole pick list, so a registrant resaving
    picks they never touched asks the database to hold a row and its replacement
    at once. The unit of work leaves the INSERTs and the DELETEs of one table
    unordered, so both uniques on ``registration_role_entity`` have to hold at
    COMMIT rather than per statement -- and did not, which is a 500 on the edit.

    The raw insert/delete pair at the end is that same sequence in the form the
    ORM's arbitrary sort will not reliably produce."""
    suffix = uuid.uuid4().hex[:8]
    slugs = [f"hero-{suffix}-{index}" for index in range(2)]

    async def _run() -> list[tuple[str, int]]:
        schema = _heroes_schema()
        seeded = await _seed(db_session, schema=schema)
        db_session.add_all(
            models.CatalogEntity(
                discipline="overwatch", kind="character", slug=slug, name=slug, image_path="x", attrs={"class": "tank"}
            )
            for slug in slugs
        )
        await db_session.commit()
        catalog = {
            row.slug: HeroCatalogEntry(id=row.id, slug=row.slug)
            for row in (
                await db_session.scalars(sa.select(models.CatalogEntity).where(models.CatalogEntity.slug.in_(slugs)))
            ).all()
        }
        picks: list[dict[str, Any]] = [{"role": "tank", "is_primary": True, "top_heroes": slugs}]
        try:
            await registration_service.submit_public_registration(
                db_session,
                tournament_id=seeded["tournament_id"],
                auth_user=seeded["auth_user"],
                body=RegistrationSubmit(
                    form_version_id=seeded["version_id"],
                    # Run-unique: the BattleTag is the GLOBAL player anchor, so a
                    # fixed one would re-resolve the player a previous run left
                    # behind and this registration would belong to that account.
                    answers={"identity_battlenet": [f"H{suffix}#1234"], "roles": picks},
                ),
            )
            registration = await registration_service.get_registration(
                db_session, seeded["tournament_id"], seeded["auth_user"].id
            )
            updated = await registration_service.update_registration(
                db_session,
                registration,
                tournament=await registration_service.tournament_repo.get(db_session, seeded["tournament_id"]),
                values={"roles": picks},
                schema=schema,
                hero_catalog=catalog,
                form_version_id=seeded["version_id"],
            )
            # The read the RPC builds from the row it just wrote. The roster
            # engine walks roles -> hero_entries, so a row handed back with that
            # chain unloaded raises MissingGreenlet instead of serving the edit.
            assert await _public_rosters(db_session, [updated])
            rows = (
                await db_session.execute(
                    sa.select(
                        models.RegistrationRoleEntity.id,
                        models.RegistrationRoleEntity.role_id,
                        models.RegistrationRoleEntity.entity_id,
                        models.RegistrationRoleEntity.priority,
                    )
                    .join(
                        models.RegistrationRole,
                        models.RegistrationRole.id == models.RegistrationRoleEntity.role_id,
                    )
                    .where(models.RegistrationRole.registration_id == registration.id)
                    .order_by(models.RegistrationRoleEntity.priority)
                )
            ).all()
            replaced = rows[0]
            await db_session.execute(
                sa.insert(models.RegistrationRoleEntity).values(
                    role_id=replaced.role_id, entity_id=replaced.entity_id, priority=replaced.priority
                )
            )
            await db_session.execute(
                sa.delete(models.RegistrationRoleEntity).where(models.RegistrationRoleEntity.id == replaced.id)
            )
            await db_session.commit()
            return [
                (slug, priority)
                for slug, priority in (
                    await db_session.execute(
                        sa.select(models.CatalogEntity.slug, models.RegistrationRoleEntity.priority)
                        .join(
                            models.RegistrationRoleEntity,
                            models.RegistrationRoleEntity.entity_id == models.CatalogEntity.id,
                        )
                        .join(
                            models.RegistrationRole,
                            models.RegistrationRole.id == models.RegistrationRoleEntity.role_id,
                        )
                        .where(models.RegistrationRole.registration_id == registration.id)
                        .order_by(models.RegistrationRoleEntity.priority)
                    )
                ).all()
            ]
        finally:
            await db_session.rollback()
            await _drop(db_session, seeded["workspace_id"])
            await db_session.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.slug.in_(slugs)))
            await db_session.commit()

    assert asyncio.run(_run()) == [(slugs[0], 1), (slugs[1], 2)]


def test_the_player_sheet_patch_round_trips_a_roles_character_picks(db_session) -> None:
    """The balancer player sheet re-sends each role's saved picks as ``top_characters`` (the native spelling it
    read them under). The organizer receiver rebuilds the pick list from that key after clearing it, so a patch
    spelled ``top_heroes`` -- the persisted form-answer spelling -- would silently delete every saved pick."""
    suffix = uuid.uuid4().hex[:8]
    slugs = [f"hero-{suffix}-{index}" for index in range(2)]

    async def _picks(registration_id: int) -> list[str]:
        return list(
            (
                await db_session.scalars(
                    sa.select(models.CatalogEntity.slug)
                    .join(
                        models.RegistrationRoleEntity,
                        models.RegistrationRoleEntity.entity_id == models.CatalogEntity.id,
                    )
                    .join(
                        models.RegistrationRole,
                        models.RegistrationRole.id == models.RegistrationRoleEntity.role_id,
                    )
                    .where(models.RegistrationRole.registration_id == registration_id)
                    .order_by(models.RegistrationRoleEntity.priority)
                )
            ).all()
        )

    def _patch(spelling: str) -> BalancerRegistrationUpdateRequest:
        # The wire body `buildRegistrationUpdateFromPlayerPayload` emits for a rated tank that keeps its picks.
        role = {
            "role": {"dimension": "player_role", "role": "tank"},
            "priority": 0,
            "is_primary": True,
            "rank_value": 3100,
            "is_active": True,
            spelling: list(reversed(slugs)),
        }
        return BalancerRegistrationUpdateRequest.model_validate({"roles": [role]})

    async def _run() -> tuple[list[str], list[str], list[str]]:
        await project_disciplines(db_session)
        schema = _heroes_schema()
        seeded = await _seed(db_session, schema=schema)
        db_session.add_all(
            models.CatalogEntity(
                discipline="overwatch", kind="character", slug=slug, name=slug, image_path="x", attrs={"class": "tank"}
            )
            for slug in slugs
        )
        await db_session.commit()
        try:
            await registration_service.submit_public_registration(
                db_session,
                tournament_id=seeded["tournament_id"],
                auth_user=seeded["auth_user"],
                body=RegistrationSubmit(
                    form_version_id=seeded["version_id"],
                    answers={
                        "identity_battlenet": [f"R{suffix}#1234"],
                        "roles": [{"role": "tank", "is_primary": True, "top_heroes": slugs}],
                    },
                ),
            )
            registration = await registration_service.get_registration(
                db_session, seeded["tournament_id"], seeded["auth_user"].id
            )
            before = await _picks(registration.id)

            async def patch(body: BalancerRegistrationUpdateRequest) -> None:
                await lifecycle_service.update_registration_profile(
                    db_session,
                    registration.id,
                    display_name=body.display_name,
                    admin_notes=body.admin_notes,
                    answers=body.answers,
                    status_value=body.status,
                    balancer_status_value=body.balancer_status,
                    roles=[role.model_dump() for role in body.roles or []],
                )

            await patch(_patch("top_characters"))
            kept = await _picks(registration.id)
            await patch(_patch("top_heroes"))
            return before, kept, await _picks(registration.id)
        finally:
            await db_session.rollback()
            await _drop(db_session, seeded["workspace_id"])
            await db_session.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.slug.in_(slugs)))
            await db_session.commit()

    before, kept, stale_spelling = asyncio.run(_run())

    assert before == slugs
    # The native spelling persists the picks the sheet sent, in the order it sent them.
    assert kept == list(reversed(slugs))
    # The persisted-form spelling is not part of this receiver's contract: it carries no picks at all.
    assert stale_spelling == []


def test_an_organizer_save_without_roles_keeps_the_role_set_while_an_empty_list_replaces_it(db_session) -> None:
    """``roles`` on the organizer receiver is a REPLACEMENT of the registration's whole role set. A save that
    changes only a name or a note must therefore leave the key out (the edit form does, unless roles or ranks
    changed): the assignments, ranks and picks stay. Sending ``[]`` is what removes them -- the contract the
    form has to respect."""
    suffix = uuid.uuid4().hex[:8]
    slugs = [f"hero-{suffix}-{index}" for index in range(2)]

    async def _run() -> tuple[tuple, tuple, tuple]:
        await project_disciplines(db_session)
        schema = _heroes_schema()
        seeded = await _seed(db_session, schema=schema)
        db_session.add_all(
            models.CatalogEntity(
                discipline="overwatch", kind="character", slug=slug, name=slug, image_path="x", attrs={"class": "tank"}
            )
            for slug in slugs
        )
        await db_session.commit()
        try:
            await registration_service.submit_public_registration(
                db_session,
                tournament_id=seeded["tournament_id"],
                auth_user=seeded["auth_user"],
                body=RegistrationSubmit(
                    form_version_id=seeded["version_id"],
                    answers={
                        "identity_battlenet": [f"K{suffix}#1234"],
                        "roles": [{"role": "tank", "is_primary": True, "top_heroes": slugs}],
                    },
                ),
            )
            registration = await registration_service.get_registration(
                db_session, seeded["tournament_id"], seeded["auth_user"].id
            )

            async def patch(payload: dict[str, Any]) -> None:
                body = BalancerRegistrationUpdateRequest.model_validate(payload)
                await lifecycle_service.update_registration_profile(
                    db_session,
                    registration.id,
                    display_name=body.display_name,
                    admin_notes=body.admin_notes,
                    answers=body.answers,
                    status_value=body.status,
                    balancer_status_value=body.balancer_status,
                    roles=[role.model_dump() for role in body.roles] if body.roles is not None else None,
                )

            async def state() -> tuple:
                ranks = (
                    await db_session.execute(
                        sa.select(models.RegistrationRole.rank_value)
                        .where(models.RegistrationRole.registration_id == registration.id)
                        .order_by(models.RegistrationRole.priority)
                    )
                ).scalars()
                picks = (
                    await db_session.scalars(
                        sa.select(models.CatalogEntity.slug)
                        .join(
                            models.RegistrationRoleEntity,
                            models.RegistrationRoleEntity.entity_id == models.CatalogEntity.id,
                        )
                        .join(
                            models.RegistrationRole,
                            models.RegistrationRole.id == models.RegistrationRoleEntity.role_id,
                        )
                        .where(models.RegistrationRole.registration_id == registration.id)
                        .order_by(models.RegistrationRoleEntity.priority)
                    )
                ).all()
                return tuple(ranks), tuple(picks)

            await patch(
                {
                    "roles": [
                        {
                            "role": {"dimension": "player_role", "role": "tank"},
                            "priority": 0,
                            "is_primary": True,
                            "rank_value": 3100,
                            "is_active": True,
                            "top_characters": slugs,
                        }
                    ]
                }
            )
            rated = await state()
            await patch({"display_name": "Renamed", "admin_notes": "seen twice"})
            kept = await state()
            await patch({"roles": []})
            return rated, kept, await state()
        finally:
            await db_session.rollback()
            await _drop(db_session, seeded["workspace_id"])
            await db_session.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.slug.in_(slugs)))
            await db_session.commit()

    rated, kept, wiped = asyncio.run(_run())

    assert rated == ((3100,), tuple(slugs))
    # No `roles` key: the rank and both picks survive a save that only touched the name and the note.
    assert kept == rated
    # An explicit empty list is a replacement by nothing.
    assert wiped == ((), ())


def test_an_edit_that_changes_the_role_set_keeps_its_overlapping_picks(db_session) -> None:
    """The other two shapes of the same edit: the role SET moves, and a surviving
    role's pick list overlaps the one it replaces.

    A role that survives is merged over in place (its organizer rank must not be
    blanked), and the throwaway row the submitted answer was parsed into must
    never reach the session -- its INSERT has no ``registration_id`` and fails
    the whole edit. A role that is dropped goes through delete-orphan, a role
    that is new is inserted, and the surviving role's picks are replaced by a
    list that shares and reorders heroes -- which only commits because both
    ``registration_role_entity`` uniques are deferred."""
    suffix = uuid.uuid4().hex[:8]
    # A top-hero pick must belong to the role's class, so each role gets its own.
    classes = {
        f"hero-{suffix}-t": enums.HeroClass.tank,
        f"hero-{suffix}-d0": enums.HeroClass.damage,
        f"hero-{suffix}-d1": enums.HeroClass.damage,
        f"hero-{suffix}-s": enums.HeroClass.support,
    }
    slugs = list(classes)
    tank_hero, damage_a, damage_b, support_hero = slugs

    async def _run() -> tuple[list[tuple[str, int, str]], list[str], list[str]]:
        schema = _heroes_schema()
        seeded = await _seed(db_session, schema=schema)
        db_session.add_all(
            models.CatalogEntity(
                discipline="overwatch",
                kind="character",
                slug=slug,
                name=slug,
                image_path="x",
                attrs={"class": hero_class.name},
            )
            for slug, hero_class in classes.items()
        )
        await db_session.commit()
        catalog = {
            row.slug: HeroCatalogEntry(id=row.id, slug=row.slug)
            for row in (
                await db_session.scalars(sa.select(models.CatalogEntity).where(models.CatalogEntity.slug.in_(slugs)))
            ).all()
        }
        try:
            await registration_service.submit_public_registration(
                db_session,
                tournament_id=seeded["tournament_id"],
                auth_user=seeded["auth_user"],
                body=RegistrationSubmit(
                    form_version_id=seeded["version_id"],
                    answers={
                        "identity_battlenet": [f"E{suffix}#1234"],
                        "roles": [
                            {"role": "tank", "is_primary": True, "top_heroes": [tank_hero]},
                            {"role": "damage", "is_primary": False, "top_heroes": [damage_a, damage_b]},
                        ],
                    },
                ),
            )
            registration = await registration_service.get_registration(
                db_session, seeded["tournament_id"], seeded["auth_user"].id
            )
            updated = await registration_service.update_registration(
                db_session,
                registration,
                tournament=await registration_service.tournament_repo.get(db_session, seeded["tournament_id"]),
                values={
                    "roles": [
                        # survives, picks overlap and swap order
                        {"role": "damage", "is_primary": True, "top_heroes": [damage_b, damage_a]},
                        # brand new role
                        {"role": "support", "is_primary": False, "top_heroes": [support_hero]},
                        # "tank" is gone
                    ]
                },
                schema=schema,
                hero_catalog=catalog,
                form_version_id=seeded["version_id"],
            )
            roster = (await _public_rosters(db_session, [updated])).get(updated.id)
            assert roster is not None
            roster_roles = [entry.role for entry in roster.roles]
            roster_damage_heroes = [
                hero.slug for entry in roster.roles if entry.role == "damage" for hero in entry.top_characters
            ]
            rows = [
                (role, priority, slug)
                for role, priority, slug in (
                    await db_session.execute(
                        sa.select(
                            models.RegistrationRole.role,
                            models.RegistrationRoleEntity.priority,
                            models.CatalogEntity.slug,
                        )
                        .select_from(models.RegistrationRole)
                        .join(
                            models.RegistrationRoleEntity,
                            models.RegistrationRoleEntity.role_id == models.RegistrationRole.id,
                        )
                        .join(
                            models.CatalogEntity,
                            models.CatalogEntity.id == models.RegistrationRoleEntity.entity_id,
                        )
                        .where(models.RegistrationRole.registration_id == registration.id)
                        .order_by(
                            models.RegistrationRole.priority,
                            models.RegistrationRoleEntity.priority,
                        )
                    )
                ).all()
            ]
            return rows, roster_roles, roster_damage_heroes
        finally:
            await db_session.rollback()
            await _drop(db_session, seeded["workspace_id"])
            await db_session.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.slug.in_(slugs)))
            await db_session.commit()

    rows, roster_roles, roster_damage_heroes = asyncio.run(_run())

    assert rows == [
        ("damage", 1, damage_b),
        ("damage", 2, damage_a),
        ("support", 1, support_hero),
    ]
    assert roster_roles == ["damage", "support"]
    assert roster_damage_heroes == [damage_b, damage_a]


assert SocialAccount is not None  # imported for the model registry the gate queries
