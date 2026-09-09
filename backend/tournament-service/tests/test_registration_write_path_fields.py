"""Every field a registration form collects has to reach a column.

Four write paths accept a registration payload (public create, public self
PATCH, admin manual create, admin profile PATCH) and each of them used to drop
part of it on the floor -- silently, because a value that is never passed on and
a value assigned to an attribute SQLAlchemy does not map both look exactly like
success:

- ``create_registration`` had no ``boosty_nick`` parameter at all, so a Boosty
  handle the form could mark *required* was validated and then discarded.
- ``update_registration`` did ``setattr(registration, key, value)`` straight off
  the payload keys, so ``custom_fields`` (the column is ``custom_fields_json``)
  and the long-removed ``primary_role`` landed in the instance ``__dict__`` and
  died with the session.
- ``create_manual_registration`` hard-coded ``status="approved"`` and knew
  nothing about custom fields, so the admin editor's status choice and every
  custom-field answer were dropped.
- ``update_registration_profile`` had no ``custom_fields_json`` parameter.

The parity tests below are the general guard: a new field on a request schema
that no writer accepts fails the suite instead of the next registrant.

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core.enums import HeroClass  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.domain.roster import PlayerRoster, RosterRole  # noqa: E402
from shared.services.roster import roster_engine  # noqa: E402
from src import (
    models,  # noqa: E402
    schemas,  # noqa: E402
)
from src.schemas.registration import RegistrationCreate, RegistrationUpdate  # noqa: E402
from src.services.registration import lifecycle as reg_lifecycle  # noqa: E402
from src.services.registration import service as reg_service  # noqa: E402


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


class TestPublicCreatePersistsEveryHandle(IsolatedAsyncioTestCase):
    async def _create(self, **overrides: Any) -> models.BalancerRegistration:
        session = _RecordingSession()
        payload: dict[str, Any] = {
            "tournament_id": 7,
            "workspace_id": 1,
            "auth_user_id": None,
            "battle_tag": "Player#1234",
            "smurf_tags": None,
            "discord_nick": "player",
            "twitch_nick": "player_tv",
            "boosty_nick": "player_boosty",
            "stream_pov": False,
            "notes": None,
            "custom_fields": None,
            **overrides,
        }
        patches = _wp_patches()
        with (
            mock.patch.object(reg_service.registration_service, "ensure_player_identity", _noop),
            mock.patch.object(reg_service, "assign_workspace_system_role", _noop),
            mock.patch.object(reg_service, "enqueue_registration_approved", _noop),
            patches[0],
            patches[1],
        ):
            return await reg_service.registration_service.create_registration(session, **payload)

    async def test_boosty_nick_reaches_the_column(self) -> None:
        registration = await self._create()

        assert registration.boosty_nick == "player_boosty"

    async def test_the_other_handles_still_land(self) -> None:
        registration = await self._create()

        assert registration.battle_tag == "Player#1234"
        assert registration.discord_nick == "player"
        assert registration.twitch_nick == "player_tv"

    async def test_custom_field_answers_reach_the_json_column(self) -> None:
        registration = await self._create(custom_fields={"vk": "vk.com/player"})

        assert registration.custom_fields_json == {"vk": "vk.com/player"}

    def test_every_create_field_is_a_writer_parameter(self) -> None:
        """Parity guard for the whole class of bug ``boosty_nick`` belonged to."""
        # ``roles`` is written as its own normalized rows by
        # submit_public_registration, not as a column on this call.
        written_elsewhere = {"roles"}
        parameters = set(inspect.signature(reg_service.registration_service.create_registration).parameters)

        missing = set(RegistrationCreate.model_fields) - written_elsewhere - parameters

        assert missing == set(), f"RegistrationCreate fields no writer accepts: {sorted(missing)}"


class TestSelfUpdateColumnMapping(IsolatedAsyncioTestCase):
    def _registration(self, **kwargs: Any) -> models.BalancerRegistration:
        return models.BalancerRegistration(id=1, tournament_id=7, status="pending", **kwargs)

    async def test_custom_fields_land_in_the_json_column(self) -> None:
        registration = self._registration()

        await reg_service.registration_service.update_registration(
            _RecordingSession(), registration, custom_fields={"vk": "vk.com/player"}
        )

        assert registration.custom_fields_json == {"vk": "vk.com/player"}

    async def test_custom_fields_merge_with_the_stored_answers(self) -> None:
        """``_validate_custom_field`` skips definitions a partial body omits, so
        a subset is a legal PATCH -- replacing wholesale would wipe the rest."""
        registration = self._registration(custom_fields_json={"vk": "old", "tg": "kept"})

        await reg_service.registration_service.update_registration(
            _RecordingSession(), registration, custom_fields={"vk": "new"}
        )

        assert registration.custom_fields_json == {"vk": "new", "tg": "kept"}

    async def test_battle_tag_is_cleaned_and_normalized(self) -> None:
        registration = self._registration()

        await reg_service.registration_service.update_registration(
            _RecordingSession(), registration, battle_tag="Player # 1234"
        )

        assert registration.battle_tag == "Player#1234"
        assert registration.battle_tag_normalized == "player#1234"

    async def test_an_unmapped_field_raises_instead_of_vanishing(self) -> None:
        with self.assertRaises(ValueError):
            await reg_service.registration_service.update_registration(
                _RecordingSession(), self._registration(), primary_role="tank"
            )

    def test_every_update_field_is_mapped_to_a_column(self) -> None:
        unmapped = set(RegistrationUpdate.model_fields) - set(reg_service._SELF_UPDATE_COLUMNS)

        assert unmapped == set(), f"RegistrationUpdate fields with no column: {sorted(unmapped)}"

    def test_every_mapped_column_exists_on_the_model(self) -> None:
        """The mapping is only worth having if it is checked against the mapper."""
        mapped = set(models.BalancerRegistration.__mapper__.columns.keys())

        assert set(reg_service._SELF_UPDATE_COLUMNS.values()) <= mapped


class TestManualCreateHonorsTheEditor(IsolatedAsyncioTestCase):
    async def _create(self, **overrides: Any) -> tuple[models.BalancerRegistration, list[str]]:
        session = _RecordingSession()
        events: list[str] = []

        async def _approved(*_args: Any, **_kwargs: Any) -> None:
            events.append("approved")

        payload: dict[str, Any] = {
            "tournament_id": 7,
            "display_name": None,
            "battle_tag": "Player#1234",
            "smurf_tags_json": None,
            "discord_nick": None,
            "twitch_nick": None,
            "notes": None,
            "admin_notes": None,
            "roles": [],
            **overrides,
        }
        patches = _wp_patches()
        with (
            mock.patch.object(reg_lifecycle.lifecycle_service, "ensure_unique_battle_tag", _noop),
            mock.patch.object(
                reg_lifecycle.lifecycle_service.common, "get_registration_form", mock.AsyncMock(return_value=None)
            ),
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

    async def test_custom_field_answers_are_written(self) -> None:
        registration, _ = await self._create(custom_fields_json={"vk": "vk.com/player"})

        assert registration.custom_fields_json == {"vk": "vk.com/player"}

    def test_every_admin_create_field_is_a_writer_parameter(self) -> None:
        # ``roles`` arrives as dicts under the same name; ``auth_user_id`` too.
        renamed = {"status": "status_value", "balancer_status": "balancer_status_value"}
        parameters = set(inspect.signature(reg_lifecycle.lifecycle_service.create_manual_registration).parameters)

        missing = {
            renamed.get(name, name) for name in schemas.BalancerRegistrationCreateRequest.model_fields
        } - parameters

        assert missing == set(), f"create request fields no writer accepts: {sorted(missing)}"


class TestAdminProfileUpdateCustomFields(IsolatedAsyncioTestCase):
    async def _update(self, registration: models.BalancerRegistration, **overrides: Any) -> None:
        payload: dict[str, Any] = {
            "display_name": None,
            "battle_tag": None,
            "smurf_tags_json": None,
            "discord_nick": None,
            "twitch_nick": None,
            "notes": None,
            "admin_notes": None,
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
                reg_lifecycle.lifecycle_service.common, "_register_registration_changed", mock.AsyncMock()
            ),
        ):
            await reg_lifecycle.lifecycle_service.update_registration_profile(
                _RecordingSession(), registration.id, **payload
            )

    async def test_custom_fields_replace_the_stored_answers(self) -> None:
        """The admin editor renders every definition on the form, so its payload
        is the complete answer set -- clearing a field there must clear it here."""
        registration = models.BalancerRegistration(
            id=1, tournament_id=7, status="approved", custom_fields_json={"vk": "old", "tg": "dropped"}
        )

        await self._update(registration, custom_fields_json={"vk": "new"})

        assert registration.custom_fields_json == {"vk": "new"}

    async def test_omitting_them_leaves_the_stored_answers_alone(self) -> None:
        registration = models.BalancerRegistration(
            id=1, tournament_id=7, status="approved", custom_fields_json={"vk": "kept"}
        )

        await self._update(registration)

        assert registration.custom_fields_json == {"vk": "kept"}

    def test_every_admin_update_field_is_a_writer_parameter(self) -> None:
        renamed = {"status": "status_value", "balancer_status": "balancer_status_value"}
        parameters = set(inspect.signature(reg_lifecycle.lifecycle_service.update_registration_profile).parameters)

        missing = {
            renamed.get(name, name) for name in schemas.BalancerRegistrationUpdateRequest.model_fields
        } - parameters

        assert missing == set(), f"update request fields no writer accepts: {sorted(missing)}"


class TestAdminProfileUpdateAutoManagedBalancerStatus(IsolatedAsyncioTestCase):
    """``ready``/``incomplete`` are derived from role ranks. The admin edit
    form always round-trips the registration's current ``balancer_status``,
    so resaving a row that already reads one of these two must recompute --
    not 400, the way an explicit ``set_balancer_status`` pin correctly does.
    """

    async def _update(self, registration: models.BalancerRegistration, **overrides: Any) -> None:
        payload: dict[str, Any] = {
            "display_name": None,
            "battle_tag": None,
            "smurf_tags_json": None,
            "discord_nick": None,
            "twitch_nick": None,
            "notes": None,
            "admin_notes": None,
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
                reg_lifecycle.lifecycle_service.common, "_register_registration_changed", mock.AsyncMock()
            ),
            mock.patch.object(roster_engine, "for_tournament", _rosters),
        ):
            await reg_lifecycle.lifecycle_service.update_registration_profile(
                _RecordingSession(), registration.id, **payload
            )

    async def test_resaving_a_ready_registration_recomputes_instead_of_rejecting(self) -> None:
        registration = models.BalancerRegistration(id=1, tournament_id=7, status="approved", balancer_status="ready")
        registration.roles = [models.BalancerRegistrationRole(role="tank", is_active=True, rank_value=2500)]

        # Must not raise -- the old behaviour 400ed on this exact resend.
        await self._update(registration, balancer_status_value="ready")

        assert registration.balancer_status == "ready"

    async def test_resaving_an_incomplete_registration_stays_incomplete(self) -> None:
        registration = models.BalancerRegistration(
            id=1, tournament_id=7, status="approved", balancer_status="incomplete"
        )
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
