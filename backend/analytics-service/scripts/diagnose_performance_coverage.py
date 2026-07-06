"""Read-only check: is Performance v2 materialised, or is the shift signal on
the division-BLIND fallback?

SELECT-only. Reads POSTGRES_* from backend/env/common.env itself (no secrets
printed — only host/db, never the password). Run:

    cd backend/analytics-service && uv run python scripts/diagnose_performance_coverage.py

Why: the Linear shift signal (and the v2 merit target) use Performance v2
``local_zscore`` (per-role, division-band normalised via DivisionGrid). Where a
tournament has NO ``analytics.performance`` rows, ``perf_merit`` silently falls
back to a division-BLIND ``performance_points`` z-score over the whole
(tournament, role) cohort — which biases against low divisions. This reports how
much of the recent field is on that fallback.
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
        conn = await asyncpg.connect(host=host, port=port, database=db, user=user, password=password, timeout=15)
    except Exception as exc:
        print(f"!! CONNECT FAILED: {type(exc).__name__}: {exc}")
        return 1

    try:
        print(f"connectivity OK (SELECT 1 -> {await conn.fetchval('SELECT 1')})\n")

        latest = await conn.fetchval("SELECT max(id) FROM tournament.tournament")
        total_t = await conn.fetchval("SELECT count(*) FROM tournament.tournament")
        t_with_perf = await conn.fetchval("SELECT count(DISTINCT tournament_id) FROM analytics.performance")
        perf_rows, perf_nonzero = await conn.fetchrow(
            "SELECT count(*), count(*) FILTER (WHERE local_zscore <> 0) FROM analytics.performance"
        )
        print("=== Performance v2 overall coverage ===")
        print(f"  latest tournament id = {latest}   total tournaments = {total_t}")
        print(
            f"  tournaments with ANY performance row = {t_with_perf} "
            f"({(t_with_perf / total_t * 100) if total_t else 0:.0f}% of all)"
        )
        print(
            f"  performance rows = {perf_rows}   with local_zscore != 0 = {perf_nonzero} "
            f"({(perf_nonzero / perf_rows * 100) if perf_rows else 0:.0f}%)\n"
        )

        print("=== recent tournaments: roster vs Performance v2 coverage ===")
        rows = await conn.fetch(
            """
            SELECT
              t.id,
              t.name,
              (SELECT count(*) FROM tournament.player p
                 WHERE p.tournament_id = t.id) AS roster,
              (SELECT count(*) FROM analytics.performance ap
                 WHERE ap.tournament_id = t.id) AS perf_rows,
              (SELECT count(*) FROM analytics.performance ap
                 WHERE ap.tournament_id = t.id AND ap.local_zscore <> 0) AS perf_nonzero,
              (SELECT count(*) FROM analytics.shifts s
                 WHERE s.tournament_id = t.id) AS shift_rows
            FROM tournament.tournament t
            ORDER BY t.id DESC
            LIMIT 15
            """
        )
        for r in rows:
            roster = r["roster"] or 0
            perf = r["perf_rows"] or 0
            gap = roster - perf
            on_fallback = (
                "ALL on fallback" if perf == 0 else (f"{gap} of {roster} on fallback" if gap > 0 else "covered")
            )
            print(
                f"  t#{r['id']:>4}  roster={roster:>3}  perf={perf:>3} "
                f"(nz={r['perf_nonzero']:>3})  shifts={r['shift_rows']:>3}  -> {on_fallback}"
            )
        print()

        print("=== local_zscore distribution on recent populated tournaments ===")
        dist = await conn.fetch(
            """
            SELECT tournament_id,
                   count(*) AS n,
                   min(local_zscore) AS min_z,
                   avg(local_zscore) AS avg_z,
                   max(local_zscore) AS max_z,
                   avg(local_reference_n) AS avg_ref_n
            FROM analytics.performance
            GROUP BY tournament_id
            ORDER BY tournament_id DESC
            LIMIT 10
            """
        )
        if not dist:
            print("  (no analytics.performance rows at all — shift signal is 100% on the division-blind fallback)")
        for r in dist:
            print(
                f"  t#{r['tournament_id']:>4}  n={r['n']:>3}  "
                f"z[min/avg/max]={r['min_z']:+.2f}/{r['avg_z']:+.2f}/{r['max_z']:+.2f}  "
                f"avg ref_n={r['avg_ref_n']:.1f}"
            )

        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
