"""Seed a live draft room for ``draft_locustfile.py``.

Everything goes through the public API, the way ``frontend/e2e`` seeds its
draft: a superuser organizer, a workspace, a draft-formation tournament, one
real account per captain (a tank main, so the pool fills two damage and two
support seats per team), the pool itself, the session (seeded in captain order
and started) and the accounts of the logged-in spectators. The room's ids and
every seat's token land in a JSON file the locustfile reads (``OWT_DRAFT_ROOM``).

The organizer is promoted to superuser with SQL, exactly like
``frontend/e2e/support/users.ts``: inside the e2e stack's throwaway Postgres,
or through ``OWT_DRAFT_PSQL`` on another stack (``README.md``, dev site).

    cd loadtests
    uv run python draft_seed.py --teams 20 --spectator-accounts 40
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

import config

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_COMPOSE = ("docker", "compose", "-p", "owt-e2e", "-f", "docker-compose.yml", "-f", "docker-compose.e2e.yml")
E2E_PSQL = (*E2E_COMPOSE, "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "anak_e2e", "-tAc")
PASSWORD = "Load-Passw0rd"
#: The captain is the team's tank; the pool fills the other four seats of an Overwatch 5v5 roster.
POOL_SEATS = ("damage", "damage", "support", "support")


class Api:
    def __init__(self, host: str, token: str | None = None) -> None:
        self.host = host.rstrip("/")
        self.http = requests.Session()
        if token:
            self.http.headers["Authorization"] = f"Bearer {token}"

    def call(self, method: str, path: str, body: Any = None, expect: int = 200) -> Any:
        resp = self.http.request(method, f"{self.host}{path}", json=body, timeout=60)
        if resp.status_code != expect:
            raise RuntimeError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else None


def sql(statement: str) -> None:
    psql = config.DRAFT_PSQL or E2E_PSQL
    subprocess.run([*psql, statement], cwd=REPO_ROOT, check=True, capture_output=True)


def make_user(host: str, prefix: str, superuser: bool = False) -> dict[str, Any]:
    name = f"{prefix}{uuid.uuid4().hex[:8]}"
    email = f"{name}@load-owt.dev"
    anon = Api(host)
    anon.call("POST", "/api/v1/auth/register", {"email": email, "username": name, "password": PASSWORD}, expect=201)
    if superuser:
        sql(f"UPDATE auth.\"user\" SET is_superuser = true, is_verified = true WHERE email = '{email}'")
    token = anon.call("POST", "/api/v1/auth/login", {"email": email, "password": PASSWORD})["access_token"]
    return {"id": Api(host, token).call("GET", "/api/v1/auth/me")["id"], "token": token}


def battle_tag() -> str:
    """A BattleTag the server's pattern accepts (2-12 chars before ``#``, 4+ digits after)."""
    return f"L{uuid.uuid4().hex[:10]}#{random.randint(1000, 9999)}"


def add_registration(api: Api, tournament_id: int, roles: list[tuple[str, int]], user_id: int | None = None) -> int:
    """An approved, organizer-created registration; ``user_id`` links it to a real account (a captain)."""
    reg = api.call(
        "POST",
        f"/api/v1/admin/balancer/tournaments/{tournament_id}/registrations",
        {
            "answers": {"identity_battlenet": [battle_tag()]},
            "status": "approved",
            "auth_user_id": user_id,
            "roles": [
                {
                    "role": {"dimension": "player_role", "role": role},
                    "rank_value": rank,
                    "is_primary": i == 0,
                    "priority": i,
                }
                for i, (role, rank) in enumerate(roles)
            ],
        },
        expect=201,
    )
    return int(reg["id"])


def seed(host: str, teams: int, extra_pool: int, spectator_accounts: int, pick_seconds: int) -> dict[str, Any]:
    organizer = make_user(host, "ltorg", superuser=True)
    api = Api(host, organizer["token"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        captains = list(pool.map(lambda i: make_user(host, f"ltcap{i}"), range(teams)))
        spectators = list(pool.map(lambda i: make_user(host, f"ltfan{i}"), range(spectator_accounts)))

    name = f"Load-{uuid.uuid4().hex[:8]}"
    workspace = api.call("POST", "/api/v1/workspaces", {"slug": name.lower(), "name": name}, expect=201)
    tournament = api.call(
        "POST",
        "/api/v1/admin/tournaments",
        {
            "workspace_id": workspace["id"],
            "discipline": "overwatch",
            "name": f"Draft {name}",
            "start_date": (date.today() + timedelta(days=7)).isoformat(),
            "end_date": (date.today() + timedelta(days=14)).isoformat(),
            "auto_transitions_enabled": False,
            "team_formation": "draft",
        },
        expect=201,
    )
    tid = int(tournament["id"])
    api.call("PATCH", f"/api/v1/admin/tournaments/{tid}/status", {"status": "draft", "force": False})

    captain_regs = [
        add_registration(api, tid, [("tank", 3600 - i * 40), ("damage", 3000 - i * 20)], user_id=cap["id"])
        for i, cap in enumerate(captains)
    ]
    for i in range(teams * len(POOL_SEATS) + extra_pool):
        role = POOL_SEATS[i % len(POOL_SEATS)]
        rank = 1800 + (i * 137) % 2200
        roles = [(role, rank)]
        # Every third player can flex, so fit and feasibility weigh real alternatives.
        if i % 3 == 0:
            roles.append(("support" if role == "damage" else "damage", rank - 150))
        add_registration(api, tid, roles)

    sessions = f"/api/v1/balancer/draft/tournaments/{tid}/sessions"
    session = api.call("POST", sessions, {"pool_source": "manual", "pick_time_seconds": pick_seconds})
    sid = int(session["id"])
    api.call(
        "POST",
        f"{sessions}/{sid}/seed",
        {"pool_captains": [{"registration_id": reg} for reg in captain_regs], "captain_order": "manual"},
    )
    api.call("POST", f"/api/v1/balancer/draft/sessions/{sid}/start")

    board = api.call("GET", f"/api/v1/balancer/draft/sessions/{sid}/board")
    team_of = {team["captain_auth_user_id"]: team["id"] for team in board["teams"]}
    return {
        "host": host,
        "workspace_id": workspace["id"],
        "tournament_id": tid,
        "session_id": sid,
        "organizer": organizer,
        "captains": [{**cap, "team_id": team_of[cap["id"]]} for cap in captains],
        "spectators": spectators,
        "pool": len(board["players"]),
        "picks": len(board["picks"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="http://localhost:8090", help="nginx edge of the e2e stack")
    parser.add_argument("--teams", type=int, default=20)
    parser.add_argument("--extra-pool", type=int, default=10, help="pool players beyond the seats to fill")
    parser.add_argument("--spectator-accounts", type=int, default=40, help="logged-in spectators")
    parser.add_argument("--pick-seconds", type=int, default=600, help="pick clock; the driver picks long before it")
    parser.add_argument("--out", default=config.DRAFT_ROOM)
    args = parser.parse_args()

    room = seed(args.host, args.teams, args.extra_pool, args.spectator_accounts, args.pick_seconds)
    Path(args.out).write_text(json.dumps(room, indent=2), encoding="utf-8")
    print(
        f"draft room: tournament={room['tournament_id']} session={room['session_id']} "
        f"teams={len(room['captains'])} pool={room['pool']} picks={room['picks']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
