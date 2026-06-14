"""Read-only diagnosis for the shift v2 ("OpenSkill + ML") algorithm on prod.

SELECT-only. Reads POSTGRES_* from backend/env/common.env itself (no secrets
printed — only host/db, never the password). Run:

    cd backend/analytics-service && uv run python scripts/diagnose_shift_v2.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

try:  # Windows consoles default to cp1252 and choke on Cyrillic team names.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ENV_FILE = Path(__file__).resolve().parents[2] / "env" / "common.env"
SHIFT_ALGORITHM_NAME = "OpenSkill + ML"


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


async def main() -> int:
    env = load_env(ENV_FILE)
    host = env.get("POSTGRES_HOST")
    port = int(env.get("POSTGRES_PORT", "5432"))
    db = env.get("POSTGRES_DB")
    user = env.get("POSTGRES_USER")
    password = env.get("POSTGRES_PASSWORD")

    print(f"Connecting to {host}:{port}/{db} as {user} …")
    try:
        conn = await asyncpg.connect(
            host=host, port=port, database=db, user=user, password=password, timeout=15
        )
    except Exception as exc:  # connectivity / auth failure
        print(f"!! CONNECT FAILED: {type(exc).__name__}: {exc}")
        return 1

    try:
        one = await conn.fetchval("SELECT 1")
        print(f"connectivity OK (SELECT 1 -> {one})\n")

        print("=== algorithms ===")
        algos = await conn.fetch(
            "SELECT id, name, produces_shifts FROM analytics.algorithms ORDER BY id"
        )
        shift_algo_id = None
        for r in algos:
            print(f"  id={r['id']:>3}  produces_shifts={r['produces_shifts']!s:<5}  {r['name']}")
            if r["name"] == SHIFT_ALGORITHM_NAME:
                shift_algo_id = r["id"]
        print(f"  -> '{SHIFT_ALGORITHM_NAME}' algorithm_id = {shift_algo_id}\n")

        print("=== latest tournaments ===")
        latest = await conn.fetchval("SELECT max(id) FROM tournament.tournament")
        total = await conn.fetchval("SELECT count(*) FROM tournament.tournament")
        print(f"  latest tournament id = {latest}   total tournaments = {total}")
        recent = await conn.fetch(
            "SELECT id, name, start_date FROM tournament.tournament ORDER BY id DESC LIMIT 15"
        )
        for r in recent:
            print(f"  #{r['id']:>4}  {str(r['start_date'])[:10]}  {r['name']}")
        print()

        print("=== active ML artifacts (freshness) ===")
        arts = await conn.fetch(
            """
            SELECT model_kind, role, version, training_cutoff_tournament_id,
                   created_at, updated_at, left(metrics::text, 300) AS metrics_head
            FROM analytics.ml_model_artifact
            WHERE is_active = true
            ORDER BY model_kind, role
            """
        )
        if not arts:
            print("  (NO active artifacts!) -> v2 inference has no model to load")
        for r in arts:
            stale = ""
            cut = r["training_cutoff_tournament_id"]
            if cut is not None and latest is not None:
                stale = f"   [latest-cutoff gap = {latest - cut}]"
            print(
                f"  {r['model_kind']:<11} role={str(r['role']):<7} v{r['version']} "
                f"cutoff={cut} created={str(r['created_at'])[:19]}{stale}"
            )
            print(f"      metrics: {r['metrics_head']}")
        print()

        if shift_algo_id is not None:
            print("=== shift v2 coverage & distribution (recent tournaments) ===")
            dist = await conn.fetch(
                """
                SELECT tournament_id,
                       count(*) AS n,
                       min(shift) AS min_shift,
                       max(shift) AS max_shift,
                       avg(shift) AS avg_shift,
                       avg(abs(shift)) AS avg_abs,
                       avg(confidence) AS avg_conf,
                       count(*) FILTER (WHERE shift = double precision 'NaN') AS nan_shift,
                       count(*) FILTER (WHERE confidence = double precision 'NaN') AS nan_conf,
                       count(*) FILTER (WHERE abs(shift) >= 2.99) AS clamped,
                       count(*) FILTER (WHERE shift = 0) AS zero_shift
                FROM analytics.shifts
                WHERE algorithm_id = $1
                GROUP BY tournament_id
                ORDER BY tournament_id DESC
                LIMIT 15
                """,
                shift_algo_id,
            )
            if not dist:
                print("  (no shift rows for this algorithm at all)")
            for r in dist:
                print(
                    f"  t#{r['tournament_id']:>4}  n={r['n']:>3}  "
                    f"shift[min/avg/max]={r['min_shift']:+.2f}/{r['avg_shift']:+.2f}/{r['max_shift']:+.2f}  "
                    f"avg|shift|={r['avg_abs']:.2f}  conf={r['avg_conf']:.2f}  "
                    f"clamped(±3)={r['clamped']}  zero={r['zero_shift']}  "
                    f"NaN(shift/conf)={r['nan_shift']}/{r['nan_conf']}"
                )
            print()

            print("=== sample of largest |shift| on the most recent populated tournament ===")
            recent_t = await conn.fetchval(
                "SELECT max(tournament_id) FROM analytics.shifts WHERE algorithm_id = $1",
                shift_algo_id,
            )
            if recent_t is not None:
                sample = await conn.fetch(
                    """
                    SELECT player_id, shift, confidence, sample_matches, sample_tournaments, log_coverage
                    FROM analytics.shifts
                    WHERE algorithm_id = $1 AND tournament_id = $2
                    ORDER BY abs(shift) DESC
                    LIMIT 12
                    """,
                    shift_algo_id,
                    recent_t,
                )
                print(f"  tournament #{recent_t}:")
                for r in sample:
                    print(
                        f"    player={r['player_id']:>6}  shift={r['shift']:+.2f}  conf={r['confidence']:.2f}  "
                        f"matches={r['sample_matches']}  tnmts={r['sample_tournaments']}  log_cov={r['log_coverage']:.2f}"
                    )
            print()

        print("=== labelled history availability (analytics.tournament, recent) ===")
        labelled = await conn.fetch(
            """
            SELECT tournament_id,
                   count(*) AS players,
                   count(*) FILTER (WHERE shift_one IS NOT NULL) AS with_prev_move
            FROM analytics.tournament
            GROUP BY tournament_id
            ORDER BY tournament_id DESC
            LIMIT 10
            """
        )
        for r in labelled:
            print(
                f"  t#{r['tournament_id']:>4}  players={r['players']:>3}  with_prev_move={r['with_prev_move']:>3}"
            )

        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
