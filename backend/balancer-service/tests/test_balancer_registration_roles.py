from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from src import models  # noqa: E402
from src.services.admin.balancer_registration import replace_registration_roles  # noqa: E402


def test_replace_registration_roles_updates_existing_rows_in_place() -> None:
    registration = models.BalancerRegistration()
    existing_dps = models.BalancerRegistrationRole(
        role="dps",
        subrole="hitscan",
        is_primary=True,
        priority=0,
        rank_value=1200,
        is_active=True,
    )
    existing_support = models.BalancerRegistrationRole(
        role="support",
        subrole="light_heal",
        is_primary=False,
        priority=1,
        rank_value=1400,
        is_active=True,
    )
    registration.roles = [existing_dps, existing_support]

    replace_registration_roles(
        registration,
        [
            {
                "role": "dps",
                "subrole": "projectile",
                "priority": 0,
                "rank_value": 1600,
                "is_active": True,
            },
            {
                "role": "support",
                "subrole": "main_heal",
                "priority": 1,
                "rank_value": 1800,
                "is_active": False,
            },
        ],
    )

    roles_by_role = {role.role: role for role in registration.roles}

    assert len(registration.roles) == 2
    assert roles_by_role["dps"] is existing_dps
    assert roles_by_role["support"] is existing_support
    assert roles_by_role["dps"].subrole == "projectile"
    assert roles_by_role["dps"].rank_value == 1600
    assert roles_by_role["support"].subrole == "main_heal"
    assert roles_by_role["support"].rank_value == 1800
    assert roles_by_role["support"].is_active is False


def test_replace_registration_roles_removes_stale_roles_and_adds_new_ones() -> None:
    registration = models.BalancerRegistration()
    existing_dps = models.BalancerRegistrationRole(
        role="dps",
        subrole="hitscan",
        is_primary=True,
        priority=0,
        rank_value=1200,
        is_active=True,
    )
    existing_support = models.BalancerRegistrationRole(
        role="support",
        subrole="light_heal",
        is_primary=False,
        priority=1,
        rank_value=1400,
        is_active=True,
    )
    registration.roles = [existing_dps, existing_support]

    replace_registration_roles(
        registration,
        [
            {
                "role": "dps",
                "subrole": "hitscan",
                "priority": 0,
                "rank_value": 1600,
                "is_active": True,
            },
            {
                "role": "tank",
                "priority": 1,
                "rank_value": 2000,
                "is_active": True,
            },
        ],
    )

    roles_by_role = {role.role: role for role in registration.roles}

    assert len(registration.roles) == 2
    assert set(roles_by_role) == {"dps", "tank"}
    assert roles_by_role["dps"] is existing_dps
    assert roles_by_role["tank"].role == "tank"
    assert roles_by_role["tank"].rank_value == 2000


def test_replace_registration_roles_updates_top_heroes() -> None:
    from shared.hero_catalog import HeroCatalogEntry
    from shared.core import enums

    hero_catalog = {
        "ana": HeroCatalogEntry(id=1, slug="ana", hero_class=enums.HeroClass.support),
        "genji": HeroCatalogEntry(id=4, slug="genji", hero_class=enums.HeroClass.damage),
    }

    registration = models.BalancerRegistration()
    existing_dps = models.BalancerRegistrationRole(
        role="dps",
        is_primary=True,
        priority=0,
        rank_value=1200,
        is_active=True,
    )
    registration.roles = [existing_dps]

    replace_registration_roles(
        registration,
        [
            {
                "role": "dps",
                "priority": 0,
                "rank_value": 1600,
                "is_active": True,
                "top_heroes": ["genji"],
            },
        ],
        hero_catalog=hero_catalog,
        max_heroes=2,
    )

    assert len(registration.roles) == 1
    role_dps = registration.roles[0]
    assert len(role_dps.hero_entries) == 1
    assert role_dps.hero_entries[0].hero_id == 4
    assert role_dps.hero_entries[0].priority == 1

