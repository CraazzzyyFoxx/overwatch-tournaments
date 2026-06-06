import sys
import os
from pathlib import Path
import asyncio

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))
os.chdir(str(backend_root))

import sqlalchemy as sa
from src.core.db import async_session_maker
from src import models

async def test_closeness():
    async with async_session_maker() as session:
        # Get one encounter
        stmt = sa.select(models.Encounter).limit(1)
        result = await session.execute(stmt)
        encounter = result.scalar_one_or_none()
        if not encounter:
            print("No encounters found in DB")
            return
        
        orig_closeness = encounter.closeness
        print(f"Original closeness for encounter {encounter.id}: {orig_closeness}")
        
        for val in [0.1, 0.2, 0.3, 0.4, 0.5]:
            try:
                print(f"Trying to set closeness to {val}...")
                encounter.closeness = val
                await session.commit()
                print(f"Successfully committed closeness={val}")
            except Exception as e:
                print(f"Error setting closeness to {val}: {e}")
                await session.rollback()
        
        # Restore original
        encounter.closeness = orig_closeness
        await session.commit()
        print("Restored original closeness")

if __name__ == "__main__":
    asyncio.run(test_closeness())
