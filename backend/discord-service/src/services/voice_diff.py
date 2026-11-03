"""The pure half of the voice reconciler: plan + rows + what Discord shows now -> what to do.

Nothing here touches Discord or the database, so every rule of ``docs/tournament-voice-channels.md``
("Applying the plan") is testable with plain values. :mod:`src.services.voice_sync` observes Discord
into :class:`Seen`, calls :func:`diff`, and applies the returned operations through the guild queue.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import discord

from shared.schemas.voice import VoicePlan

__all__ = (
    "CATEGORY_LIMIT",
    "DELETE_AFTER",
    "CreateCategory",
    "CreateChannel",
    "Diff",
    "EditCategory",
    "EditChannel",
    "Forget",
    "Issue",
    "MarkDeleting",
    "Overwrites",
    "Reorder",
    "Revive",
    "Row",
    "Seen",
    "SeenChannel",
    "deletion_due",
    "diff",
    "permission_issues",
    "private_overwrites",
    "select_round_moves",
)

#: Discord's limit of children per category, foreign channels included.
CATEGORY_LIMIT = 50
#: A dropped channel is deleted once empty, or this long after it was dropped.
DELETE_AFTER = timedelta(minutes=10)

#: ``{("role" | "member", id): (allow bits, deny bits)}`` -- one channel's permission overwrites.
Overwrites = dict[tuple[str, int], tuple[int, int]]

_VIEW_CONNECT = discord.Permissions(view_channel=True, connect=True).value
_GUEST = discord.Permissions(view_channel=True, connect=True, speak=True).value
_BOT = discord.Permissions(
    view_channel=True, connect=True, move_members=True, manage_channels=True, manage_permissions=True
).value

# What the bot needs in the guild (and in the category it puts channels in).
_NEEDED = ("manage_channels", "manage_roles", "move_members", "view_channel", "connect")


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Row:
    """One ``tournament.voice_channel`` row."""

    slot_key: str
    kind: str
    channel_id: int | None
    owned: bool = True
    status: str = "active"
    delete_requested_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SeenChannel:
    id: int
    name: str
    #: ``None`` for a category and for a channel outside any.
    parent_id: int | None = None
    position: int = 0
    is_category: bool = False
    #: A voice channel whose permissions follow its category.
    synced: bool = False
    overwrites: Overwrites = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Seen:
    """The guild as the bot's cache shows it."""

    channels: Mapping[int, SeenChannel]
    everyone_id: int
    bot_id: int
    role_ids: frozenset[int] = frozenset()
    #: Every member of the guild, or ``None`` when the cache is not complete (then no id is dropped up front).
    member_ids: frozenset[int] | None = None


# --- operations ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateCategory:
    ref: str
    name: str
    #: Placed right after this category (``category:<n-1>``); ``None`` for the first one.
    after: str | None = None


@dataclass(frozen=True, slots=True)
class EditCategory:
    ref: str
    name: str | None = None
    after: str | None = None


@dataclass(frozen=True, slots=True)
class CreateChannel:
    slot_key: str
    kind: str
    name: str
    category_ref: str
    stage_id: int | None = None
    team_id: int | None = None
    #: ``None``: public, follows the category.
    overwrites: Overwrites | None = None


@dataclass(frozen=True, slots=True)
class EditChannel:
    slot_key: str
    name: str | None = None
    category_ref: str | None = None
    #: Follow the category again (public channel).
    sync: bool = False
    #: Write exactly these overwrites (private channel).
    overwrites: Overwrites | None = None


@dataclass(frozen=True, slots=True)
class Reorder:
    category_ref: str
    slot_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarkDeleting:
    slot_key: str


@dataclass(frozen=True, slots=True)
class Revive:
    slot_key: str


@dataclass(frozen=True, slots=True)
class Forget:
    """Drop a row whose Discord channel is gone and which the plan does not want back."""

    slot_key: str


Op = CreateCategory | EditCategory | CreateChannel | EditChannel | Reorder | MarkDeleting | Revive | Forget


@dataclass(slots=True)
class Diff:
    ops: list[Op] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    #: ``category:<n>`` -> the Discord category that already exists for it (the organizer's one included).
    categories: dict[str, int] = field(default_factory=dict)


# --- permissions --------------------------------------------------------------------------------


def _norm(overwrites: Overwrites) -> Overwrites:
    return {key: pair for key, pair in overwrites.items() if pair != (0, 0)}


def private_overwrites(
    base: Overwrites, *, everyone_id: int, staff_role_ids: Sequence[int], member_ids: Sequence[int], bot_id: int
) -> Overwrites:
    """The category's overwrites, then deny ``@everyone``, allow staff roles and members, allow the bot."""
    out = dict(base)

    def allow(key: tuple[str, int], bits: int) -> None:
        a, d = out.get(key, (0, 0))
        out[key] = (a | bits, d & ~bits)

    a, d = out.get(("role", everyone_id), (0, 0))
    out[("role", everyone_id)] = (a & ~_VIEW_CONNECT, d | _VIEW_CONNECT)
    for role_id in staff_role_ids:
        allow(("role", role_id), _GUEST)
    for member_id in member_ids:
        allow(("member", member_id), _GUEST)
    allow(("member", bot_id), _BOT)
    return _norm(out)


def permission_issues(guild: discord.Permissions, category: discord.Permissions | None) -> list[Issue]:
    """``missing_permission:<name>`` for each one the bot lacks in the guild or in the organizer's category."""
    missing: list[str] = []
    for scope in (guild, category):
        if scope is None or scope.administrator:
            continue
        missing += [name for name in _NEEDED if not getattr(scope, name) and name not in missing]
    return [Issue(f"missing_permission:{name}") for name in missing]


# --- the diff -----------------------------------------------------------------------------------


def _ids(values: Sequence[str]) -> list[int]:
    return [int(v) for v in values if str(v).isdigit()]


def diff(plan: VoicePlan, rows: Sequence[Row], seen: Seen) -> Diff:
    """Everything to do so Discord and ``voice_channel`` match ``plan``; empty when they already do."""
    out = Diff()
    by_key = {row.slot_key: row for row in rows}
    wanted = sorted(plan.channels, key=lambda c: c.position)
    wanted_keys = {c.slot_key for c in wanted}

    def alive(row: Row | None) -> SeenChannel | None:
        return seen.channels.get(row.channel_id) if row is not None and row.channel_id is not None else None

    # --- categories -----------------------------------------------------------------------------
    organizer: SeenChannel | None = None
    if plan.category_id:
        found = seen.channels.get(int(plan.category_id)) if plan.category_id.isdigit() else None
        if found is not None and found.is_category:
            organizer = found
        else:
            out.issues.append(Issue("category_not_found", plan.category_id))
    base_name = organizer.name if organizer is not None else plan.tournament_name

    def category_ref(n: int) -> str:
        return f"category:{n}"

    def category_seen(n: int) -> SeenChannel | None:
        if n == 1 and organizer is not None:
            return organizer
        return alive(by_key.get(category_ref(n)))

    def category_name(n: int) -> str:
        if n == 1:
            return plan.tournament_name[:100]
        suffix = f" · {n}"
        return base_name[: 100 - len(suffix)] + suffix

    kept = {c.channel_id for c in (by_key.get(k) for k in wanted_keys) if c is not None and alive(c) is not None}

    def room(n: int) -> int:
        cat = category_seen(n)
        if cat is None:
            return CATEGORY_LIMIT
        # Children not placed by this plan -- foreign channels and channels waiting to be deleted -- keep their seats.
        occupied = sum(1 for ch in seen.channels.values() if ch.parent_id == cat.id and ch.id not in kept)
        return CATEGORY_LIMIT - occupied

    placement: dict[str, int] = {}
    count = 0
    n = 1
    for channel in wanted:
        while room(n) - count <= 0:
            n += 1
            count = 0
        placement[channel.slot_key] = n
        count += 1
    used = sorted(set(placement.values()))
    if used and used[-1] > 1:
        out.issues.append(Issue("category_overflow", f"{used[-1]} categories"))

    top = used[-1] if used else 0
    for n in range(1, top + 1):
        existing = category_seen(n)
        if existing is not None:
            out.categories[category_ref(n)] = existing.id
    for n in used:
        ref = category_ref(n)
        existing = category_seen(n)
        after = category_ref(n - 1) if n > 1 else None
        if existing is None:
            out.ops.append(CreateCategory(ref, category_name(n), after))
            continue
        if n == 1 and organizer is not None:
            continue  # the organizer's own category is never renamed or moved
        previous = category_seen(n - 1) if n > 1 else None
        edit = EditCategory(
            ref,
            name=category_name(n) if existing.name != category_name(n) else None,
            after=after if previous is not None and existing.position != previous.position + 1 else None,
        )
        if edit.name is not None or edit.after is not None:
            out.ops.append(edit)

    # --- channels -------------------------------------------------------------------------------
    staff = _ids(plan.staff_role_ids)
    unknown_roles = [r for r in staff if r not in seen.role_ids]
    if unknown_roles:
        out.issues.append(Issue("role_not_found", ", ".join(map(str, unknown_roles))))
    staff = [r for r in staff if r in seen.role_ids]
    dropped: list[str] = []

    for channel in wanted:
        row = by_key.get(channel.slot_key)
        current = alive(row)
        ref = category_ref(placement[channel.slot_key])
        target = category_seen(placement[channel.slot_key])

        desired: Overwrites | None = None
        if plan.private and channel.kind != "hub":
            members = _ids(channel.member_discord_ids)
            if seen.member_ids is not None:
                gone = [m for m in members if m not in seen.member_ids]
                dropped += [f"{channel.slot_key}:{m}" for m in gone]
                members = [m for m in members if m in seen.member_ids]
            desired = private_overwrites(
                dict(target.overwrites) if target is not None else {},
                everyone_id=seen.everyone_id,
                staff_role_ids=staff,
                member_ids=members,
                bot_id=seen.bot_id,
            )

        if current is None:
            out.ops.append(
                CreateChannel(
                    channel.slot_key, channel.kind, channel.name, ref, channel.stage_id, channel.team_id, desired
                )
            )
            continue

        if row is not None and row.status == "deleting":
            out.ops.append(Revive(channel.slot_key))
        moved = target is None or current.parent_id != target.id
        edit = EditChannel(
            channel.slot_key,
            name=channel.name if current.name != channel.name else None,
            category_ref=ref if moved else None,
            sync=desired is None and (moved or not current.synced),
            overwrites=desired if desired is not None and _norm(current.overwrites) != desired else None,
        )
        if edit.name is not None or edit.category_ref is not None or edit.sync or edit.overwrites is not None:
            out.ops.append(edit)

    if dropped:
        out.issues.append(Issue("member_overwrite_failed", ", ".join(dropped[:10])))

    # --- order inside each category -------------------------------------------------------------
    for n in used:
        keys = [c.slot_key for c in wanted if placement[c.slot_key] == n]
        cat = category_seen(n)
        here = [
            (seen_ch.position, seen_ch.id, key)
            for key in keys
            if (seen_ch := alive(by_key.get(key))) is not None and cat is not None and seen_ch.parent_id == cat.id
        ]
        in_place = [key for _, _, key in sorted(here)]
        # New and arriving channels land at the bottom in plan order, so only a prefix mismatch needs moving.
        if len(keys) > 1 and in_place != keys[: len(in_place)]:
            out.ops.append(Reorder(category_ref(n), tuple(keys)))

    # --- what the plan dropped ------------------------------------------------------------------
    for row in sorted(rows, key=lambda r: r.kind == "category"):
        if row.slot_key in wanted_keys or not row.owned:
            continue
        if row.kind == "category":
            number = row.slot_key.removeprefix("category:")
            if number.isdigit() and int(number) in used and (int(number) > 1 or organizer is None):
                if alive(row) is not None and row.status == "deleting":
                    out.ops.append(Revive(row.slot_key))
                continue
        if alive(row) is None:
            out.ops.append(Forget(row.slot_key))
        elif row.status != "deleting":
            out.ops.append(MarkDeleting(row.slot_key))
    return out


# --- deletion and moves ---------------------------------------------------------------------------


def deletion_due(kind: str, delete_requested_at: datetime | None, now: datetime, occupants: int) -> bool:
    """Whether a ``deleting`` row's Discord channel goes now.

    A voice channel: when nobody is in it, or ``DELETE_AFTER`` after it was dropped. A category: only
    when it holds nothing at all -- deleting it would strand whatever is left in it.
    """
    if kind == "category":
        return occupants == 0
    if occupants == 0:
        return True
    return delete_requested_at is not None and now - delete_requested_at >= DELETE_AFTER


def select_round_moves(
    old_routes: Mapping[str, str],
    new_routes: Mapping[str, str],
    sitting_in: Mapping[str, int],
    channel_ids: Mapping[str, int],
    order: Mapping[str, int],
) -> list[tuple[str, int]]:
    """``(user, channel)`` moves after a sync: members whose route changed and who sit in a channel of the tournament.

    ``sitting_in`` is user -> the tournament's tracked channel they are in right now (others are not
    in it). Ordered by the plan position of the channel they go to.
    """
    moves: list[tuple[int, str, int]] = []
    for user, key in new_routes.items():
        target = channel_ids.get(key)
        if old_routes.get(user) == key or target is None or sitting_in.get(user) in (None, target):
            continue
        moves.append((order.get(key, 0), user, target))
    return [(user, target) for _, user, target in sorted(moves)]
