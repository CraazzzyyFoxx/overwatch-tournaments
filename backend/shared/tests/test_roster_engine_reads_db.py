"""``for_tournament`` reads plain Core rows; ``resolve`` reads the ORM rows a caller loaded. Both must agree."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.disciplines import rated_role_codes
from shared.repository import CatalogRoleRepository
from shared.services.roster import registration_load_options, roster_engine
from shared.testing import create_test_async_engine
from shared.testing.cache import configure_test_cache


class RosterEngineReadsTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        configure_test_cache()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"rer-{uuid.uuid4().hex[:12]}"
        catalog = CatalogRoleRepository()
        async with self.Session() as s:
            home, foreign = models.Workspace(slug=tag, name=tag), models.Workspace(slug=f"{tag}-b", name=f"{tag}-b")
            s.add_all([home, foreign])
            await s.flush()
            self.workspace_ids = (home.id, foreign.id)
            tank = await catalog.resolve(s, discipline="overwatch", workspace_id=None, dimension=None, code="tank")
            s.add(
                models.CatalogRole(
                    dimension_id=tank.dimension_id,
                    workspace_id=home.id,
                    parent_role_id=tank.id,
                    code="tank_main",
                    name="Main Tank",
                )
            )
            await s.flush()
            roles = await catalog.rated_rows(s, discipline="overwatch", workspace_id=home.id)
            heroes = [
                models.CatalogEntity(discipline="overwatch", kind="character", slug=f"{tag}-h{i}", name=f"H{i}")
                for i in range(2)
            ]
            auth = models.AuthUser(email=f"{tag}@test.local", username=tag)
            s.add_all([*heroes, auth])
            await s.flush()
            self.hero_ids = [hero.id for hero in heroes]
            self.auth_user_id = auth.id
            users = [models.User(name=f"{tag}-{i}", auth_user_id=auth.id if i == 0 else None) for i in range(4)]
            s.add_all(users)
            await s.flush()
            self.user_ids = [user.id for user in users]
            members = [
                models.WorkspaceMember(workspace_id=home.id if i < 3 else foreign.id, player_id=users[i].id)
                for i in range(4)
            ]
            s.add_all(members)
            await s.flush()
            tournament = models.Tournament(workspace_id=home.id, name=tag, slug=tag)
            s.add(tournament)
            await s.flush()
            self.tournament_id = tournament.id

            def registration(**values) -> models.Registration:
                values.setdefault("balancer_status", "ready")
                return models.Registration(tournament_id=tournament.id, status="approved", **values)

            def role(code: str, priority: int, rank: int | None, **values) -> models.RegistrationRole:
                leaf = roles[code]
                return models.RegistrationRole(
                    catalog_role=leaf, dimension_id=leaf.dimension_id, priority=priority, rank_value=rank, **values
                )

            def identity(provider: str, position: int, handle: str) -> models.RegistrationIdentity:
                return models.RegistrationIdentity(
                    provider=provider, position=position, handle=handle, handle_normalized=handle.lower()
                )

            main_tank = role("tank_main", 0, 3000, is_primary=True)
            # Inserted out of order: a role's top characters are read in their priority order.
            main_tank.hero_entries = [
                models.RegistrationRoleEntity(entity_id=heroes[1].id, priority=1),
                models.RegistrationRoleEntity(entity_id=heroes[0].id, priority=0),
            ]
            registrations = [
                registration(
                    workspace_member_id=members[0].id,
                    display_name="One",
                    public_notes="public",
                    admin_notes="admin",
                    custom_fields_json={"vk": "vk.com/one"},
                    checked_in=True,
                    stream_pov=True,
                    roles=[main_tank, role("support", 1, None)],
                    identities=[
                        identity("battlenet", 1, "Alt#2222"),
                        identity("battlenet", 0, "One#1111"),
                        identity("discord", 0, "one"),
                    ],
                ),
                registration(
                    workspace_member_id=members[1].id,
                    roles=[role("damage", 0, 2500, is_active=False), role("support", 1, 2000, is_primary=True)],
                    identities=[identity("battlenet", 0, "Two#1111")],
                ),
                registration(balancer_status="excluded", roles=[role("damage", 0, 2400)]),
                # A member of another workspace: the home workspace's canon must not reach it.
                registration(workspace_member_id=members[3].id, roles=[role("tank", 0, None)]),
                registration(
                    workspace_member_id=members[2].id, deleted_at=datetime.now(UTC), roles=[role("tank", 0, 2200)]
                ),
            ]
            s.add_all(registrations)
            s.add_all(
                models.MemberRank(
                    workspace_id=home.id,
                    workspace_member_id=member.id,
                    dimension_id=roles[code].dimension_id,
                    role_id=roles[code].id,
                    rank_value=rank,
                )
                for member, code, rank in ((members[0], "support", 2700), (members[3], "tank", 3500))
            )
            await s.commit()
            self.ids = [registration.id for registration in registrations]

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.Tournament).where(models.Tournament.id == self.tournament_id))
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id.in_(self.workspace_ids)))
            await s.execute(sa.delete(models.User).where(models.User.id.in_(self.user_ids)))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id == self.auth_user_id))
            await s.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.id.in_(self.hero_ids)))
            await s.commit()
        await self.engine.dispose()

    async def test_for_tournament_reads_what_resolve_reads_off_loaded_rows(self) -> None:
        one, two, excluded, foreign, deleted = self.ids
        for kwargs, expected in (
            ({}, {one, two, excluded, foreign}),
            ({"pool_only": True}, {one, two, foreign}),
            ({"registration_ids": self.ids, "include_deleted": True}, set(self.ids)),
        ):
            async with self.Session() as s:
                rosters = await roster_engine.for_tournament(s, self.tournament_id, **kwargs)
            async with self.Session() as s:
                rows = await s.scalars(
                    sa.select(models.Registration)
                    .where(models.Registration.id.in_(rosters))
                    .options(*registration_load_options())
                )
                loaded = await roster_engine.resolve(
                    s,
                    list(rows),
                    workspace_id=self.workspace_ids[0],
                    tournament_id=self.tournament_id,
                    discipline="overwatch",
                    role_codes=rated_role_codes("overwatch"),
                )
            assert set(rosters) == expected
            assert rosters == loaded

        first = rosters[one]
        tank = next(entry for entry in first.roles if entry.role == "tank")
        assert (tank.subrole, [character.id for character in tank.top_characters]) == ("tank_main", self.hero_ids)
        assert (first.rank_on("support"), first.role_sources["support"]) == (2700, "workspace")
        assert (first.auth_user_id, first.identity.handle, first.additional_handles) == (
            self.auth_user_id,
            "One#1111",
            ("Alt#2222",),
        )
        assert rosters[foreign].rank_on("tank") is None

    async def test_pool_ids_keep_only_the_balancer_pool(self) -> None:
        one, two, _excluded, foreign, _deleted = self.ids
        async with self.Session() as s:
            assert await roster_engine.pool_ids(s, self.tournament_id, self.ids) == {one, two, foreign}
