"""The whole registration-admin surface used to authorize every subject
against a single blanket ``team`` resource -- inherited verbatim from the old
FastAPI deps' ``require_registration_permission("team", ...)`` -- even though
the RBAC catalog has dedicated ``registration``/``registration_status``/
``registration_form``/``subscription`` resources (some, like
``registration.approve``/``reject``/``check_in``, exist for no other reason).
A role granted only ``registration.approve`` could not actually approve a
registration; a role granted ``team.create`` could delete one. This pins the
resource each subject now authorizes against, so the RBAC grid the catalog
describes matches what the handlers actually check.

Only ``regteam_*`` (operates on ``BalancerRegistrationTeam``, a real team
entity) keeps the ``team`` resource -- that mapping was already correct.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest import TestCase

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
TOURNAMENT_SERVICE_ROOT = REPO_BACKEND_ROOT / "tournament-service"
for candidate in (str(REPO_BACKEND_ROOT), str(TOURNAMENT_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.rpc import registration_admin  # noqa: E402


def _handler_source(subject: str) -> str:
    source = inspect.getsource(registration_admin)
    start = source.index(f'@broker.subscriber("{subject}")')
    end = source.index("return await _run(logger, op)", start)
    return source[start:end]


class RegistrationCtxDefaultTests(TestCase):
    def test_registration_ctx_now_defaults_to_the_registration_resource(self) -> None:
        source = inspect.getsource(registration_admin._registration_ctx)
        self.assertIn('resource: str = "registration"', source)


class DedicatedActionTests(TestCase):
    """The three catalog actions that exist for exactly one handler each."""

    def test_reg_approve_uses_the_approve_action(self) -> None:
        self.assertIn('_registration_ctx(session, data, "approve")', _handler_source("rpc.tournament.reg_approve"))

    def test_reg_reject_uses_the_reject_action(self) -> None:
        self.assertIn('_registration_ctx(session, data, "reject")', _handler_source("rpc.tournament.reg_reject"))

    def test_reg_check_in_uses_the_check_in_action(self) -> None:
        self.assertIn('_registration_ctx(session, data, "check_in")', _handler_source("rpc.tournament.reg_check_in"))

    def test_reg_bulk_approve_uses_the_approve_action_on_registration(self) -> None:
        source = _handler_source("rpc.tournament.reg_bulk_approve")
        self.assertIn('_tournament_ctx(session, data, "approve", resource="registration")', source)

    def test_reg_delete_uses_the_delete_action(self) -> None:
        self.assertIn('_registration_ctx(session, data, "delete")', _handler_source("rpc.tournament.reg_delete"))


class RegistrationFormResourceTests(TestCase):
    def test_form_get_and_upsert_use_the_registration_form_resource(self) -> None:
        self.assertIn('resource="registration_form"', _handler_source("rpc.tournament.reg_form_get"))
        self.assertIn('resource="registration_form"', _handler_source("rpc.tournament.reg_form_upsert"))


class RegistrationStatusResourceTests(TestCase):
    def test_every_regstatus_subject_uses_the_registration_status_resource(self) -> None:
        subjects = [
            "rpc.tournament.regstatus_catalog",
            "rpc.tournament.regstatus_list",
            "rpc.tournament.regstatus_create",
            "rpc.tournament.regstatus_update",
            "rpc.tournament.regstatus_delete",
            "rpc.tournament.regstatus_builtin_upsert",
            "rpc.tournament.regstatus_builtin_reset",
        ]
        for subject in subjects:
            with self.subTest(subject=subject):
                self.assertIn('resource="registration_status"', _handler_source(subject))

    def test_create_uses_the_real_create_action_not_update(self) -> None:
        """The catalog gives ``registration_status`` full CRUD; the handler
        that creates a new custom status must ask for ``create``, not the
        blanket ``update`` every ``team``-resource write used to share."""
        source = _handler_source("rpc.tournament.regstatus_create")
        self.assertIn('_workspace_ctx(data, "create", resource="registration_status")', source)

    def test_delete_uses_the_real_delete_action(self) -> None:
        source = _handler_source("rpc.tournament.regstatus_delete")
        self.assertIn('_workspace_ctx(data, "delete", resource="registration_status")', source)


class SubscriptionResourceTests(TestCase):
    def test_every_sub_subject_uses_the_subscription_resource(self) -> None:
        """Matches ``parser-service``'s own ``subscription.read``/``update`` gate
        on the same Twitch-subscription-verification feature area."""
        subjects = [
            "rpc.tournament.sub_config_list",
            "rpc.tournament.sub_config_upsert",
            "rpc.tournament.sub_requirement_get",
            "rpc.tournament.sub_requirement_upsert",
        ]
        for subject in subjects:
            with self.subTest(subject=subject):
                self.assertIn('resource="subscription"', _handler_source(subject))


class RegteamStaysOnTeamResourceTests(TestCase):
    """The one group where ``team`` was already the correct resource."""

    def test_regteam_subjects_do_not_declare_an_explicit_resource(self) -> None:
        """No ``resource=`` override means they still ride ``_tournament_ctx``'s
        ``team`` default -- unchanged by the migration."""
        subjects = [
            "rpc.tournament.regteam_list",
            "rpc.tournament.regteam_reject",
            "rpc.tournament.regteam_invite_revoke_admin",
            "rpc.tournament.regteam_invite_cap_reset",
            "rpc.tournament.regteam_invite_history",
            "rpc.tournament.regteam_rename_admin",
            "rpc.tournament.regteam_unlock",
            "rpc.tournament.regteam_admission",
            "rpc.tournament.regteam_notes",
            "rpc.tournament.regteam_place_admin",
            "rpc.tournament.regteam_attach_admin",
        ]
        for subject in subjects:
            with self.subTest(subject=subject):
                self.assertNotIn("resource=", _handler_source(subject))
