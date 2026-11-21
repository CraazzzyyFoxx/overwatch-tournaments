"""A player merge must not strand ``encounter.team_member`` snapshots (D66).

The source player is deleted and its ``workspace_member`` rows cascade away; the
roster FK has no cascade, so the merge first hands the source's members (and the
seats on them) to the survivor. Real PostgreSQL; the case rolls back.
"""

import asyncio
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core.errors import ApiHTTPException
from shared.models.encounter import Encounter, EncounterTeam, EncounterTeamMember, ScoringRule
from shared.models.mix import CustomGame, CustomGameLobby, CustomGameRound, CustomGameRoundMember
from shared.testing.db import create_test_async_engine, ensure_test_postgres
from src import schemas
from src.services.admin.user_merge import UserMergeService

_WINS_END = "games >= best_of or max_wins * 2 > best_of"


class UserMergeRosterTests(IsolatedAsyncioTestCase):
    loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(
            bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        self.merges = UserMergeService()
        tag = uuid4().hex
        self.source = models.User(name=f"source-{tag}")
        self.target = models.User(name=f"target-{tag}")
        self.workspace = models.Workspace(name="Merge roster", slug=f"merge-roster-{tag}")
        self.session.add_all([self.source, self.target, self.workspace])
        await self.session.flush()
        tournament = models.Tournament(
            workspace_id=self.workspace.id,
            discipline="overwatch",
            name=tag,
            slug=tag,
            status=enums.TournamentStatus.LIVE,
        )
        rule = ScoringRule(workspace_id=self.workspace.id, preset="wins", game_formula="win", end_formula=_WINS_END)
        self.session.add_all([tournament, rule])
        await self.session.flush()
        self.tournament_id, self.rule_id = tournament.id, rule.id

    async def asyncTearDown(self):
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def _seat(self, encounter_id, slot, member_id) -> EncounterTeamMember:
        team = EncounterTeam(encounter_id=encounter_id, tournament_id=self.tournament_id, slot=slot, name=f"T{slot}")
        self.session.add(team)
        await self.session.flush()
        seat = EncounterTeamMember(
            encounter_id=encounter_id,
            encounter_team_id=team.id,
            active=True,
            workspace_member_id=member_id,
            display_name_snapshot=f"m{member_id}",
        )
        self.session.add(seat)
        await self.session.flush()
        return seat

    async def _encounter(self, name) -> int:
        encounter = Encounter(
            workspace_id=self.workspace.id,
            discipline="overwatch",
            tournament_id=self.tournament_id,
            scoring_rule_id=self.rule_id,
            name=name,
            slot_count=2,
            status=enums.EncounterStatus.OPEN,
        )
        self.session.add(encounter)
        await self.session.flush()
        return encounter.id

    async def _merge(self) -> None:
        preview = await self.merges.preview_merge(
            self.session,
            schemas.UserMergePreviewRequest(source_user_id=self.source.id, target_user_id=self.target.id),
        )
        await self.merges.execute_merge(
            self.session,
            schemas.UserMergeExecuteRequest(
                source_user_id=self.source.id,
                target_user_id=self.target.id,
                preview_fingerprint=preview.preview_fingerprint,
                field_policy={},
                identity_selection={},
            ),
            operator_auth_user_id=None,
        )
        # The roster FK is DEFERRED: fire it now, as the outer commit would in production.
        await self.session.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))

    async def _owners(self) -> dict[str, int]:
        rows = await self.session.execute(
            sa.select(EncounterTeamMember.display_name_snapshot, models.WorkspaceMember.player_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == EncounterTeamMember.workspace_member_id)
            .where(EncounterTeamMember.encounter_id.in_(self._encounters))
        )
        return dict(rows.all())

    async def test_merging_a_rostered_player_without_a_survivor_member_repoints_the_member_row(self):
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        self.session.add(source_member)
        await self.session.flush()
        self._encounters = [await self._encounter("E1")]
        await self._seat(self._encounters[0], 1, source_member.id)

        await self._merge()

        self.assertEqual({f"m{source_member.id}": self.target.id}, await self._owners())
        self.assertEqual(
            self.target.id,
            await self.session.scalar(
                sa.select(models.WorkspaceMember.player_id).where(models.WorkspaceMember.id == source_member.id)
            ),
        )

    async def test_merging_onto_a_survivor_member_moves_seats_and_drops_a_duplicate_seat(self):
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        target_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id)
        self.session.add_all([source_member, target_member])
        await self.session.flush()
        shared_encounter = await self._encounter("shared")
        own_encounter = await self._encounter("own")
        self._encounters = [shared_encounter, own_encounter]
        # Both sat in ``shared``: the source seat duplicates the survivor's and goes.
        await self._seat(shared_encounter, 1, source_member.id)
        survivor_seat = await self._seat(shared_encounter, 2, target_member.id)
        moved_seat = await self._seat(own_encounter, 1, source_member.id)

        await self._merge()

        seats = (
            await self.session.execute(
                sa.select(EncounterTeamMember.id, EncounterTeamMember.workspace_member_id).where(
                    EncounterTeamMember.encounter_id.in_(self._encounters)
                )
            )
        ).all()
        self.assertEqual(
            {(survivor_seat.id, target_member.id), (moved_seat.id, target_member.id)},
            set(seats),
        )
        self.assertIsNone(
            await self.session.scalar(
                sa.select(models.WorkspaceMember.id).where(models.WorkspaceMember.id == source_member.id)
            )
        )

    async def test_merging_onto_a_survivor_member_moves_custom_game_round_rows_and_drops_a_duplicate(self):
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        target_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id)
        mix_rule = ScoringRule(workspace_id=self.workspace.id, preset="wins", game_formula="win", end_formula=_WINS_END)
        self.session.add_all([source_member, target_member, mix_rule])
        await self.session.flush()
        mix = CustomGame(workspace_id=self.workspace.id, name="Mix", scoring_rule_id=mix_rule.id)
        self.session.add(mix)
        await self.session.flush()
        rounds = []
        for name in ("shared", "own"):
            encounter = Encounter(
                workspace_id=self.workspace.id,
                discipline="overwatch",
                custom_game_id=mix.id,
                scoring_rule_id=mix_rule.id,
                name=name,
                slot_count=2,
                best_of=1,
                status=enums.EncounterStatus.OPEN,
            )
            self.session.add(encounter)
            await self.session.flush()
            self.session.add(CustomGameRound(encounter_id=encounter.id, lobby_index=0))
            rounds.append(encounter.id)
        await self.session.flush()
        shared_round, own_round = rounds
        self.session.add_all(
            [
                CustomGameRoundMember(encounter_id=shared_round, workspace_member_id=source_member.id, busy=True),
                CustomGameRoundMember(
                    encounter_id=shared_round, workspace_member_id=target_member.id, busy=False, rank_delta_applied=4
                ),
                CustomGameRoundMember(
                    encounter_id=own_round, workspace_member_id=source_member.id, busy=False, rank_delta_applied=-3
                ),
            ]
        )
        await self.session.flush()

        await self._merge()

        rows = (
            await self.session.execute(
                sa.select(
                    CustomGameRoundMember.encounter_id,
                    CustomGameRoundMember.workspace_member_id,
                    CustomGameRoundMember.rank_delta_applied,
                ).where(CustomGameRoundMember.encounter_id.in_(rounds))
            )
        ).all()
        self.assertEqual({(shared_round, target_member.id, 4), (own_round, target_member.id, -3)}, set(rows))

    async def test_custom_game_round_collision_keeps_the_seated_row_and_the_survivors_on_a_tie(self):
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        target_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id)
        mix_rule = ScoringRule(workspace_id=self.workspace.id, preset="wins", game_formula="win", end_formula=_WINS_END)
        self.session.add_all([source_member, target_member, mix_rule])
        await self.session.flush()
        mix = CustomGame(workspace_id=self.workspace.id, name="Mix", scoring_rule_id=mix_rule.id)
        self.session.add(mix)
        await self.session.flush()
        rounds = []
        for name in ("seated-vs-busy", "both-busy", "both-seated"):
            encounter = Encounter(
                workspace_id=self.workspace.id,
                discipline="overwatch",
                custom_game_id=mix.id,
                scoring_rule_id=mix_rule.id,
                name=name,
                slot_count=2,
                best_of=1,
                status=enums.EncounterStatus.OPEN,
            )
            self.session.add(encounter)
            await self.session.flush()
            self.session.add(CustomGameRound(encounter_id=encounter.id, lobby_index=0))
            rounds.append(encounter.id)
        await self.session.flush()
        seated_vs_busy, both_busy, both_seated = rounds
        self.session.add_all(
            [
                CustomGameRoundMember(
                    encounter_id=seated_vs_busy, workspace_member_id=source_member.id, busy=False, rank_delta_applied=7
                ),
                CustomGameRoundMember(encounter_id=seated_vs_busy, workspace_member_id=target_member.id, busy=True),
                CustomGameRoundMember(encounter_id=both_busy, workspace_member_id=source_member.id, busy=True),
                CustomGameRoundMember(encounter_id=both_busy, workspace_member_id=target_member.id, busy=True),
                CustomGameRoundMember(
                    encounter_id=both_seated, workspace_member_id=source_member.id, busy=False, rank_delta_applied=1
                ),
                CustomGameRoundMember(
                    encounter_id=both_seated, workspace_member_id=target_member.id, busy=False, rank_delta_applied=2
                ),
            ]
        )
        await self.session.flush()

        await self._merge()

        rows = (
            await self.session.execute(
                sa.select(
                    CustomGameRoundMember.encounter_id,
                    CustomGameRoundMember.workspace_member_id,
                    CustomGameRoundMember.busy,
                    CustomGameRoundMember.rank_delta_applied,
                ).where(CustomGameRoundMember.encounter_id.in_(rounds))
            )
        ).all()
        self.assertEqual(
            {
                (seated_vs_busy, target_member.id, False, 7),
                (both_busy, target_member.id, True, None),
                (both_seated, target_member.id, False, 2),
            },
            set(rows),
        )

    async def _mix_draft_seats(self, status: str, *, seat_target: bool) -> tuple[models.WorkspaceMember, list[int]]:
        """A one-lobby mix whose draft (in ``status``) seats the source's member, and the target's too when asked.
        Returns the target's member and the seat ids, source seat first."""
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        target_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id)
        mix_rule = ScoringRule(workspace_id=self.workspace.id, preset="wins", game_formula="win", end_formula=_WINS_END)
        self.session.add_all([source_member, target_member, mix_rule])
        await self.session.flush()
        mix = CustomGame(workspace_id=self.workspace.id, name="Mix", scoring_rule_id=mix_rule.id)
        self.session.add(mix)
        await self.session.flush()
        self.session.add(CustomGameLobby(custom_game_id=mix.id, lobby_index=0))
        await self.session.flush()
        draft = models.DraftSession(
            custom_game_id=mix.id, lobby_index=0, workspace_id=self.workspace.id, discipline="overwatch", status=status
        )
        self.session.add(draft)
        await self.session.flush()
        seats = [models.DraftPlayer(session_id=draft.id, workspace_member_id=source_member.id)]
        if seat_target:
            seats.append(models.DraftPlayer(session_id=draft.id, workspace_member_id=target_member.id))
        self.session.add_all(seats)
        await self.session.flush()
        self._draft_id = draft.id
        return target_member, [seat.id for seat in seats]

    async def _seat_members(self, seat_ids: list[int]) -> list[int]:
        rows = dict(
            (
                await self.session.execute(
                    sa.select(models.DraftPlayer.id, models.DraftPlayer.workspace_member_id).where(
                        models.DraftPlayer.id.in_(seat_ids)
                    )
                )
            ).all()
        )
        return [rows[seat_id] for seat_id in seat_ids]

    async def test_merging_onto_a_survivor_member_moves_a_mix_draft_seat(self):
        """A mix seat has no registration: its member is its only identity, so the merge moves it to the survivor
        before the duplicate member goes (the seat FK is NO ACTION, deferred)."""
        target_member, seat_ids = await self._mix_draft_seats(enums.DraftStatus.SETUP.value, seat_target=False)

        await self._merge()

        self.assertEqual([target_member.id], await self._seat_members(seat_ids))

    async def test_a_merge_refuses_two_seats_of_one_person_in_a_running_draft(self):
        """Both players seated in a live draft: the merge would leave one person two usable seats, so it is refused
        before any write and names the draft."""
        target_member, seat_ids = await self._mix_draft_seats(enums.DraftStatus.LIVE.value, seat_target=True)
        # Committed, so the merge's own rollback cannot hide what it would have changed.
        await self.session.commit()
        before = await self._seat_members(seat_ids)
        source_id = self.source.id

        with self.assertRaises(ApiHTTPException) as caught:
            await self._merge()

        self.assertEqual(409, caught.exception.status_code)
        self.assertEqual("merge_draft_seat_conflict", caught.exception.detail[0]["code"])
        self.assertIn(str(self._draft_id), caught.exception.detail[0]["msg"])
        self.assertEqual(before, await self._seat_members(seat_ids))
        self.assertIsNotNone(await self.session.scalar(sa.select(models.User.id).where(models.User.id == source_id)))

    async def test_a_finished_draft_keeps_both_seats_of_one_person_as_history(self):
        """A completed draft is history: both seats move onto the survivor and the merge goes through."""
        target_member, seat_ids = await self._mix_draft_seats(enums.DraftStatus.COMPLETED.value, seat_target=True)

        await self._merge()

        self.assertEqual([target_member.id, target_member.id], await self._seat_members(seat_ids))

    async def test_merging_onto_a_survivor_member_keeps_the_player_in_an_individual_swiss_pool(self):
        """The pool row cascades with the member: a merge mid-stage once left the pool a player short and stopped every
        later round. The source's row moves to the survivor; where the survivor already has one, theirs stays."""
        source_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.source.id)
        target_member = models.WorkspaceMember(workspace_id=self.workspace.id, player_id=self.target.id)
        stages = [
            models.Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name=name,
                stage_type=enums.StageType.INDIVIDUAL_SWISS,
            )
            for name in ("source only", "both")
        ]
        self.session.add_all([source_member, target_member, *stages])
        await self.session.flush()
        only, both = (stage.id for stage in stages)

        def row(stage_id: int, member_id: int, rank: int) -> models.PlayerStanding:
            return models.PlayerStanding(
                tournament_id=self.tournament_id,
                stage_id=stage_id,
                workspace_member_id=member_id,
                display_name=f"m{member_id}",
                role="damage",
                start_rank=rank,
                rank=rank,
            )

        self.session.add_all(
            [
                row(only, source_member.id, 3500),
                row(both, source_member.id, 1000),
                row(both, target_member.id, 2000),
                models.PlayerStandingPin(stage_id=only, workspace_member_id=source_member.id, position=1),
            ]
        )
        await self.session.flush()

        await self._merge()

        pool = await self.session.execute(
            sa.select(
                models.PlayerStanding.stage_id, models.PlayerStanding.workspace_member_id, models.PlayerStanding.rank
            ).where(models.PlayerStanding.stage_id.in_([only, both]))
        )
        self.assertEqual({(only, target_member.id, 3500), (both, target_member.id, 2000)}, set(pool.all()))
        pins = await self.session.execute(
            sa.select(models.PlayerStandingPin.stage_id, models.PlayerStandingPin.workspace_member_id).where(
                models.PlayerStandingPin.stage_id == only
            )
        )
        self.assertEqual([(only, target_member.id)], list(pins.all()))
