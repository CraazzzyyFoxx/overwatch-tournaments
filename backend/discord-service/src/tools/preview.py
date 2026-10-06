"""Posts card JSON to a channel: ``python -m src.tools.preview --channel ID card.json ...``.

For looking at a card the way Discord actually draws it -- emoji, accent
colour, button row -- without waiting for the event that would publish it.
Each file is one ``DiscordCard`` payload, the same shape a publisher puts in
``DiscordCommandEvent.card``.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import discord

from shared.schemas.events import DiscordCard
from src.core.config import Settings
from src.interactions.cards import card_view
from src.interactions.emoji import registry


async def _run(channel_id: int, paths: list[Path]) -> None:
    cards = [DiscordCard.model_validate_json(path.read_text(encoding="utf-8")) for path in paths]
    client = discord.Client(intents=discord.Intents.none())
    await client.login(Settings().discord_token)
    try:
        await registry.load(client)
        channel = await client.fetch_channel(channel_id)
        for path, card in zip(paths, cards, strict=True):
            message = await channel.send(view=card_view(card), allowed_mentions=discord.AllowedMentions.none())
            print(f"{path}: {message.jump_url}")
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", required=True, type=int, help="channel id to post into")
    parser.add_argument("cards", nargs="+", type=Path, metavar="card.json", help="DiscordCard JSON files")
    args = parser.parse_args()
    asyncio.run(_run(args.channel, args.cards))


if __name__ == "__main__":
    main()
