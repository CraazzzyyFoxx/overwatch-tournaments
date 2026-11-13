"""Shared real-PostgreSQL environment for the canonical-ingest tests.

One migrated (head) template per test module is built once: catalog/ontology projection, then the identity-service
world (real users, workspaces, API keys, resolved by the real ``validate_token`` handler) and tournament data in two
workspaces. Every test clones it, commits for real and may open independent sessions; only S3 is substituted.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared import models
from shared.core import enums
from shared.rpc.identity import rehydrate_user
from shared.services.ontology import project_disciplines
from shared.testing.stats_parity import cached_template, legacy_database, upgrade_database

STATS = Path(__file__).resolve().parents[1]
IDENTITY = STATS.parent / "identity-service"

DOC = {
    "protocol": "owt.match/1",
    "discipline": "overwatch",
    "source": {"kind": "external", "external_id": "g1"},
    "played_at": "2026-10-15T12:00:00Z",
    "duration_s": 60,
    "map": "ilios",
    "teams": [{"key": "alpha", "placement": 1}, {"key": "beta", "placement": 2}],
    "participants": [
        {
            "key": "a",
            "team": "alpha",
            "identity": {"provider": "battlenet", "id": "Ana#1234"},
            "role": {"dimension": "player_role", "role": "support"},
        },
        {"key": "b", "team": "beta", "identity": {"provider": "battlenet", "id": "Mercy#5678"}},
    ],
    "segments": [{"index": 1, "kind": "round", "attrs": {}}],
    "facts": [
        {"team": "alpha", "stat": "score", "value": 2},
        {"team": "beta", "stat": "score", "value": 1},
        {"participant": "a", "stat": "eliminations", "value": 3, "entity": "ana"},
    ],
    "events": [{"t": 10, "type": "kill", "actor": "a", "target": "b", "entity": "ana", "segment": 1}],
}


def make_doc(external_id: str | None = "g1", **changes) -> dict:
    raw = copy.deepcopy(DOC)
    raw.update(copy.deepcopy(changes))
    if external_id is None:
        raw["source"] = {"kind": raw["source"]["kind"]}
    else:
        raw["source"] = {**raw["source"], "external_id": external_id}
    return raw


def body(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


class RawStore:
    """S3 stand-in with switchable failures."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_ok = True
        self.fail_prefix: str | None = None
        self.deleted: list[str] = []
        self.delete_ok = True

    async def put_object(self, key, content):
        if not self.put_ok or (self.fail_prefix and key.startswith(self.fail_prefix)):
            return False
        self.objects[key] = content
        return True

    async def get_object(self, key):
        return self.objects.get(key)

    async def delete_object(self, key):
        if not self.delete_ok:
            return False
        self.deleted.append(key)
        return self.objects.pop(key, None) is not None or True


def _async_url(url: str):
    return make_url(url).set(drivername="postgresql+asyncpg")


def _seed_world(url: str) -> SimpleNamespace:
    """Catalog + ontology projection, identity world, then tournaments in workspaces A and B."""
    import asyncio

    async def project() -> None:
        engine = create_async_engine(_async_url(url))
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await project_disciplines(session)
            await session.commit()
        await engine.dispose()

    asyncio.run(project())
    database = make_url(url).database
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("_identity_world.py")), str(IDENTITY)],
        cwd=IDENTITY,
        env={**os.environ, "POSTGRES_DB": database},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    line = next((x for x in result.stdout.splitlines() if x.startswith("__WORLD__")), None)
    if result.returncode or line is None:
        raise RuntimeError(f"identity world failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}")
    world = json.loads(line.removeprefix("__WORLD__"))

    async def seed() -> dict:
        engine = create_async_engine(_async_url(url))
        ids: dict = {}
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            tag = uuid4().hex[:8]
            session.add_all(
                [
                    models.CatalogEntity(
                        discipline="overwatch", kind="map", slug="ilios", name=f"Ilios {tag}", attrs={}
                    ),
                    models.CatalogEntity(
                        discipline="overwatch",
                        kind="character",
                        slug="ana",
                        name=f"Ana {tag}",
                        attrs={"class": "support"},
                    ),
                ]
            )
            await session.flush()
            ilios = await session.scalar(sa.select(models.CatalogEntity).where(models.CatalogEntity.slug == "ilios"))
            for name in ("A", "B"):
                workspace_id = world["workspaces"][name]
                tournament = models.Tournament(
                    workspace_id=workspace_id,
                    discipline="overwatch",
                    name=f"{name} cup",
                    slug=f"ing-{name.lower()}-{tag}",
                )
                rule = models.ScoringRule(
                    workspace_id=workspace_id,
                    preset="wins",
                    game_formula="win",
                    end_formula="games >= best_of or max_wins * 2 > best_of",
                )
                session.add_all([tournament, rule])
                await session.flush()
                encounter = models.Encounter(
                    workspace_id=workspace_id,
                    discipline="overwatch",
                    tournament_id=tournament.id,
                    scoring_rule_id=rule.id,
                    name="Series",
                    slot_count=2,
                    status=enums.EncounterStatus.OPEN,
                )
                session.add(encounter)
                await session.flush()
                game = models.EncounterGame(
                    encounter_id=encounter.id, position=1, map_id=ilios.id, state=enums.EncounterGameState.PLANNED
                )
                session.add(game)
                await session.flush()
                ids[name] = {"tournament": tournament.id, "encounter": encounter.id, "game": game.id}
            ids["map"] = ilios.id
            await session.commit()
        await engine.dispose()
        return ids

    return SimpleNamespace(world=world, ids=asyncio.run(seed()))


def _build_ingest_template(url: str) -> dict:
    migrated = upgrade_database(url, "head")
    if migrated.returncode:
        raise RuntimeError(f"head migration failed:\n{migrated.stdout}\n{migrated.stderr}")
    seeded = _seed_world(url)
    return {"world": seeded.world, "ids": seeded.ids}


@pytest.fixture(scope="module")
def ingest_template() -> tuple[str, SimpleNamespace]:
    """The persistent, read-only ingest template; the seed reads shared models/ontology and the identity world."""
    url, payload = cached_template(
        "ingest",
        _build_ingest_template,
        Path(__file__),
        Path(__file__).with_name("_identity_world.py"),
        STATS.parent / "shared",
        IDENTITY / "src",
    )
    return url, SimpleNamespace(**payload)


@asynccontextmanager
async def open_environment(url: str, seeded: SimpleNamespace):
    engine = create_async_engine(_async_url(url))
    env = SimpleNamespace(
        sf=async_sessionmaker(engine, expire_on_commit=False),
        engine=engine,
        s3=RawStore(),
        ws=seeded.world["workspaces"],
        ids=seeded.ids,
        keys=seeded.world["keys"],
        session_identity=seeded.world["session"],
        world=seeded.world,
    )
    try:
        yield env
    finally:
        await engine.dispose()


@pytest.fixture
def ingest_database(ingest_template) -> Iterator[tuple[str, SimpleNamespace]]:
    template, seeded = ingest_template
    with legacy_database(template_url=template) as url:
        yield url, seeded


def user_of(env: SimpleNamespace, label: str):
    """The principal exactly as the worker rehydrates the identity the gateway stamped for ``label``."""
    identity = env.session_identity if label == "session" else env.keys[label]["identity"]
    assert identity is not None, f"{label} must not authenticate"
    return rehydrate_user(identity)


async def counts(env: SimpleNamespace) -> dict:
    """Everything a rejected request must leave untouched."""
    async with env.sf() as session:
        return {
            "jobs": await session.scalar(sa.select(sa.func.count()).select_from(models.IngestJob)),
            "outbox": await session.scalar(sa.select(sa.func.count()).select_from(models.EventOutbox)),
            "audit": await session.scalar(sa.select(sa.func.count()).select_from(models.AuditLog)),
            "misses": await session.scalar(sa.select(sa.func.count()).select_from(models.CatalogAliasMiss)),
            "objects": sorted(env.s3.objects),
        }
