"""``merge_league`` (spec §15.3) on a three-day league.

Days 1-3: a stage, ``Registration → Teams → stage`` nodes, a registration form with one version, team "Alpha" (m0, m1)
and team "Bravo" (empty; m2 on day 2), one encounter Alpha vs Bravo with a bracket row and standings (Alpha 1st, 3 pts).
m0 and m1 register on every day, m2 on day 2 only; each registration has an approved entry on its day's node. Days 1
and 2 have a registered team "Alpha" (captain m0). Day 1 also has a second encounter and a link into it, a discord
channel and a stream session; day 2 a stream session with the same stream id; day 3 a discord channel.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.core import db, enums
from shared.models.tournament.flow import FlowEdge, FlowNode
from shared.services.encounter.participants import place_team
from shared.testing import create_test_async_engine, ensure_test_postgres
from shared.tests.encounter_writer_case import WINS_END
from src.services.flow.league_merge import (
    REGISTRATION_FKS,
    TOURNAMENT_FKS,
    LeagueEntry,
    MergeError,
    apply_mapping,
    merge_league,
)

_TAG = itertools.count()
AGG = {"unit": "players", "score": {"preset": "placement_table", "table": {"1": 10, "2": 5}}, "mode": "sum_all"}


def _fk_columns_into(table_names: set[str], also_named: str | None = None) -> set[str]:
    """Every ``schema.table.column`` of a FK whose target is one of ``table_names`` (or a column named ``also_named``
    inside any FK — the composite copies of ``tournament_id``)."""
    found = set()
    for table in db.Base.metadata.tables.values():
        for fk in table.foreign_key_constraints:
            for element in fk.elements:
                if element.column.table.fullname in table_names or element.parent.name == also_named:
                    found.add(f"{table.fullname}.{element.parent.name}")
    return found


def test_every_column_carrying_a_tournament_is_classified() -> None:
    # ``draft.session``, ``encounter.encounter`` and ``roster.team_format`` copy ``workspace_id`` and ``discipline`` in the
    # same composite FK as their tournament id; those two columns are not tournament ids.
    columns = {
        c
        for c in _fk_columns_into({"tournament.tournament"}, also_named="tournament_id")
        if c.rsplit(".", 1)[1] not in ("workspace_id", "discipline")
    }
    assert columns == set(TOURNAMENT_FKS)


def test_every_registration_reference_is_classified() -> None:
    assert _fk_columns_into({"registration.registration"}) == set(REGISTRATION_FKS)


def test_classified_keys_are_real_columns() -> None:
    for key in TOURNAMENT_FKS:
        table, column = key.rsplit(".", 1)
        assert column in db.Base.metadata.tables[table].c, key
    for key in REGISTRATION_FKS:
        table, column = key.rsplit(".", 1)
        assert column in db.Base.metadata.tables[table].c, key


class LeagueMergeCase(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.ids = await self._seed()

    async def asyncTearDown(self) -> None:
        async with self.Session() as s:
            await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == self.ids["ws"]))
            await s.execute(sa.delete(models.User).where(models.User.id.in_(self.ids["users"])))
            await s.commit()
        await self.engine.dispose()

    def entry(self, **over) -> LeagueEntry:
        raw = {
            "league": "L",
            "season": 1,
            "name": "Weekly League",
            "target_tournament_id": self.ids["d1"],
            "aggregate": AGG,
            "days": [{"tournament_id": self.ids[f"d{n}"], "day": n} for n in (1, 2, 3)],
        }
        return LeagueEntry.model_validate(raw | over)

    async def _seed(self) -> dict:
        """See the module docstring. Returns ids: ws, users, m0..m2, d1..d3, and per day n: stage{n}, reg{n},
        form{n}, teams{n} (the Teams node), alpha{n}, bravo{n}, enc{n}, reg_m{k}_{n}, rteam{n} (days 1-2),
        enc1b, link1, discord1, discord3, stream1, stream2."""
        tag = f"lm-{os.getpid()}-{next(_TAG)}"
        ids: dict = {}
        now = datetime.now(UTC)
        async with self.Session() as s:
            ws = models.Workspace(slug=tag, name=tag, verification_status="verified")
            users = [models.User(name=f"{tag}-{i}") for i in range(3)]
            s.add_all([ws, *users])
            await s.flush()
            members = [models.WorkspaceMember(workspace_id=ws.id, player_id=u.id) for u in users]
            rule = models.ScoringRule(workspace_id=ws.id, preset="wins", game_formula="win", end_formula=WINS_END)
            s.add_all([*members, rule])
            await s.flush()
            ids |= {"ws": ws.id, "users": [u.id for u in users], **{f"m{i}": m.id for i, m in enumerate(members)}}
            for n in (1, 2, 3):
                tournament = models.Tournament(
                    workspace_id=ws.id,
                    discipline="overwatch",
                    name=f"{tag} L | Day {n}",
                    slug=f"{tag}-d{n}",
                    status=enums.TournamentStatus.COMPLETED,
                    is_finished=True,
                    start_date=datetime(2026, 1, 7 * n, 18, tzinfo=UTC),
                )
                s.add(tournament)
                await s.flush()
                t = tournament.id
                ids[f"d{n}"] = t
                stage = models.Stage(
                    tournament_id=t, scoring_rule_id=rule.id, name=f"Groups {n}", stage_type="round_robin", order=0
                )
                s.add(stage)
                await s.flush()
                reg = FlowNode(
                    tournament_id=t, kind="registration", name="Registration", status="closed", config={}, position_x=0
                )
                teams = FlowNode(
                    tournament_id=t,
                    kind="formation",
                    name="Teams",
                    status="completed",
                    config={"mode": "manual"},
                    position_x=300,
                )
                stage_node = FlowNode(
                    tournament_id=t,
                    kind="stage",
                    name=stage.name,
                    status="completed",
                    config={},
                    stage_id=stage.id,
                    position_x=600,
                )
                s.add_all([reg, teams, stage_node])
                await s.flush()
                s.add_all(
                    [
                        FlowEdge(
                            tournament_id=t,
                            source_node_id=reg.id,
                            source_port="participants",
                            target_node_id=teams.id,
                            target_port="players",
                        ),
                        FlowEdge(
                            tournament_id=t,
                            source_node_id=teams.id,
                            source_port="teams",
                            target_node_id=stage_node.id,
                            target_port="participants",
                        ),
                    ]
                )
                form = models.RegistrationForm(tournament_id=t, workspace_id=ws.id)
                s.add(form)
                await s.flush()
                version = models.RegistrationFormVersion(form_id=form.id, number=1, schema_json={})
                s.add(version)
                await s.flush()
                form.current_version_id = version.id
                ids |= {f"stage{n}": stage.id, f"reg{n}": reg.id, f"teams{n}": teams.id, f"form{n}": form.id}

                regs = {}
                for k in (0, 1, 2) if n == 2 else (0, 1):
                    registration = models.Registration(
                        tournament_id=t, workspace_member_id=ids[f"m{k}"], form_version_id=version.id
                    )
                    s.add(registration)
                    await s.flush()
                    s.add(
                        models.RegistrationEntry(
                            registration_node_id=reg.id, registration_id=registration.id, status="approved"
                        )
                    )
                    regs[k] = registration
                    ids[f"reg_m{k}_{n}"] = registration.id
                if n in (1, 2):
                    rteam = models.RegistrationTeam(
                        tournament_id=t,
                        registration_node_id=reg.id,
                        workspace_id=ws.id,
                        name="Alpha",
                        name_normalized="alpha",
                        captain_registration_id=regs[0].id,
                    )
                    s.add(rteam)
                    await s.flush()
                    ids[f"rteam{n}"] = rteam.id
                    regs[0].registration_team_id = regs[1].registration_team_id = rteam.id

                alpha = models.Team(tournament_id=t, name="Alpha", balancer_name="Alpha")
                bravo = models.Team(tournament_id=t, name="Bravo", balancer_name="Bravo")
                s.add_all([alpha, bravo])
                await s.flush()
                ids |= {f"alpha{n}": alpha.id, f"bravo{n}": bravo.id}
                for k, team in ((0, alpha), (1, alpha), *(((2, bravo),) if n == 2 else ())):
                    s.add(
                        models.Player(
                            name=f"p{k}",
                            rank=2500,
                            tournament_id=t,
                            team_id=team.id,
                            workspace_member_id=ids[f"m{k}"],
                        )
                    )
                encounter = models.Encounter(
                    workspace_id=ws.id,
                    discipline="overwatch",
                    tournament_id=t,
                    scoring_rule_id=rule.id,
                    name=f"E{n}",
                    slot_count=2,
                    best_of=3,
                    status=enums.EncounterStatus.COMPLETED,
                    result_status="confirmed",
                    result_source="admin",
                    confirmed_at=now,
                )
                s.add(encounter)
                await s.flush()
                ids[f"enc{n}"] = encounter.id
                await place_team(s, encounter, slot=1, team_id=alpha.id, name="Alpha", seed=1, members=[])
                await place_team(s, encounter, slot=2, team_id=bravo.id, name="Bravo", seed=2, members=[])
                s.add(models.BracketEncounter(encounter_id=encounter.id, tournament_id=t, stage_id=stage.id, round=1))
                for position, (team, wins, loses, points) in enumerate(((alpha, 1, 0, 3.0), (bravo, 0, 1, 0.0)), 1):
                    s.add(
                        models.Standing(
                            tournament_id=t,
                            team_id=team.id,
                            stage_id=stage.id,
                            position=position,
                            overall_position=position,
                            matches=1,
                            win=wins,
                            lose=loses,
                            points=points,
                        )
                    )
                if n == 1:
                    second = models.Encounter(
                        workspace_id=ws.id,
                        discipline="overwatch",
                        tournament_id=t,
                        scoring_rule_id=rule.id,
                        name="E1b",
                        slot_count=2,
                        best_of=3,
                        status=enums.EncounterStatus.OPEN,
                    )
                    s.add(second)
                    await s.flush()
                    ids["enc1b"] = second.id
                    link = models.EncounterLink(
                        tournament_id=t,
                        source_encounter_id=encounter.id,
                        source_position=1,
                        target_encounter_id=second.id,
                        target_slot=1,
                    )
                    s.add(link)
                if n in (1, 3):
                    channel = models.TournamentDiscordChannel(
                        tournament_id=t, channel_id=int(9e17) + next(_TAG) * 10 + n, is_active=True
                    )
                    s.add(channel)
                    await s.flush()
                    ids[f"discord{n}"] = channel.id
                if n in (1, 2):
                    session_row = models.StreamSession(
                        tournament_id=t,
                        user_id=users[0].id,
                        channel="c",
                        broadcaster_id="b",
                        stream_id="s1",
                        started_at=now,
                        last_seen_at=now,
                    )
                    s.add(session_row)
                    await s.flush()
                    ids[f"stream{n}"] = session_row.id
            await s.commit()
        return ids

    async def _merge(self, entry: LeagueEntry | None = None):
        async with self.Session() as s:
            log = await merge_league(s, entry or self.entry())
            await s.commit()
        return log

    async def _scalars(self, statement, **params) -> list:
        async with self.Session() as s:
            return list((await s.execute(sa.text(statement), params)).scalars())

    async def test_merge_deletes_the_emptied_days_and_keeps_the_target(self) -> None:
        log = await self._merge()
        d1, d2, d3 = (self.ids[f"d{n}"] for n in (1, 2, 3))
        assert log.target_tournament_id == d1 and sorted(log.deleted_tournament_ids) == sorted([d2, d3])
        assert await self._scalars(
            "SELECT id FROM tournament.tournament WHERE id IN (:a, :b, :c)", a=d1, b=d2, c=d3
        ) == [d1]

    async def test_encounters_move_with_their_composite_rows(self) -> None:
        await self._merge()
        encounters = [self.ids[k] for k in ("enc1", "enc2", "enc3", "enc1b")]
        for statement in (
            "SELECT DISTINCT tournament_id FROM encounter.encounter WHERE id = ANY(:e)",
            "SELECT DISTINCT tournament_id FROM encounter.team WHERE encounter_id = ANY(:e)",
            "SELECT DISTINCT tournament_id FROM tournament.bracket_encounter WHERE encounter_id = ANY(:e)",
            "SELECT DISTINCT tournament_id FROM tournament.encounter_link WHERE source_encounter_id = ANY(:e)",
        ):
            assert await self._scalars(statement, e=encounters) == [self.ids["d1"]], statement
        seated = await self._scalars(
            "SELECT count(*) FROM encounter.team WHERE encounter_id = ANY(:e) AND team_id IS NOT NULL", e=encounters
        )
        assert seated == [6]

    async def test_day_teams_and_players_belong_to_their_day_formation(self) -> None:
        await self._merge()
        async with self.Session() as s:
            rows = (
                await s.execute(
                    sa.select(models.Team.id, models.Team.formation_node_id, models.Team.tournament_id).where(
                        models.Team.id.in_([self.ids[f"{t}{n}"] for t in ("alpha", "bravo") for n in (1, 2, 3)])
                    )
                )
            ).all()
            players = (
                await s.execute(
                    sa.select(models.Player.team_id, models.Player.formation_node_id).where(
                        models.Player.tournament_id == self.ids["d1"]
                    )
                )
            ).all()
        formation_of = {self.ids[f"{t}{n}"]: self.ids[f"teams{n}"] for t in ("alpha", "bravo") for n in (1, 2, 3)}
        assert {r.id: r.formation_node_id for r in rows} == formation_of
        assert {r.tournament_id for r in rows} == {self.ids["d1"]}
        assert all(p.formation_node_id == formation_of[p.team_id] for p in players) and len(players) == 7

    async def test_each_member_keeps_the_latest_profile_and_every_day_entry(self) -> None:
        log = await self._merge()
        async with self.Session() as s:
            profiles = dict(
                (
                    await s.execute(
                        sa.select(models.Registration.workspace_member_id, models.Registration.id).where(
                            models.Registration.tournament_id == self.ids["d1"],
                            models.Registration.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            entries = (
                await s.execute(
                    sa.select(
                        models.RegistrationEntry.registration_id, models.RegistrationEntry.registration_node_id
                    ).where(models.RegistrationEntry.registration_id.in_(profiles.values()))
                )
            ).all()
        m0, m1, m2 = self.ids["m0"], self.ids["m1"], self.ids["m2"]
        assert profiles == {m0: self.ids["reg_m0_3"], m1: self.ids["reg_m1_3"], m2: self.ids["reg_m2_2"]}
        nodes = {n: self.ids[f"reg{n}"] for n in (1, 2, 3)}
        assert sorted(node for reg, node in entries if reg == profiles[m0]) == sorted(nodes.values())
        assert sorted(node for reg, node in entries if reg == profiles[m1]) == sorted(nodes.values())
        assert [node for reg, node in entries if reg == profiles[m2]] == [nodes[2]]
        dropped = {d.row_id for d in log.dropped if d.table == "registration.registration"}
        assert dropped == {self.ids[f"reg_m{k}_{n}"] for k in (0, 1) for n in (1, 2)}

    async def test_forms_collapse_into_the_latest_with_every_version(self) -> None:
        await self._merge()
        forms = await self._scalars("SELECT id FROM registration.form WHERE tournament_id = :t", t=self.ids["d1"])
        assert forms == [self.ids["form3"]]
        numbers = await self._scalars(
            "SELECT number FROM registration.form_version WHERE form_id = :f ORDER BY number", f=forms[0]
        )
        assert numbers == [1, 2, 3]
        dangling = await self._scalars(
            "SELECT count(*) FROM registration.registration r WHERE r.tournament_id = :t AND r.form_version_id IS NULL",
            t=self.ids["d1"],
        )
        assert dangling == [0]

    async def test_same_name_registered_teams_collapse_into_the_latest(self) -> None:
        log = await self._merge()
        teams = await self._scalars(
            "SELECT id FROM registration.team WHERE tournament_id = :t AND deleted_at IS NULL", t=self.ids["d1"]
        )
        assert teams == [self.ids["rteam2"]]
        captain = await self._scalars("SELECT captain_registration_id FROM registration.team WHERE id = :i", i=teams[0])
        assert captain == [self.ids["reg_m0_3"]]  # the day-2 captain profile was dropped for m0's latest
        assert [d.row_id for d in log.dropped if d.table == "registration.team"] == [self.ids["rteam1"]]

    async def test_unique_per_tournament_rows_keep_the_latest_day_and_are_logged(self) -> None:
        log = await self._merge()
        channels = await self._scalars(
            "SELECT id FROM stats.discord_channel WHERE tournament_id = :t", t=self.ids["d1"]
        )
        streams = await self._scalars("SELECT id FROM stream.session WHERE tournament_id = :t", t=self.ids["d1"])
        assert (channels, streams) == ([self.ids["discord3"]], [self.ids["stream2"]])
        assert {(d.table, d.row_id) for d in log.dropped} >= {
            ("stats.discord_channel", self.ids["discord1"]),
            ("stream.session", self.ids["stream1"]),
        }

    async def test_soft_deleted_registrations_move_untouched(self) -> None:
        async with self.Session() as s:
            await s.execute(
                sa.text("UPDATE registration.registration SET deleted_at = now() WHERE id = :i"),
                {"i": self.ids["reg_m1_1"]},
            )
            await s.commit()
        await self._merge()
        moved = await self._scalars(
            "SELECT tournament_id FROM registration.registration WHERE id = :i", i=self.ids["reg_m1_1"]
        )
        assert moved == [self.ids["d1"]]

    async def test_refuses_a_day_of_another_workspace(self) -> None:
        async with self.Session() as s:
            other = models.Workspace(slug=f"{self.ids['ws']}-other", name="o")
            s.add(other)
            await s.flush()
            foreign = models.Tournament(
                workspace_id=other.id,
                discipline="overwatch",
                name="x",
                slug=f"{self.ids['ws']}-foreign",
                status=enums.TournamentStatus.COMPLETED,
            )
            s.add(foreign)
            await s.commit()
            foreign_id, other_id = foreign.id, other.id
        try:
            entry = self.entry(
                days=[{"tournament_id": self.ids["d1"], "day": 1}, {"tournament_id": foreign_id, "day": 2}]
            )
            async with self.Session() as s:
                with self.assertRaisesRegex(MergeError, f"tournament {foreign_id} is not in workspace"):
                    await merge_league(s, entry)
        finally:
            async with self.Session() as s:
                await s.execute(sa.delete(models.Workspace).where(models.Workspace.id == other_id))
                await s.commit()

    async def test_refuses_a_missing_day(self) -> None:
        await self._merge()
        async with self.Session() as s:
            with self.assertRaisesRegex(MergeError, f"tournament {self.ids['d2']} does not exist"):
                await merge_league(s, self.entry())

    async def _nodes(self) -> list[FlowNode]:
        async with self.Session() as s:
            return list(
                (
                    await s.scalars(
                        sa.select(FlowNode).where(FlowNode.tournament_id == self.ids["d1"]).order_by(FlowNode.id)
                    )
                ).all()
            )

    async def test_each_day_is_a_named_branch_feeding_aggregate_and_leaderboard(self) -> None:
        await self._merge()
        nodes = await self._nodes()
        by_id = {n.id: n for n in nodes}
        assert [n.name for n in nodes if n.kind == "registration"] == ["Day 1", "Day 2", "Day 3"]
        assert [n.name for n in nodes if n.kind == "formation"] == ["Day 1 · Teams", "Day 2 · Teams", "Day 3 · Teams"]
        assert [n.name for n in nodes if n.kind == "stage"] == [
            "Day 1 · Groups 1",
            "Day 2 · Groups 2",
            "Day 3 · Groups 3",
        ]
        assert [n.position_y for n in nodes if n.kind == "registration"] == [0, 400, 800]
        (aggregate,) = [n for n in nodes if n.kind == "aggregate"]
        (leaderboard,) = [n for n in nodes if n.kind == "leaderboard"]
        assert (aggregate.name, leaderboard.name) == ("Weekly League · Season", "Table")
        assert aggregate.config["mode"] == "sum_all" and aggregate.config["unit"] == "players"
        async with self.Session() as s:
            edges = (
                await s.scalars(
                    sa.select(FlowEdge).where(FlowEdge.tournament_id == self.ids["d1"]).order_by(FlowEdge.id)
                )
            ).all()
        into_aggregate = [e for e in edges if e.target_node_id == aggregate.id]
        assert [by_id[e.source_node_id].name for e in into_aggregate] == [
            "Day 1 · Groups 1",
            "Day 2 · Groups 2",
            "Day 3 · Groups 3",
        ]
        assert [(e.source_port, e.target_port) for e in into_aggregate] == [("ranking", "inputs")] * 3
        assert [
            (e.source_node_id, e.source_port, e.target_port) for e in edges if e.target_node_id == leaderboard.id
        ] == [(aggregate.id, "ranking", "ranking")]

    async def test_days_display_in_order_and_the_target_spans_the_season(self) -> None:
        await self._merge()
        orders = await self._scalars(
            'SELECT "order" FROM tournament.stage WHERE id = ANY(:s) ORDER BY id',
            s=[self.ids[f"stage{n}"] for n in (1, 2, 3)],
        )
        assert orders == [0, 1, 2]
        async with self.Session() as s:
            target = await s.get_one(models.Tournament, self.ids["d1"])
        assert (target.name, target.slug.endswith("-d1")) == ("Weekly League", True)
        assert target.end_date == datetime(2026, 1, 21, 18, tzinfo=UTC)

    async def test_the_table_scores_every_day_and_feeds_participant_results(self) -> None:
        await self._merge()
        (leaderboard,) = [n for n in await self._nodes() if n.kind == "leaderboard"]
        async with self.Session() as s:
            scores = dict(
                (
                    await s.execute(
                        sa.select(models.FlowNodeResult.workspace_member_id, models.FlowNodeResult.score).where(
                            models.FlowNodeResult.node_id == leaderboard.id
                        )
                    )
                ).all()
            )
            placed = set(
                (
                    await s.scalars(
                        sa.select(models.ParticipantResult.workspace_member_id).where(
                            models.ParticipantResult.tournament_id == self.ids["d1"]
                        )
                    )
                ).all()
            )
        m0, m1, m2 = self.ids["m0"], self.ids["m1"], self.ids["m2"]
        # Alpha (m0, m1) won every day: 3 x 10; Bravo (m2 on day 2 only) placed 2nd once: 5.
        assert {k: float(v) for k, v in scores.items()} == {m0: 30.0, m1: 30.0, m2: 5.0}
        assert placed == {m0, m1, m2}

    async def test_dry_run_writes_nothing(self) -> None:
        (log,) = await apply_mapping(self.Session, [self.entry()], dry_run=True)
        assert sorted(log.deleted_tournament_ids) == sorted([self.ids["d2"], self.ids["d3"]])
        alive = await self._scalars(
            "SELECT id FROM tournament.tournament WHERE id = ANY(:i) ORDER BY id",
            i=[self.ids[f"d{n}"] for n in (1, 2, 3)],
        )
        assert alive == sorted(self.ids[f"d{n}"] for n in (1, 2, 3))
        assert [n.name for n in await self._nodes()] == ["Registration", "Teams", "Groups 1"]
        assert await self._scalars(
            "SELECT tournament_id FROM tournament.stage WHERE id = :s", s=self.ids["stage2"]
        ) == [self.ids["d2"]]
