"""``owt-1``: our player-pool export, and the one property that makes it safe.

The pool can be exported in two shapes (``RosterEngine.balancer_input`` and
``RosterEngine.full_export``). ``xv-1`` is the solver's own input contract --
``player_loader.parse_player_node`` is its only reader -- so the moment a second
format exists, the question is whether ours is still loadable. It is, by
construction: ``owt-1`` keeps every ``xv-1`` key verbatim and only adds
namespaced ones, which the loader ignores.

Two additions are load-bearing rather than cosmetic and are pinned here:

* declared-but-unranked roles ride along as ``isActive: false`` (``xv-1`` drops
  them, so the file cannot answer "is this player fully ranked yet"). The loader
  checks ``isActive`` BEFORE it compares ``rank <= 0``, so their ``null`` rank
  never reaches that comparison -- if that order ever flips, the ``None <= 0``
  TypeError silently drops the whole player, which is what the equivalence test
  below would catch.
* the roster shape travels with the file, flex slot included. The solver takes
  the flex mask from the tournament, never from the payload, so without it an
  export cannot be replayed anywhere.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from shared.core.enums import HeroClass  # noqa: E402
from shared.division_grid import DivisionGrid, DivisionTier  # noqa: E402
from shared.domain.roster import HeroRef, PlayerRoster, RosterRole  # noqa: E402
from shared.domain.roster_shape import FLEX_SLOT_CODE, parse_roster_slots  # noqa: E402
from shared.services.roster import RosterEngine  # noqa: E402
from src.domain.balancer.player_loader import load_players_from_dict  # noqa: E402

ROLE_MASK = {"tank": 1, "dps": 2, "support": 2}
FLEX_MASK = {"tank": 1, FLEX_SLOT_CODE: 4}

GRID = DivisionGrid(
    version_id=7,
    tiers=(
        DivisionTier(id=1, slug="d1", number=11, name="Diamond 1", rank_min=2500, rank_max=2999, icon_url=""),
        DivisionTier(id=2, slug="d2", number=12, name="Diamond 2", rank_min=3000, rank_max=3499, icon_url=""),
    ),
)


def _roster(
    registration_id: int,
    roles: tuple[RosterRole, ...],
    *,
    battle_tag: str | None = None,
    **overrides: object,
) -> PlayerRoster:
    return PlayerRoster(
        registration_id=registration_id,
        battle_tag=battle_tag if battle_tag is not None else f"player{registration_id}#2100",
        display_name=None,
        player_id=None,
        auth_user_id=None,
        workspace_member_id=None,
        roles=roles,
        is_full_flex=False,
        **overrides,  # type: ignore[arg-type]
    )


def _role(
    role: HeroClass,
    rank: int | None,
    *,
    priority: int = 0,
    is_primary: bool = False,
    subrole: str | None = None,
    source: str = "registration",
    top_heroes: tuple[HeroRef, ...] = (),
) -> RosterRole:
    return RosterRole(
        role=role,
        rank=rank,
        source=source,  # type: ignore[arg-type]
        is_primary=is_primary,
        priority=priority,
        subrole=subrole,
        top_heroes=top_heroes,
    )


def _pool() -> list[PlayerRoster]:
    return [
        # Ranked on both declared roles.
        _roster(
            1,
            (
                _role(HeroClass.tank, 3100, priority=0, is_primary=True, subrole="main_tank"),
                _role(HeroClass.support, 2600, priority=1),
            ),
        ),
        # Declares support too, but nothing ranked it -- the role xv-1 drops.
        _roster(
            2,
            (
                _role(HeroClass.damage, 2800, priority=0, is_primary=True),
                _role(HeroClass.support, None, priority=1, source="none"),
            ),
        ),
        # Not draftable at all: no role has a rank.
        _roster(3, (_role(HeroClass.damage, None, priority=0, source="none"),)),
    ]


def _export(**overrides):
    engine = RosterEngine()
    return engine.full_export(
        _pool(),
        shape=overrides.pop("shape", parse_roster_slots(ROLE_MASK)),
        flex_role_mode=overrides.pop("flex_role_mode", "optional"),
        grid=overrides.pop("grid", GRID),
        source=overrides.pop("source", {"tournament_id": 84, "scope": "pool"}),
        **overrides,
    )


def _loaded(payload: dict, mask: dict[str, int]) -> dict[str, tuple]:
    return {
        player.uuid: (player.name, tuple(sorted(player.ratings.items())), tuple(player.preferences))
        for player in load_players_from_dict(payload, mask)
    }


# ---------------------------------------------------------------------------
# The superset property: our file is still the solver's file
# ---------------------------------------------------------------------------


def test_owt_export_loads_exactly_like_the_xv1_export() -> None:
    engine = RosterEngine()

    assert _loaded(_export(), ROLE_MASK) == _loaded(engine.balancer_input(_pool()), ROLE_MASK)


def test_owt_export_loads_exactly_like_the_xv1_export_under_a_flex_mask() -> None:
    engine = RosterEngine()
    owt = _export(shape=parse_roster_slots(FLEX_MASK))

    loaded = _loaded(owt, FLEX_MASK)
    assert loaded == _loaded(engine.balancer_input(_pool()), FLEX_MASK)
    # The flex slot still gets the synthesized best rating through our file.
    assert dict(loaded["1"][1])[FLEX_SLOT_CODE] == 3100


def test_unranked_declared_role_travels_but_is_inactive() -> None:
    node = _export()["players"]["2"]

    assert node["stats"]["classes"]["support"] == {
        "isActive": False,
        "rank": None,
        "priority": 1,
        "subtype": None,
    }
    # ...and the loader neither rates it nor chokes on the null rank.
    assert dict(_loaded(_export(), ROLE_MASK)["2"][1]) == {"dps": 2800}


def test_undraftable_registration_is_exported_and_still_not_loaded() -> None:
    payload = _export()

    assert payload["players"]["3"]["owt"]["draftable"] is False
    # xv-1 drops it outright; ours keeps the row, the loader keeps ignoring it.
    assert "3" not in _loaded(payload, ROLE_MASK)
    assert "3" not in RosterEngine().balancer_input(_pool())["players"]


# ---------------------------------------------------------------------------
# What the format is actually for: everything xv-1 cannot say
# ---------------------------------------------------------------------------


def test_roster_shape_and_flex_mode_travel_with_the_export() -> None:
    payload = _export(shape=parse_roster_slots(FLEX_MASK), flex_role_mode="forced")

    assert payload["format"] == "owt-1"
    assert payload["roster"] == {
        "slots": {"tank": 1, FLEX_SLOT_CODE: 4},
        "team_size": 5,
        "flex_slots": 4,
        "flex_role_mode": "forced",
    }
    assert payload["source"]["tournament_id"] == 84
    assert payload["source"]["player_key"] == "registration_id"


def test_role_entries_carry_rank_source_division_and_heroes() -> None:
    engine = RosterEngine()
    roster = _roster(
        9,
        (
            _role(
                HeroClass.tank,
                3100,
                is_primary=True,
                subrole="main_tank",
                source="ow",
                top_heroes=(HeroRef(id=3, slug="dva", image_path="/dva.png"),),
            ),
        ),
    )

    owt = engine.full_export(
        [roster],
        shape=parse_roster_slots(ROLE_MASK),
        flex_role_mode="optional",
        grid=GRID,
    )["players"]["9"]["owt"]

    assert owt["roles"] == [
        {
            "role": "tank",
            "rank": 3100,
            "source": "ow",
            "is_primary": True,
            "priority": 0,
            "subrole": "main_tank",
            "playable": True,
            "division": {"number": 12, "name": "Diamond 2"},
            "top_heroes": [{"hero_id": 3, "slug": "dva", "image_path": "/dva.png"}],
        }
    ]
    assert owt["primary_role"] == "tank"
    assert owt["flex_rating"] == 3100
    assert owt["ranked_complete"] is True


def test_workflow_fields_ride_along() -> None:
    engine = RosterEngine()
    roster = _roster(
        4,
        (_role(HeroClass.tank, 3100),),
        status="approved",
        balancer_status="in_balancer",
        checked_in=True,
        registration_team_id=17,
        team_slot_code=FLEX_SLOT_CODE,
        is_substitute=True,
    )

    owt = engine.full_export(
        [roster],
        shape=parse_roster_slots(ROLE_MASK),
        flex_role_mode="optional",
    )["players"]["4"]["owt"]

    assert (owt["status"], owt["balancer_status"], owt["checked_in"]) == ("approved", "in_balancer", True)
    assert (owt["registration_team_id"], owt["team_slot_code"], owt["is_substitute"]) == (17, FLEX_SLOT_CODE, True)


# ---------------------------------------------------------------------------
# The private block is opt-in
# ---------------------------------------------------------------------------


def test_private_answers_are_withheld_unless_asked_for() -> None:
    engine = RosterEngine()
    roster = _roster(
        5,
        (_role(HeroClass.tank, 3100),),
        notes="prefers off-tank",
        admin_notes="banned last season",
        custom_fields={"shirt": "L"},
        discord_nick="player#0001",
        smurf_tags=("alt#1111",),
    )
    kwargs = {"shape": parse_roster_slots(ROLE_MASK), "flex_role_mode": "optional"}

    public = engine.full_export([roster], **kwargs)["players"]["5"]["owt"]
    private = engine.full_export([roster], include_private=True, **kwargs)["players"]["5"]["owt"]

    assert "private" not in public
    assert private["private"]["admin_notes"] == "banned last season"
    assert private["private"]["notes"] == "prefers off-tank"
    assert private["private"]["custom_fields"] == {"shirt": "L"}
    assert private["private"]["discord_nick"] == "player#0001"
    assert private["private"]["smurf_tags"] == ["alt#1111"]
