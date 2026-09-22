"""Who may rewrite a registration's answers, and what the ``reserve`` answer is.

Two rules meet here and both are pinned:

* **Editing is an allowlist.** ``FormField.editable`` is off by default, so a
  form nobody re-opened in the builder keeps every answer frozen. Two keys are
  floored regardless of the flag, and one exception (a question never answered)
  opens in the other direction.
* **``reserve`` is the registrant's own availability note** -- "I play, and you
  can call me in if somebody drops or I cannot make the start". Nothing writes
  it on their behalf and nothing acts on it: a late sign-up is marked late, and
  a pool sweep enrols an on-call player like anybody else.

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase, TestCase, mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core.enums import TournamentStatus  # noqa: E402
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.domain.forms import FormField, FormSchema, FormSection  # noqa: E402
from shared.services.roster import roster_engine  # noqa: E402
from src import models  # noqa: E402
from src.services.registration import service as reg_service  # noqa: E402
from src.services.registration.answers import answer_service  # noqa: E402
from src.services.registration.rank_autofill import _rank_autofill_balancer_addition  # noqa: E402
from src.services.registration.self_edit import self_edit_policy  # noqa: E402

NOW = datetime.now(UTC)


def _schema(*, editable_keys: frozenset[str] = frozenset()) -> FormSchema:
    """The three floored keys plus two ordinary ones, each opened or not."""
    keys = (("battle_tag", "builtin"), ("roles", "builtin"), ("reserve", "builtin"), ("public_notes", "builtin"))
    return FormSchema(
        sections=[
            FormSection(
                key="all",
                fields=[
                    *(
                        FormField(key=key, kind=kind, editable=key in editable_keys)  # type: ignore[arg-type]
                        for key, kind in keys
                    ),
                    FormField(key="vk", kind="text", label="VK", editable="vk" in editable_keys),
                ],
            )
        ]
    )


def _tournament(*, ends_in: timedelta | None = timedelta(days=1)) -> models.Tournament:
    """A tournament whose REGISTRATION window ends ``ends_in`` from now.

    A negative delta with ``allow_late_registration`` is the late case: open, and
    every sign-up in it is a reserve.
    """
    tournament = models.Tournament(id=7, status=TournamentStatus.REGISTRATION, allow_late_registration=True)
    tournament.phase_schedule = [
        models.TournamentPhaseSchedule(
            tournament_id=7,
            status=TournamentStatus.REGISTRATION,
            starts_at=NOW - timedelta(days=10),
            ends_at=None if ends_in is None else NOW + ends_in,
        )
    ]
    return tournament


def _registration(**kwargs: Any) -> models.BalancerRegistration:
    defaults: dict[str, Any] = {
        "id": 1,
        "tournament_id": 7,
        "status": "approved",
        "balancer_status": "not_in_balancer",
        "submitted_at": NOW - timedelta(days=2),
        "battle_tag": "Player#1234",
        "public_notes": "hi",
    }
    return models.BalancerRegistration(**{**defaults, **kwargs})


class PolicyTests(TestCase):
    def test_only_the_questions_the_organizer_opened_are_writable(self) -> None:
        policy = self_edit_policy(_registration(), _tournament(), _schema(editable_keys=frozenset({"public_notes"})))

        assert policy.can_edit is True
        assert "public_notes" in policy.writable_keys
        assert "battle_tag" not in policy.writable_keys

    def test_a_question_this_row_never_answered_is_writable_anyway(self) -> None:
        """Otherwise a new question leaves everyone stuck on a stale version they
        cannot clear -- the normal case once the flag defaults to closed."""
        policy = self_edit_policy(_registration(), _tournament(), _schema())

        assert "vk" in policy.writable_keys
        assert "public_notes" not in policy.writable_keys

    def test_a_form_with_nothing_open_cannot_be_edited_at_all(self) -> None:
        answered = _registration(custom_fields_json={"vk": "x"}, is_reserve=False)
        answered.roles = [models.BalancerRegistrationRole(role="tank", is_primary=True, priority=0)]
        # Every schema key now has a stored answer, so the "never answered"
        # exception cannot open anything: this is the whole-form kill switch.
        policy = self_edit_policy(answered, _tournament(), _schema())

        assert policy.can_edit is False
        assert policy.reason == "nothing_editable"

    def test_the_window_closes_editing_too(self) -> None:
        closed = models.Tournament(id=7, status=TournamentStatus.REGISTRATION, allow_late_registration=False)
        closed.phase_schedule = [
            models.TournamentPhaseSchedule(
                tournament_id=7,
                status=TournamentStatus.REGISTRATION,
                starts_at=NOW - timedelta(days=10),
                ends_at=NOW - timedelta(days=1),
            )
        ]

        policy = self_edit_policy(_registration(), closed, _schema(editable_keys=frozenset({"public_notes"})))

        assert (policy.can_edit, policy.reason) == (False, "window_closed")

    def test_check_in_freezes_the_entry(self) -> None:
        policy = self_edit_policy(
            _registration(checked_in=True), _tournament(), _schema(editable_keys=frozenset({"public_notes"}))
        )

        assert (policy.can_edit, policy.reason) == (False, "checked_in")

    def test_a_settled_registration_is_over(self) -> None:
        for status in ("withdrawn", "rejected"):
            policy = self_edit_policy(
                _registration(status=status), _tournament(), _schema(editable_keys=frozenset({"public_notes"}))
            )
            assert (policy.can_edit, policy.reason) == (False, "status_locked"), status

    def test_the_battle_tag_re_locks_once_the_row_was_reviewed(self) -> None:
        """It is the row's identity anchor: the unique index, the member link and
        every inherited rank layer are read through it."""
        opened = _schema(editable_keys=frozenset({"battle_tag", "public_notes"}))

        assert "battle_tag" in self_edit_policy(_registration(), _tournament(), opened).writable_keys
        assert "battle_tag" not in self_edit_policy(_registration(reviewed_at=NOW), _tournament(), opened).writable_keys

    def test_roles_re_lock_once_the_balancer_has_them(self) -> None:
        opened = _schema(editable_keys=frozenset({"roles"}))

        assert "roles" in self_edit_policy(_registration(), _tournament(), opened).writable_keys
        assert (
            "roles" not in self_edit_policy(_registration(balancer_status="ready"), _tournament(), opened).writable_keys
        )
        assert (
            "roles" not in self_edit_policy(_registration(registration_team_id=3), _tournament(), opened).writable_keys
        )

    def test_a_late_registrant_still_owns_their_on_call_answer(self) -> None:
        """The schedule marks the entry late; it never speaks for the player.
        Locking this was the counterpart of the write that forced it on."""
        opened = _schema(editable_keys=frozenset({"reserve"}))
        late = _tournament(ends_in=-timedelta(days=3))

        assert "reserve" in self_edit_policy(_registration(), _tournament(), opened).writable_keys
        assert "reserve" in self_edit_policy(_registration(), late, opened).writable_keys


class _RecordingSession:
    def __init__(self) -> None:
        self.info: dict = {}
        self.added: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        return None

    async def scalar(self, *_args: Any, **_kwargs: Any) -> Any:
        return 42

    def begin_nested(self) -> Any:
        return _Savepoint()


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _no_rosters(*_args: Any, **_kwargs: Any) -> dict:
    return {}


class WritePathTests(IsolatedAsyncioTestCase):
    async def _update(self, registration: models.BalancerRegistration, values: dict[str, Any], schema: FormSchema):
        return await reg_service.registration_service.update_registration(
            _RecordingSession(),
            registration,
            tournament=_tournament(),
            values=values,
            schema=schema,
            form_version_id=5,
        )

    async def test_an_opened_answer_is_written(self) -> None:
        registration = _registration()

        await self._update(registration, {"public_notes": "new"}, _schema(editable_keys=frozenset({"public_notes"})))

        assert registration.public_notes == "new"

    async def test_a_frozen_answer_is_refused_under_its_own_key(self) -> None:
        """Reported per key so the message lands on the control the registrant
        just touched, not as one opaque toast."""
        with self.assertRaises(HTTPException) as caught:
            await self._update(
                _registration(), {"battle_tag": "Other#1"}, _schema(editable_keys=frozenset({"public_notes"}))
            )

        assert caught.exception.status_code == 409
        assert [(item["field"], item["code"]) for item in caught.exception.detail] == [("battle_tag", "locked")]

    async def test_a_late_sign_up_answers_nothing_on_the_registrants_behalf(self) -> None:
        """The schedule marks the entry late; it does not tick a question for
        them. Writing ``is_reserve`` here made the roster claim the player had
        volunteered to be called in when they never said so."""
        session = _RecordingSession()
        with (
            mock.patch.object(reg_service.registration_service, "ensure_player_identity", _noop),
            mock.patch.object(reg_service, "assign_workspace_system_role", _noop),
            mock.patch.object(reg_service, "enqueue_registration_approved", _noop),
            mock.patch.object(roster_engine, "for_tournament", _no_rosters),
        ):
            registration = await reg_service.registration_service.create_registration(
                session,
                tournament_id=7,
                workspace_id=1,
                auth_user_id=None,
                values={"battle_tag": "Player#1234", "reserve": False},
                schema=_schema(),
                form_version_id=3,
            )

        assert registration.is_reserve is False

    async def test_an_on_time_sign_up_keeps_its_own_answer(self) -> None:
        session = _RecordingSession()
        with (
            mock.patch.object(reg_service.registration_service, "ensure_player_identity", _noop),
            mock.patch.object(reg_service, "assign_workspace_system_role", _noop),
            mock.patch.object(reg_service, "enqueue_registration_approved", _noop),
            mock.patch.object(roster_engine, "for_tournament", _no_rosters),
        ):
            registration = await reg_service.registration_service.create_registration(
                session,
                tournament_id=7,
                workspace_id=1,
                auth_user_id=None,
                values={"battle_tag": "Player#1234", "reserve": True},
                schema=_schema(),
                form_version_id=3,
            )

        assert registration.is_reserve is True
        assert answer_service.answers_of(registration)["reserve"] is True


class PoolSweepTests(TestCase):
    def test_the_on_call_answer_changes_nothing_about_a_sweep(self) -> None:
        """The answer says "you can ring me", not "leave me out": holding these
        rows back from the pool was the whole misreading. Same inputs, same
        verdict, whichever way the switch was set."""
        on_call = _rank_autofill_balancer_addition(_registration(is_reserve=True), [], add_to_balancer=True)
        plain = _rank_autofill_balancer_addition(_registration(is_reserve=False), [], add_to_balancer=True)

        assert on_call == plain
