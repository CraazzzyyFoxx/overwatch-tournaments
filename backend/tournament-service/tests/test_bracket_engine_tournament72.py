"""Integration tests for the bracket engine, driven by real tournament #72.

Reference: production tournament id=72 («Дворовой турнир #1», 20 teams).
Structure copied verbatim from the production DB (tournament.stage,
tournament.stage_item_input, tournament.encounter, tournament.standing):

- Stage «Groups» (id 165): SWISS, two groups A/B of 10 teams, 5 rounds,
  ``settings_json`` = ``{"ranking_preset": "challonge_swiss",
  "tiebreak_order": ["points", "match_wins", "median_buchholz", "buchholz",
  "score_differential", "head_to_head", "manual_override"]}``.
- Stage «Playoffs» (id 175): DOUBLE_ELIMINATION with a split lower bracket —
  group 1st/2nd places seed the upper bracket, 3rd/4th places start in the
  lower bracket. ``settings_json`` = ``{"de_grand_final_type": "no_reset",
  "tiebreak_order": ["points", "head_to_head", "median_buchholz",
  "score_differential", "match_wins", "buchholz", "manual_override"]}``.

The tests replay the recorded results through the bracket engine
(``generate_bracket`` + advancement edges) and through the standings
calculators, and assert that the engine reproduces the production bracket
history and final standings exactly. They also verify that different
``tiebreak_order`` parameter sets rank the same results differently, and
that concurrent result editing by several participants (both captains, an
admin) is serialised by the row lock + result-status state machine.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")

from shared.core.enums import StageType  # noqa: E402
from shared.services.bracket.engine import generate_bracket  # noqa: E402
from shared.services.bracket.swiss import SwissStanding  # noqa: E402
from shared.services.bracket.types import BracketSkeleton  # noqa: E402

standings_service = importlib.import_module("src.services.standings.service")
captain_service = importlib.import_module("src.services.encounter.captain")
models = importlib.import_module("src.models")
enums = importlib.import_module("shared.core.enums")

# ---------------------------------------------------------------------------
# Tournament 72 reference data (production DB, tournament_id=72)
# ---------------------------------------------------------------------------

# Group A (stage_item 163) team ids: Averet=2069, Scorpion=2067, zMize=2055,
# HOTUKEV=2056, DemonDimon=2054, Txao=2072, TeYzee=2061, NoBrain=2070,
# SanekTheRio=2057, Стрелок=2064.
GROUP_A_TEAMS = [2069, 2067, 2055, 2061, 2070, 2057, 2072, 2054, 2064, 2056]

# Group B (stage_item 164) team ids: litnik=2071, Rasetsu=2068, vac3x=2060,
# TenYokai=2058, XitryiDmitry=2062, ЕдкийЕж=2063, zlode1=2065, Tref=2066,
# ВорТрусиков=2059, W7sh=2053.
GROUP_B_TEAMS = [2060, 2053, 2071, 2065, 2063, 2058, 2068, 2066, 2059, 2062]

# (round, home_team_id, away_team_id, home_score, away_score) — encounters
# 5517–5561 (group A) and 5522–5566 (group B), all COMPLETED.
GROUP_A_RESULTS = [
    (1, 2069, 2057, 2, 0),
    (1, 2067, 2072, 2, 0),
    (1, 2055, 2054, 1, 1),
    (1, 2061, 2064, 1, 1),
    (1, 2070, 2056, 1, 1),
    (2, 2069, 2067, 2, 0),
    (2, 2055, 2064, 2, 0),
    (2, 2061, 2056, 1, 1),
    (2, 2070, 2054, 1, 1),
    (2, 2057, 2072, 1, 1),
    (3, 2069, 2055, 2, 0),
    (3, 2067, 2057, 2, 0),
    (3, 2070, 2061, 1, 1),
    (3, 2056, 2054, 2, 0),
    (3, 2064, 2072, 0, 2),
    (4, 2069, 2056, 2, 0),
    (4, 2067, 2054, 1, 1),
    (4, 2061, 2055, 1, 1),
    (4, 2072, 2070, 1, 1),
    (4, 2057, 2064, 1, 1),
    (5, 2069, 2061, 1, 1),
    (5, 2057, 2070, 1, 1),
    (5, 2056, 2072, 1, 1),
    (5, 2055, 2067, 2, 0),
    (5, 2054, 2064, 2, 0),
]

GROUP_B_RESULTS = [
    (1, 2060, 2058, 1, 1),
    (1, 2053, 2068, 0, 2),
    (1, 2071, 2066, 2, 0),
    (1, 2065, 2059, 1, 1),
    (1, 2063, 2062, 1, 1),
    (2, 2071, 2068, 1, 1),
    (2, 2060, 2059, 1, 1),
    (2, 2065, 2062, 1, 1),
    (2, 2063, 2058, 1, 1),
    (2, 2053, 2066, 0, 2),
    (3, 2071, 2065, 2, 0),
    (3, 2068, 2058, 2, 0),
    (3, 2063, 2053, 2, 0),
    (3, 2059, 2066, 1, 1),
    (3, 2062, 2060, 0, 2),
    (4, 2071, 2060, 2, 0),
    (4, 2068, 2063, 2, 0),
    (4, 2059, 2058, 0, 2),
    (4, 2066, 2062, 0, 2),
    (4, 2065, 2053, 2, 0),
    (5, 2071, 2063, 2, 0),
    (5, 2068, 2065, 2, 0),
    (5, 2062, 2059, 2, 0),
    (5, 2060, 2053, 2, 0),
    (5, 2058, 2066, 2, 0),
]

# Stage 165 settings_json (verbatim).
SWISS_SETTINGS = {
    "ranking_preset": "challonge_swiss",
    "tiebreak_order": [
        "points",
        "match_wins",
        "median_buchholz",
        "buchholz",
        "score_differential",
        "head_to_head",
        "manual_override",
    ],
}

# Stage 175 settings_json (verbatim).
PLAYOFF_SETTINGS = {
    "de_grand_final_type": "no_reset",
    "tiebreak_order": [
        "points",
        "head_to_head",
        "median_buchholz",
        "score_differential",
        "match_wins",
        "buchholz",
        "manual_override",
    ],
}

# Production standings order (stage 165, positions 1..10 per stage item).
GROUP_A_PROD_ORDER = [2069, 2055, 2067, 2056, 2054, 2072, 2061, 2070, 2057, 2064]
GROUP_B_PROD_ORDER = [2071, 2068, 2060, 2058, 2062, 2063, 2065, 2066, 2059, 2053]

# Playoff entrants: stage_item_input rows of stage item 176
# (source_stage_item_id/source_position wiring: A1,B1,B2,A2 → UB; A3,B3,B4,A4 → LB).
# The engine seeds UB pairs as (t[0] vs t[3], t[1] vs t[2]); this order
# reproduces the production round-1 pairings litnik–zMize / Averet–Rasetsu.
PLAYOFF_UB_SEEDS = [2071, 2069, 2068, 2055]  # litnik, Averet, Rasetsu, zMize
PLAYOFF_LB_SEEDS = [2067, 2058, 2060, 2056]  # Scorpion, TenYokai, vac3x, HOTUKEV

# Recorded playoff results as (winner_id, winner_score, loser_score) per
# matchup, in chronological order (encounters 5651–5660). The Averet–litnik
# pair occurs twice: UB Final (litnik 2:0) and Grand Final (Averet 3:0).
PLAYOFF_RESULTS: dict[frozenset[int], list[tuple[int, int, int]]] = {
    frozenset({2071, 2055}): [(2071, 2, 1)],
    frozenset({2069, 2068}): [(2069, 2, 0)],
    frozenset({2067, 2058}): [(2067, 2, 0)],
    frozenset({2060, 2056}): [(2060, 2, 0)],
    frozenset({2069, 2071}): [(2071, 2, 0), (2069, 3, 0)],
    frozenset({2067, 2055}): [(2055, 2, 0)],
    frozenset({2060, 2068}): [(2060, 2, 1)],
    frozenset({2055, 2060}): [(2060, 2, 0)],
    frozenset({2060, 2069}): [(2069, 2, 1)],
}

# Production bracket history: {round: set of matchups} (stage 175).
PLAYOFF_PROD_MATCHES = {
    1: {frozenset({2071, 2055}), frozenset({2069, 2068})},
    2: {frozenset({2069, 2071})},
    3: {frozenset({2069, 2071})},
    -1: {frozenset({2067, 2058}), frozenset({2060, 2056})},
    -2: {frozenset({2067, 2055}), frozenset({2060, 2068})},
    -3: {frozenset({2055, 2060})},
    -4: {frozenset({2060, 2069})},
}

# Production standings (stage 175): team → (position, wins, loses, matches).
PLAYOFF_PROD_STANDINGS = {
    2069: (1, 3, 1, 4),
    2071: (2, 2, 1, 3),
    2060: (3, 3, 1, 4),
    2055: (4, 1, 2, 3),
    2067: (5, 1, 1, 2),
    2068: (5, 0, 2, 2),
    2058: (7, 0, 1, 1),
    2056: (7, 0, 1, 1),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encounter(
    home_team_id: int,
    away_team_id: int,
    home_score: int,
    away_score: int,
    round_number: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=home_score,
        away_score=away_score,
        round=round_number,
        status=enums.EncounterStatus.COMPLETED,
        result_status=enums.EncounterResultStatus.NONE,
    )


def _group_encounters(results: list[tuple[int, int, int, int, int]]) -> list[SimpleNamespace]:
    return [_encounter(home, away, hs, aws, rnd) for rnd, home, away, hs, aws in results]


def _simulate_bracket(skeleton: BracketSkeleton, decide) -> list[SimpleNamespace]:
    """Replay a skeleton: fill TBD slots by walking advancement edges.

    ``local_id`` order is topological in both generators (every edge points
    from a lower to a higher local_id), so a single forward pass suffices.
    ``decide(home, away) -> (home_score, away_score)`` supplies each result.
    """
    slots: dict[int, dict[str, int | None]] = {
        pairing.local_id: {"home": pairing.home_team_id, "away": pairing.away_team_id} for pairing in skeleton.pairings
    }
    outgoing = defaultdict(list)
    for edge in skeleton.advancement_edges:
        assert edge.source_local_id < edge.target_local_id, "edges must move forward"
        outgoing[edge.source_local_id].append(edge)

    encounters: list[SimpleNamespace] = []
    for pairing in sorted(skeleton.pairings, key=lambda p: p.local_id):
        home = slots[pairing.local_id]["home"]
        away = slots[pairing.local_id]["away"]
        assert home is not None and away is not None, f"unfilled slot in {pairing.name}"
        home_score, away_score = decide(home, away)
        winner, loser = (home, away) if home_score > away_score else (away, home)
        encounters.append(_encounter(home, away, home_score, away_score, pairing.round_number))
        for edge in outgoing[pairing.local_id]:
            slots[edge.target_local_id][edge.target_slot] = winner if edge.role == "winner" else loser
    return encounters


def _recorded_result(results: dict[frozenset[int], list[tuple[int, int, int]]]):
    """Decide function replaying recorded results; repeated matchups are
    consumed chronologically (UB Final before Grand Final)."""
    remaining = {key: list(games) for key, games in results.items()}

    def decide(home: int, away: int) -> tuple[int, int]:
        winner, winner_score, loser_score = remaining[frozenset({home, away})].pop(0)
        if winner == home:
            return winner_score, loser_score
        return loser_score, winner_score

    return decide


def _stage(stage_type, settings_json: dict | None) -> object:
    stage = models.Stage(
        tournament_id=72,
        name="Stage",
        stage_type=stage_type,
        order=0,
        settings_json=settings_json,
    )
    stage.id = 165
    return stage


# ---------------------------------------------------------------------------
# Swiss group stage: tiebreak parameters against production standings
# ---------------------------------------------------------------------------


class SwissGroupStageTournament72Tests(TestCase):
    """The group-stage ranking pipeline must reproduce the production
    standings of both tournament-72 groups under the stage's tiebreak_order,
    and rank differently under a different tiebreak parameter set."""

    def _rank(self, results, tiebreak_order):
        ranked = standings_service.prepare_teams_for_groups(
            _group_encounters(results),
            win_points=1.0,
            draw_points=0.5,
            loss_points=0.0,
            tiebreak_order=tiebreak_order,
        )
        return [team.team_id for team in ranked], {team.team_id: team for team in ranked}

    def test_group_a_reproduces_production_standings(self) -> None:
        order, by_id = self._rank(GROUP_A_RESULTS, SWISS_SETTINGS["tiebreak_order"])
        self.assertEqual(GROUP_A_PROD_ORDER, order)

        averet = by_id[2069]
        self.assertEqual((4, 1, 0, 4.5), (averet.wins, averet.draws, averet.loses, averet.points))
        # Production `buchholz` column stores the trimmed (median) Buchholz.
        self.assertEqual(7.5, averet.median_buchholz)

        # Six teams tie on 2.5 points; match_wins then median_buchholz then
        # full buchholz split them: Scorpion (2 wins) > HOTUKEV (mb 7.5,
        # bh 14.5) > DemonDimon (mb 7.5, bh 11.5) > Txao (mb 6.5) >
        # TeYzee (0 wins, mb 8.0) > NoBrain (0 wins, mb 7.5).
        cluster = [team_id for team_id in order if by_id[team_id].points == 2.5]
        self.assertEqual([2067, 2056, 2054, 2072, 2061, 2070], cluster)

    def test_group_b_reproduces_production_standings(self) -> None:
        order, by_id = self._rank(GROUP_B_RESULTS, SWISS_SETTINGS["tiebreak_order"])
        self.assertEqual(GROUP_B_PROD_ORDER, order)

        # litnik and Rasetsu tie on points (4.5), wins (4) and median
        # Buchholz (7.0); the full-Buchholz parameter decides first place
        # (13.0 vs 11.5) — with a shorter tiebreak list they would be
        # indistinguishable.
        litnik, rasetsu = by_id[2071], by_id[2068]
        self.assertEqual(litnik.points, rasetsu.points)
        self.assertEqual(litnik.wins, rasetsu.wins)
        self.assertEqual(litnik.median_buchholz, rasetsu.median_buchholz)
        self.assertGreater(litnik.buchholz, rasetsu.buchholz)

        # Production median-buchholz values for the 3.0-point cluster.
        self.assertEqual(7.5, by_id[2060].median_buchholz)
        self.assertEqual(6.5, by_id[2058].median_buchholz)
        self.assertEqual(5.5, by_id[2062].median_buchholz)

    def test_alternative_tiebreak_order_changes_ranking(self) -> None:
        """Same results, different tiebreak parameters → different table.

        bracket_default puts head_to_head before median_buchholz and demotes
        match_wins to the last slot; inside group A's six-team 2.5-point
        cluster this promotes all-draws TeYzee (strong opposition) above
        DemonDimon/Txao and drops Txao behind NoBrain.
        """
        swiss_order, _ = self._rank(GROUP_A_RESULTS, SWISS_SETTINGS["tiebreak_order"])
        default_order, _ = self._rank(GROUP_A_RESULTS, standings_service.RULE_PRESET_DEFAULTS["bracket_default"])

        self.assertNotEqual(swiss_order, default_order)
        self.assertEqual([2069, 2055, 2067, 2056, 2061, 2054, 2070, 2072, 2057, 2064], default_order)
        # Leaders and stragglers are tiebreak-insensitive.
        self.assertEqual(swiss_order[:2], default_order[:2])
        self.assertEqual(swiss_order[-2:], default_order[-2:])
        # TeYzee: 7th under the swiss preset, 5th under bracket_default.
        self.assertEqual(6, swiss_order.index(2061))
        self.assertEqual(4, default_order.index(2061))

    def test_stage_settings_resolve_tiebreak_parameters(self) -> None:
        """_tiebreak_order must prefer the explicit stage parameter list and
        fall back to the ranking_preset defaults when it is absent."""
        explicit = _stage(enums.StageType.SWISS, SWISS_SETTINGS)
        self.assertEqual(SWISS_SETTINGS["tiebreak_order"], standings_service._tiebreak_order(explicit))

        preset_only = _stage(enums.StageType.SWISS, {"ranking_preset": "challonge_swiss"})
        self.assertEqual(
            standings_service.RULE_PRESET_DEFAULTS["challonge_swiss"],
            standings_service._tiebreak_order(preset_only),
        )

        playoff = _stage(enums.StageType.DOUBLE_ELIMINATION, PLAYOFF_SETTINGS)
        self.assertEqual(PLAYOFF_SETTINGS["tiebreak_order"], standings_service._tiebreak_order(playoff))


# ---------------------------------------------------------------------------
# Swiss round generation on top of real standings
# ---------------------------------------------------------------------------


class SwissRoundGenerationTournament72Tests(TestCase):
    """generate_bracket(SWISS) must produce a legal round 5 for group A given
    the real standings and played pairs after four rounds."""

    def test_round_5_is_complete_and_rematch_free(self) -> None:
        first_four = [row for row in GROUP_A_RESULTS if row[0] <= 4]
        ranked = standings_service.prepare_teams_for_groups(
            _group_encounters(first_four),
            tiebreak_order=SWISS_SETTINGS["tiebreak_order"],
        )
        standings = [SwissStanding(team_id=team.team_id, points=team.points, buchholz=team.buchholz) for team in ranked]
        played_pairs = {frozenset({home, away}) for _, home, away, _, _ in first_four}

        skeleton = generate_bracket(
            StageType.SWISS,
            GROUP_A_TEAMS,
            swiss_standings=standings,
            swiss_played_pairs=played_pairs,
            swiss_round_number=5,
        )

        self.assertEqual(5, len(skeleton.pairings))
        self.assertIsNone(skeleton.bye_team_id)  # 10 teams — no bye
        seen: set[int] = set()
        for pairing in skeleton.pairings:
            self.assertEqual(5, pairing.round_number)
            pair = frozenset({pairing.home_team_id, pairing.away_team_id})
            self.assertEqual(2, len(pair))
            self.assertNotIn(pair, played_pairs, "swiss round 5 must not contain rematches")
            seen.update(pair)
        self.assertEqual(set(GROUP_A_TEAMS), seen)


# ---------------------------------------------------------------------------
# Double elimination playoffs: full replay of the production bracket
# ---------------------------------------------------------------------------


class DoubleEliminationPlayoffTournament72Tests(TestCase):
    """Engine skeleton + advancement edges + recorded results must reproduce
    the production playoff history and the production final standings."""

    def _skeleton(self) -> BracketSkeleton:
        return generate_bracket(
            StageType.DOUBLE_ELIMINATION,
            PLAYOFF_UB_SEEDS,
            lower_bracket_team_ids=PLAYOFF_LB_SEEDS,
            de_include_reset=False,  # de_grand_final_type == "no_reset"
        )

    def test_skeleton_shape_matches_production_bracket(self) -> None:
        skeleton = self._skeleton()

        # 2 UB semis + UB final + GF + 4 LB rounds (2+2+1+1) = 10 matches.
        self.assertEqual(10, len(skeleton.pairings))
        self.assertEqual(3, skeleton.total_rounds)
        by_round = defaultdict(list)
        for pairing in skeleton.pairings:
            by_round[pairing.round_number].append(pairing)
        self.assertEqual(
            {1: 2, 2: 1, 3: 1, -1: 2, -2: 2, -3: 1, -4: 1},
            {round_number: len(matches) for round_number, matches in by_round.items()},
        )
        self.assertEqual("Grand Final", by_round[3][0].name)

        # UB round 1 and LB round 1 carry concrete teams; production pairings.
        self.assertEqual(
            PLAYOFF_PROD_MATCHES[1],
            {frozenset({p.home_team_id, p.away_team_id}) for p in by_round[1]},
        )
        self.assertEqual(
            PLAYOFF_PROD_MATCHES[-1],
            {frozenset({p.home_team_id, p.away_team_id}) for p in by_round[-1]},
        )

    def test_replay_reproduces_production_history(self) -> None:
        encounters = _simulate_bracket(self._skeleton(), _recorded_result(PLAYOFF_RESULTS))

        played = defaultdict(set)
        for encounter in encounters:
            played[encounter.round].add(frozenset({encounter.home_team_id, encounter.away_team_id}))
        self.assertEqual(PLAYOFF_PROD_MATCHES, dict(played))

        # Grand Final: litnik (UB champion, home) 0:3 Averet (LB champion).
        grand_final = next(e for e in encounters if e.round == 3)
        self.assertEqual((2071, 2069), (grand_final.home_team_id, grand_final.away_team_id))
        self.assertEqual((0, 3), (grand_final.home_score, grand_final.away_score))

    def test_standings_match_production(self) -> None:
        encounters = _simulate_bracket(self._skeleton(), _recorded_result(PLAYOFF_RESULTS))
        calculator = standings_service.PLAYOFF_CALCULATORS[StageType.DOUBLE_ELIMINATION]
        rows = {row.id: row for row in calculator(encounters)}

        self.assertEqual(set(PLAYOFF_PROD_STANDINGS), set(rows))
        for team_id, (position, wins, loses, matches) in PLAYOFF_PROD_STANDINGS.items():
            row = rows[team_id]
            self.assertEqual(
                (position, wins, loses, matches),
                (row.ranking, row.wins, row.loses, row.matches),
                f"team {team_id}",
            )


# ---------------------------------------------------------------------------
# Single elimination: alternative format over the same entrants
# ---------------------------------------------------------------------------


class SingleEliminationFormatTournament72Tests(TestCase):
    """The same eight playoff entrants run through the SINGLE_ELIMINATION
    format: standard seeding, edge propagation and placement calculation."""

    # Overall playoff seeding (production stage_item_input slots 1..8).
    SEEDS = [2069, 2071, 2068, 2055, 2067, 2060, 2058, 2056]

    @classmethod
    def _better_seed_wins(cls, home: int, away: int) -> tuple[int, int]:
        return (2, 0) if cls.SEEDS.index(home) < cls.SEEDS.index(away) else (0, 2)

    def test_bracket_and_placements(self) -> None:
        skeleton = generate_bracket(StageType.SINGLE_ELIMINATION, self.SEEDS)

        self.assertEqual(7, len(skeleton.pairings))  # 8 teams → 7 matches
        self.assertEqual(3, skeleton.total_rounds)
        round_one = {frozenset({p.home_team_id, p.away_team_id}) for p in skeleton.pairings if p.round_number == 1}
        # Standard 1v8 / 4v5 / 2v7 / 3v6 seeding.
        self.assertEqual(
            {
                frozenset({2069, 2056}),
                frozenset({2055, 2067}),
                frozenset({2071, 2058}),
                frozenset({2068, 2060}),
            },
            round_one,
        )

        encounters = _simulate_bracket(skeleton, self._better_seed_wins)
        final = next(e for e in encounters if e.round == 3)
        self.assertEqual({2069, 2071}, {final.home_team_id, final.away_team_id})

        calculator = standings_service.PLAYOFF_CALCULATORS[StageType.SINGLE_ELIMINATION]
        rankings = {row.id: row.ranking for row in calculator(encounters)}
        self.assertEqual(
            {2069: 1, 2071: 2, 2068: 3, 2055: 3, 2067: 5, 2060: 5, 2058: 5, 2056: 5},
            rankings,
        )

    def test_engine_rejects_duplicate_entrants_across_brackets(self) -> None:
        with self.assertRaises(ValueError):
            generate_bracket(
                StageType.DOUBLE_ELIMINATION,
                PLAYOFF_UB_SEEDS,
                lower_bracket_team_ids=[PLAYOFF_UB_SEEDS[0], 2058, 2060, 2056],
            )


# ---------------------------------------------------------------------------
# Concurrent result editing by several participants
# ---------------------------------------------------------------------------

# Grand Final of tournament 72 (encounter 5660): litnik (home, 2071) vs
# Averet (away, 2069), recorded result 0:3. Captain player ids are synthetic —
# the flow only compares them against ``team.captain_id``.
GF_ENCOUNTER_ID = 5660
LITNIK_CAPTAIN = 100  # home captain
AVERET_CAPTAIN = 200  # away captain
OUTSIDER_CAPTAIN = 999  # captain of a team not in this encounter (e.g. vac3x)


@contextmanager
def _assert_http_status(test_case: IsolatedAsyncioTestCase, expected_status: int):
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - the service raises HTTPException
        test_case.assertEqual(expected_status, getattr(exc, "status_code", None))
    else:
        test_case.fail(f"expected an exception with status_code {expected_status}")


def _gf_encounter() -> SimpleNamespace:
    home_team = SimpleNamespace(id=2071, captain_id=LITNIK_CAPTAIN)
    away_team = SimpleNamespace(id=2069, captain_id=AVERET_CAPTAIN)
    return SimpleNamespace(
        id=GF_ENCOUNTER_ID,
        tournament_id=72,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        home_team=home_team,
        away_team=away_team,
        stage=SimpleNamespace(stage_type=enums.StageType.DOUBLE_ELIMINATION),
        round=3,
        result_status=enums.EncounterResultStatus.NONE,
        status=enums.EncounterStatus.OPEN,
        home_score=0,
        away_score=0,
        closeness=None,
        submitted_by_id=None,
        submitted_at=None,
        confirmed_by_id=None,
        confirmed_at=None,
        captain_reports=[],
    )


class _EditorSession(SimpleNamespace):
    """Mock AsyncSession for one service call by one participant.

    Every participant action goes through a fresh session (as separate HTTP
    requests do) but all sessions share the same ``encounter`` object — this
    models the DB row that ``SELECT … FOR UPDATE`` serialises access to.
    The first executed query (the encounter load) is captured for lock
    inspection.
    """

    def __init__(self, encounter: SimpleNamespace, linked_player_id: int) -> None:
        execute_count = 0
        captured: list[object] = []

        async def fake_execute(query):
            nonlocal execute_count
            execute_count += 1
            result_mock = Mock()
            # Every result also answers .all()/.scalars() so any query shape
            # (encounter load, player lookup, picked-pool select, challonge probe,
            # delete) is safe regardless of call order.
            result_mock.all.return_value = []
            scalars_mock = Mock()
            scalars_mock.all.return_value = []
            result_mock.scalars.return_value = scalars_mock
            if execute_count == 1:  # _load_encounter
                captured.append(query)
                result_mock.scalar_one_or_none.return_value = encounter
            elif execute_count == 2:  # linked-player lookup (submit flow)
                result_mock.scalar_one_or_none.return_value = SimpleNamespace(id=linked_player_id)
            else:  # challonge-link resolution etc. — "not linked"
                result_mock.scalar_one_or_none.return_value = None
            return result_mock

        super().__init__(
            execute=AsyncMock(side_effect=fake_execute),
            commit=AsyncMock(),
            refresh=AsyncMock(),
            flush=AsyncMock(),
            add=lambda _obj: None,
            captured_queries=captured,
        )


class ConcurrentResultEditingTournament72Tests(IsolatedAsyncioTestCase):
    """Several participants edit the Grand Final result at once.

    The system serialises concurrent editors with a row lock
    (``SELECT … FOR UPDATE`` in ``_load_encounter``); whoever acquires the
    lock first moves the result-status state machine, and every action that
    lost the race is rejected with 400 once the lock is released.
    """

    def setUp(self) -> None:
        self.encounter = _gf_encounter()
        self.recalc = AsyncMock()
        self.completed = AsyncMock()

        async def fake_finalize(_session, _encounter_id, **kwargs):
            self.encounter.status = enums.EncounterStatus.COMPLETED
            self.encounter.result_status = kwargs["result_status"]
            self.encounter.home_score = kwargs["home_score"]
            self.encounter.away_score = kwargs["away_score"]
            self.encounter.confirmed_by_id = kwargs.get("confirmed_by_id")
            self.encounter.confirmed_at = kwargs.get("confirmed_at")
            return SimpleNamespace(encounter=self.encounter, advanced_encounters=[])

        patchers = [
            patch.object(captain_service, "finalize_encounter_score", AsyncMock(side_effect=fake_finalize)),
            patch.object(captain_service, "_enqueue_tournament_recalculation", self.recalc),
            patch.object(captain_service, "_enqueue_encounter_completed", self.completed),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _session(self, player_id: int) -> _EditorSession:
        return _EditorSession(self.encounter, player_id)

    async def _report(self, player_id: int, home_score: int, away_score: int, closeness: int = 5) -> None:
        await captain_service.submit_captain_report(
            self._session(player_id),
            SimpleNamespace(id=player_id),
            encounter_id=GF_ENCOUNTER_ID,
            home_score=home_score,
            away_score=away_score,
            closeness=closeness,
        )

    async def test_encounter_row_is_locked_for_update(self) -> None:
        """The load query must request a row lock — this serialises truly
        simultaneous reporters into a deterministic order."""
        session = self._session(LITNIK_CAPTAIN)
        await captain_service.submit_captain_report(
            session,
            SimpleNamespace(id=LITNIK_CAPTAIN),
            encounter_id=GF_ENCOUNTER_ID,
            home_score=2,
            away_score=0,
            closeness=5,
        )
        self.assertIn("FOR UPDATE", str(session.captured_queries[0]))

    async def test_outsider_participant_cannot_report(self) -> None:
        with _assert_http_status(self, 403):
            await self._report(OUTSIDER_CAPTAIN, 5, 0)
        self.assertEqual(enums.EncounterResultStatus.NONE, self.encounter.result_status)
        self.recalc.assert_not_awaited()

    async def test_first_report_pending_second_matching_confirms(self) -> None:
        """One report -> pending (no completion); the second matching report
        auto-confirms and averages closeness."""
        await self._report(LITNIK_CAPTAIN, 0, 3, closeness=8)
        self.assertEqual(enums.EncounterResultStatus.PENDING_CONFIRMATION, self.encounter.result_status)
        self.assertIsNone(self.encounter.closeness)
        self.completed.assert_not_awaited()

        await self._report(AVERET_CAPTAIN, 0, 3, closeness=6)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, self.encounter.result_status)
        self.assertEqual(enums.EncounterStatus.COMPLETED, self.encounter.status)
        self.assertEqual((0, 3), (self.encounter.home_score, self.encounter.away_score))
        self.assertEqual(AVERET_CAPTAIN, self.encounter.confirmed_by_id)
        self.assertAlmostEqual(self.encounter.closeness, 0.7)  # avg(8, 6) / 10
        self.assertEqual(1, self.completed.await_count)

    async def test_mismatching_reports_dispute(self) -> None:
        await self._report(LITNIK_CAPTAIN, 2, 0)
        await self._report(AVERET_CAPTAIN, 0, 3)
        self.assertEqual(enums.EncounterResultStatus.DISPUTED, self.encounter.result_status)
        self.assertIsNone(self.encounter.closeness)
        self.completed.assert_not_awaited()

    async def test_confirmed_result_is_immutable_for_captains(self) -> None:
        await self._report(LITNIK_CAPTAIN, 0, 3)
        await self._report(AVERET_CAPTAIN, 0, 3)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, self.encounter.result_status)

        for player in (LITNIK_CAPTAIN, AVERET_CAPTAIN):
            with _assert_http_status(self, 400):
                await self._report(player, 3, 0)
        self.assertEqual((0, 3), (self.encounter.home_score, self.encounter.away_score))
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, self.encounter.result_status)

    async def test_admin_confirm_resolves_dispute(self) -> None:
        await self._report(LITNIK_CAPTAIN, 2, 0)
        await self._report(AVERET_CAPTAIN, 0, 3)
        self.assertEqual(enums.EncounterResultStatus.DISPUTED, self.encounter.result_status)

        await captain_service.admin_confirm_result(self._session(LITNIK_CAPTAIN), encounter_id=GF_ENCOUNTER_ID)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, self.encounter.result_status)
        self.assertEqual(enums.EncounterStatus.COMPLETED, self.encounter.status)


# ---------------------------------------------------------------------------
# Real advancement pipeline: finalize_encounter_score + advance_winner
# ---------------------------------------------------------------------------

finalize_module = importlib.import_module("src.services.encounter.finalize")


class _Rows:
    """Minimal stand-in for a SQLAlchemy Result."""

    def __init__(self, rows: list | None = None, scalar: object | None = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def all(self):
        return list(self._rows)


def _where_values(query) -> dict:
    """Collect ``column == value`` pairs from a statement's WHERE clause."""
    values: dict = {}
    clause = getattr(query, "whereclause", None)
    stack = [clause] if clause is not None else []
    while stack:
        node = stack.pop()
        clauses = getattr(node, "clauses", None)
        if clauses is not None:
            stack.extend(clauses)
            continue
        key = getattr(getattr(node, "left", None), "key", None)
        right = getattr(node, "right", None)
        if key is not None and hasattr(right, "value"):
            values[key] = right.value
    return values


class _BracketStore:
    """Shared in-memory 'database' for one bracket scenario."""

    def __init__(
        self,
        *,
        encounters: list[SimpleNamespace],
        links: list[SimpleNamespace],
        teams: dict[int, str],
        stages: dict[int, SimpleNamespace],
        players_by_auth: dict[int, int],
    ) -> None:
        self.encounters = {encounter.id: encounter for encounter in encounters}
        self.links = links
        self.teams = teams
        self.stages = stages
        self.players_by_auth = players_by_auth
        self.added: list[object] = []


class _BracketDbSession:
    """Query-dispatching fake AsyncSession backed by a :class:`_BracketStore`.

    Supports exactly the statements issued by the captain flow, the
    tournament-service ``finalize_encounter_score`` and the shared
    ``advance_winner`` — everything else resolves to an empty result
    (e.g. the Challonge-link probe → "not linked").
    """

    def __init__(self, store: _BracketStore) -> None:
        self.store = store

    async def execute(self, query):
        descs = getattr(query, "column_descriptions", []) or []
        first = descs[0] if descs else {}
        entity = first.get("entity")
        name = str(first.get("name", ""))
        where = _where_values(query)

        if name.startswith("max"):  # GF-reset probe: max positive round in item
            item_id = where.get("stage_item_id")
            rounds = [
                encounter.round
                for encounter in self.store.encounters.values()
                if encounter.stage_item_id == item_id and encounter.round > 0
            ]
            return _Rows(scalar=max(rounds) if rounds else None)
        if name == "stage_type":  # draw-guard stage lookup
            stage = self.store.stages.get(where.get("id"))
            return _Rows(scalar=stage.stage_type if stage else None)
        if entity is models.EncounterLink:
            source_id = where.get("source_encounter_id")
            return _Rows(rows=[link for link in self.store.links if link.source_encounter_id == source_id])
        if entity is models.User:
            player_id = self.store.players_by_auth.get(where.get("auth_user_id"))
            return _Rows(scalar=SimpleNamespace(id=player_id) if player_id is not None else None)
        if entity is models.Team:
            return _Rows(rows=list(self.store.teams.items()))
        if entity is models.Encounter:
            if "id" in where:
                return _Rows(scalar=self.store.encounters.get(where["id"]))
            matches = [
                encounter
                for encounter in self.store.encounters.values()
                if all(getattr(encounter, key, None) == value for key, value in where.items())
            ]
            return _Rows(rows=matches, scalar=matches[0] if matches else None)
        if entity is models.Stage:
            return _Rows(scalar=self.store.stages.get(where.get("id")))
        return _Rows()

    async def scalar(self, query):
        return (await self.execute(query)).scalar_one_or_none()

    async def get(self, model, primary_key, with_for_update=False):
        if model is models.Encounter:
            return self.store.encounters.get(primary_key)
        if model is models.Stage:
            return self.store.stages.get(primary_key)
        return None

    def add(self, obj) -> None:
        self.store.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, _obj) -> None:
        pass


def _db_encounter(
    *,
    enc_id: int,
    round_number: int,
    home_team_id: int | None,
    away_team_id: int | None,
    home_captain_id: int | None = None,
    away_captain_id: int | None = None,
    stage_id: int = 175,
    stage_item_id: int = 176,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=enc_id,
        tournament_id=72,
        stage_id=stage_id,
        stage_item_id=stage_item_id,
        round=round_number,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_team=SimpleNamespace(id=home_team_id, captain_id=home_captain_id),
        away_team=SimpleNamespace(id=away_team_id, captain_id=away_captain_id),
        stage=None,
        name="",
        home_score=0,
        away_score=0,
        closeness=None,
        status=enums.EncounterStatus.OPEN,
        result_status=enums.EncounterResultStatus.NONE,
        submitted_by_id=None,
        submitted_at=None,
        confirmed_by_id=None,
        confirmed_at=None,
        captain_reports=[],
    )


def _link(link_id: int, source: int, target: int, role, slot) -> SimpleNamespace:
    return SimpleNamespace(
        id=link_id,
        source_encounter_id=source,
        target_encounter_id=target,
        role=role,
        target_slot=slot,
    )


class BracketAutoAdvancementTournament72Tests(IsolatedAsyncioTestCase):
    """End-to-end result pipeline on the tail of the tournament-72 playoff
    bracket (UB Final → Grand Final, UB Final loser → LB Final), with REAL
    ``finalize_encounter_score`` and ``advance_winner`` and real
    ``EncounterLink`` rows: captain confirmation must complete the match and
    move the bracket forward automatically; admin corrections must un-wind
    stale downstream results; elimination draws must be rejected."""

    UB_FINAL = 5653  # Averet (home) vs litnik (away), round 2
    GRAND_FINAL = 5660  # round 3, both slots fed by links
    LB_FINAL = 5659  # vac3x (home) vs <UB Final loser>, round -4

    def setUp(self) -> None:
        role, slot = enums.EncounterLinkRole, enums.EncounterLinkSlot
        self.store = _BracketStore(
            encounters=[
                _db_encounter(
                    enc_id=self.UB_FINAL,
                    round_number=2,
                    home_team_id=2069,
                    away_team_id=2071,
                    home_captain_id=AVERET_CAPTAIN,
                    away_captain_id=LITNIK_CAPTAIN,
                ),
                _db_encounter(enc_id=self.GRAND_FINAL, round_number=3, home_team_id=None, away_team_id=None),
                _db_encounter(enc_id=self.LB_FINAL, round_number=-4, home_team_id=2060, away_team_id=None),
            ],
            links=[
                _link(1, self.UB_FINAL, self.GRAND_FINAL, role.WINNER, slot.HOME),
                _link(2, self.UB_FINAL, self.LB_FINAL, role.LOSER, slot.AWAY),
                _link(3, self.LB_FINAL, self.GRAND_FINAL, role.WINNER, slot.AWAY),
            ],
            teams={2069: "Averet", 2071: "litnik", 2060: "vac3x"},
            stages={
                175: SimpleNamespace(id=175, stage_type=enums.StageType.DOUBLE_ELIMINATION),
                165: SimpleNamespace(id=165, stage_type=enums.StageType.SWISS),
            },
            players_by_auth={AVERET_CAPTAIN: AVERET_CAPTAIN, LITNIK_CAPTAIN: LITNIK_CAPTAIN},
        )
        # The captain flow's outbox/event writers need a real DB — stub them;
        # finalize/advance run for real.
        for target in ("_enqueue_tournament_recalculation", "_enqueue_encounter_completed"):
            patcher = patch.object(captain_service, target, AsyncMock())
            patcher.start()
            self.addCleanup(patcher.stop)

    def _session(self) -> _BracketDbSession:
        return _BracketDbSession(self.store)

    @property
    def ub_final(self) -> SimpleNamespace:
        return self.store.encounters[self.UB_FINAL]

    @property
    def grand_final(self) -> SimpleNamespace:
        return self.store.encounters[self.GRAND_FINAL]

    @property
    def lb_final(self) -> SimpleNamespace:
        return self.store.encounters[self.LB_FINAL]

    async def _play_ub_final(self, home_score: int, away_score: int) -> None:
        # Both captains file matching reports -> the second one auto-confirms.
        for auth in (AVERET_CAPTAIN, LITNIK_CAPTAIN):
            await captain_service.submit_captain_report(
                self._session(),
                SimpleNamespace(id=auth),
                encounter_id=self.UB_FINAL,
                home_score=home_score,
                away_score=away_score,
                closeness=5,
            )

    async def test_captain_reports_complete_match_and_advance_bracket(self) -> None:
        # Averet's captain reports litnik's 0:2 win — one report alone must
        # NOT complete the match nor move the bracket.
        await captain_service.submit_captain_report(
            self._session(),
            SimpleNamespace(id=AVERET_CAPTAIN),
            encounter_id=self.UB_FINAL,
            home_score=0,
            away_score=2,
            closeness=5,
        )
        self.assertEqual(enums.EncounterStatus.OPEN, self.ub_final.status)
        self.assertIsNone(self.grand_final.home_team_id)
        self.assertIsNone(self.lb_final.away_team_id)

        # litnik's captain files a matching report → scores agree, the match
        # auto-confirms and completes…
        await captain_service.submit_captain_report(
            self._session(),
            SimpleNamespace(id=LITNIK_CAPTAIN),
            encounter_id=self.UB_FINAL,
            home_score=0,
            away_score=2,
            closeness=5,
        )
        self.assertEqual(enums.EncounterStatus.COMPLETED, self.ub_final.status)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, self.ub_final.result_status)
        self.assertEqual(LITNIK_CAPTAIN, self.ub_final.confirmed_by_id)

        # …and the bracket moves forward automatically: winner → GF home,
        # loser → LB Final away, names rebuilt from real team names.
        self.assertEqual(2071, self.grand_final.home_team_id)
        self.assertEqual("litnik vs TBD", self.grand_final.name)
        self.assertEqual(2069, self.lb_final.away_team_id)
        self.assertEqual("vac3x vs Averet", self.lb_final.name)

    async def test_admin_score_correction_unwinds_stale_downstream_results(self) -> None:
        """The remark fix: correcting an already-completed match whose winner
        changes must reset every stale downstream result, recursively."""
        await self._play_ub_final(0, 2)  # litnik advances to GF
        # LB Final and Grand Final get played on top of that outcome.
        await finalize_module.finalize_encounter_score(
            self._session(), self.LB_FINAL, home_score=1, away_score=2, source="admin"
        )
        await finalize_module.finalize_encounter_score(
            self._session(), self.GRAND_FINAL, home_score=0, away_score=3, source="admin"
        )
        self.assertEqual(2069, self.grand_final.away_team_id)
        self.assertEqual(enums.EncounterStatus.COMPLETED, self.grand_final.status)

        # Admin corrects the UB Final: Averet actually won 2:0.
        await finalize_module.finalize_encounter_score(
            self._session(), self.UB_FINAL, home_score=2, away_score=0, source="admin"
        )

        # GF home slot is rewired to Averet and its stale result is wiped.
        self.assertEqual(2069, self.grand_final.home_team_id)
        self.assertEqual(enums.EncounterStatus.OPEN, self.grand_final.status)
        self.assertEqual(enums.EncounterResultStatus.NONE, self.grand_final.result_status)
        self.assertEqual((0, 0), (self.grand_final.home_score, self.grand_final.away_score))
        # LB Final now hosts the new loser (litnik), its result is wiped too…
        self.assertEqual(2071, self.lb_final.away_team_id)
        self.assertEqual(enums.EncounterStatus.OPEN, self.lb_final.status)
        self.assertEqual((0, 0), (self.lb_final.home_score, self.lb_final.away_score))
        self.assertEqual("vac3x vs litnik", self.lb_final.name)
        # …and the cascade cleared the GF slot the stale LB result had fed.
        self.assertIsNone(self.grand_final.away_team_id)
        self.assertEqual("Averet vs TBD", self.grand_final.name)

    async def test_refinalize_with_same_winner_leaves_downstream_untouched(self) -> None:
        """Score-only correction (winner unchanged) must be a no-op for the
        rest of the bracket — played downstream matches stay played."""
        await self._play_ub_final(0, 2)
        await finalize_module.finalize_encounter_score(
            self._session(), self.LB_FINAL, home_score=1, away_score=2, source="admin"
        )
        await finalize_module.finalize_encounter_score(
            self._session(), self.GRAND_FINAL, home_score=0, away_score=3, source="admin"
        )

        await finalize_module.finalize_encounter_score(
            self._session(), self.UB_FINAL, home_score=1, away_score=2, source="admin"
        )

        self.assertEqual((1, 2), (self.ub_final.home_score, self.ub_final.away_score))
        self.assertEqual(enums.EncounterStatus.COMPLETED, self.grand_final.status)
        self.assertEqual((0, 3), (self.grand_final.home_score, self.grand_final.away_score))
        self.assertEqual(enums.EncounterStatus.COMPLETED, self.lb_final.status)
        self.assertEqual(2069, self.grand_final.away_team_id)

    async def test_elimination_draw_is_rejected(self) -> None:
        """The remark fix: a drawn score can no longer complete an
        elimination-bracket match (it would silently strand the bracket)."""
        with _assert_http_status(self, 400):
            await finalize_module.finalize_encounter_score(
                self._session(), self.UB_FINAL, home_score=1, away_score=1, source="admin"
            )
        self.assertEqual(enums.EncounterStatus.OPEN, self.ub_final.status)
        self.assertEqual((0, 0), (self.ub_final.home_score, self.ub_final.away_score))
        self.assertIsNone(self.grand_final.home_team_id)

        # The captain path hits the same guard when a second matching report
        # would auto-confirm a drawn elimination match.
        await captain_service.submit_captain_report(
            self._session(),
            SimpleNamespace(id=AVERET_CAPTAIN),
            encounter_id=self.UB_FINAL,
            home_score=1,
            away_score=1,
            closeness=5,
        )
        with _assert_http_status(self, 400):
            await captain_service.submit_captain_report(
                self._session(),
                SimpleNamespace(id=LITNIK_CAPTAIN),
                encounter_id=self.UB_FINAL,
                home_score=1,
                away_score=1,
                closeness=5,
            )
        self.assertEqual(enums.EncounterStatus.OPEN, self.ub_final.status)
        self.assertEqual(enums.EncounterResultStatus.PENDING_CONFIRMATION, self.ub_final.result_status)

    async def test_group_stage_draw_is_still_allowed(self) -> None:
        """Draws stay legal outside elimination stages (Swiss groups)."""
        swiss_encounter = _db_encounter(
            enc_id=5557,
            round_number=5,
            home_team_id=2069,
            away_team_id=2071,
            stage_id=165,
            stage_item_id=163,
        )
        self.store.encounters[swiss_encounter.id] = swiss_encounter

        result = await finalize_module.finalize_encounter_score(
            self._session(), swiss_encounter.id, home_score=1, away_score=1, source="admin"
        )

        self.assertEqual(enums.EncounterStatus.COMPLETED, swiss_encounter.status)
        self.assertEqual([], list(result.advanced_encounters))
