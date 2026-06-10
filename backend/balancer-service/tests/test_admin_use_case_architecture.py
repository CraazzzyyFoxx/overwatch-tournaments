from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src.application.admin.background_use_cases import (  # noqa: E402
    SyncDueRegistrationSheets,
)
from src.application.admin.balancer_use_cases import (  # noqa: E402
    ExportBalance,
    SaveBalance,
    SyncTournamentSheet,
)
from src.application.admin.registration_status_use_cases import (  # noqa: E402
    CreateCustomStatus,
    ListStatusCatalog,
)
from src.application.admin.registration_use_cases import (  # noqa: E402
    CreateRegistration,
    UpdateRegistration,
)


class RegistrationAdminUseCaseTests(IsolatedAsyncioTestCase):
    async def test_create_registration_resolves_workspace_before_service_call(self) -> None:
        captured = {}

        class FakeRegistrationService:
            async def ensure_tournament_exists(self, session, tournament_id: int):
                return SimpleNamespace(workspace_id=91)

            async def create_manual_registration(self, session, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(id=12, workspace_id=kwargs["workspace_id"])

        use_case = CreateRegistration(registration_service=FakeRegistrationService())
        result = await use_case.execute(
            session=object(),
            tournament_id=77,
            payload=SimpleNamespace(
                display_name="Player",
                battle_tag="Player#1234",
                smurf_tags_json=[],
                discord_nick=None,
                twitch_nick=None,
                stream_pov=False,
                notes=None,
                admin_notes=None,
                roles=[],
            ),
        )

        self.assertEqual(result.id, 12)
        self.assertEqual(captured["workspace_id"], 91)
        self.assertEqual(captured["tournament_id"], 77)

    async def test_update_registration_passes_profile_fields_to_service(self) -> None:
        captured = {}

        class FakeRegistrationService:
            async def update_registration_profile(self, session, registration_id: int, **kwargs):
                captured["registration_id"] = registration_id
                captured.update(kwargs)
                return SimpleNamespace(id=registration_id)

        use_case = UpdateRegistration(registration_service=FakeRegistrationService())
        result = await use_case.execute(
            session=object(),
            registration_id=33,
            payload=SimpleNamespace(
                display_name="Updated",
                battle_tag="Updated#1234",
                smurf_tags_json=[],
                discord_nick="discord",
                twitch_nick="twitch",
                stream_pov=True,
                notes="notes",
                admin_notes="admin",
                status="approved",
                balancer_status="ready",
                roles=[SimpleNamespace(model_dump=lambda: {"role": "tank"})],
            ),
        )

        self.assertEqual(result.id, 33)
        self.assertEqual(captured["registration_id"], 33)
        self.assertEqual(captured["balancer_status_value"], "ready")
        self.assertEqual(captured["roles"], [{"role": "tank"}])


class BalancerAdminUseCaseTests(IsolatedAsyncioTestCase):
    async def test_sync_tournament_sheet_delegates_to_registration_service(self) -> None:
        class FakeRegistrationService:
            async def sync_google_sheet_feed(self, session, tournament_id: int):
                return ("feed", 1, 2, 3, 4)

        use_case = SyncTournamentSheet(registration_service=FakeRegistrationService())
        result = await use_case.execute(session=object(), tournament_id=66)

        self.assertEqual(result, ("feed", 1, 2, 3, 4))

    async def test_save_balance_delegates_to_balance_service(self) -> None:
        class FakeBalancerService:
            async def save_balance(self, session, tournament_id: int, data, user):
                return SimpleNamespace(id=99, tournament_id=tournament_id, saved_by=user.id)

        use_case = SaveBalance(balancer_service=FakeBalancerService())
        result = await use_case.execute(
            session=object(),
            tournament_id=12,
            payload=SimpleNamespace(result_json={"teams": []}),
            user=SimpleNamespace(id=7),
        )

        self.assertEqual(result.id, 99)
        self.assertEqual(result.saved_by, 7)

    async def test_export_balance_delegates_to_balance_service(self) -> None:
        class FakeBalancerService:
            async def export_balance(self, session, balance_id: int):
                return (SimpleNamespace(id=balance_id), 5, 6)

        use_case = ExportBalance(balancer_service=FakeBalancerService())
        result = await use_case.execute(session=object(), balance_id=44)

        self.assertEqual(result[0].id, 44)
        self.assertEqual(result[1:], (5, 6))

    async def test_sync_due_registration_sheets_uses_session_factory(self) -> None:
        marker = object()

        class FakeRegistrationService:
            async def sync_due_google_sheet_feeds(self, session_factory):
                self.session_factory = session_factory
                return [{"status": "success"}]

        service = FakeRegistrationService()
        use_case = SyncDueRegistrationSheets(registration_service=service)
        result = await use_case.execute(session_factory=marker)

        self.assertEqual(result, [{"status": "success"}])
        self.assertIs(service.session_factory, marker)


class RegistrationStatusUseCaseTests(IsolatedAsyncioTestCase):
    async def test_list_status_catalog_delegates_to_status_service(self) -> None:
        class FakeStatusService:
            async def list_status_catalog(self, session, workspace_id: int):
                return [SimpleNamespace(id=1, workspace_id=workspace_id)]

        use_case = ListStatusCatalog(status_service=FakeStatusService())
        result = await use_case.execute(session=object(), workspace_id=8)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].workspace_id, 8)

    async def test_create_custom_status_delegates_to_status_service(self) -> None:
        captured = {}

        class FakeStatusService:
            async def create_custom_status(self, session, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(id=13, workspace_id=kwargs["workspace_id"])

        use_case = CreateCustomStatus(status_service=FakeStatusService())
        payload = SimpleNamespace(
            scope="registration",
            icon_slug="sparkles",
            icon_color="#fff",
            name="Featured",
            description="Featured player",
        )
        result = await use_case.execute(session=object(), workspace_id=4, payload=payload)

        self.assertEqual(result.id, 13)
        self.assertEqual(captured["workspace_id"], 4)
        self.assertEqual(captured["name"], "Featured")
