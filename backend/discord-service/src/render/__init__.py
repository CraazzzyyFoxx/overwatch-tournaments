"""Every message this service sends on the platform's behalf, rendered from the platform's own rows.

A ``discord_message`` row says what it is about -- ``kind``, ``subject``,
``slot``, ``payload_json`` -- and :func:`render` turns that into the card as
things stand now: a notification from the payload its publisher stored, a mix
card from the view balancer-service answers (``rpc.balancer.custom.discord_view``).
The gateway renders when it sends a row, the projector again whenever its mix
changes; no other process holds a card.
"""

from __future__ import annotations

import asyncio
import enum
import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import discord
import httpx
import sqlalchemy as sa
from cachetools import TTLCache
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.messaging.rpc import request_rpc
from shared.repository.discord_message import LIVE_STATUSES
from shared.repository.notification import NotificationWorkspaceConfigRepository
from shared.services import discord_messages
from src.core.config import settings
from src.render.card import DiscordCard
from src.render.mix import SignupLobby, SignupPlayer, lineup_card, lineup_picture, signup_card
from src.render.mix_lineup_image import LineupPicture, render_png
from src.render.notifications import DELIVERABLE_KINDS, render_discord

__all__ = ("KEEP", "Rendered", "lineup_key", "render")

#: The mix view the bot renders mix cards from (balancer-service, internal: no identity).
DISCORD_VIEW_SUBJECT = "rpc.balancer.custom.discord_view"
_RPC_TIMEOUT = 5.0

#: Fetched pictures by URL. A failure is not kept, so the next draw tries again.
_IMAGES: TTLCache[str, bytes] = TTLCache(maxsize=256, ttl=3600)

_configs = NotificationWorkspaceConfigRepository()


class Keep(enum.Enum):
    """A card the mix has moved past (its match recorded, the mix over): it stays as it was posted."""

    KEEP = "keep"


KEEP = Keep.KEEP


@dataclass(frozen=True, slots=True)
class Rendered:
    """One message as Discord takes it."""

    card: DiscordCard
    #: The PNG the card shows (``card.attachment_name``); ``None`` when it shows
    #: none or the message already carries this very picture.
    file: discord.File | None = None
    allowed_mentions: discord.AllowedMentions = field(default_factory=discord.AllowedMentions.none)


def lineup_key(slot: str) -> tuple[int, int] | None:
    """``lineup:1:3`` -> ``(1, 3)``: the lobby a lineup row belongs to and the match it announces."""
    prefix, _, rest = slot.partition(":")
    lobby, _, match = rest.partition(":")
    if prefix != "lineup" or not lobby.isdigit() or not match.isdigit():
        return None
    return int(lobby), int(match)


async def render(session: AsyncSession, row: models.DiscordMessage, *, broker: Any) -> Rendered | Keep | None:
    """The message ``row`` stands for, as of now.

    ``None`` is nothing to show (the mix is gone, the payload fills no card),
    :data:`KEEP` a lineup that is history -- leave its message alone. A
    failure to reach balancer-service raises: that is an outage, not an answer.
    """
    if row.kind in DELIVERABLE_KINDS:
        return await _notification(session, row)
    if row.kind == "mix.signup":
        return await _signup(row, broker)
    if row.kind == "mix.lineup":
        return await _lineup(session, row, broker)
    logger.error(f"❌ discord_message {row.id} is a {row.kind!r}, which nothing here renders")
    return None


# --- notifications -----------------------------------------------------------


async def _notification(session: AsyncSession, row: models.DiscordMessage) -> Rendered | None:
    payload = row.payload_json
    if not isinstance(payload, Mapping):
        logger.error(f"❌ discord_message {row.id} ({row.kind}) carries no payload to render")
        return None
    config = await _configs.for_workspace(session, row.workspace_id) if row.workspace_id is not None else None
    workspace_name, image_url = await _branding(session, row.workspace_id, payload)
    try:
        card = render_discord(
            row.kind,
            payload,
            locale=config.locale if config is not None else "ru",
            site_url=settings.public_site_url,
            workspace_name=workspace_name,
            image_url=image_url,
            personal=row.channel == "discord_dm",
        )
    except (KeyError, ValueError) as exc:
        # The publisher stored a payload this kind's template cannot be filled
        # from: it fails the same way on every retry.
        logger.error(f"❌ discord_message {row.id}: its payload does not fill a {row.kind} card: {exc!r}")
        return None
    return Rendered(card)


async def _branding(
    session: AsyncSession, workspace_id: int | None, payload: Mapping[str, Any]
) -> tuple[str | None, str | None]:
    """The organizer's name, and the card's picture: tournament logo, else workspace icon.

    Read when the card is rendered rather than snapshotted into the payload, so
    the card shows the organizer's current branding; a row deleted since just
    leaves it plain.
    """
    name = icon = logo = None
    if workspace_id is not None:
        found = (
            await session.execute(
                sa.select(models.Workspace.name, models.Workspace.icon_url).where(models.Workspace.id == workspace_id)
            )
        ).first()
        if found is not None:
            name, icon = found
    tournament_id = payload.get("tournament_id")
    if isinstance(tournament_id, int):
        logo = (
            await session.execute(sa.select(models.Tournament.logo_url).where(models.Tournament.id == tournament_id))
        ).scalar_one_or_none()
    return name, logo or icon


# --- mixes -------------------------------------------------------------------


async def _view(broker: Any, custom_game_id: int, lineups: list[dict[str, int]]) -> Mapping[str, Any] | None:
    """balancer-service's view of one mix; ``None`` when the mix is gone."""
    reply = await request_rpc(
        broker, {"custom_game_id": custom_game_id, "lineups": lineups}, DISCORD_VIEW_SUBJECT, timeout=_RPC_TIMEOUT
    )
    if reply is None:
        raise RuntimeError(f"{DISCORD_VIEW_SUBJECT} answered without an envelope")
    if not reply.ok:
        if reply.code == "not_found":
            return None
        raise RuntimeError(f"{DISCORD_VIEW_SUBJECT} failed: {reply.code}: {reply.message}")
    return reply.data


async def _signup(row: models.DiscordMessage, broker: Any) -> Rendered | None:
    custom_game_id = discord_messages.mix_id(row.subject)
    if custom_game_id is None:
        logger.error(f"❌ discord_message {row.id} is a signup card of {row.subject!r}, which is no mix")
        return None
    view = await _view(broker, custom_game_id, [])
    if view is None:
        return None
    signup = view["signup"]
    card = signup_card(
        mix_name=signup["mix_name"],
        host_name=signup.get("host_name"),
        board_url=view["board_url"],
        custom_game_id=custom_game_id,
        self_signup=signup["self_signup"],
        status=signup["status"],
        lobby_count=signup["lobby_count"],
        players=[
            SignupPlayer(
                name=player["name"],
                role=player.get("role"),
                benched=bool(player.get("benched")),
                rank=player.get("rank"),
                away=bool(player.get("away")),
            )
            for player in signup["players"]
        ],
        updated_at=datetime.fromisoformat(signup["updated_at"]),
        discipline=str(view.get("discipline") or ""),
        roles=[(str(role["code"]), str(role["label"])) for role in view.get("discipline_roles") or ()],
        flex=bool(view.get("discipline_flex")),
        lobbies=[
            SignupLobby(
                index=int(lobby["lobby_index"]),
                state=str(lobby["state"]),
                since=datetime.fromisoformat(lobby["live_started_at"]) if lobby.get("live_started_at") else None,
            )
            for lobby in signup.get("lobbies") or ()
        ],
    )
    return Rendered(card)


async def _lineup(session: AsyncSession, row: models.DiscordMessage, broker: Any) -> Rendered | Keep | None:
    custom_game_id = discord_messages.mix_id(row.subject)
    key = lineup_key(row.slot)
    if custom_game_id is None or key is None:
        logger.error(
            f"❌ discord_message {row.id} is a lineup card of {row.subject!r}/{row.slot!r}, which is no lineup"
        )
        return None
    lobby_index, match_number = key
    view = await _view(broker, custom_game_id, [{"lobby_index": lobby_index, "match_number": match_number}])
    if view is None:
        return None
    lineup = next(
        (
            entry
            for entry in view["lineups"]
            if entry["lobby_index"] == lobby_index and entry["match_number"] == match_number
        ),
        None,
    )
    # Only the lobby's newest card moves people: an older one gives its voice buttons up.
    lobby_rows = [
        other.id
        for other in await discord_messages.repository.for_subject(session, row.subject, statuses=LIVE_STATUSES)
        if (other_key := lineup_key(other.slot)) is not None and other_key[0] == lobby_index
    ]
    newest = lobby_rows[-1:] == [row.id]
    shown = row.card_json or {}

    if lineup is None or not lineup["current"]:
        # History: the card stays as it was posted -- minus the voice buttons
        # once a newer lineup of the lobby carries them.
        if newest or not shown.get("answers"):
            return KEEP
        return Rendered(DiscordCard.model_validate(shown).model_copy(update={"answers": []}))

    mix_name = view["signup"]["mix_name"]
    next_map = tuple(lineup["next_map"]) if lineup.get("next_map") else None
    picture = lineup_picture(
        mix_name=mix_name,
        match_number=match_number,
        variant=lineup["variant"],
        players=lineup["players"],
        # JSON object keys are strings; the picture looks teams up by index.
        team_names={int(index): name for index, name in (lineup.get("team_names") or {}).items()},
        next_map=next_map,
        map_image=lineup.get("map_image"),
        points_per_win=lineup.get("points_per_win"),
        board_url=view["board_url"],
        lobby_label=lineup.get("lobby_label"),
        discipline=str(view.get("discipline") or ""),
    )
    card = lineup_card(
        mix_name=mix_name,
        match_number=match_number,
        next_map=next_map,
        points_per_win=lineup.get("points_per_win"),
        board_url=view["board_url"],
        image_filename=picture.filename,
        lobby_label=lineup.get("lobby_label"),
        lobby_code=lineup.get("lobby_code"),
        mentions=lineup.get("mention_user_ids") or (),
        voice_target=lineup["voice_target"] if newest else None,
        map_choice=lineup.get("map_choice", True),
    )
    # The file name hashes everything drawn: the same name is the same picture,
    # already on the message -- nothing to fetch, draw or upload.
    file = None if shown.get("image_url") == card.image_url else await _draw(picture)
    # The card mentions the players it seats; a lineup nobody is pinged by is
    # one half the lobby misses. Users only: card text quotes user-written names.
    mentions = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)
    return Rendered(card, file, mentions)


async def _load_images(urls: Iterable[str]) -> dict[str, bytes]:
    """The bytes behind ``urls``; one that cannot be fetched is missing from the result."""
    wanted = set(urls)
    missing = wanted - _IMAGES.keys()
    if missing:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:

            async def fetch(url: str) -> None:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.warning(f"Lineup picture: could not load {url}: {exc!r}")
                    return
                _IMAGES[url] = response.content

            await asyncio.gather(*(fetch(url) for url in missing))
    return {url: _IMAGES[url] for url in wanted if url in _IMAGES}


async def _draw(picture: LineupPicture) -> discord.File:
    """``picture`` as an upload: its pictures fetched first, the draw off the event loop."""
    images = await _load_images(picture.image_urls)
    png = await asyncio.to_thread(render_png, picture, images)
    return discord.File(io.BytesIO(png), filename=picture.filename)
