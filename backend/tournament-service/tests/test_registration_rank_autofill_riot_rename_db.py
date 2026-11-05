"""A LoL registration keeps its native autofill rank after its Riot ID is renamed (final-review fix, Task 8).

The registration stores the handle it was submitted with; the LoL collector follows a Riot ID change onto
``players.social_account``. The stored handle then no longer names the account, but the registration's member still
names the player, and the player's Solo/Duo rank is still the ``ow`` stage's candidate.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.models.platform.outbox import EventOutbox
from shared.services.ontology import project_disciplines
from shared.services.social_identity import social_identity_service
from shared.testing import create_test_async_engine
from shared.testing.factories import registration_node
from src.services.registration.lifecycle import lifecycle_service
from src.services.registration.rank_autofill import rank_autofill_service


def _snapshot(account: models.SocialAccount, queue: str, division: str, tier: int, value: int, at: datetime):
    return models.UserRankSnapshot(
        discipline="lol",
        user_id=account.user_id,
        social_account_id=account.id,
        handle=account.username,
        queue=queue,
        division=division,
        tier=tier,
        lp=50,
        wins=10,
        losses=5,
        rank_value=value,
        is_ranked=True,
        captured_at=at,
        source="scheduled",
    )


class RiotRenameAutofillTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tag = uuid.uuid4().hex[:10]
        tag = f"riot-rename-{self.tag}"
        async with self.Session() as s:
            await project_disciplines(s)
            workspace = models.Workspace(slug=tag, name=tag, disciplines_enabled=["overwatch", "lol"])
            s.add(workspace)
            await s.flush()
            grid = models.DivisionGrid(workspace_id=workspace.id, discipline="lol", slug=tag, name=tag)
            s.add(grid)
            await s.flush()
            version = models.DivisionGridVersion(grid_id=grid.id, version=1, label="v1", status="published")
            s.add(version)
            await s.flush()
            # No native ranges: a native value lands by containment, so Solo (1650) and Flex (2700) part ways.
            for order, (slug, low, high) in enumerate((("low", 0, 1599), ("plat", 1600, 1699), ("high", 1700, None))):
                s.add(
                    models.DivisionGridTier(
                        version_id=version.id,
                        slug=slug,
                        number=order + 1,
                        name=slug,
                        sort_order=order,
                        rank_min=low,
                        rank_max=high,
                        icon_url=f"/{slug}.png",
                    )
                )
            tournament = models.Tournament(
                workspace_id=workspace.id,
                name=tag,
                slug=tag,
                discipline="lol",
                division_grid_version_id=version.id,
                start_date=datetime.now(UTC),
                end_date=datetime.now(UTC),
            )
            s.add(tournament)
            await s.flush()
            self.node_id = await registration_node(s, tournament.id)
            await s.commit()
            self.workspace_id, self.tournament_id = workspace.id, tournament.id

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            player_ids = set(
                await s.scalars(
                    sa.select(models.WorkspaceMember.player_id).where(
                        models.WorkspaceMember.workspace_id == self.workspace_id
                    )
                )
            )
            await s.execute(
                sa.delete(EventOutbox).where(
                    EventOutbox.payload_json["tournament_id"].as_string() == str(self.tournament_id)
                )
            )
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.workspace_id))
            await s.execute(sa.delete(models.User).where(models.User.id.in_(player_ids)))
            await s.commit()
        await self.engine.dispose()

    async def test_a_renamed_riot_id_still_fills_the_players_solo_rank(self) -> None:
        old, new = f"Old{self.tag}#EUW", f"New{self.tag}#EUW"
        async with self.Session() as s:
            entry = await lifecycle_service.create_manual_registration(
                s,
                self.node_id,
                display_name=None,
                admin_notes=None,
                answers={"identity_riot": [old]},
                roles=[
                    {
                        "role": {"dimension": "position", "role": "mid"},
                        "priority": 0,
                        "is_primary": True,
                        "rank_value": None,
                        "is_active": True,
                    }
                ],
            )
            registration_id, player_id = entry.registration_id, entry.registration.workspace_member.player_id
            account = await s.scalar(
                sa.select(models.SocialAccount).where(
                    models.SocialAccount.user_id == player_id, models.SocialAccount.provider == "riot"
                )
            )
            assert account.username == old
            # What the LoL collector does when Riot reports a new Riot ID (``collector._rename``).
            account = await social_identity_service.update(s, account_id=account.id, user_id=player_id, username=new)
            now = datetime.now(UTC)
            s.add_all(
                [
                    models.RankAccountState(
                        discipline="lol", social_account_id=account.id, handle=new, last_success_at=now
                    ),
                    _snapshot(account, "solo", "PLATINUM", 2, 1650, now - timedelta(hours=1)),
                    _snapshot(account, "flex", "DIAMOND", 1, 2700, now - timedelta(hours=1)),
                ]
            )
            await s.commit()

        async with self.Session() as s:
            loaded = await lifecycle_service.get_registration_by_id(s, registration_id)
            assert [identity.handle for identity in loaded.identities] == [old]
            result = await rank_autofill_service.autofill_registration_ranks_from_parsed(
                s, self.tournament_id, self.node_id, registration_ids=[registration_id]
            )

        [row] = result["players"]
        assert (row["status"], row["reason"]) == ("will_update", None)
        [mid] = row["roles"]
        assert (mid["action"], mid["parsed_rank_value"], mid["used_source"]) == ("set", 1600, "ow")
