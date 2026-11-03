"""Keeps a tournament's Discord voice channels equal to its plan (``docs/tournament-voice-channels.md``).

tournament-service decides what should exist (``rpc.tournament.voice_plan``); this reconciles Discord
with it. Every sync fetches the whole plan, diffs it against ``tournament.voice_channel`` and what the
guild cache shows (:func:`src.services.voice_diff.diff`, pure), and applies the difference through the
per-guild queue. A lost event, a 429 or a channel deleted by hand is repaired by the next sync.

Process memory only (single replica, like the mix projector): the debounce timers, the routes of the
last sync the hub reads, the id -> tournament map the drift listeners read, the rename ledger. A restart
loses nothing that the startup sync does not rebuild, and it moves nobody (no earlier routes to compare).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from typing import Any

import discord
import sqlalchemy as sa
from faststream.rabbit.annotations import RabbitMessage
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared import models
from shared.messaging.config import (
    CACHE_INVALIDATION_DISCORD_VOICE_QUEUE,
    CACHE_INVALIDATION_EXCHANGE,
    DISCORD_VOICE_SYNC_QUEUE,
    TOURNAMENT_EVENTS_EXCHANGE,
)
from shared.messaging.rpc import request_rpc
from shared.observability import observe_message_processing
from shared.repository.voice import TournamentVoiceChannelRepository
from shared.schemas.events import CacheInvalidatedEvent, TournamentVoiceSyncRequestedEvent
from shared.schemas.voice import VOICE_PLAN_SUBJECT, VoicePlan
from src.core.broker import optional_broker
from src.services import voice_diff as vd
from src.services.guild_queue import GuildQueues, Priority

__all__ = ("DEBOUNCE_SECONDS", "VoiceSync")

#: Requests of one tournament within this window become one sync.
DEBOUNCE_SECONDS = 3.0
#: After a sync, the bot's own channel edits are still arriving as gateway events; they are not drift.
QUIET_SECONDS = 5.0
RETRY_SECONDS = 30.0
MAX_FAILURES = 5
#: Discord allows about two renames per channel per ten minutes.
RENAMES_PER_WINDOW = 2
RENAME_WINDOW = 600.0
_PLAN_TIMEOUT = 15.0
_REASON = "OWT tournament voice"
_channels_repo = TournamentVoiceChannelRepository()


def _overwrites(channel: discord.abc.GuildChannel) -> vd.Overwrites:
    out: vd.Overwrites = {}
    for target, overwrite in channel.overwrites.items():
        is_role = isinstance(target, discord.Role) or getattr(target, "type", None) is discord.Role
        allow, deny = overwrite.pair()
        out[("role" if is_role else "member", target.id)] = (allow.value, deny.value)
    return {key: pair for key, pair in out.items() if pair != (0, 0)}


def observe(guild: discord.Guild) -> vd.Seen:
    """The guild's channels as the cache holds them."""
    channels: dict[int, vd.SeenChannel] = {}
    for channel in guild.channels:
        is_category = isinstance(channel, discord.CategoryChannel)
        ours = is_category or isinstance(channel, discord.VoiceChannel)
        channels[channel.id] = vd.SeenChannel(
            id=channel.id,
            name=channel.name,
            parent_id=None if is_category else channel.category_id,
            position=channel.position,
            is_category=is_category,
            synced=bool(ours and not is_category and channel.permissions_synced),
            overwrites=_overwrites(channel) if ours else {},
        )
    return vd.Seen(
        channels=channels,
        everyone_id=guild.default_role.id,
        bot_id=guild.me.id,
        role_ids=frozenset(role.id for role in guild.roles),
        member_ids=frozenset(m.id for m in guild.members) if guild.chunked else None,
    )


def _row(model: models.TournamentVoiceChannel) -> vd.Row:
    return vd.Row(
        slot_key=model.slot_key,
        kind=model.kind,
        channel_id=model.discord_channel_id,
        owned=model.owned,
        status=model.status,
        delete_requested_at=model.delete_requested_at,
    )


class VoiceSync:
    def __init__(
        self, *, bot: discord.Client, session_maker: async_sessionmaker[AsyncSession], queues: GuildQueues
    ) -> None:
        self._bot = bot
        self._session_maker = session_maker
        self._queues = queues
        #: Tournaments with enabled settings or rows: the only ones an event can wake.
        self._known: set[int] = set()
        self._stamp: dict[int, int] = {}
        self._runners: dict[int, asyncio.Task[None]] = {}
        self._retries: dict[int, asyncio.TimerHandle] = {}
        self._failures: dict[int, int] = {}
        self._busy: set[int] = set()
        self._quiet_until: dict[int, float] = {}
        #: What the last sync of each tournament left: ``slot_key -> channel id``, routes, tracked ids.
        self._channels: dict[int, dict[str, int]] = {}
        self._routes: dict[int, dict[str, str]] = {}
        self._tracked: dict[int, int] = {}
        self._renames: dict[int, list[float]] = {}
        self._own_deletes: set[int] = set()

    # --- triggers -------------------------------------------------------------------------------

    def register(self, broker: Any) -> None:
        # `msg` MUST be annotated RabbitMessage (see MixProjector.register).
        @broker.subscriber(DISCORD_VOICE_SYNC_QUEUE, TOURNAMENT_EVENTS_EXCHANGE)
        async def handle_voice_sync_requested(body: dict[str, Any], msg: RabbitMessage) -> None:
            async with observe_message_processing(
                queue=DISCORD_VOICE_SYNC_QUEUE, handler="handle_voice_sync_requested", message=msg, logger=logger
            ):
                self.request(TournamentVoiceSyncRequestedEvent.model_validate(body).tournament_id, explicit=True)

        @broker.subscriber(CACHE_INVALIDATION_DISCORD_VOICE_QUEUE, CACHE_INVALIDATION_EXCHANGE)
        async def handle_voice_cache_invalidated(body: dict[str, Any], msg: RabbitMessage) -> None:
            async with observe_message_processing(
                queue=CACHE_INVALIDATION_DISCORD_VOICE_QUEUE,
                handler="handle_voice_cache_invalidated",
                message=msg,
                logger=logger,
            ):
                event = CacheInvalidatedEvent.model_validate(body)
                if event.scope_kind == "tournament":
                    self.request(event.scope_id)

    def request(self, tournament_id: int, *, explicit: bool = False) -> None:
        """Ask for a sync. ``explicit`` (the organizer's request) wakes a tournament the bot has never heard of."""
        if explicit:
            self._known.add(tournament_id)
        elif tournament_id not in self._known:
            return
        self._stamp[tournament_id] = self._stamp.get(tournament_id, 0) + 1
        if tournament_id not in self._runners:
            self._runners[tournament_id] = asyncio.create_task(self._run(tournament_id))

    async def start(self) -> None:
        """Remember what exists and sync every tournament that has enabled settings or rows."""
        async with self._session_maker() as session:
            rows = list((await session.scalars(sa.select(models.TournamentVoiceChannel))).all())
            enabled = (
                await session.scalars(
                    sa.select(models.TournamentVoiceSettings.tournament_id).where(
                        models.TournamentVoiceSettings.enabled.is_(True)
                    )
                )
            ).all()
        for tournament_id in {r.tournament_id for r in rows}:
            self._remember(tournament_id, [r for r in rows if r.tournament_id == tournament_id], None)
        for tournament_id in {*enabled, *(r.tournament_id for r in rows)}:
            self.request(tournament_id, explicit=True)

    def close(self) -> None:
        for task in self._runners.values():
            task.cancel()
        for handle in self._retries.values():
            handle.cancel()

    async def _run(self, tournament_id: int) -> None:
        try:
            await self._bot.wait_until_ready()
            while True:
                stamp = self._stamp[tournament_id]
                await asyncio.sleep(DEBOUNCE_SECONDS)
                if self._stamp[tournament_id] != stamp:
                    continue  # asked again while waiting: wait for quiet
                if (handle := self._retries.pop(tournament_id, None)) is not None:
                    handle.cancel()
                self._busy.add(tournament_id)
                retry_in: float | None = None
                try:
                    retry_in = await self._sync(tournament_id)
                    self._failures.pop(tournament_id, None)
                except Exception:
                    logger.exception(f"❌ Voice sync of tournament {tournament_id} failed")
                    failures = self._failures[tournament_id] = self._failures.get(tournament_id, 0) + 1
                    retry_in = RETRY_SECONDS * failures if failures < MAX_FAILURES else None
                finally:
                    self._busy.discard(tournament_id)
                    self._quiet_until[tournament_id] = time.monotonic() + QUIET_SECONDS
                if retry_in is not None:
                    self._retries[tournament_id] = asyncio.get_running_loop().call_later(
                        retry_in, self.request, tournament_id
                    )
                if self._stamp[tournament_id] == stamp:
                    break  # nothing asked mid-sync; otherwise one follow-up covers every request since
        finally:
            self._runners.pop(tournament_id, None)

    # --- one sync -------------------------------------------------------------------------------

    async def _plan(self, tournament_id: int) -> VoicePlan | None:
        broker = optional_broker()
        if broker is None:
            raise RuntimeError("RabbitMQ is not available; cannot fetch the voice plan")
        reply = await request_rpc(broker, {"tournament_id": tournament_id}, VOICE_PLAN_SUBJECT, timeout=_PLAN_TIMEOUT)
        if reply is None:
            raise RuntimeError("voice plan reply is not an RPC envelope")
        if not reply.ok:
            if reply.code == "not_found":
                return None
            raise RuntimeError(f"voice plan refused: {reply.code} {reply.message}")
        return VoicePlan.model_validate(reply.data)

    async def _models(self, session: AsyncSession, tournament_id: int) -> list[models.TournamentVoiceChannel]:
        result = await session.scalars(
            sa.select(models.TournamentVoiceChannel).where(models.TournamentVoiceChannel.tournament_id == tournament_id)
        )
        return list(result.all())

    async def _sync(self, tournament_id: int) -> float | None:
        """One reconciliation; seconds until it wants another (a deferred rename), if it does."""
        plan = await self._plan(tournament_id)
        if plan is None:  # the tournament is gone; its rows went with it
            self._forget(tournament_id)
            return None
        issues: list[vd.Issue] = []
        retry_in: float | None = None
        async with self._session_maker() as session:
            rows = await self._models(session, tournament_id)
            guild = self._bot.get_guild(int(plan.guild_id)) if plan.guild_id and plan.guild_id.isdigit() else None
            if guild is None or guild.me is None:
                if plan.enabled or rows:
                    issues.append(vd.Issue("guild_not_found", plan.guild_id))
            else:
                issues += self._permission_issues(guild, plan, rows)
                result = vd.diff(plan, [_row(r) for r in rows], observe(guild))
                issues += result.issues
                applier = _Apply(self, guild, session, tournament_id, {r.slot_key: r for r in rows}, result.categories)
                await applier.run(result.ops)
                issues += applier.issues
                retry_in = applier.retry_in
                rows = await self._models(session, tournament_id)
                previous = self._routes.get(tournament_id)
                self._remember(tournament_id, rows, plan.routes)
                if previous is not None:
                    await self._round_moves(guild, tournament_id, plan, previous)
            await self._report(session, tournament_id, issues, rows)
        return retry_in

    @staticmethod
    def _permission_issues(
        guild: discord.Guild, plan: VoicePlan, rows: Sequence[models.TournamentVoiceChannel]
    ) -> list[vd.Issue]:
        if not (plan.enabled or rows):
            return []
        category = guild.get_channel(int(plan.category_id)) if plan.category_id and plan.category_id.isdigit() else None
        return vd.permission_issues(
            guild.me.guild_permissions,
            category.permissions_for(guild.me) if isinstance(category, discord.CategoryChannel) else None,
        )

    async def _report(
        self, session: AsyncSession, tournament_id: int, issues: list[vd.Issue], rows: Sequence[Any]
    ) -> None:
        settings = await session.scalar(
            sa.select(models.TournamentVoiceSettings).where(
                models.TournamentVoiceSettings.tournament_id == tournament_id
            )
        )
        if settings is not None:
            unique = list(dict.fromkeys(issues))
            settings.last_synced_at = datetime.now(UTC)
            settings.sync_issues = [{"code": i.code, "detail": i.detail} for i in unique]
            await session.commit()
        if (settings is None or not settings.enabled) and not rows:
            self._forget(tournament_id)

    def _forget(self, tournament_id: int) -> None:
        self._known.discard(tournament_id)
        self._routes.pop(tournament_id, None)
        self._channels.pop(tournament_id, None)
        self._tracked = {c: t for c, t in self._tracked.items() if t != tournament_id}

    def _remember(
        self, tournament_id: int, rows: Sequence[models.TournamentVoiceChannel], routes: dict[str, str] | None
    ) -> None:
        self._tracked = {c: t for c, t in self._tracked.items() if t != tournament_id}
        channels: dict[str, int] = {}
        for row in rows:
            if row.discord_channel_id is None:
                continue
            self._tracked[row.discord_channel_id] = tournament_id
            if row.kind != "category":
                channels[row.slot_key] = row.discord_channel_id
        self._channels[tournament_id] = channels
        if routes is not None:
            # Only routes whose channel exists: a route to a channel that failed to appear still counts as a change next time.
            self._routes[tournament_id] = {user: key for user, key in routes.items() if key in channels}

    # --- moves ----------------------------------------------------------------------------------

    async def hub_joined(self, member: discord.Member, channel: discord.abc.GuildChannel) -> None:
        """A member joined a channel: if it is a tournament's hub, send them to theirs."""
        tournament_id = self._tracked.get(channel.id)
        channels = self._channels.get(tournament_id, {}) if tournament_id is not None else {}
        if tournament_id is None or channels.get("hub") != channel.id:
            return
        key = self._routes.get(tournament_id, {}).get(str(member.id))
        target = member.guild.get_channel(channels[key]) if key in channels else None
        if target is None or target.id == channel.id:
            return
        try:
            await self._queues.submit(
                member.guild.id, Priority.HUB_MOVE, partial(member.move_to, target, reason=_REASON)
            )
        except discord.HTTPException as exc:  # left voice meanwhile, or no Move Members
            logger.warning(f"⚠️ Could not send {member.id} from the hub of tournament {tournament_id}: {exc}")

    async def _round_moves(
        self, guild: discord.Guild, tournament_id: int, plan: VoicePlan, previous: dict[str, str]
    ) -> None:
        sitting: dict[str, int] = {}
        for channel_id, owner in self._tracked.items():
            if owner == tournament_id:
                for member in getattr(guild.get_channel(channel_id), "members", ()):
                    sitting[str(member.id)] = channel_id
        moves = vd.select_round_moves(
            previous,
            plan.routes,
            sitting,
            self._channels.get(tournament_id, {}),
            {c.slot_key: c.position for c in plan.channels},
        )
        pending = []
        for user, channel_id in moves:
            member, target = guild.get_member(int(user)), guild.get_channel(channel_id)
            if member is not None and target is not None:
                pending.append(
                    self._queues.submit(guild.id, Priority.ROUND_MOVE, partial(member.move_to, target, reason=_REASON))
                )
        for result in await asyncio.gather(*pending, return_exceptions=True):
            if isinstance(result, Exception):
                logger.warning(f"⚠️ Round move in tournament {tournament_id} failed: {result}")

    # --- drift ----------------------------------------------------------------------------------

    async def channel_deleted(self, channel: discord.abc.GuildChannel) -> None:
        tournament_id = self._tracked.get(channel.id)
        if tournament_id is None or channel.id in self._own_deletes:
            return
        async with self._session_maker() as session:
            await _channels_repo.detach(session, channel.id)
            await session.commit()
        del self._tracked[channel.id]
        self._channels[tournament_id] = {
            k: v for k, v in self._channels.get(tournament_id, {}).items() if v != channel.id
        }
        self.request(tournament_id)

    def channel_updated(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        tournament_id = self._tracked.get(after.id)
        if tournament_id is None or tournament_id in self._busy:
            return
        if self._quiet_until.get(tournament_id, 0.0) > time.monotonic():
            return  # our own edit, still arriving
        if (before.name, before.overwrites, getattr(before, "category_id", None)) != (
            after.name,
            after.overwrites,
            getattr(after, "category_id", None),
        ):
            self.request(tournament_id)

    # --- deletion -------------------------------------------------------------------------------

    async def sweep_deleting(self) -> None:
        """Delete the channels of ``deleting`` rows that are empty, or 10 minutes past their drop; then the rows."""
        now = datetime.now(UTC)
        async with self._session_maker() as session:
            rows = list(
                (
                    await session.scalars(
                        sa.select(models.TournamentVoiceChannel).where(
                            models.TournamentVoiceChannel.status == "deleting"
                        )
                    )
                ).all()
            )
            # Voice channels first: a category goes only once nothing is left in it.
            for row in sorted(rows, key=lambda r: r.kind == "category"):
                try:
                    await self._delete_if_due(session, row, now)
                except Exception:
                    logger.exception(f"❌ Could not delete voice channel {row.slot_key} ({row.discord_channel_id})")
                    await session.rollback()

    async def _delete_if_due(self, session: AsyncSession, row: models.TournamentVoiceChannel, now: datetime) -> None:
        channel_id = row.discord_channel_id
        channel = self._bot.get_channel(channel_id) if channel_id is not None else None
        if channel is None and channel_id is not None:
            try:
                channel = await self._bot.fetch_channel(channel_id)
            except discord.NotFound:
                channel = None
            except discord.HTTPException:
                return  # cannot tell; try again next round
        if channel is not None:
            is_category = isinstance(channel, discord.CategoryChannel)
            occupants = len(channel.channels) if is_category else len(getattr(channel, "members", ()))
            if not vd.deletion_due("category" if is_category else row.kind, row.delete_requested_at, now, occupants):
                return
            self._own_deletes.add(channel.id)
            asyncio.get_running_loop().call_later(60, self._own_deletes.discard, channel.id)
            try:
                await self._queues.submit(channel.guild.id, Priority.DELETE, partial(channel.delete, reason=_REASON))
            except discord.NotFound:
                pass
        self._tracked.pop(channel_id, None)
        await _channels_repo.delete(session, row)
        await session.commit()
        if (tournament_id := row.tournament_id) in self._channels:
            self._channels[tournament_id] = {k: v for k, v in self._channels[tournament_id].items() if v != channel_id}

    # --- rename ledger --------------------------------------------------------------------------

    def rename_wait(self, channel_id: int) -> float:
        """0 when the channel may be renamed now, else seconds until it may."""
        now = time.monotonic()
        recent = [t for t in self._renames.get(channel_id, []) if now - t < RENAME_WINDOW]
        self._renames[channel_id] = recent
        return 0.0 if len(recent) < RENAMES_PER_WINDOW else recent[0] + RENAME_WINDOW - now

    def renamed(self, channel_id: int) -> None:
        self._renames.setdefault(channel_id, []).append(time.monotonic())


class _Apply:
    """Applies one diff's operations in order, through the guild queue, persisting rows as it goes."""

    def __init__(
        self,
        sync: VoiceSync,
        guild: discord.Guild,
        session: AsyncSession,
        tournament_id: int,
        rows: dict[str, models.TournamentVoiceChannel],
        categories: dict[str, int],
    ) -> None:
        self._sync = sync
        self._guild = guild
        self._session = session
        self._tournament_id = tournament_id
        self._rows = rows
        self._categories = {ref: discord.Object(id_) for ref, id_ in categories.items()}
        self.issues: list[vd.Issue] = []
        #: Seconds until a deferred rename may be tried.
        self.retry_in: float | None = None

    async def run(self, ops: Sequence[vd.Op]) -> None:
        for op in ops:
            try:
                await self._apply(op)
            except discord.Forbidden:
                with_overwrites = getattr(op, "overwrites", None) is not None
                self.issues.append(
                    vd.Issue(f"missing_permission:{'manage_roles' if with_overwrites else 'manage_channels'}")
                )
            except discord.HTTPException as exc:
                self.issues.append(
                    vd.Issue("discord_error", f"{type(op).__name__}: HTTP {exc.status} (code {exc.code})")
                )

    def _submit[T](self, work: Callable[[], Awaitable[T]]) -> asyncio.Future[T]:
        return self._queues.submit(self._guild.id, Priority.STRUCTURE, work)

    @property
    def _queues(self) -> GuildQueues:
        return self._sync._queues

    async def _apply(self, op: vd.Op) -> None:
        match op:
            case vd.CreateCategory():
                await self._create_category(op)
            case vd.EditCategory():
                await self._edit_category(op)
            case vd.CreateChannel():
                await self._create_channel(op)
            case vd.EditChannel():
                await self._edit_channel(op)
            case vd.Reorder():
                await self._reorder(op)
            case vd.MarkDeleting():
                self._rows[op.slot_key].status = "deleting"
                self._rows[op.slot_key].delete_requested_at = datetime.now(UTC)
                await self._session.commit()
            case vd.Revive():
                self._rows[op.slot_key].status = "active"
                self._rows[op.slot_key].delete_requested_at = None
                await self._session.commit()
            case vd.Forget():
                await _channels_repo.delete(self._session, self._rows.pop(op.slot_key))
                await self._session.commit()

    def _save(self, slot_key: str, **fields: Any) -> None:
        row = self._rows.get(slot_key)
        if row is None:
            row = self._rows[slot_key] = _channels_repo.stage(self._session, self._tournament_id, slot_key)
        for name, value in fields.items():
            setattr(row, name, value)

    def _targets(self, overwrites: vd.Overwrites) -> dict[Any, discord.PermissionOverwrite]:
        out: dict[Any, discord.PermissionOverwrite] = {}
        for (kind, target_id), (allow, deny) in overwrites.items():
            # A role must be the real object: creation reads every ``Object`` as a member.
            target = (
                self._guild.get_role(target_id) if kind == "role" else discord.Object(target_id, type=discord.Member)
            )
            if target is not None:
                out[target] = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(allow), discord.Permissions(deny)
                )
        return out

    async def _with_members[T](
        self, overwrites: vd.Overwrites | None, call: Callable[[vd.Overwrites | None], Awaitable[T]]
    ) -> T:
        """``call(overwrites)``; if Discord rejects a member that is not in the guild, again without those members."""
        try:
            return await self._submit(partial(call, overwrites))
        except discord.HTTPException as exc:
            if exc.status != 400 or not overwrites:
                raise
            bot_id = self._guild.me.id
            reduced = {
                key: pair
                for key, pair in overwrites.items()
                if key[0] != "member" or key[1] == bot_id or self._guild.get_member(key[1]) is not None
            }
            if reduced == overwrites:
                raise
            self.issues.append(
                vd.Issue("member_overwrite_failed", ", ".join(str(k[1]) for k in overwrites if k not in reduced))
            )
            return await self._submit(partial(call, reduced))

    def _category(self, ref: str) -> discord.Object | None:
        return self._categories.get(ref)

    def _channel(self, slot_key: str) -> Any:
        row = self._rows.get(slot_key)
        return self._guild.get_channel(row.discord_channel_id) if row is not None and row.discord_channel_id else None

    async def _create_category(self, op: vd.CreateCategory) -> None:
        category = await self._submit(partial(self._guild.create_category, op.name, reason=_REASON))
        self._categories[op.ref] = discord.Object(category.id)
        self._save(
            op.ref,
            kind="category",
            discord_channel_id=category.id,
            owned=True,
            status="active",
            delete_requested_at=None,
        )
        await self._session.commit()
        if op.after is not None and (after := self._category(op.after)) is not None:
            await self._submit(partial(category.move, after=after, reason=_REASON))

    async def _edit_category(self, op: vd.EditCategory) -> None:
        category = self._guild.get_channel(self._categories[op.ref].id)
        if category is None:
            return
        name = op.name
        if name is not None and (wait := self._sync.rename_wait(category.id)):
            name, self.retry_in = None, min(wait, self.retry_in or wait)
        if name is not None:
            await self._submit(partial(category.edit, name=name, reason=_REASON))
            self._sync.renamed(category.id)
        if op.after is not None and (after := self._category(op.after)) is not None:
            await self._submit(partial(category.move, after=after, reason=_REASON))

    async def _create_channel(self, op: vd.CreateChannel) -> None:
        parent = self._category(op.category_ref)
        if parent is None:  # its category could not be made; the error is already reported
            return
        guild = self._guild

        def create(overwrites: vd.Overwrites | None) -> Awaitable[discord.VoiceChannel]:
            extra = {} if overwrites is None else {"overwrites": self._targets(overwrites)}
            return guild.create_voice_channel(op.name, category=parent, reason=_REASON, **extra)

        channel = await self._with_members(op.overwrites, create)
        self._save(
            op.slot_key,
            kind=op.kind,
            stage_id=op.stage_id,
            team_id=op.team_id,
            discord_channel_id=channel.id,
            owned=True,
            status="active",
            delete_requested_at=None,
        )
        await self._session.commit()

    async def _edit_channel(self, op: vd.EditChannel) -> None:
        channel = self._channel(op.slot_key)
        if channel is None:
            return
        options: dict[str, Any] = {}
        if op.name is not None:
            if wait := self._sync.rename_wait(channel.id):
                self.retry_in = min(wait, self.retry_in or wait)
            else:
                options["name"] = op.name
        if op.category_ref is not None:
            if (parent := self._category(op.category_ref)) is None:
                return
            options["category"] = parent
        if op.sync:
            options["sync_permissions"] = True
        if not options and op.overwrites is None:
            return

        def edit(overwrites: vd.Overwrites | None) -> Awaitable[Any]:
            extra = {} if overwrites is None else {"overwrites": self._targets(overwrites)}
            return channel.edit(reason=_REASON, **options, **extra)

        await self._with_members(op.overwrites, edit)
        if "name" in options:
            self._sync.renamed(channel.id)

    async def _reorder(self, op: vd.Reorder) -> None:
        channels = [c for key in op.slot_keys if (c := self._channel(key)) is not None]
        for previous, channel in zip(channels, channels[1:], strict=False):
            await self._submit(partial(channel.move, after=previous, reason=_REASON))
