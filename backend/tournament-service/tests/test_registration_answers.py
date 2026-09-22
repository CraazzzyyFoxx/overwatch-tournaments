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
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from shared.core import enums  # noqa: E402
from shared.core.errors import ApiHTTPException  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection  # noqa: E402
from shared.hero_catalog import HeroCatalogEntry  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.social import SocialAccount  # noqa: E402
from shared.models.registration.registration import (  # noqa: E402
    BalancerRegistrationForm,
    BalancerRegistrationFormVersion,
)
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament, TournamentPhaseSchedule  # noqa: E402
from src import models  # noqa: E402
from src.schemas.registration import RegistrationSubmit  # noqa: E402
from src.services.registration.answers import answer_service  # noqa: E402
from src.services.registration.service import registration_service  # noqa: E402


def _schema(**overrides: Any) -> FormSchema:
    """A form that asks a required BattleTag, one identity, roles, both notes and
    two custom questions."""
    fields = [
        FormField(key="battle_tag", kind="builtin", required=True, params=overrides.get("battle_tag_params", {})),
        FormField(key="identity_discord", kind="builtin", params=overrides.get("discord_params", {})),
        FormField(key="smurf_tags", kind="builtin"),
        FormField(key="roles", kind="builtin"),
        FormField(key="public_notes", kind="builtin"),
        FormField(key="organizer_notes", kind="builtin", visibility="organizers"),
        FormField(key="age", kind="number", label="Age"),
        FormField(key="vk", kind="text", label="VK"),
    ]
    return FormSchema(sections=[FormSection(key="all", fields=fields)])


SCHEMA = _schema()


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
                hero_catalog=None,
            )
        )
    finally:
        answers_module.resolve_subrole_catalog = original


def _errors(exc: ApiHTTPException) -> list[dict[str, Any]]:
    """``ApiHTTPException`` serializes its ``ApiExc`` list on construction, so the
    wire shape is what a caller actually sees."""
    return list(exc.detail)


# ── validate: one pass, every error ─────────────────────────────────────────


def test_a_submission_is_reduced_to_typed_values() -> None:
    values = _validate(
        {
            "battle_tag": " Player # 1234 ",
            "identity_discord": "Player",
            "age": "21",
            "roles": [{"role": "tank", "is_primary": True}],
        }
    )

    assert values["battle_tag"] == "Player # 1234"
    # Identity handles are normalised by the provider's own rule at coercion time.
    assert values["identity_discord"] == "player"
    assert values["age"] == 21
    assert values["roles"] == [{"role": "tank", "is_primary": True}]


def test_every_stage_reports_before_anything_is_raised() -> None:
    """Normalisation, role rules and the verified gate all contribute to ONE
    422. Raising after stage one would make the registrant resubmit to discover
    the role error waiting behind it."""
    schema = _schema(discord_params={"require_verified": True})

    with pytest.raises(ApiHTTPException) as caught:
        _validate(
            {"age": "not a number", "identity_discord": "ghost", "roles": [{"role": "tank", "is_primary": False}]},
            schema=schema,
            session=_FakeSession([]),
        )

    by_field = {error["field"]: error["code"] for error in _errors(caught.value)}
    assert by_field["age"] == "invalid_type"
    assert by_field["battle_tag"] == "required"
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
            {"battle_tag": "Player#1234", "identity_discord": "Bad Name!"},
            schema=schema,
            session=_FakeSession([("discord", "bad name!")]),
        )

    assert [(e["field"], e["code"]) for e in _errors(caught.value)] == [("identity_discord", "invalid_format")]


def test_a_gated_answer_left_blank_is_still_not_verified() -> None:
    """The other half: ``require_verified`` implies the field is required, so a
    genuinely blank answer must keep failing the gate even though the field
    itself is optional and normalisation therefore said nothing about it."""
    schema = _schema(discord_params={"require_verified": True})

    with pytest.raises(ApiHTTPException) as caught:
        _validate({"battle_tag": "Player#1234", "identity_discord": ""}, schema=schema, session=_FakeSession([]))

    assert [(e["field"], e["code"]) for e in _errors(caught.value)] == [("identity_discord", "not_verified")]


def test_a_gated_identity_matching_a_verified_account_passes() -> None:
    schema = _schema(discord_params={"require_verified": True})

    values = _validate(
        {"battle_tag": "Player#1234", "identity_discord": "Player"},
        schema=schema,
        session=_FakeSession([("discord", "player")]),
    )

    assert values["identity_discord"] == "player"


def test_a_gated_identity_with_no_linked_player_is_not_verified() -> None:
    """Ownership is provable only through OAuth, so a submission with no player
    behind it cannot satisfy the gate -- and must not reach the database."""
    schema = _schema(discord_params={"require_verified": True})
    session = _FakeSession([("discord", "player")])

    with pytest.raises(ApiHTTPException) as caught:
        _validate(
            {"battle_tag": "Player#1234", "identity_discord": "Player"}, schema=schema, session=session, player_id=None
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


def test_a_gated_battle_tag_is_checked_against_the_battlenet_account() -> None:
    schema = _schema(battle_tag_params={"require_verified": True})

    with pytest.raises(ApiHTTPException) as caught:
        _validate({"battle_tag": "Other#9999"}, schema=schema, session=_FakeSession([("battlenet", "player#1234")]))

    assert _errors(caught.value)[0]["field"] == "battle_tag"
    # The same tag in another casing/spacing is the same account.
    assert (
        _validate(
            {"battle_tag": " PLAYER # 1234 "}, schema=schema, session=_FakeSession([("battlenet", "player#1234")])
        )["battle_tag"]
        == "PLAYER # 1234"
    )


def test_an_organizers_draft_neither_requires_nor_verifies() -> None:
    """``enforce_required=False`` is the organizer path: they are entering what
    they know, and nobody's OAuth proves their typing."""
    schema = _schema(discord_params={"require_verified": True})
    session = _FakeSession([])

    values = _validate(
        {"identity_discord": "ghost"},
        schema=schema,
        session=session,
        partial=True,
        enforce_required=False,
        player_id=None,
    )

    assert values["identity_discord"] == "ghost"
    assert session.executed == 0


def test_a_blank_answer_survives_validation_as_an_explicit_clear() -> None:
    """``normalize_answers`` drops a blank optional answer, which is right for
    "never mentioned" and wrong for "emptied". The writer has to tell them apart
    or a PATCH that clears a question would silently leave it stored."""
    values = _validate({"vk": ""}, partial=True, enforce_required=False)

    assert values == {"vk": None}
    assert _validate({}, partial=True, enforce_required=False) == {}


# ── apply: the one writer ───────────────────────────────────────────────────


def _registration(**kwargs: Any) -> models.BalancerRegistration:
    return models.BalancerRegistration(id=1, tournament_id=7, status="pending", **kwargs)


def test_role_update_preserves_rank_value_on_surviving_roles() -> None:
    """Organizer state, not registrant state: ``rank_value``/``is_active`` come
    from rank autofill and the admin editor, and the public form submits
    neither. Rebuilding the rows would blank every rank the moment a player
    reordered their roles."""
    registration = _registration()
    registration.roles = [
        models.BalancerRegistrationRole(role="tank", rank_value=3200, is_active=True, is_primary=True, priority=0),
        models.BalancerRegistrationRole(role="damage", rank_value=2500, is_active=True, is_primary=False, priority=1),
    ]

    answer_service.apply(
        registration,
        {"roles": [{"role": "damage", "is_primary": True}, {"role": "support", "is_primary": False}]},
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
    built on a THROWAWAY ``BalancerRegistrationRole``. Handing over that row's live
    collection drags the throwaway into the session through the backref: a second
    role row with no ``registration_id``, so the next flush dies on the NOT NULL
    constraint. Every self-edit of a form with the top-heroes ask switched on was
    a 500."""
    schema = FormSchema(
        sections=[
            FormSection(
                key="all",
                fields=[
                    FormField(key="battle_tag", kind="builtin", required=True),
                    FormField(key="roles", kind="builtin", params={"top_heroes": {"enabled": True, "max": 3}}),
                ],
            )
        ]
    )
    catalog = {"ana": HeroCatalogEntry(id=11, slug="ana", hero_class=enums.HeroClass.support)}
    registration = _registration()
    registration.roles = [models.BalancerRegistrationRole(role="tank", is_primary=True, priority=0)]
    session = sa.orm.Session()
    session.add(registration)

    answer_service.apply(
        registration,
        {"roles": [{"role": "tank", "is_primary": True, "top_heroes": ["ana"]}]},
        schema=schema,
        hero_catalog=catalog,
    )

    pending_roles = [row for row in session.new if isinstance(row, models.BalancerRegistrationRole)]
    assert [row for row in pending_roles if row not in registration.roles] == []
    assert [entry.hero_id for entry in registration.roles[0].hero_entries] == [11]


def test_an_identity_answer_upserts_and_a_blank_one_deletes() -> None:
    registration = _registration()

    answer_service.apply(registration, {"identity_discord": "Player"}, schema=SCHEMA, hero_catalog=None)
    assert [(row.provider, row.handle_normalized) for row in registration.identities] == [("discord", "player")]

    answer_service.apply(registration, {"identity_discord": "Renamed"}, schema=SCHEMA, hero_catalog=None)
    assert [row.handle for row in registration.identities] == ["Renamed"]

    answer_service.apply(registration, {"identity_discord": None}, schema=SCHEMA, hero_catalog=None)
    assert registration.identities == []


def test_an_identity_the_form_does_not_ask_about_is_not_written() -> None:
    """The schema is the authority on what a registration may carry; a client
    inventing a key must not create a row for it."""
    registration = _registration()

    answer_service.apply(registration, {"identity_twitch": "player_tv"}, schema=SCHEMA, hero_catalog=None)

    assert registration.identities == []


def test_answers_of_projects_what_apply_wrote() -> None:
    registration = _registration()
    answer_service.apply(
        registration,
        {
            "battle_tag": "Player#1234",
            "smurf_tags": ["Alt#1111"],
            "identity_discord": "player",
            "stream_pov": True,
            "public_notes": "hi",
            "organizer_notes": "seed me low",
            "vk": "vk.com/player",
        },
        schema=SCHEMA,
        hero_catalog=None,
    )

    assert answer_service.answers_of(registration) == {
        "smurf_tags": ["Alt#1111"],
        "stream_pov": True,
        "identity_discord": "player",
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

    form = BalancerRegistrationForm(tournament_id=tournament.id, workspace_id=workspace.id)
    session.add(form)
    await session.flush()
    version = BalancerRegistrationFormVersion(form_id=form.id, number=1, schema_json=schema.model_dump(mode="json"))
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
                        "battle_tag": "Answerer#1234",
                        "identity_discord": "Answerer",
                        "smurf_tags": ["Alt#1111"],
                        "public_notes": "hi organizers",
                        "vk": "vk.com/answerer",
                        "roles": [{"role": "tank", "is_primary": True}],
                    },
                ),
            )
            row = await db_session.scalar(
                sa.select(models.BalancerRegistration)
                .where(models.BalancerRegistration.id == read.id)
                .options(
                    sa.orm.selectinload(models.BalancerRegistration.identities),
                    sa.orm.selectinload(models.BalancerRegistration.roles),
                )
            )
            return read, _row_image(row, seeded["version_id"])
        finally:
            await _drop(db_session, seeded["workspace_id"])

    read, image = asyncio.run(_run())

    assert image == {
        "battle_tag": "Answerer#1234",
        "battle_tag_normalized": "answerer#1234",
        "display_name": "Answerer#1234",
        "smurf_tags_json": ["Alt#1111"],
        "public_notes": "hi organizers",
        "custom_fields_json": {"vk": "vk.com/answerer"},
        "identities": [("discord", "answerer", "answerer")],
        "roles": [("tank", True)],
        "stamped_current_version": True,
    }
    # The read model the caller gets back carries the same answers, flat.
    assert read.battle_tag == "Answerer#1234"
    assert read.answers["identity_discord"] == "answerer"
    assert read.answers["vk"] == "vk.com/answerer"
    assert read.form_version_stale is False


def _row_image(row: Any, version_id: int) -> dict[str, Any]:
    return {
        "battle_tag": row.battle_tag,
        "battle_tag_normalized": row.battle_tag_normalized,
        "display_name": row.display_name,
        "smurf_tags_json": row.smurf_tags_json,
        "public_notes": row.public_notes,
        "custom_fields_json": row.custom_fields_json,
        "identities": [(i.provider, i.handle, i.handle_normalized) for i in row.identities],
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
                        answers={"battle_tag": "Answerer#1234"},
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
                        answers={"battle_tag": "Answerer#1234", "identity_discord": "someone_else"},
                    ),
                )
            await db_session.rollback()
            written = await db_session.scalar(
                sa.select(sa.func.count())
                .select_from(models.BalancerRegistration)
                .where(models.BalancerRegistration.tournament_id == seeded["tournament_id"])
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
                    FormField(key="battle_tag", kind="builtin", required=True),
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


def test_a_role_top_hero_list_survives_being_replaced_in_place(db_session) -> None:
    """A self-edit replaces the role's whole pick list, so a registrant resaving
    picks they never touched asks the database to hold a row and its replacement
    at once. The unit of work leaves the INSERTs and the DELETEs of one table
    unordered, so both uniques on ``registration_role_hero`` have to hold at
    COMMIT rather than per statement -- and did not, which is a 500 on the edit.

    The raw insert/delete pair at the end is that same sequence in the form the
    ORM's arbitrary sort will not reliably produce."""
    suffix = uuid.uuid4().hex[:8]
    slugs = [f"hero-{suffix}-{index}" for index in range(2)]

    async def _run() -> list[tuple[str, int]]:
        schema = _heroes_schema()
        seeded = await _seed(db_session, schema=schema)
        db_session.add_all(
            models.Hero(slug=slug, name=slug, image_path="x", type=enums.HeroClass.tank) for slug in slugs
        )
        await db_session.commit()
        catalog = {
            row.slug: HeroCatalogEntry(id=row.id, slug=row.slug, hero_class=enums.HeroClass.tank)
            for row in (await db_session.scalars(sa.select(models.Hero).where(models.Hero.slug.in_(slugs)))).all()
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
                    answers={"battle_tag": f"H{suffix}#1234", "roles": picks},
                ),
            )
            registration = await registration_service.get_registration(
                db_session, seeded["tournament_id"], seeded["auth_user"].id
            )
            await registration_service.update_registration(
                db_session,
                registration,
                tournament=await registration_service.tournament_repo.get(db_session, seeded["tournament_id"]),
                values={"roles": picks},
                schema=schema,
                hero_catalog=catalog,
                form_version_id=seeded["version_id"],
            )
            rows = (
                await db_session.execute(
                    sa.select(
                        models.BalancerRegistrationRoleHero.id,
                        models.BalancerRegistrationRoleHero.role_id,
                        models.BalancerRegistrationRoleHero.hero_id,
                        models.BalancerRegistrationRoleHero.priority,
                    )
                    .join(
                        models.BalancerRegistrationRole,
                        models.BalancerRegistrationRole.id == models.BalancerRegistrationRoleHero.role_id,
                    )
                    .where(models.BalancerRegistrationRole.registration_id == registration.id)
                    .order_by(models.BalancerRegistrationRoleHero.priority)
                )
            ).all()
            replaced = rows[0]
            await db_session.execute(
                sa.insert(models.BalancerRegistrationRoleHero).values(
                    role_id=replaced.role_id, hero_id=replaced.hero_id, priority=replaced.priority
                )
            )
            await db_session.execute(
                sa.delete(models.BalancerRegistrationRoleHero).where(
                    models.BalancerRegistrationRoleHero.id == replaced.id
                )
            )
            await db_session.commit()
            return [
                (slug, priority)
                for slug, priority in (
                    await db_session.execute(
                        sa.select(models.Hero.slug, models.BalancerRegistrationRoleHero.priority)
                        .join(
                            models.BalancerRegistrationRoleHero,
                            models.BalancerRegistrationRoleHero.hero_id == models.Hero.id,
                        )
                        .join(
                            models.BalancerRegistrationRole,
                            models.BalancerRegistrationRole.id == models.BalancerRegistrationRoleHero.role_id,
                        )
                        .where(models.BalancerRegistrationRole.registration_id == registration.id)
                        .order_by(models.BalancerRegistrationRoleHero.priority)
                    )
                ).all()
            ]
        finally:
            await db_session.rollback()
            await _drop(db_session, seeded["workspace_id"])
            await db_session.execute(sa.delete(models.Hero).where(models.Hero.slug.in_(slugs)))
            await db_session.commit()

    assert asyncio.run(_run()) == [(slugs[0], 1), (slugs[1], 2)]


assert SocialAccount is not None  # imported for the model registry the gate queries
