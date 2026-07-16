"""Locust load tests for the OWT public API.

Traffic model — four user archetypes mirroring real frontend usage, all
hitting the nginx -> Go gateway edge (the same path production traffic takes):

* ``AnonymousBrowser`` (weight 6) — landing dashboard, tournament pages,
  matches, teams, cached metadata. The bulk of real traffic.
* ``ProfileViewer``   (weight 3) — player profile tabs (profile, tournaments,
  heroes, maps, teammates, encounters) and player compare.
* ``StatsAnalyst``    (weight 2) — statistics + analytics endpoints, the
  heaviest cold-cache reads in the system.
* ``SearchUser``      (weight 2) — user search / filtered user lists
  (trigram search paths).

Only the public read surface (AuthNone / AuthOptional routes) is exercised,
so no credentials are required. Auth endpoints are intentionally NOT load
tested: nginx rate-limits ``/api/auth/`` at 10 r/s per IP, so from a single
load generator they would only measure the limiter.

Run (see loadtests/README.md):
    cd loadtests
    uv run locust                     # web UI on :8089, defaults from locust.conf
    uv run locust --headless -u 100 -r 10 -t 5m --host http://localhost
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task

import config
from seed import SeedData, ensure_seeded

# Detail endpoints may legitimately 404 (hidden-tournament visibility gating,
# rows deleted between seeding and the request). Treat those as OK so the
# failure column measures real errors (5xx, 429, timeouts), not data drift.
_OK_DETAIL = frozenset({200, 404})


class OwtUser(HttpUser):
    """Shared plumbing: id pools, auth header, tolerant GET helper."""

    abstract = True
    seed: SeedData

    def on_start(self) -> None:
        self.seed = ensure_seeded(self.host or "")
        if config.AUTH_TOKEN:
            self.client.headers["Authorization"] = f"Bearer {config.AUTH_TOKEN}"

    # -- helpers ------------------------------------------------------------

    def ws_params(self, **extra: object) -> dict:
        params = dict(extra)
        if self.seed.workspace_id is not None:
            params["workspace_id"] = self.seed.workspace_id
        return params

    def pick(self, pool: list[int]) -> int | None:
        return random.choice(pool) if pool else None

    def get(self, path: str, name: str, params: dict | None = None, *, detail: bool = False) -> None:
        ok = _OK_DETAIL if detail else (200,)
        with self.client.get(path, name=name, params=params, catch_response=True) as resp:
            if resp.status_code in ok:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")


class AnonymousBrowser(OwtUser):
    """Casual visitor: dashboard -> tournament pages -> matches/teams."""

    weight = 6
    wait_time = between(1, 4)

    @task(3)
    def dashboard(self) -> None:
        self.get("/api/v1/statistics/dashboard", "/api/v1/statistics/dashboard", self.ws_params())

    @task(3)
    def list_tournaments(self) -> None:
        self.get(
            "/api/v1/tournaments",
            "/api/v1/tournaments",
            self.ws_params(page=random.randint(1, 3), per_page=20),
        )

    @task(4)
    def view_tournament(self) -> None:
        tid = self.pick(self.seed.tournament_ids)
        if tid is None:
            return
        self.get(f"/api/v1/tournaments/{tid}", "/api/v1/tournaments/[id]", detail=True)
        self.get(f"/api/v1/tournaments/{tid}/stages", "/api/v1/tournaments/[id]/stages", detail=True)
        self.get(f"/api/v1/tournaments/{tid}/standings", "/api/v1/tournaments/[id]/standings", detail=True)

    @task(2)
    def list_encounters(self) -> None:
        params = self.ws_params(page=1, per_page=20)
        tid = self.pick(self.seed.tournament_ids)
        if tid is not None:
            params["tournament_id"] = tid
        self.get("/api/v1/encounters", "/api/v1/encounters", params)

    @task(1)
    def view_encounter(self) -> None:
        eid = self.pick(self.seed.encounter_ids)
        if eid is None:
            return
        self.get(f"/api/v1/encounters/{eid}", "/api/v1/encounters/[id]", detail=True)

    @task(2)
    def view_match(self) -> None:
        mid = self.pick(self.seed.match_ids)
        if mid is None:
            return
        self.get(f"/api/v1/matches/{mid}", "/api/v1/matches/[id]", self.ws_params(), detail=True)

    @task(2)
    def view_team(self) -> None:
        team_id = self.pick(self.seed.team_ids)
        if team_id is None:
            return
        self.get(f"/api/v1/teams/{team_id}", "/api/v1/teams/[id]", detail=True)

    @task(2)
    def metadata(self) -> None:
        # Heavily cached (1-day Redis TTL) — cheap, high-frequency requests.
        path = random.choice(("/api/v1/heroes", "/api/v1/maps", "/api/v1/gamemodes", "/api/v1/achievements"))
        self.get(path, path, {"page": 1, "per_page": 50})

    @task(1)
    def list_workspaces(self) -> None:
        self.get("/api/v1/workspaces", "/api/v1/workspaces")


class ProfileViewer(OwtUser):
    """Visitor digging through a player's profile tabs."""

    weight = 3
    wait_time = between(2, 6)

    @task(4)
    def profile(self) -> None:
        uid = self.pick(self.seed.user_ids)
        if uid is None:
            return
        self.get(f"/api/v1/users/{uid}/profile", "/api/v1/users/[id]/profile", self.ws_params(), detail=True)

    @task(3)
    def profile_tournaments(self) -> None:
        uid = self.pick(self.seed.user_ids)
        if uid is None:
            return
        self.get(f"/api/v1/users/{uid}/tournaments", "/api/v1/users/[id]/tournaments", self.ws_params(), detail=True)

    @task(2)
    def profile_heroes(self) -> None:
        uid = self.pick(self.seed.user_ids)
        if uid is None:
            return
        self.get(f"/api/v1/users/{uid}/heroes", "/api/v1/users/[id]/heroes", self.ws_params(), detail=True)

    @task(2)
    def profile_maps_summary(self) -> None:
        uid = self.pick(self.seed.user_ids)
        if uid is None:
            return
        self.get(f"/api/v1/users/{uid}/maps/summary", "/api/v1/users/[id]/maps/summary", self.ws_params(), detail=True)

    @task(2)
    def profile_teammates(self) -> None:
        uid = self.pick(self.seed.user_ids)
        if uid is None:
            return
        self.get(
            f"/api/v1/users/{uid}/teammates",
            "/api/v1/users/[id]/teammates",
            self.ws_params(page=1, per_page=10),
            detail=True,
        )

    @task(2)
    def profile_encounters(self) -> None:
        uid = self.pick(self.seed.user_ids)
        if uid is None:
            return
        self.get(
            f"/api/v1/users/{uid}/encounters",
            "/api/v1/users/[id]/encounters",
            self.ws_params(page=1, per_page=10),
            detail=True,
        )

    @task(1)
    def profile_matches_summary(self) -> None:
        uid = self.pick(self.seed.user_ids)
        if uid is None:
            return
        self.get(
            f"/api/v1/users/{uid}/matches/summary",
            "/api/v1/users/[id]/matches/summary",
            self.ws_params(),
            detail=True,
        )

    @task(1)
    def compare(self) -> None:
        if len(self.seed.user_ids) < 2:
            return
        uid, other = random.sample(self.seed.user_ids, 2)
        self.get(
            f"/api/v1/users/{uid}/compare",
            "/api/v1/users/[id]/compare",
            {"baseline": "global", "target_user_id": other},
            detail=True,
        )


class StatsAnalyst(OwtUser):
    """Statistics + analytics pages — the expensive aggregate queries."""

    weight = 2
    wait_time = between(2, 5)

    @task(2)
    def champion_stats(self) -> None:
        self.get(
            "/api/v1/statistics/champion",
            "/api/v1/statistics/champion",
            self.ws_params(page=1, per_page=20),
        )

    @task(2)
    def winrate_stats(self) -> None:
        self.get(
            "/api/v1/statistics/winrate",
            "/api/v1/statistics/winrate",
            self.ws_params(page=1, per_page=20),
        )

    @task(2)
    def won_maps_stats(self) -> None:
        self.get(
            "/api/v1/statistics/won-maps",
            "/api/v1/statistics/won-maps",
            self.ws_params(page=1, per_page=20),
        )

    @task(2)
    def heroes_playtime(self) -> None:
        self.get(
            "/api/v1/heroes/statistics/playtime",
            "/api/v1/heroes/statistics/playtime",
            self.ws_params(page=1, per_page=20),
        )

    @task(2)
    def hero_leaderboard(self) -> None:
        hid = self.pick(self.seed.hero_ids)
        if hid is None:
            return
        self.get(
            f"/api/v1/heroes/{hid}/leaderboard",
            "/api/v1/heroes/[id]/leaderboard",
            self.ws_params(),
            detail=True,
        )

    @task(2)
    def tournament_statistics(self) -> None:
        kind = random.choice(("history", "division", "overall"))
        self.get(
            f"/api/v1/tournaments/statistics/{kind}",
            f"/api/v1/tournaments/statistics/{kind}",
            self.ws_params(),
        )

    @task(1)
    def analytics_algorithms(self) -> None:
        self.get("/api/analytics/algorithms", "/api/analytics/algorithms", {"page": 1, "per_page": 20})

    @task(1)
    def analytics_for_algorithm(self) -> None:
        aid = self.pick(self.seed.algorithm_ids)
        tid = self.pick(self.seed.tournament_ids)
        if aid is None or tid is None:
            return
        self.get(
            "/api/analytics",
            "/api/analytics",
            self.ws_params(algorithm=aid, tournament_id=tid),
            detail=True,
        )

    @task(1)
    def analytics_streaks(self) -> None:
        tid = self.pick(self.seed.tournament_ids)
        if tid is None:
            return
        self.get("/api/analytics/streaks", "/api/analytics/streaks", {"tournament_id": tid}, detail=True)

    @task(1)
    def analytics_balance_quality(self) -> None:
        tid = self.pick(self.seed.tournament_ids)
        if tid is None:
            return
        self.get(
            "/api/analytics/balance-quality",
            "/api/analytics/balance-quality",
            {"tournament_id": tid},
            detail=True,
        )


class SearchUser(OwtUser):
    """Type-ahead search behaviour: short prefixes of real player names."""

    weight = 2
    wait_time = between(1, 3)

    def _query(self) -> str | None:
        if not self.seed.user_names:
            return None
        name = random.choice(self.seed.user_names)
        # Simulate incremental type-ahead: 2..4-char prefix of a real name.
        return name[: random.randint(2, min(4, len(name)))]

    @task(3)
    def search(self) -> None:
        query = self._query()
        if query is None:
            return
        self.get(
            "/api/v1/users/search",
            "/api/v1/users/search",
            {"query": query, "fields": "name"},
        )

    @task(1)
    def filtered_user_list(self) -> None:
        query = self._query()
        if query is None:
            return
        self.get(
            "/api/v1/users",
            "/api/v1/users?query",
            {"page": 1, "per_page": 20, "query": query, "fields": "name"},
        )
