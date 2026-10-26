"""Admin tournament writes on the test Postgres: link invalidation, slug
generation around retired slugs, and the Challonge link fetch running outside
any transaction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from shared import models
from shared.domain.tournament_slug import slugify
from shared.models.platform.audit import AuditLog
from shared.models.platform.realtime import WorkspaceEvent
from shared.services.audit import record_audit
from shared.services.realtime import INVALIDATION_EVENT_TYPE, Resource
from shared.services.tournament.slug import generate_unique_tournament_slug
from src import schemas
from src.services.admin import tournament as admin_tournament
from src.services.admin.tournament_link import tournament_link_service
from tests._encounter_layer import EncounterLayerCase


class TournamentLinkInvalidationTests(EncounterLayerCase):
    async def _detail_invalidations(self) -> int:
        async with self.Session() as s:
            payloads = (
                await s.scalars(
                    sa.select(WorkspaceEvent.payload).where(
                        WorkspaceEvent.tournament_id == self.tournament_id,
                        WorkspaceEvent.event_type == INVALIDATION_EVENT_TYPE,
                    )
                )
            ).all()
        return sum(Resource.TOURNAMENT_DETAIL.value in payload["resources"] for payload in payloads)

    async def test_create_update_and_deactivate_each_stale_the_cached_overview(self) -> None:
        async with self.Session() as s:
            link = await tournament_link_service.create_link(
                s,
                schemas.TournamentLinkCreate(
                    tournament_id=self.tournament_id, kind="discord", url="https://discord.gg/example"
                ),
            )
        self.assertEqual(1, await self._detail_invalidations())

        async with self.Session() as s:
            await tournament_link_service.update_link(s, link.id, schemas.TournamentLinkUpdate(label="Join us"))
        self.assertEqual(2, await self._detail_invalidations())

        async with self.Session() as s:
            await tournament_link_service.deactivate_link(s, link.id)
        self.assertEqual(3, await self._detail_invalidations())


class SlugGenerationTests(EncounterLayerCase):
    async def test_a_retired_slug_is_never_handed_out_again(self) -> None:
        name = f"Spring Cup {self.tournament_id}"
        base = slugify(name)
        async with self.Session() as s:
            s.add(models.TournamentSlugRedirect(old_slug=base, tournament_id=self.tournament_id))
            await s.flush()

            self.assertEqual(f"{base}-2", await generate_unique_tournament_slug(s, name))
            await s.rollback()


class ChallongeLinkFetchTests(EncounterLayerCase):
    async def test_the_fetch_runs_outside_a_transaction_and_keeps_the_staged_audit_row(self) -> None:
        seen: list[bool] = []
        action = f"test.challonge_link.{self.tournament_id}"

        async with self.Session() as s:

            async def fetch_tournament(slug: str) -> SimpleNamespace:
                seen.append(s.in_transaction())
                return SimpleNamespace(id=424242, url=slug)

            # The CRUD engine's shape: a permission read opens the transaction,
            # then the audit row is staged before the service runs.
            await s.get(models.Tournament, self.tournament_id)
            await record_audit(s, action=action, source="admin", workspace_id=self.workspace_id)
            with patch.object(admin_tournament.challonge_client, "fetch_tournament", fetch_tournament):
                await admin_tournament.tournament_service.update_tournament(
                    s, self.tournament_id, schemas.TournamentUpdate(challonge_slug="winter-cup")
                )

        self.assertEqual([False], seen)
        async with self.Session() as s:
            audit_rows = await s.scalar(
                sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action == action)
            )
            source = await s.scalar(
                sa.select(models.ChallongeSource).where(models.ChallongeSource.tournament_id == self.tournament_id)
            )
            # ``audit_log`` carries no foreign key, so the workspace teardown would leave it behind.
            await s.execute(sa.delete(AuditLog).where(AuditLog.action == action))
            await s.commit()
        self.assertEqual(1, audit_rows)
        self.assertEqual((424242, "winter-cup"), (source.challonge_tournament_id, source.slug))
