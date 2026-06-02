import sys
import os
from pathlib import Path

# Adjust paths to match main imports
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

# Set working directory to backend so .env is loaded
os.chdir(str(backend_root))

import asyncio
import sqlalchemy as sa
from src.core.db import async_session_maker
from src import models, schemas
from src.services.team import service as team_service

async def main():
    async with async_session_maker() as session:
        # Check tournaments in DB
        res_t = await session.execute(sa.select(models.Tournament.id, models.Tournament.workspace_id, models.Tournament.name))
        tournaments = res_t.all()
        print("--- Tournaments in DB ---")
        for t_id, w_id, name in tournaments:
            print(f"Tournament ID: {t_id}, Workspace ID: {w_id}, Name: {name}")

        # Check total teams in DB
        total_teams_count = (await session.execute(sa.select(sa.func.count(models.Team.id)))).scalar_one()
        print(f"\nTotal teams in database: {total_teams_count}")

        # Check teams count per tournament
        res_count = await session.execute(
            sa.select(models.Team.tournament_id, sa.func.count(models.Team.id))
            .group_by(models.Team.tournament_id)
        )
        print("\n--- Teams count per tournament ---")
        for t_id, count in res_count.all():
            print(f"Tournament ID: {t_id}, Teams count: {count}")

        # Running get_all with only_count=False to see results
        params = schemas.TeamFilterParams(
            page=1,
            per_page=100,
            only_count=False,
            tournament_id=61,
            entities=[]
        )
        print("\nRunning team_service.get_all(only_count=False, tournament_id=61, workspace_id=1)...")
        results, total = await team_service.get_all(session, params, workspace_id=1)
        print(f"Results length: {len(results)}")
        print(f"Total returned: {total}")
        for r in results:
            print(f"  Team ID: {r.id}, Name: {r.name}, Tournament ID: {r.tournament_id}")

if __name__ == "__main__":
    asyncio.run(main())
