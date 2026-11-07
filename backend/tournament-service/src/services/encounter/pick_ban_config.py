"""``PickBanConfig`` CRUD, validation and serialization for both kinds.

The organizer-facing half of the pick-ban domain: the list/get/upsert/delete of
the config rows that :mod:`pick_ban_session` later cascade-resolves onto an
encounter, plus the body validation and the wire shape those rows are written
and read through.

The rules themselves are a document validated by the pure engine
(:mod:`shared.domain.pick_ban_rules`); what stays here is everything the engine
cannot know -- the POOL the rules will be played out of, the cascade
coordinates, and the DB vocabulary of item groups.

The cascade RESOLUTION (which of these configs applies to a given encounter)
is the session's question, not this module's, and stays in
``pick_ban_session.resolve_config_at_level``.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.core import http_status as status
from shared.core.enums import (
    FirstBanRotation,
    FirstPickRule,
    MapVetoMode,
    PickBanKind,
)
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES, DisciplineSpec
from shared.domain import pick_ban_rules as pbr
from shared.domain.pick_ban_config import has_pool, pick_config
from shared.models.catalog.entity import CatalogEntity
from shared.models.encounter.encounter import Encounter
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.pick_ban import (
    PickBanConfig,
    PickBanConfigItem,
    PickBanConfigSlot,
    PickBanConfigSlotItem,
)
from shared.models.tournament.tournament import Tournament
from shared.repository import PickBanConfigRepository, StageRepository
from shared.repository.pick_ban import CONFIG_POOL_LOAD
from shared.services.team_format import tournament_slot_shape
from src.services.encounter.veto_session import SLOT_CANDIDATE_FLOOR

#: ``detail["code"]`` of the 422 a ruleset with validation errors raises. The
#: constructor branches on it to paint the offending fields.
RULESET_INVALID = "ruleset_invalid"


@dataclass(frozen=True)
class SlotSpec:
    """One slot of a slot-mode upsert, as plain data.

    A value type rather than the transport's pydantic body model: the service
    must not import from ``rpc/``, and every caller of the upsert agrees on
    "candidates + optional reserve" and nothing else. ``position`` is absent on
    purpose -- list order IS the position, assigned 1-based by
    :meth:`PickBanConfigService.upsert_config`.
    """

    candidates: list[int] = field(default_factory=list)
    reserve_item_id: int | None = None


# ── item groups (the DB half of the engine's vocabulary) ─────────────────────


def installed_discipline(discipline: str) -> DisciplineSpec:
    """The module behind ``discipline``; 404 ``discipline_not_installed`` for a code nobody declares.

    Never the registry's side-less stand-in: a catalog, vocabulary or save for a game that is not installed must fail,
    not quietly answer with an empty vocabulary."""
    spec = DISCIPLINES.get(discipline)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[ApiExc(code="discipline_not_installed", msg=f"Discipline {discipline!r} is not installed")],
        )
    return spec


async def tournament_discipline(session: AsyncSession, tournament_id: int) -> str:
    """The tournament's discipline code: the owner scope every rule, group and pool of its configs is read in."""
    code = await session.scalar(select(Tournament.discipline).where(Tournament.id == tournament_id))
    if code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return str(code)


async def group_vocabulary(session: AsyncSession, kind: PickBanKind, discipline: str) -> list[str]:
    """Every ``item_group`` value a condition of this kind may name in ``discipline``.

    The engine is pure and cannot know them: a character's group is its class, which is the discipline module's
    declared ``character_classes`` (never an assigned player role), but a map's group is its gamemode slug, which is
    catalog data an admin edits -- and a game that declares no ``mode`` kind (League) has none. Both the catalog op
    (what the constructor offers) and the upsert validation (what it accepts) read the vocabulary from here so the
    editor can never author a group the validator then refuses.
    """
    spec = installed_discipline(discipline)
    if kind == PickBanKind.HERO:
        return [group for group in (pbr.normalize_group(name) for name in spec.character_classes) if group]
    if "mode" not in spec.kinds:
        return []
    slugs = await session.scalars(
        select(CatalogEntity.slug)
        .where(CatalogEntity.kind == "mode", CatalogEntity.discipline == discipline)
        .order_by(CatalogEntity.slug)
    )
    return [group for group in (pbr.normalize_group(slug) for slug in slugs) if group]


async def pool_composition(
    session: AsyncSession, kind: PickBanKind, item_ids: Sequence[int], discipline: str
) -> tuple[dict[str, int], int]:
    """``({group: how many pool items are in it}, pool size)`` -- the preview's budget.

    "How many supports are left on map 5?" is only answerable against a real
    pool, so the preview takes the counts rather than the ids. Only items of
    ``discipline`` and of the kind's catalog count: an id of another game is not a
    member of this pool. An item with no group (a League map has no gamemode, a
    champion may have no class) still counts toward the size: the pool's
    cardinality never depends on optional grouping data.
    """
    if not item_ids:
        return {}, 0
    if kind == PickBanKind.HERO:
        query = select(CatalogEntity.attrs["class"].astext).where(
            CatalogEntity.id.in_(item_ids),
            CatalogEntity.kind == "character",
            CatalogEntity.discipline == discipline,
        )
    else:
        mode = aliased(CatalogEntity, name="mode")
        query = (
            select(mode.slug)
            .select_from(CatalogEntity)
            .outerjoin(
                mode,
                and_(mode.id == CatalogEntity.parent_id, mode.kind == "mode", mode.discipline == discipline),
            )
            .where(
                CatalogEntity.id.in_(item_ids),
                CatalogEntity.kind == "map",
                CatalogEntity.discipline == discipline,
            )
        )
    counts: dict[str, int] = {}
    size = 0
    for raw in await session.scalars(query):
        size += 1
        group = pbr.normalize_group(raw)
        if group:
            counts[group] = counts.get(group, 0) + 1
    return counts, size


async def assert_pool_in_discipline(
    session: AsyncSession,
    *,
    kind: PickBanKind,
    discipline: str,
    item_ids: Sequence[int],
    slots: Sequence[tuple[Sequence[int], int | None]],
) -> set[int]:
    """Every pool id (flat items, slot candidates and reserves) is a catalog row of ``discipline`` and of the
    kind's catalog (a character for the hero kind, a map for the map kind); 422 ``pool_item_not_in_catalog``
    otherwise. A map pool's flat items may also name the discipline's modes when it declares the ``mode`` kind: ingest
    then admits only logs of those modes, and a room never offers a mode as a map (``CONFIG_ROOM_LOAD``). Returns
    those mode items. The shared save boundary: the admin upsert and the scrim custom pool both go through it."""
    wanted = set(item_ids)
    for candidates, reserve in slots:
        wanted.update(candidates)
        if reserve is not None:
            wanted.add(reserve)
    if not wanted:
        return set()
    found = set(
        await session.scalars(
            select(CatalogEntity.id).where(
                CatalogEntity.id.in_(wanted),
                CatalogEntity.kind == ("character" if kind == PickBanKind.HERO else "map"),
                CatalogEntity.discipline == discipline,
            )
        )
    )
    modes: set[int] = set()
    flat = set(item_ids) - found
    if kind == PickBanKind.MAP and flat and "mode" in installed_discipline(discipline).kinds:
        modes = set(
            await session.scalars(
                select(CatalogEntity.id).where(
                    CatalogEntity.id.in_(flat),
                    CatalogEntity.kind == "mode",
                    CatalogEntity.discipline == discipline,
                )
            )
        )
    if missing := sorted(wanted - found - modes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                ApiExc(
                    code="pool_item_not_in_catalog",
                    msg=f"Not a {discipline} {kind.value} catalog item: {', '.join(str(item) for item in missing)}",
                )
            ],
        )
    return modes


async def scope_best_of(
    session: AsyncSession, *, tournament_id: int, kind: PickBanKind, stage_id: int | None, round: int | None
) -> int | None:
    """The longest series a config saved at this cascade level would play.

    Read off the generated bracket: every encounter the level covers, minus those a narrower pooled config already
    serves (they never reach this one). ``None`` before the bracket exists -- the editor's preview is the check then.
    """
    query = (
        select(BracketEncounter.stage_id, BracketEncounter.round, Encounter.best_of)
        .join(Encounter, Encounter.id == BracketEncounter.encounter_id)
        .where(BracketEncounter.tournament_id == tournament_id)
    )
    if stage_id is not None:
        query = query.where(BracketEncounter.stage_id == stage_id)
    if round is not None:
        query = query.where(BracketEncounter.round == round)
    level = 0 if stage_id is None else 1 if round is None else 2
    narrower = [
        config
        for config in await pick_ban_config_service.list_configs(session, tournament_id=tournament_id, kind=kind)
        if has_pool(config) and (0 if config.stage_id is None else 1 if config.round is None else 2) > level
    ]
    lengths = [
        best_of
        for encounter_stage, encounter_round, best_of in (await session.execute(query)).all()
        if pick_config(narrower, stage_id=encounter_stage, round=encounter_round) is None
    ]
    return max(lengths, default=None)


async def validate_config(
    session: AsyncSession,
    *,
    kind: PickBanKind,
    mode: MapVetoMode,
    ruleset: Any,
    item_ids: Sequence[int],
    slots: Sequence[tuple[Sequence[int], int | None]],
    stage_id: int | None,
    round: int | None,
    discipline: str,
    tournament_id: int | None = None,
) -> None:
    """The whole save gate of a config body: the pool's membership in the discipline's catalog, the ruleset against
    the discipline's group vocabulary, and the pool's shape (its mode items do not count toward a room's demand).
    ``tournament_id`` lets a progressive pool be sized against the series its bracket actually plays."""
    modes = await assert_pool_in_discipline(session, kind=kind, discipline=discipline, item_ids=item_ids, slots=slots)
    best_of = None
    if mode == MapVetoMode.PROGRESSIVE and tournament_id is not None:
        best_of = await scope_best_of(session, tournament_id=tournament_id, kind=kind, stage_id=stage_id, round=round)
    validate_config_payload(
        kind=kind,
        mode=mode,
        ruleset=ruleset,
        item_ids=item_ids,
        slots=slots,
        stage_id=stage_id,
        round=round,
        discipline=discipline,
        groups=await group_vocabulary(session, kind, discipline),
        modes=modes,
        best_of=best_of,
    )


async def roster_slot_counts(session: AsyncSession, tournament_id: int) -> dict[str, int] | None:
    """``{role: players per team}`` for the preview's per-player ban arithmetic.

    A per-player ban step spends one ban on each opponent player whose role the
    hero matches, so a role can absorb at most as many bans per round as the
    team fields players in it. Without this the preview has to assume every ban
    of such a step lands on one role and reports a far bleaker map 5 than the
    rules can actually produce.

    The tournament owns its frozen format; its projection is also what the
    organizer's editor displays.

    Handed to the engine RAW. It matches keys case-insensitively, drops
    non-positive counts and ignores keys that are not pool groups -- and
    ``flex`` MUST survive: a role-less player matches every hero under
    ``target_role_match``, so their bans raise every role's ceiling. Filtering
    flex out here would make the preview optimistic and swallow a real warning.
    """
    return (await tournament_slot_shape(session, tournament_id)).slots


# ── upsert validation ────────────────────────────────────────────────────────


def validate_pick_ban_slot_config(slots: list[list[int]], *, reserves: list[int | None]) -> None:
    """Validate the slot POOL of a slot-mode :class:`PickBanConfig` upsert.

    A slot is a pool partition, not a rule -- the steps that ban a slot down to
    its survivor are the ``slot_veto`` generator's business. Items are map or
    hero ids, per the config's ``kind``."""
    if not slots:
        raise HTTPException(status_code=422, detail="slots must not be empty")
    if len(reserves) != len(slots):
        raise HTTPException(status_code=422, detail="reserves must have one entry per slot")
    for index, (candidates, reserve) in enumerate(zip(slots, reserves, strict=True), start=1):
        if len(candidates) < SLOT_CANDIDATE_FLOOR:
            raise HTTPException(status_code=422, detail=f"slot {index} must have at least two candidate items")
        if len(set(candidates)) != len(candidates):
            repeated = ", ".join(str(m) for m in sorted({m for m in candidates if candidates.count(m) > 1}))
            raise HTTPException(status_code=422, detail=f"slot {index} must not repeat candidate item(s): {repeated}")
        if reserve is not None and reserve in candidates:
            raise HTTPException(status_code=422, detail=f"slot {index} reserve must not be one of its own candidates")


#: Stand-in seats: only HOW MANY participations an actor token resolves to
#: matters to the demand, never which.
_DEMAND_SEATS = (1, 2)


def _phase_demand(phase: pbr.Phase) -> int:
    """How many pool items one round of ``phase`` consumes, worst case.

    Each item-spending step spends ``count`` per acting participation
    (``both`` is everyone); a decider settles exactly one, and a side pick
    spends nothing from the pool. Actors come from the engine's own resolver so
    the two never drift.
    """

    def _spend(step: pbr.Step) -> int:
        if step.action == "decider":
            return 1
        if step.action == "side_pick":
            return 0
        try:
            actors = pbr.resolve_actors(step.actors, participants=_DEMAND_SEATS, opener=_DEMAND_SEATS[0])
        except pbr.UnassignedSide:
            # ``side:<code>`` only resolves once the round's ``side_pick`` is
            # played, and it always names exactly ONE participation -- which is
            # all the demand arithmetic needs, so it is counted rather than
            # raising a 500 on a perfectly valid sided ruleset.
            actors = [_DEMAND_SEATS[0]]
        return step.count * len(actors)

    return sum(_spend(step) for step in phase.steps)


def validate_config_payload(
    *,
    kind: PickBanKind,
    mode: MapVetoMode,
    ruleset: Any,
    item_ids: Sequence[int],
    slots: Sequence[tuple[Sequence[int], int | None]],
    stage_id: int | None,
    round: int | None,
    discipline: str,
    groups: Sequence[str] | None = None,
    modes: Collection[int] = (),
    best_of: int | None = None,
) -> None:
    """Everything an upsert body must satisfy before it becomes a config row.

    Two halves that cannot be merged: the RULES are validated by the pure
    engine (``pbr.validate_ruleset``), which knows nothing about the pool; the
    POOL is validated here, because only the transport layer knows whether the
    caller sent slots or a flat list and how big it is.

    A pool-less row is a rules TEMPLATE -- authored at a wide cascade scope so
    narrower ones inherit its rotation and steps. It plays nothing
    (``ensure_pick_ban_session`` refuses to open a room on a config with no
    pool), so the pool-shaped rules have nothing to hold and are not checked.
    Except a hero template that picks sides: 422 ``pool_required``, because
    ``side_pick_required`` reads its side step all the same and would hold every
    game's result behind a room that never opens.

    ``groups`` is the kind's item-group vocabulary (see :func:`group_vocabulary`);
    ``None`` skips map-group name checks. ``discipline`` decides what the actor
    vocabulary may say -- whether the game has sides to pick at all. ``modes``
    are the flat items that are modes, not maps: they restrict logs, never a
    room, so a pool of only modes is a template to the room. ``best_of`` is the
    longest series the scope plays (progressive mode only): every map of it has
    to find its maps in what the earlier ones left.
    """
    if round is not None and stage_id is None:
        raise HTTPException(status_code=422, detail="round requires stage_id")

    issues = pbr.validate_ruleset(ruleset, kind=kind.value, mode=mode.value, discipline=discipline, groups=groups)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        # A dict detail WITHOUT ``msg``: ``shared.rpc.common.http_error``'s
        # attribute-bag branch is the only one that carries extra keys through
        # to the client untouched (the ``msg`` branch flattens to field/msg/code
        # and would drop ``issues``). Warnings ride along so the editor can show
        # them next to the blockers it must fix.
        raise HTTPException(
            status_code=422,
            detail={
                "code": RULESET_INVALID,
                "message": f"ruleset has {len(errors)} validation error(s)",
                "issues": [issue.to_json() for issue in issues],
            },
        )

    if (
        kind == PickBanKind.HERO
        and not item_ids
        and not slots
        and any(step.action == "side_pick" for phase in pbr.parse_ruleset(ruleset).phases for step in phase.steps)
    ):
        label = installed_discipline(discipline).kinds.get("character", "character").lower()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                ApiExc(
                    code="pool_required",
                    msg=(
                        f"These rules pick sides, so the {label} pool has to be saved first: "
                        "without a pool the room never opens and every game waits on its side pick"
                    ),
                )
            ],
        )

    if mode == MapVetoMode.SLOTS:
        if item_ids:
            raise HTTPException(status_code=422, detail="item_ids must be empty in slots mode")
        if slots:
            validate_pick_ban_slot_config(
                [list(candidates) for candidates, _ in slots],
                reserves=[reserve for _, reserve in slots],
            )
        return

    if slots:
        raise HTTPException(status_code=422, detail="slots must be empty in pool mode")
    if not item_ids:
        return
    if len(set(item_ids)) != len(item_ids):
        raise HTTPException(status_code=422, detail="item_ids must be unique")
    # Only the map kind can run out: a hero phase bans out of a pool that stays
    # playable and is replayed per map, so its steps are not "spent" items.
    if kind != PickBanKind.MAP:
        return
    maps = len([item for item in item_ids if item not in modes])
    if not maps:
        return
    for index, phase in enumerate(pbr.parse_ruleset(ruleset).phases):
        if phase.generator is not None:
            # A generator sizes itself to the pool it is given.
            continue
        demand = _phase_demand(phase)
        if demand > maps:
            raise HTTPException(
                status_code=422,
                detail=f"phase {index} ({phase.id}) consumes {demand} items per map but the pool has only {maps}",
            )
    if mode == MapVetoMode.PROGRESSIVE and best_of is not None:
        preview = pbr.preview_series(
            ruleset, kind=kind.value, discipline=discipline, mode=mode.value, best_of=best_of, pool_size=maps
        )
        exhausted = next((issue for issue in preview["issues"] if issue["code"] == pbr.POOL_EXHAUSTED), None)
        if exhausted is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[
                    ApiExc(
                        code="pool_too_small",
                        msg=f"This bracket plays up to best-of-{best_of}: {exhausted['message']}. Add maps or ban fewer.",
                    )
                ],
            )


def serialize_pick_ban_config(config: PickBanConfig) -> dict:
    return {
        "id": config.id,
        "tournament_id": config.tournament_id,
        "kind": config.kind,
        "stage_id": config.stage_id,
        "round": config.round,
        "mode": config.mode,
        "first_pick_rule": config.first_pick_rule,
        "first_ban_rotation": config.first_ban_rotation,
        "ruleset": config.ruleset_json,
        "item_ids": [item.item_id for item in config.items],
        "slots": [
            {
                "position": slot.position,
                "reserve_item_id": slot.reserve_item_id,
                "candidates": [item.item_id for item in slot.items],
            }
            # Play order, not row order -- the relationship's own order_by
            # already sorts a DB-loaded config, but this must not depend on
            # that: a transient/in-memory config (stage-merge copier, tests)
            # is not guaranteed sorted.
            for slot in sorted(config.slots, key=lambda s: s.position)
        ],
    }


def normalized_ruleset(ruleset: Any) -> dict:
    """The ruleset as the database stores it: parsed, defaulted, re-dumped.

    Storing the raw body would let two configs that mean the same thing differ
    byte-wise, which the stage-merge signature and the session snapshot both
    compare. ``parse_ruleset`` raises ``RulesetError`` on a malformed document;
    every write path validates first, so reaching it here is a bug, not a user
    error.
    """
    return pbr.parse_ruleset(ruleset).to_json()


class PickBanConfigService:
    def __init__(
        self,
        *,
        config_repo: PickBanConfigRepository = PickBanConfigRepository(),
        stage_repo: StageRepository = StageRepository(),
    ) -> None:
        self.config_repo = config_repo
        self.stage_repo = stage_repo

    async def list_configs(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        kind: PickBanKind | None = None,
    ) -> Sequence[PickBanConfig]:
        """Every config in a tournament, cascade order, pool eagerly loaded.

        ``kind=None`` lists both kinds (the admin editor's view); a kind narrows
        it to one (the public map-config read).

        Ordered here rather than in the repository: the ordering IS the cascade
        the resolver applies -- most general first, ``NULL`` stage before a
        stage, ``NULL`` round before a round -- so it is a domain rule, not a
        CRUD default. Leading with ``kind`` groups the two rulebooks in the
        admin view and is a no-op once ``kind`` is given.
        """
        query = self.config_repo.select().where(PickBanConfig.tournament_id == tournament_id)
        if kind is not None:
            query = query.where(PickBanConfig.kind == kind)
        query = query.options(*CONFIG_POOL_LOAD).order_by(
            PickBanConfig.kind.asc(),
            PickBanConfig.stage_id.asc().nulls_first(),
            PickBanConfig.round.asc().nulls_first(),
            PickBanConfig.id.asc(),
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def get_config(self, session: AsyncSession, config_id: int) -> PickBanConfig:
        """One config by id, or 404. The pool is NOT loaded: the only caller
        needs the row's ``tournament_id`` to gate on and then deletes it."""
        config = await self.config_repo.get(session, config_id)
        if config is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pick-ban config not found")
        return config

    async def upsert_config(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        kind: PickBanKind,
        stage_id: int | None = None,
        round: int | None = None,
        mode: MapVetoMode,
        first_pick_rule: FirstPickRule,
        first_ban_rotation: FirstBanRotation,
        ruleset: Any,
        item_ids: list[int],
        slots: Sequence[SlotSpec] = (),
    ) -> PickBanConfig:
        """Create or update the config at the ``(tournament, kind, stage, round)``
        cascade level, replacing its pool wholesale.

        Does NOT commit: the caller owns the unit of work (and, for the admin
        route, the ``refresh`` + serialization that follows it). Body-shape
        validation is the caller's too -- :func:`validate_config_payload` --
        because it depends only on the payload, never on the database.
        """
        if stage_id is not None:
            stage_tournament_id = await self.stage_repo.get_tournament_id(session, stage_id)
            if stage_tournament_id is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
            if stage_tournament_id != tournament_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Stage does not belong to this tournament",
                )

        ruleset_json = normalized_ruleset(ruleset)

        # Upsert key = (tournament_id, kind, stage_id, round): one config per
        # cascade level and kind.
        config = await self.config_repo.find_for_stage_round(
            session,
            tournament_id=tournament_id,
            kind=kind,
            stage_id=stage_id,
            round=round,
            options=CONFIG_POOL_LOAD,
        )

        if config is None:
            config = PickBanConfig(
                tournament_id=tournament_id,
                kind=kind,
                stage_id=stage_id,
                round=round,
                mode=mode,
                first_pick_rule=first_pick_rule,
                first_ban_rotation=first_ban_rotation,
                ruleset_json=ruleset_json,
                # Set while pending: initializes both collections locally, so the
                # replacement below assigns onto loaded collections. Without them
                # `create`'s flush makes the row persistent with `items`/`slots`
                # unloaded and the assignment lazy-loads -> `MissingGreenlet`.
                items=[],
                slots=[],
            )
            await self.config_repo.create(session, config)
        else:
            config.mode = mode
            config.first_pick_rule = first_pick_rule
            config.first_ban_rotation = first_ban_rotation
            config.ruleset_json = ruleset_json
            # Wholesale replace, cleared+flushed first: SQLAlchemy would otherwise
            # emit the new children's INSERTs before the old ones' DELETEs and trip
            # the plain UNIQUE constraints on position/item_id. The clear rides the
            # `delete-orphan` cascade, so the loaded collection stays in step.
            config.items = []
            config.slots = []
            await session.flush()

        config.items = [PickBanConfigItem(item_id=item_id, sort_order=idx) for idx, item_id in enumerate(item_ids)]
        config.slots = [
            PickBanConfigSlot(
                position=index + 1,
                reserve_item_id=slot.reserve_item_id,
                items=[
                    PickBanConfigSlotItem(item_id=item_id, sort_order=order)
                    for order, item_id in enumerate(slot.candidates)
                ],
            )
            for index, slot in enumerate(slots)
        ]
        return config

    async def delete_config(self, session: AsyncSession, config_id: int) -> None:
        """Delete one config, or 404. Its items/slots go with it through the
        same ``delete-orphan`` cascade the upsert's replacement rides."""
        config = await self.get_config(session, config_id)
        await self.config_repo.delete(session, config)


pick_ban_config_service = PickBanConfigService()

__all__ = (
    "RULESET_INVALID",
    "PickBanConfigService",
    "SlotSpec",
    "assert_pool_in_discipline",
    "group_vocabulary",
    "normalized_ruleset",
    "pick_ban_config_service",
    "pool_composition",
    "roster_slot_counts",
    "serialize_pick_ban_config",
    "validate_config",
    "validate_config_payload",
    "validate_pick_ban_slot_config",
)
