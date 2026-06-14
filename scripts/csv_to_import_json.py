"""
Convert team.csv + player.csv exports into Atravkovs-format JSON files
that can be uploaded via POST /admin/balancer/tournaments/{id}/teams/import.

Produces:
  - tournament_1_teams.json
  - tournament_2_teams.json
  - substitutions.json  (players that need manual creation via admin UI)
"""

from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


ROLE_MAP = {
    "damage": "dps",
    "support": "support",
    "tank": "tank",
}


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_import_json(teams_csv: list[dict], players_csv: list[dict], tournament_id: str) -> tuple[dict, list[dict]]:
    """Build Atravkovs-format JSON for a single tournament.

    Returns (payload_dict, list_of_substitution_players).
    """
    t_teams = [t for t in teams_csv if t["tournament_id"] == tournament_id]
    t_players = [p for p in players_csv if p["tournament_id"] == tournament_id]

    players_by_team: dict[str, list[dict]] = {}
    substitutions: list[dict] = []

    for p in t_players:
        if p["is_substitution"] == "True":
            substitutions.append(p)
            continue
        players_by_team.setdefault(p["team_id"], []).append(p)

    teams_out = []
    for team in t_teams:
        members = []
        for p in players_by_team.get(team["id"], []):
            members.append({
                "uuid": str(uuid.uuid4()),
                "name": p["name"],
                "primary": p["primary"] == "True",
                "secondary": p["secondary"] == "True",
                "role": ROLE_MAP.get(p["role"], p["role"]),
                "rank": int(p["rank"]),
            })

        teams_out.append({
            "uuid": str(uuid.uuid4()),
            "avgSr": float(team["avg_sr"]),
            "name": team["balancer_name"],
            "totalSr": int(team["total_sr"]),
            "members": members,
        })

    payload = {"data": {"teams": teams_out}}
    return payload, substitutions


def main() -> None:
    teams_csv = read_csv(SCRIPT_DIR / "team.csv")
    players_csv = read_csv(SCRIPT_DIR / "player.csv")

    all_subs = []
    for tid in ("1", "2"):
        payload, subs = build_import_json(teams_csv, players_csv, tid)
        out_path = SCRIPT_DIR / f"tournament_{tid}_teams.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Wrote {out_path.name}: {len(payload['data']['teams'])} teams")
        all_subs.extend(subs)

    if all_subs:
        subs_path = SCRIPT_DIR / "substitutions.json"
        subs_out = []
        for s in all_subs:
            subs_out.append({
                "tournament_id": int(s["tournament_id"]),
                "team_id": int(s["team_id"]),
                "user_id": int(s["user_id"]),
                "name": s["name"],
                "role": ROLE_MAP.get(s["role"], s["role"]),
                "rank": int(s["rank"]),
                "primary": s["primary"] == "True",
                "secondary": s["secondary"] == "True",
                "related_player_id": int(s["related_player_id"]) if s["related_player_id"] else None,
            })
        with open(subs_path, "w", encoding="utf-8") as f:
            json.dump(subs_out, f, ensure_ascii=False, indent=2)
        print(f"Wrote {subs_path.name}: {len(subs_out)} substitution players (add manually via admin)")


if __name__ == "__main__":
    main()
