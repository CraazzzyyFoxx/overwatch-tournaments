"""Every answer a registration form collects has to reach the database.

Four write paths accept a registration payload (public create, public self
PATCH, admin manual create, admin profile PATCH) and each of them used to drop
part of it on the floor -- silently, because a value that is never passed on and
a value assigned to an attribute SQLAlchemy does not map both look exactly like
success: ``create_registration`` had no ``boosty_nick`` parameter, so a Boosty
handle the form could mark *required* was validated and then discarded;
``update_registration`` did ``setattr`` straight off the payload keys, so
``custom_fields`` died with the session.

That whole class of bug is gone by construction: there is no keyword per
question any more. One flat ``answers`` document goes through one writer
(:class:`RegistrationAnswerService`), so a new question needs no writer change
at all -- which is why the two "every request field is a writer parameter"
parity guards this module used to carry were deleted rather than re-pinned.
What is still worth pinning is that each of the four paths hands its answers to
that writer, and what each of them means by "the registrant left this out".

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core.enums import HeroClass  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection  # noqa: E402
from shared.domain.roster import PlayerRoster, RosterRole  # noqa: E402
from shared.services.roster import roster_engine  # noqa: E402
from src import models  # noqa: E402
from src.services.registration import lifecycle as reg_lifecycle  # noqa: E402
from src.services.registration import service as reg_service  # noqa: E402


def _schema() -> FormSchema:
    """A form asking a BattleTag, one identity, roles, both notes and one custom
    question -- enough for every branch the writers have."""
    return FormSchema(
        sections=[
            FormSection(
                key="all",
                fields=[
                    FormField(key="battle_tag", kind="builtin"),
                    FormField(key="identity_discord", kind="builtin"),
                    FormField(key="smurf_tags", kind="builtin"),
                    FormField(key="roles", kind="builtin"),
                    FormField(key="public_notes", kind="builtin"),
                    FormField(key="organizer_notes", kind="builtin", visibility="organizers"),
                    FormField(key="vk", kind="text", label="VK"),
                    FormField(key="tg", kind="text", label="Telegram"),
                ],
            )
        ]
    )


SCHEMA = _schema()


class _RecordingSession:
    """Stands in for the AsyncSession. ``info`` backs
    ``register_tournament_realtime_update``; ``scalar`` answers the one
    workspace-id lookup the manual-create path makes."""

    def __init__(self, *, scalar_value: Any = 42) -> None:
        self.info: dict = {}
        self.added: list[Any] = []
        self.commits = 0
        self._scalar_value = scalar_value

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        return None

    async def scalar(self, *_args: Any, **_kwargs: Any) -> Any:
        return self._scalar_value

    def begin_nested(self) -> Any:
        return _Savepoint()


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def _fake_resolve(*_args: Any, **_kwargs: Any) -> dict:
    return {}


def _wp_patches():
    # Identity provisioning is patched out (it would hit the DB), and the roster
    # engine with it: this suite asserts which registration FIELDS a write path
    # persists, not what the balancer status derives from them.
    return (
        mock.patch.object(
            reg_service.registration_service, "ensure_player_identity", mock.AsyncMock(return_value=None)
        ),
        mock.patch.object(roster_engine, "for_tournament", _fake_resolve),
    )


def _roster_of(registration: models.BalancerRegistration) -> PlayerRoster:
    """What the engine would answer for a row with no tenancy behind it: the
    registration's own layer only, over the roles it declares active."""
    return PlayerRoster(
        registration_id=registration.id,
        battle_tag=registration.battle_tag,
        display_name=registration.display_name,
        player_id=None,
        auth_user_id=None,
        workspace_member_id=None,
        roles=tuple(
            RosterRole(
                role=HeroClass.from_slot_code(role.role),
                rank=role.rank_value,
                source="registration" if role.rank_value is not None else "none",
                is_primary=bool(role.is_primary),
                priority=priority,
                subrole=role.subrole,
            )
            for priority, role in enumerate(role for role in registration.roles if role.is_active)
        ),
        is_full_flex=False,
    )


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


class TestPublicCreatePersistsEveryAnswer(IsolatedAsyncioTestCase):
    async def _create(self, answers: dict[str, Any]) -> models.BalancerRegistration:
        session = _RecordingSession()
        patches = _wp_patches()
        with (
            mock.patch.object(reg_service.registration_service, "ensure_player_identity", _noop),
            mock.patch.object(reg_service, "assign_workspace_system_role", _noop),
            mock.patch.object(reg_service, "enqueue_registration_approved", _noop),
            patches[0],
            patches[1],
        ):
            return await reg_service.registration_service.create_registration(
                session,
                tournament_id=7,
                workspace_id=1,
                auth_user_id=None,
                values=answers,
                schema=SCHEMA,
                form_version_id=3,
            )

    async def test_the_battle_tag_lands_in_both_of_its_columns(self) -> None:
        registration = await self._create({"battle_tag": "Player # 1234"})

        assert registration.battle_tag == "Player#1234"
        assert registration.battle_tag_normalized == "player#1234"
        # The row is named after the tag, as it always was.
        assert registration.display_name == "Player#1234"

    async def test_an_identity_answer_becomes_a_provider_row(self) -> None:
        registration = await self._create({"battle_tag": "Player#1234", "identity_discord": "Player"})

        assert [(row.provider, row.handle, row.handle_normalized) for row in registration.identities] == [
            ("discord", "Player", "player")
        ]

    async def test_custom_answers_reach_the_json_column(self) -> None:
        registration = await self._create({"battle_tag": "Player#1234", "vk": "vk.com/player"})

        assert registration.custom_fields_json == {"vk": "vk.com/player"}

    async def test_the_two_note_questions_land_in_their_own_columns(self) -> None:
        registration = await self._create(
            {"battle_tag": "Player#1234", "public_notes": "hi", "organizer_notes": "seed me low"}
        )

        assert registration.public_notes == "hi"
        assert registration.organizer_notes == "seed me low"

    async def test_the_answered_version_is_stamped_on_the_row(self) -> None:
        registration = await self._create({"battle_tag": "Player#1234"})

        assert registration.form_version_id == 3


class TestSelfUpdateAppliesAnswers(IsolatedAsyncioTestCase):
    def _registration(self, **kwargs: Any) -> models.BalancerRegistration:
        return models.BalancerRegistration(id=1, tournament_id=7, status="pending", **kwargs)

    async def _update(self, registration: models.BalancerRegistration, values: dict[str, Any]) -> None:
        await reg_service.registration_service.update_registration(
            _RecordingSession(), registration, values=values, schema=SCHEMA, form_version_id=5
        )

    async def test_custom_answers_merge_with_the_stored_ones(self) -> None:
        """A PATCH names only the questions it changes; replacing wholesale would
        wipe the answers it did not mention."""
        registration = self._registration(custom_fields_json={"vk": "old", "tg": "kept"})

        await self._update(registration, {"vk": "new"})

        assert registration.custom_fields_json == {"vk": "new", "tg": "kept"}

    async def test_a_blank_custom_answer_removes_the_key(self) -> None:
        registration = self._registration(custom_fields_json={"vk": "old", "tg": "kept"})

        await self._update(registration, {"vk": None})

        assert registration.custom_fields_json == {"tg": "kept"}

    async def test_an_unmentioned_question_is_left_alone(self) -> None:
        registration = self._registration(public_notes="kept", custom_fields_json={"vk": "kept"})

        await self._update(registration, {"battle_tag": "Player#1234"})

        assert registration.public_notes == "kept"
        assert registration.custom_fields_json == {"vk": "kept"}

    async def test_battle_tag_is_cleaned_and_normalized(self) -> None:
        registration = self._registration()

        await self._update(registration, {"battle_tag": "Player # 1234"})

        assert registration.battle_tag == "Player#1234"
        assert registration.battle_tag_normalized == "player#1234"

    async def test_the_edit_moves_the_row_onto_the_version_it_answered(self) -> None:
        registration = self._registration(form_version_id=4)

        await self._update(registration, {"battle_tag": "Player#1234"})

        assert registration.form_version_id == 5

    async def test_a_settled_registration_cannot_be_edited(self) -> None:
        registration = models.BalancerRegistration(id=1, tournament_id=7, status="approved")

        with self.assertRaises(HTTPException) as caught:
            await self._update(registration, {"battle_tag": "Player#1234"})

        assert caught.exception.status_code == 400


class _FormStub:
    """A form whose ``current_version`` carries ``SCHEMA`` -- the shape
    ``schema_from_form`` reads, without a database behind it."""

    workspace_id = 1
    current_version_id = 12
    auto_approve = False
    show_ranks = False

    def __init__(self) -> None:
        from types import SimpleNamespace

        self.current_version = SimpleNamespace(id=12, schema_json=SCHEMA.model_dump(mode="json"))


class TestManualCreateHonorsTheEditor(IsolatedAsyncioTestCase):
    async def _create(self, **overrides: Any) -> tuple[models.BalancerRegistration, list[str]]:
        session = _RecordingSession()
        events: list[str] = []

        async def _approved(*_args: Any, **_kwargs: Any) -> None:
            events.append("approved")

        payload: dict[str, Any] = {
            "tournament_id": 7,
            "display_name": None,
            "admin_notes": None,
            "answers": {"battle_tag": "Player#1234"},
            "roles": [],
            **overrides,
        }
        patches = _wp_patches()
        with (
            mock.patch.object(reg_lifecycle.lifecycle_service, "ensure_unique_battle_tag", _noop),
            mock.patch.object(
                reg_lifecycle.lifecycle_service.common,
                "get_registration_form",
                mock.AsyncMock(return_value=_FormStub()),
            ),
            mock.patch.object(reg_lifecycle, "_resolve_top_heroes_config", mock.AsyncMock(return_value=(None, None))),
            mock.patch.object(reg_lifecycle.lifecycle_service, "validate_registration_status_value", _noop),
            mock.patch.object(reg_lifecycle, "enqueue_registration_approved", _approved),
            mock.patch.object(
                reg_lifecycle.lifecycle_service,
                "get_registration_by_id",
                mock.AsyncMock(side_effect=lambda _s, _i: session.added[0]),
            ),
            patches[0],
            patches[1],
        ):
            registration = await reg_lifecycle.lifecycle_service.create_manual_registration(session, **payload)
        return registration, events

    async def test_the_default_is_still_approved(self) -> None:
        registration, events = await self._create()

        assert registration.status == "approved"
        assert events == ["approved"]

    async def test_the_chosen_status_is_used(self) -> None:
        registration, _ = await self._create(status_value="pending")

        assert registration.status == "pending"

    async def test_a_non_approved_row_fires_no_approval_event(self) -> None:
        _, events = await self._create(status_value="pending")

        assert events == []

    async def test_ready_is_a_sentinel_computed_from_the_attached_roles(self) -> None:
        # No active roles were passed -> "ready" is impossible; the create
        # path resolves the ready/incomplete sentinel from the roles just
        # attached rather than accepting it literally (an admin-forced
        # "ready" with no ranks would violate the rest of the system's
        # "ready implies rank-complete" invariant).
        registration, _ = await self._create(balancer_status_value="ready")

        assert registration.balancer_status == "incomplete"
        assert registration.exclude_reason is None

    async def test_a_literal_non_auto_status_is_used_as_is(self) -> None:
        registration, _ = await self._create(balancer_status_value="excluded")

        assert registration.balancer_status == "excluded"

    async def test_the_organizers_answers_are_written(self) -> None:
        registration, _ = await self._create(
            answers={"battle_tag": "Player#1234", "vk": "vk.com/player", "organizer_notes": "walk-in"}
        )

        assert registration.custom_fields_json == {"vk": "vk.com/player"}
        assert registration.organizer_notes == "walk-in"

    async def test_a_required_question_left_blank_is_not_an_error_for_an_organizer(self) -> None:
        """``enforce_required=False``: an organizer enters what they know."""
        registration, _ = await self._create(answers={})

        assert registration.battle_tag is None


class TestAdminProfileUpdateAnswers(IsolatedAsyncioTestCase):
    async def _update(self, registration: models.BalancerRegistration, **overrides: Any) -> None:
        payload: dict[str, Any] = {
            "display_name": None,
            "admin_notes": None,
            "answers": {},
            "status_value": None,
            "balancer_status_value": None,
            "roles": None,
            **overrides,
        }
        with (
            mock.patch.object(
                reg_lifecycle.lifecycle_service, "get_registration_by_id", mock.AsyncMock(return_value=registration)
            ),
            mock.patch.object(
                reg_lifecycle.lifecycle_service.common,
                "get_registration_form",
                mock.AsyncMock(return_value=_FormStub()),
            ),
            mock.patch.object(reg_lifecycle, "_resolve_top_heroes_config", mock.AsyncMock(return_value=(None, None))),
            mock.patch.object(reg_lifecycle.lifecycle_service, "ensure_unique_battle_tag", _noop),
            mock.patch.object(reg_lifecycle.lifecycle_service.registrations, "ensure_player_identity", _noop),
            mock.patch.object(
                reg_lifecycle.lifecycle_service.common, "_register_registration_changed", mock.AsyncMock()
            ),
        ):
            await reg_lifecycle.lifecycle_service.update_registration_profile(
                _RecordingSession(), registration.id, **payload
            )

    def _registration(self, **kwargs: Any) -> models.BalancerRegistration:
        registration = models.BalancerRegistration(id=1, tournament_id=7, status="approved", **kwargs)
        registration.tournament = mock.Mock(workspace_id=1)
        return registration

    async def test_the_editor_clears_an_answer_by_sending_it_blank(self) -> None:
        """The admin editor round-trips every definition on the form, so a field
        it sends empty is a deletion -- that is what makes its save a replace."""
        registration = self._registration(custom_fields_json={"vk": "old", "tg": "dropped"})

        await self._update(registration, answers={"vk": "new", "tg": ""})

        assert registration.custom_fields_json == {"vk": "new"}

    async def test_omitting_them_leaves_the_stored_answers_alone(self) -> None:
        registration = self._registration(custom_fields_json={"vk": "kept"})

        await self._update(registration)

        assert registration.custom_fields_json == {"vk": "kept"}

    async def test_a_blank_identity_answer_deletes_its_row(self) -> None:
        registration = self._registration()
        registration.identities.append(
            models.BalancerRegistrationIdentity(provider="discord", handle="old", handle_normalized="old")
        )

        await self._update(registration, answers={"identity_discord": ""})

        assert registration.identities == []


class TestAdminProfileUpdateAutoManagedBalancerStatus(IsolatedAsyncioTestCase):
    """``ready``/``incomplete`` are derived from role ranks. The admin edit
    form always round-trips the registration's current ``balancer_status``,
    so resaving a row that already reads one of these two must recompute --
    not 400, the way an explicit ``set_balancer_status`` pin correctly does.
    """

    async def _update(self, registration: models.BalancerRegistration, **overrides: Any) -> None:
        payload: dict[str, Any] = {
            "display_name": None,
            "admin_notes": None,
            "answers": {},
            "status_value": None,
            "balancer_status_value": None,
            "roles": None,
            **overrides,
        }

        async def _rosters(*_a: Any, **_k: Any) -> dict:
            return {registration.id: _roster_of(registration)}

        with (
            mock.patch.object(
                reg_lifecycle.lifecycle_service, "get_registration_by_id", mock.AsyncMock(return_value=registration)
            ),
            mock.patch.object(
                reg_lifecycle.lifecycle_service.common, "get_registration_form", mock.AsyncMock(return_value=None)
            ),
            mock.patch.object(reg_lifecycle.lifecycle_service.registrations, "ensure_player_identity", _noop),
            mock.patch.object(
                reg_lifecycle.lifecycle_service.common, "_register_registration_changed", mock.AsyncMock()
            ),
            mock.patch.object(roster_engine, "for_tournament", _rosters),
        ):
            await reg_lifecycle.lifecycle_service.update_registration_profile(
                _RecordingSession(), registration.id, **payload
            )

    def _registration(self, **kwargs: Any) -> models.BalancerRegistration:
        registration = models.BalancerRegistration(id=1, tournament_id=7, status="approved", **kwargs)
        registration.tournament = mock.Mock(workspace_id=1)
        return registration

    async def test_resaving_a_ready_registration_recomputes_instead_of_rejecting(self) -> None:
        registration = self._registration(balancer_status="ready")
        registration.roles = [models.BalancerRegistrationRole(role="tank", is_active=True, rank_value=2500)]

        # Must not raise -- the old behaviour 400ed on this exact resend.
        await self._update(registration, balancer_status_value="ready")

        assert registration.balancer_status == "ready"

    async def test_resaving_an_incomplete_registration_stays_incomplete(self) -> None:
        registration = self._registration(balancer_status="incomplete")
        registration.roles = [models.BalancerRegistrationRole(role="tank", is_active=True, rank_value=None)]

        await self._update(registration, balancer_status_value="incomplete")

        assert registration.balancer_status == "incomplete"

    async def test_admin_managed_values_are_still_rejected_by_the_helper(self) -> None:
        """The dedicated pin action (`set_balancer_status`) must keep rejecting
        an explicit ready/incomplete request outright -- only the profile
        resave path gained tolerance."""
        # The concrete type, not a blind `Exception`: a bare AttributeError from a
        # renamed helper would satisfy that and read as the guard still working.
        with self.assertRaises(HTTPException) as caught:
            reg_lifecycle._reject_auto_managed_status("ready")

        assert caught.exception.status_code == 400
