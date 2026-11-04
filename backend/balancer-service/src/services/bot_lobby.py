"""A pickup mix's bot lobby: the in-game party a game's bot opens for a lobby's live match, and the match id it reports.

``create`` binds the party to the lobby's live encounter (a Recreate replaces it) and writes its join code to the
lobby's ``lobby_code``. The match id comes back by the source's callback (:meth:`accept_callback`, authorized by the
one-time token in the URL -- only its SHA-256 is stored -- and the party's secret) or by :func:`run_poll_tick`, which
asks the source every minute for parties still unanswered; both store it on the row, and the stats worker files it as
the round's import (``stats.match_search``). ``ingest_status`` tells, per roster row, whether that player's own client
uploads their matches -- what the by-players search depends on.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from cashews import cache
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES
from shared.disciplines.lobby import BotLobbyFailed, BotLobbyRateLimited, BotLobbyRequest, IngestStatus
from shared.observability import observe_scheduled_job
from shared.repository import (
    CustomGameBotLobbyRepository,
    SocialAccountRepository,
    UserBalancerConfigRepository,
)
from shared.services.distributed_lock import (
    DistributedLockUnavailable,
    acquire_distributed_lock,
    release_distributed_lock,
)
from shared.services.pickup_mix_realtime import emit_pickup_mix_changed
from shared.services.scheduler import IntervalScheduler
from src.core import db
from src.core.config import config
from src.domain.bot_lobby import POLL_WINDOW, merge_ingest_status, parse_match_id, secret_matches, token_sha256
from src.services.custom_game import custom_game_service

__all__ = ("BotLobbyService", "bot_lobby_service", "run_poll_tick", "shutdown_scheduler", "start_scheduler")

#: The game source POSTs the match id here (the gateway's public, token-addressed route).
CALLBACK_PATH = "/api/v1/deadlock/lobby-callback/{token}"
POLL_SECONDS = 60
#: The poll's own lease: one replica asks the source per tick.
LEADER_LOCK_KEY = "balancer:bot_lobby:poll:leader"
_LEASE_SECONDS = 50
_STATUS_TTL_SECONDS = 15 * 60
_scheduler = IntervalScheduler(job_id="bot_lobby_poll", label="Bot lobby poll")


def _slug(code: int, slug: str, headers: dict[str, str] | None = None) -> HTTPException:
    return HTTPException(status_code=code, detail=slug, headers=headers)


def _status_key(discipline: str, account_id: str) -> str:
    return f"balancer:ingest_status:{discipline}:{account_id}"


def _dump_status(value: IngestStatus) -> dict[str, Any]:
    return {
        "active": value.active,
        "last_upload_at": value.last_upload_at.isoformat() if value.last_upload_at else None,
        "window_days": value.window_days,
    }


def _load_status(raw: Mapping[str, Any]) -> IngestStatus:
    uploaded = raw["last_upload_at"]
    return IngestStatus(
        active=raw["active"],
        last_upload_at=datetime.fromisoformat(uploaded) if uploaded else None,
        window_days=raw["window_days"],
    )


class BotLobbyService:
    def __init__(
        self,
        *,
        bot_lobbies: CustomGameBotLobbyRepository = CustomGameBotLobbyRepository(),
        configs: UserBalancerConfigRepository = UserBalancerConfigRepository(),
        accounts: SocialAccountRepository = SocialAccountRepository(),
    ) -> None:
        self.bot_lobbies = bot_lobbies
        self.configs = configs
        self.accounts = accounts

    async def region_for(self, session: AsyncSession, user_id: int | None, discipline: str) -> str | None:
        """The region ``user_id`` last opened a bot lobby of ``discipline`` in, if it is still one of the game's."""
        spec = DISCIPLINES[discipline].lobby_bot
        row = await self.configs.get_by_user(session, user_id) if user_id is not None else None
        region = (row.bot_lobby_regions or {}).get(discipline) if row is not None else None
        return region if spec is not None and region in spec.regions else None

    @staticmethod
    def callback_url(token: str) -> str | None:
        """The public URL the source reports the match to; ``None`` on a site with no public address (the poll covers)."""
        base = config.public_site_url.rstrip("/")
        if urlparse(base).hostname in (None, "localhost", "127.0.0.1", "::1"):
            return None
        return base + CALLBACK_PATH.format(token=token)

    async def create(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        custom_game_id: int,
        lobby_index: int,
        region: str,
        actor_user_id: int,
        actor_is_superuser: bool = False,
    ) -> models.CustomGame:
        """Open the game's bot lobby for the lobby's live match, replacing the one it already has.

        422 ``unsupported_lobby_bot`` / ``invalid_region``, 409 ``no_live_match``, 429 ``lobby_bot_rate_limited:<s>``
        (``Retry-After`` too), 503 ``lobby_bot_failed`` when the source is down or refuses.
        """
        game, lobby = await custom_game_service.writable_lobby(
            session,
            workspace_id=workspace_id,
            custom_game_id=custom_game_id,
            lobby_index=lobby_index,
            actor_user_id=actor_user_id,
            actor_is_superuser=actor_is_superuser,
        )
        spec = DISCIPLINES[game.discipline].lobby_bot
        if spec is None:
            raise _slug(status.HTTP_422_UNPROCESSABLE_ENTITY, "unsupported_lobby_bot")
        if region not in spec.regions:
            raise _slug(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_region")
        if lobby.live_encounter_id is None:
            raise _slug(status.HTTP_409_CONFLICT, "no_live_match")
        sizes = await custom_game_service.lobbies.team_sizes(session, lobby.live_encounter_id)
        token = secrets.token_urlsafe(32)
        try:
            # Holds the mix's row lock for the source's answer (its client times out in seconds).
            party = await spec.create(
                BotLobbyRequest(
                    region=region,
                    team_size=max(sizes, default=0),
                    roster_size=sum(sizes),
                    callback_url=self.callback_url(token),
                )
            )
        except BotLobbyRateLimited as exc:
            seconds = exc.retry_after
            raise _slug(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "lobby_bot_rate_limited" if seconds is None else f"lobby_bot_rate_limited:{seconds}",
                None if seconds is None else {"Retry-After": str(seconds)},
            ) from exc
        except BotLobbyFailed as exc:
            logger.warning("Bot lobby for mix {} lobby {} failed: {}", game.id, lobby_index, exc)
            raise _slug(status.HTTP_503_SERVICE_UNAVAILABLE, "lobby_bot_failed") from exc
        await self.bot_lobbies.replace(
            session,
            models.CustomGameBotLobby(
                workspace_id=game.workspace_id,
                custom_game_id=game.id,
                lobby_index=lobby_index,
                encounter_id=lobby.live_encounter_id,
                discipline=game.discipline,
                party_id=party.party_id,
                party_code=party.party_code,
                callback_token_sha256=token_sha256(token),
                callback_secret=party.callback_secret,
                created_by_user_id=actor_user_id,
            ),
        )
        lobby.lobby_code = party.party_code
        await self._remember_region(session, actor_user_id, game.discipline, region)
        await session.flush()
        return game

    async def _remember_region(self, session: AsyncSession, user_id: int, discipline: str, region: str) -> None:
        row = await self.configs.get_by_user(session, user_id)
        if row is None:
            await self.configs.create(
                session, models.UserBalancerConfig(user_id=user_id, bot_lobby_regions={discipline: region})
            )
        else:
            # A new dict: an in-place edit of a JSONB value is not tracked.
            await self.configs.update_fields(
                session, row, {"bot_lobby_regions": {**(row.bot_lobby_regions or {}), discipline: region}}
            )

    async def accept_callback(
        self, session: AsyncSession, *, token: str, body: str, secret: str | None, now: datetime | None = None
    ) -> None:
        """The source's report that a party's match started. Silent on every refusal -- unknown, answered or expired
        token, wrong secret, a body without a match id -- so the endpoint is no oracle; the caller commits."""
        row = await self.bot_lobbies.get_awaiting_by_token(session, token_sha256(token))
        if row is None or (now or datetime.now(UTC)) - row.created_at > POLL_WINDOW:
            return
        if not secret_matches(row.callback_secret, secret):
            logger.warning("Bot lobby callback for mix {} sent the wrong secret", row.custom_game_id)
            return
        match_id = parse_match_id(body)
        if match_id is None:
            logger.warning(
                "Bot lobby callback for mix {} carried no match id ({} bytes)", row.custom_game_id, len(body)
            )
            return
        await self._record_match_id(session, row, match_id)

    async def _record_match_id(self, session: AsyncSession, row: models.CustomGameBotLobby, match_id: str) -> None:
        row.match_id = match_id
        await session.flush()
        await emit_pickup_mix_changed(session, row.workspace_id, custom_game_id=row.custom_game_id, change="bot_lobby")

    async def ingest_status(self, session: AsyncSession, game: models.CustomGame) -> dict[str, Any]:
        """``{window_days, players: {player id: {active, last_upload_at} | None}}`` for the mix's roster; a player
        whose account the source could not answer for (or who has none linked) is ``None``, never inactive."""
        spec = DISCIPLINES[game.discipline]
        if spec.ingest_status is None or spec.identity_provider is None:
            raise _slug(status.HTTP_422_UNPROCESSABLE_ENTITY, "unsupported_ingest_status")
        roster = await custom_game_service.roster.list_for_game(session, game.id)
        members = await custom_game_service.members(
            session, game.workspace_id, [row.workspace_member_id for row in roster], discipline=game.discipline
        )
        player_ids = sorted({member.player_id for member in members.values()})
        handles = await self.accounts.handles_by_user(session, player_ids, provider=spec.identity_provider)
        known = await self._statuses(
            game.discipline, spec.ingest_status, sorted({h for hs in handles.values() for h in hs})
        )
        merged = {
            player_id: merge_ingest_status([known.get(handle) for handle in handles.get(player_id, ())])
            if player_id in handles
            else None
            for player_id in player_ids
        }
        window = next((value.window_days for value in merged.values() if value is not None), 14)
        return {
            "window_days": window,
            "players": {
                str(player_id): None
                if value is None
                else {
                    "active": value.active,
                    "last_upload_at": value.last_upload_at.isoformat() if value.last_upload_at else None,
                }
                for player_id, value in merged.items()
            },
        }

    async def _statuses(self, discipline: str, source: Any, account_ids: list[str]) -> dict[str, IngestStatus | None]:
        """Each account's status: the 15-minute cache first, the source for the rest. An unknown answer is not cached."""
        out: dict[str, IngestStatus | None] = {}
        cached = cache.is_setup()
        for account_id in account_ids:
            if cached:
                try:
                    raw = await cache.get(_status_key(discipline, account_id))
                except Exception:  # noqa: BLE001 -- the cache is best-effort
                    raw = None
                if raw is not None:
                    out[account_id] = _load_status(raw)
        missing = [account_id for account_id in account_ids if account_id not in out]
        if missing:
            try:
                fresh = await source(missing)
            except Exception:
                logger.exception("Ingest status read failed for {}", discipline)
                fresh = {}
            for account_id, value in fresh.items():
                out[account_id] = value
                if cached and value is not None:
                    try:
                        await cache.set(
                            _status_key(discipline, account_id), _dump_status(value), expire=_STATUS_TTL_SECONDS
                        )
                    except Exception:  # noqa: BLE001 -- the cache is best-effort
                        pass
        return out

    async def poll_awaiting(self, session_factory: Any, *, now: datetime | None = None) -> int:
        """Ask the source for the match id of every party still unanswered; returns how many it learned."""
        moment = now or datetime.now(UTC)
        async with session_factory() as session:
            waiting = [
                (row.id, row.discipline, row.party_id)
                for row in await self.bot_lobbies.list_awaiting(session, since=moment - POLL_WINDOW)
            ]
        learned = 0
        for row_id, discipline, party_id in waiting:
            spec = DISCIPLINES[discipline].lobby_bot
            match_id = await spec.match_id(party_id) if spec is not None else None
            if match_id is None:
                continue
            async with session_factory() as session:
                row = await self.bot_lobbies.get_awaiting_for_update(session, row_id)
                if row is None:  # the callback answered first, or the match is gone
                    continue
                await self._record_match_id(session, row, match_id)
                await session.commit()
            learned += 1
        return learned


bot_lobby_service = BotLobbyService()


async def run_poll_tick(*, redis: Any, session_factory: Any = db.async_session_maker) -> int:
    """One pass under the poll's lease; a replica that does not hold it does nothing."""
    async with observe_scheduled_job("bot_lobby_poll"):
        try:
            token = await acquire_distributed_lock(
                redis, LEADER_LOCK_KEY, ttl_seconds=_LEASE_SECONDS, acquire_timeout_seconds=0.5
            )
        except DistributedLockUnavailable:
            return 0
        try:
            return await bot_lobby_service.poll_awaiting(session_factory)
        except Exception:
            logger.exception("Bot lobby poll failed; retried next tick")
            return 0
        finally:
            await release_distributed_lock(redis, token)


def start_scheduler(*, redis: Any) -> None:
    _scheduler.start(run_poll_tick, seconds=POLL_SECONDS, kwargs={"redis": redis})


def shutdown_scheduler() -> None:
    _scheduler.shutdown()
