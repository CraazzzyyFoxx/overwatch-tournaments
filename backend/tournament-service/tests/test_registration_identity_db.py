"""Optional writers and provider-scoped sheet/team identities against PostgreSQL."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.core.social import display_social_handle, normalize_social_handle
from shared.domain.forms import FormSchema, FormSection
from shared.domain.team_format import TeamFormat
from shared.models.platform.outbox import EventOutbox
from shared.services.ontology import project_disciplines
from shared.services.roster import roster_engine
from shared.services.team_format import save_tournament_format
from shared.testing import create_test_async_engine
from src.services.registration.lifecycle import lifecycle_service
from src.services.registration.serializers import serialize_registration
from src.services.registration.service import registration_service
from src.services.registration.sheet_sync import sheet_sync_service
from src.services.registration.teams import teams_service
from src.services.tournament.flows import TournamentFlowsService


class RegistrationIdentityTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        tag = f"optional-id-{uuid.uuid4().hex[:12]}"
        async with self.Session() as s:
            await project_disciplines(s)
            workspace = models.Workspace(slug=tag, name=tag, disciplines_enabled=["overwatch", "lol"])
            auth = models.AuthUser(email=f"{tag}@example.com", username=tag)
            s.add_all([workspace, auth])
            await s.flush()
            user = models.User(name=tag, auth_user_id=auth.id)
            grid = models.DivisionGrid(workspace_id=workspace.id, discipline="lol", slug=tag, name=tag)
            s.add_all([user, grid])
            await s.flush()
            version = models.DivisionGridVersion(grid_id=grid.id, version=1, label="v1", status="published")
            s.add(version)
            await s.flush()
            s.add(
                models.DivisionGridTier(
                    version_id=version.id,
                    slug="t-1",
                    number=1,
                    name="T 1",
                    sort_order=0,
                    rank_min=0,
                    rank_max=None,
                    icon_url="/t.png",
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
            await s.commit()
            self.workspace_id, self.tournament_id = workspace.id, tournament.id
            self.auth_id, self.user_id = auth.id, user.id

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            player_ids = set(
                await s.scalars(
                    sa.select(models.WorkspaceMember.player_id).where(
                        models.WorkspaceMember.workspace_id == self.workspace_id
                    )
                )
            ) | {self.user_id}
            await s.execute(
                sa.delete(EventOutbox).where(
                    EventOutbox.payload_json["tournament_id"].as_string() == str(self.tournament_id)
                )
            )
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.workspace_id))
            await s.execute(sa.delete(models.User).where(models.User.id.in_(player_ids)))
            await s.execute(sa.delete(models.AuthUser).where(models.AuthUser.id == self.auth_id))
            await s.commit()
        await self.engine.dispose()

    async def test_manual_optional_identity_keeps_owned_player_and_unlinked_rows(self) -> None:
        async with self.Session() as s:
            linked = await lifecycle_service.create_manual_registration(
                s,
                tournament_id=self.tournament_id,
                display_name="LoL Support",
                admin_notes=None,
                auth_user_id=self.auth_id,
                roles=[
                    {
                        "role": {"dimension": "position", "role": "support"},
                        "priority": 0,
                        "is_primary": True,
                        "rank_value": 100,
                        "is_active": True,
                    }
                ],
            )
            anonymous = await lifecycle_service.create_manual_registration(
                s,
                tournament_id=self.tournament_id,
                display_name="Anonymous",
                admin_notes=None,
                roles=[],
            )
            assert linked.identities == anonymous.identities == []
            assert linked.workspace_member.player_id == self.user_id
            assert anonymous.workspace_member_id is None
            ids = linked.id, anonymous.id
        async with self.Session() as s:
            rosters = await roster_engine.for_tournament(s, self.tournament_id)
        assert set(rosters) == set(ids)
        assert rosters[ids[0]].player_id == self.user_id
        assert rosters[ids[0]].rank_on("support") == 100
        assert all(row.identity is None for row in rosters.values())

    async def test_self_service_without_an_identity_question_keeps_owned_player(self) -> None:
        async with self.Session() as s:
            registration = await registration_service.create_registration(
                s,
                tournament_id=self.tournament_id,
                workspace_id=self.workspace_id,
                auth_user_id=self.auth_id,
                values={},
                schema=FormSchema(sections=[FormSection(key="details")]),
            )
            registration_id = registration.id
        async with self.Session() as s:
            loaded = await lifecycle_service.get_registration_by_id(s, registration_id)
            assert loaded.identities == []
            assert loaded.workspace_member.player_id == self.user_id

    async def test_approve_and_check_in_responses_name_who_did_it(self) -> None:
        """The refetch after the write reads the row already in the session, whose
        ``reviewer`` / ``checked_in_by_user`` were loaded as None before the FK moved."""
        async with self.Session() as s:
            username = await s.scalar(sa.select(models.AuthUser.username).where(models.AuthUser.id == self.auth_id))
        async with self.Session() as s:
            created = await lifecycle_service.create_manual_registration(
                s, tournament_id=self.tournament_id, display_name="Walk-in", admin_notes=None, roles=[]
            )
            approved = await lifecycle_service.approve_registration(s, created.id, reviewed_by=self.auth_id)
            read = serialize_registration(approved, workspace_id=self.workspace_id, provider="riot")
            assert read.reviewed_by_username == username
            checked = await lifecycle_service.check_in_registration(s, created.id, checked_in_by=self.auth_id)
            read = serialize_registration(checked, workspace_id=self.workspace_id, provider="riot")
            assert read.checked_in_by_username == username

    async def test_sheet_without_game_identity_persists_and_reloads(self) -> None:
        async with self.Session() as s:
            s.add(
                models.RegistrationGoogleSheetFeed(
                    tournament_id=self.tournament_id,
                    source_url="http://sheet.example/optional",
                    sheet_id="optional",
                    mapping_config_json={
                        "targets": {
                            "source_record_key": {"mode": "columns", "columns": ["Key"], "parser": "string"},
                            "display_name": {"mode": "columns", "columns": ["Name"], "parser": "string"},
                        }
                    },
                )
            )
            await s.commit()

            async def fetch(*args, **kwargs):
                return [["Key", "Name"], ["optional", "Optional Sheet Player"]]

            with patch("src.services.registration.sheet_sync.fetch_google_sheet_rows", fetch):
                result = await sheet_sync_service.sync_google_sheet_feed(s, self.tournament_id)
            assert result.created == 1 and result.errors == []
        async with self.Session() as s:
            rosters = await roster_engine.for_tournament(s, self.tournament_id)
        assert len(rosters) == 1
        roster = next(iter(rosters.values()))
        assert roster.display_name == "Optional Sheet Player"
        assert roster.identity is None and roster.player_id is None

    async def _sync_riot_sheet(self, *, explicit_key: bool) -> None:
        suffix = uuid.uuid4().hex[:4]
        raw_handles = [f"Faker{suffix}#KR1", f"Hide {suffix} # EUW", f"Foo {suffix} Bar#123", f"Foo{suffix}Bar#123"]
        handles = [display_social_handle("riot", handle) for handle in raw_handles]
        rows = [["Riot ID", "Key"], *[[handle, f"Row {index}"] for index, handle in enumerate(raw_handles)]]
        targets = {"identity_riot": {"mode": "columns", "columns": ["Riot ID"], "parser": "battle_tag_list"}}
        if explicit_key:
            targets["source_record_key"] = {"mode": "columns", "columns": ["Key"], "parser": "string"}

        async def fetch(*args, **kwargs):
            return rows

        async with self.Session() as s:
            with patch("src.services.registration.sheet_sync.fetch_google_sheet_rows", fetch):
                feed = await sheet_sync_service.upsert_google_sheet_feed(
                    s,
                    self.tournament_id,
                    source_url="https://docs.google.com/spreadsheets/d/riot-identity/edit",
                    title=None,
                    auto_sync_enabled=False,
                    auto_sync_interval_seconds=300,
                    mapping_config_json={"targets": targets},
                    value_mapping_json={},
                )
                preview = await sheet_sync_service.preview_google_sheet_mapping(s, self.tournament_id)
                assert preview["create_count"] == 4 and preview["skip_count"] == 0
                assert [row["parsed_fields"]["answers"]["identity_riot"] for row in preview["rows"]] == [
                    [handle] for handle in handles
                ]
                result = await sheet_sync_service.sync_google_sheet_feed(s, self.tournament_id)
                assert result.created == 4 and result.skipped == 0 and result.errors == []
                repeated = await sheet_sync_service.sync_google_sheet_feed(s, self.tournament_id)
                assert repeated.created == 0 and repeated.updated == 0 and repeated.errors == []
                keys = set(await sheet_sync_service.binding_repo.list_source_record_keys(s, feed.id))
                expected_keys = (
                    {f"row{index}" for index in range(4)}
                    if explicit_key
                    else {normalize_social_handle("riot", handle) for handle in handles}
                )
                assert keys == expected_keys

        async with self.Session() as s:
            rosters = await roster_engine.for_tournament(s, self.tournament_id)
            assert {row.identity.handle for row in rosters.values()} == set(handles)
            assert len({row.player_id for row in rosters.values()}) == 4
            for row in rosters.values():
                loaded = await lifecycle_service.get_registration_by_id(s, row.registration_id)
                assert [(identity.provider, identity.handle) for identity in loaded.identities] == [
                    ("riot", row.identity.handle)
                ]
                assert row.player_id is not None
                account = await s.scalar(
                    sa.select(models.SocialAccount).where(
                        models.SocialAccount.user_id == row.player_id, models.SocialAccount.provider == "riot"
                    )
                )
                assert account.username == row.identity.handle

    async def test_riot_sheet_without_record_key_keeps_space_distinct_identities(self) -> None:
        await self._sync_riot_sheet(explicit_key=False)

    async def test_riot_sheet_with_record_key_persists_alpha_tags(self) -> None:
        await self._sync_riot_sheet(explicit_key=True)

    async def _attach_team_game_handles(self, *, discipline: str, provider: str, other_provider: str) -> None:
        suffix = uuid.uuid4().hex[:6]
        handle = f"Attach{suffix}#1234"
        second_handle = f"Team {suffix} # KR1" if provider == "riot" else f"Other{suffix}#5678"
        async with self.Session() as s:
            tournament = await s.get(models.Tournament, self.tournament_id)
            tournament.discipline = discipline
            if discipline == "overwatch":
                tournament.division_grid_version_id = None
            await save_tournament_format(
                s, tournament, TeamFormat(discipline=discipline, name="Open two", starter_min=2, starter_max=2)
            )
            team = models.RegistrationTeam(
                tournament_id=tournament.id,
                workspace_id=self.workspace_id,
                name="Identity",
                name_normalized="identity",
                status="forming",
            )
            wrong_provider = models.Registration(
                tournament_id=tournament.id,
                display_name=handle,
                status="approved",
                identities=[
                    models.RegistrationIdentity(
                        provider=other_provider,
                        position=0,
                        handle=handle,
                        handle_normalized=normalize_social_handle(other_provider, handle),
                    )
                ],
            )
            s.add_all([team, wrong_provider])
            await s.commit()
            team_id, wrong_id = team.id, wrong_provider.id
            for candidate in (handle, handle.lower(), second_handle):
                await teams_service.attach_member_as_organizer(
                    s,
                    tournament_id=self.tournament_id,
                    team_id=team_id,
                    handle=candidate,
                    slot_code="flex",
                )
        async with self.Session() as s:
            rosters = await roster_engine.for_tournament(s, self.tournament_id)
            assert rosters[wrong_id].registration_team_id is None
            assert rosters[wrong_id].identity is None
            attached = [row for row in rosters.values() if row.registration_team_id == team_id]
            assert {row.identity.handle for row in attached} == {handle, display_social_handle(provider, second_handle)}
            for row in attached:
                loaded = await lifecycle_service.get_registration_by_id(s, row.registration_id)
                assert [(identity.provider, identity.handle) for identity in loaded.identities] == [
                    (provider, row.identity.handle)
                ]
                assert row.player_id is not None
                account = await s.scalar(
                    sa.select(models.SocialAccount).where(
                        models.SocialAccount.user_id == row.player_id,
                        models.SocialAccount.provider == provider,
                    )
                )
                assert account.username == row.identity.handle

    async def test_lol_organizer_attach_is_visible_to_riot_roster_consumers(self) -> None:
        await self._attach_team_game_handles(discipline="lol", provider="riot", other_provider="battlenet")

    async def test_overwatch_organizer_attach_never_reuses_a_riot_registration(self) -> None:
        await self._attach_team_game_handles(discipline="overwatch", provider="battlenet", other_provider="riot")

    async def test_default_forms_and_tournament_read_follow_persisted_discipline(self) -> None:
        async with self.Session() as s:
            tournament = await lifecycle_service.common.ensure_tournament_exists(s, self.tournament_id)
            for code, provider in (("lol", "riot"), ("overwatch", "battlenet")):
                tournament.discipline = code
                if code == "overwatch":
                    tournament.division_grid_version_id = None
                await s.flush()
                schema = await sheet_sync_service._registration_schema(s, tournament.id)
                assert schema.builtin(f"identity_{provider}").required
                view = await TournamentFlowsService().to_pydantic(s, tournament, [])
                assert view.model_dump()["identity_provider"] == provider
