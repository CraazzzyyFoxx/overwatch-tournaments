"""A whole pick-ban room over the in-memory store: configs, catalogs, rosters
and the handful of calls the service suites drive it with.

Shared by ``test_pick_ban_action.py``, ``test_pick_ban_undo.py`` and
``test_pick_ban_room_scenarios.py`` so all three exercise the REAL services
(``get_pick_ban_state`` / ``perform_pick_ban_action`` / ``submit_items`` /
``dispute_step`` / ``perform_undo``) against rows that actually exist, rather
than re-mocking the runtime they are supposed to be testing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import (  # noqa: E402
    EncounterStatus,
    FirstBanRotation,
    HeroClass,
    MapPickSide,
    MapVetoMode,
    PickBanKind,
)
from shared.domain import pick_ban_rules as pbr  # noqa: E402
from shared.models.catalog.hero import Hero  # noqa: E402
from shared.models.tournament.encounter import Encounter  # noqa: E402
from shared.models.tournament.pick_ban import (  # noqa: E402
    EncounterReadiness,
    PickBanConfig,
    PickBanConfigItem,
    PickBanConfigSlot,
    PickBanConfigSlotItem,
    PickBanSession,
    PickBanSubmission,
)
from shared.models.tournament.team import Player  # noqa: E402
from src.services.encounter.map_report import map_report_service  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from src.services.encounter.pick_ban_undo import pick_ban_undo_service  # noqa: E402
from tests._pregame_store import _Store  # noqa: E402

HOME_TEAM, AWAY_TEAM = 10, 20
HOME, AWAY = MapPickSide.HOME.value, MapPickSide.AWAY.value

#: A hero catalog wide enough for two rounds of per-player bans plus slack:
#: five tanks, ten damage, ten support.
TANKS = list(range(1, 6))
DAMAGE = list(range(11, 21))
SUPPORTS = list(range(21, 31))
HEROES: dict[int, HeroClass] = {
    **dict.fromkeys(TANKS, HeroClass.tank),
    **dict.fromkeys(DAMAGE, HeroClass.damage),
    **dict.fromkeys(SUPPORTS, HeroClass.support),
}

MAP_SLOTS = [[11, 12, 13], [21, 22, 23], [31, 32, 33]]

#: One standard 5v5 roster shape per team.
ROSTER_ROLES = (HeroClass.tank, HeroClass.damage, HeroClass.damage, HeroClass.support, HeroClass.support)


def v1_ruleset(**kwargs: Any) -> dict:
    """A ruleset exactly as the v1 migration produced it."""
    payload: dict[str, Any] = {
        "kind": "hero",
        "mode": "pool",
        "preset": "custom",
        "sequence": [],
        "no_repeat_scope": "none",
        "unique_attribute": None,
        "turn_timer_seconds": None,
    }
    payload.update(kwargs)
    return pbr.ruleset_from_v1(**payload).to_json()


def hero_config(ruleset: dict, *, item_ids: list[int] | None = None) -> PickBanConfig:
    config = PickBanConfig(
        tournament_id=7,
        kind=PickBanKind.HERO,
        stage_id=None,
        round=None,
        mode=MapVetoMode.POOL,
        first_ban_rotation=FirstBanRotation.FIXED,
        ruleset_json=ruleset,
    )
    config.slots = []
    config.items = [
        PickBanConfigItem(item_id=item_id, sort_order=index)
        for index, item_id in enumerate(item_ids if item_ids is not None else sorted(HEROES))
    ]
    return config


def map_config(*, rotation: str = FirstBanRotation.RESULT_WINNER_FIRST) -> PickBanConfig:
    config = PickBanConfig(
        tournament_id=7,
        kind=PickBanKind.MAP,
        stage_id=None,
        round=None,
        mode=MapVetoMode.SLOTS,
        first_ban_rotation=rotation,
        ruleset_json=v1_ruleset(kind="map", mode="slots", preset="bracket"),
    )
    config.items = []
    config.slots = [
        PickBanConfigSlot(position=position, reserve_item_id=None) for position, _ in enumerate(MAP_SLOTS, start=1)
    ]
    for slot, item_ids in zip(config.slots, MAP_SLOTS, strict=True):
        slot.items = [PickBanConfigSlotItem(item_id=item_id) for item_id in item_ids]
    return config


def flat_map_config(ruleset: dict, item_ids: list[int]) -> PickBanConfig:
    """The classic flat veto: one pool, one round, ``round IS NULL``."""
    config = PickBanConfig(
        tournament_id=7,
        kind=PickBanKind.MAP,
        stage_id=None,
        round=None,
        mode=MapVetoMode.POOL,
        first_ban_rotation=FirstBanRotation.FIXED,
        ruleset_json=ruleset,
    )
    config.slots = []
    config.items = [PickBanConfigItem(item_id=item_id, sort_order=index) for index, item_id in enumerate(item_ids)]
    return config


def encounter(*, best_of: int = 3) -> Encounter:
    return Encounter(
        tournament_id=7,
        stage_id=None,
        stage_item_id=None,
        round=1,
        best_of=best_of,
        home_team_id=HOME_TEAM,
        away_team_id=AWAY_TEAM,
        home_score=0,
        away_score=0,
        status=EncounterStatus.OPEN,
    )


class Room:
    """One encounter's pre-game room, wired to the real services."""

    def __init__(
        self,
        *,
        hero_ruleset: dict | None = None,
        hero_items: list[int] | None = None,
        map_ruleset: dict | None = None,
        map_items: list[int] | None = None,
        with_map_veto: bool = False,
        with_rosters: bool = False,
        best_of: int = 3,
    ) -> None:
        self.store = _Store()
        self.encounter = encounter(best_of=best_of)
        rows: list[Any] = [self.encounter]
        self.hero_config = hero_config(hero_ruleset, item_ids=hero_items) if hero_ruleset is not None else None
        if self.hero_config is not None:
            rows.append(self.hero_config)
        if map_ruleset is not None:
            self.map_config = flat_map_config(map_ruleset, map_items or [])
        else:
            self.map_config = map_config() if with_map_veto else None
        if self.map_config is not None:
            rows.append(self.map_config)
        # Explicit catalog ids: the pool ids the configs name, not the store's
        # insertion order.
        rows.extend(
            Hero(id=hero_id, slug=f"h{hero_id}", name=f"H{hero_id}", image_path="", type=role)
            for hero_id, role in HEROES.items()
        )
        self.store.seed(*rows)
        self.encounter_id = self.encounter.id
        self.store.seed(
            EncounterReadiness(encounter_id=self.encounter_id, side=HOME, ready_user_id=None),
            EncounterReadiness(encounter_id=self.encounter_id, side=AWAY, ready_user_id=None),
        )
        self.players: dict[str, list[Player]] = {}
        if with_rosters:
            self._seed_rosters()

    def _seed_rosters(self) -> None:
        for side, team_id in ((HOME, HOME_TEAM), (AWAY, AWAY_TEAM)):
            roster = [
                Player(
                    name=f"{side}-{index}",
                    team_id=team_id,
                    tournament_id=7,
                    workspace_member_id=index,
                    rank=1,
                    role=role,
                    sub_role=None,
                    is_substitution=False,
                )
                for index, role in enumerate(ROSTER_ROLES, start=1)
            ]
            self.store.seed(*roster)
            self.players[side] = roster

    # -- reads -------------------------------------------------------------
    async def read(self, kind: PickBanKind = PickBanKind.HERO, viewer: str | None = HOME) -> dict:
        """The state read exactly as the RPC issues it: pure. It opens nothing,
        settles nothing, writes nothing and takes no lock."""
        return await pick_ban_action_service.get_pick_ban_state(self.store, self.encounter_id, kind, viewer_side=viewer)

    async def reconcile(self) -> bool:
        """The write-side healer the fake store cannot trigger for itself.

        A real session runs it from ``room_reconcile``'s post-commit hook; here
        every write and every read calls it by hand. Looped because a pass can
        unlock the next one (a map round settling opens the hero session, whose
        first round then owes its system steps) and because the contract is that
        it CONVERGES -- the loop would not terminate otherwise.
        """
        changed = False
        for _ in range(6):
            if not await pick_ban_action_service.reconcile_room(self.store, self.encounter_id, skip_locked=False):
                return changed
            changed = True
        raise AssertionError("reconcile_room never converged")

    async def state(self, kind: PickBanKind = PickBanKind.HERO, viewer: str | None = HOME) -> dict:
        """What a client actually SEES: the room healed, then read.

        In production the heal comes first too -- on the trigger that follows
        every room write, or on the one-second tick -- and the client refetches
        on the signal it publishes. Use :meth:`read` to assert on the read alone.
        """
        await self.reconcile()
        return await self.read(kind, viewer=viewer)

    async def open(self, kind: PickBanKind = PickBanKind.HERO) -> dict:
        """The room's first client-visible state. Session creation is a WRITE
        now, so the heal inside :meth:`state` is what performs it."""
        return await self.state(kind)

    def session(self, kind: PickBanKind = PickBanKind.HERO) -> PickBanSession:
        return next(row for row in self.store.all_of(PickBanSession) if row.kind == kind)

    def submissions(self, kind: PickBanKind = PickBanKind.HERO) -> list[PickBanSubmission]:
        session_id = self.session(kind).id
        return [row for row in self.store.all_of(PickBanSubmission) if row.session_id == session_id]

    # -- writes ------------------------------------------------------------
    async def act(
        self,
        side: str,
        item_id: int,
        *,
        kind: PickBanKind = PickBanKind.HERO,
        action: str = "ban",
        target_player_id: int | None = None,
    ) -> dict:
        await self.open(kind)
        await pick_ban_action_service.perform_pick_ban_action(
            self.store,
            self.encounter_id,
            kind,
            side,
            item_id=item_id,
            action=action,
            target_player_id=target_player_id,
        )
        return await self._settled(kind, side)

    async def submit(
        self,
        side: str,
        items: list[dict] | list[int],
        *,
        lock: bool = True,
        kind: PickBanKind = PickBanKind.HERO,
    ) -> dict:
        normalized = [item if isinstance(item, dict) else {"item_id": item, "target_player_id": None} for item in items]
        await self.open(kind)
        await pick_ban_action_service.submit_items(
            self.store, self.encounter_id, kind, side, items=normalized, lock=lock
        )
        return await self._settled(kind, side)

    async def dispute(self, side: str, *, kind: PickBanKind = PickBanKind.HERO) -> dict:
        await self.open(kind)
        await pick_ban_action_service.dispute_step(self.store, self.encounter_id, kind, side)
        return await self._settled(kind, side)

    async def admin_reopen(self, *, kind: PickBanKind = PickBanKind.HERO) -> dict:
        await self.open(kind)
        await pick_ban_action_service.admin_reopen_step(self.store, self.encounter_id, kind)
        return await self._settled(kind, None)

    async def undo(self, side: str, *, kind: PickBanKind = PickBanKind.HERO, consent: bool = True) -> dict:
        await self.open(kind)
        result = await pick_ban_undo_service.perform_undo(self.store, self.encounter_id, kind, side, consent=consent)
        await self.reconcile()
        return result

    async def _settled(self, kind: PickBanKind, viewer: str | None) -> dict:
        """The state a client sees after a write: the room healed, then re-read.
        A write commits what IT owns; everything the write made owed elsewhere
        (the other kind's rounds, the series' games) arrives with the reconcile."""
        await self.reconcile()
        return await self.state(kind, viewer=viewer)

    # -- the map/report loop ----------------------------------------------
    async def ban_out_the_map_round(self) -> int:
        """Both sides ban this round's first two candidates; the decider takes
        the survivor. Returns the map the round settled on."""
        state = await self.open(PickBanKind.MAP)
        available = [entry["item_id"] for entry in state["pool"] if entry["status"] == "available"]
        for item_id in available[:2]:
            state = await self.open(PickBanKind.MAP)
            await self.act(state["acting_sides"][0], item_id, kind=PickBanKind.MAP)
        return available[2]

    async def report(self, position: int, home_score: int, away_score: int) -> None:
        """Both captains file the same score for one position."""
        state = await self.open(PickBanKind.MAP)
        game_id = next(game["id"] for game in state["games"] if game["position"] == position)
        for side in (HOME, AWAY):
            await map_report_service.submit_map_report(
                self.store,
                self.encounter,
                game_id=game_id,
                side=side,
                reporter_user_id=None,
                home_score=home_score,
                away_score=away_score,
            )
        await self.reconcile()


def pool_of(state: dict, *, round: int | None = None) -> list[dict]:
    return [entry for entry in state["pool"] if round is None or entry["round"] == round]


def available_of(state: dict) -> list[int]:
    return [
        entry["item_id"]
        for entry in state["pool"]
        if entry["status"] == "available" and entry["round"] == state["current_round"]
    ]


def banned_of(state: dict, *, round: int | None = None) -> list[dict]:
    return [entry for entry in pool_of(state, round=round) if entry["status"] == "banned"]
