"""Publish the bot's slash commands to Discord. A deploy step, never a startup one.

``python -m src.tools.sync_commands`` registers them globally (Discord rolls a
global command out over roughly an hour); ``--guild <id>`` registers them in
one guild, which is instant and is what development uses.

Syncing on every boot would spend one of Discord's few daily sync calls per
restart and would publish whatever the running process happens to hold, so the
bot never does it: this tool logs in (no gateway connection, no RabbitMQ, no
emoji fetch), builds the command tree exactly as ``setup_hook`` would, syncs
and leaves.
"""

from __future__ import annotations

import argparse
import asyncio

import discord

from src.bot import LogCollectorBot
from src.cogs.interactions import InteractionsCog
from src.core.config import Settings


async def sync(guild_id: int | None) -> list[str]:
    settings = Settings()
    bot = LogCollectorBot(settings)
    try:
        await bot.login(settings.discord_token)
        await bot.add_cog(InteractionsCog(bot))
        guild = discord.Object(id=guild_id) if guild_id is not None else None
        if guild is not None:
            # A guild sync publishes a *copy* of the global tree, which is why
            # the commands are copied in first rather than declared per guild.
            bot.tree.copy_global_to(guild=guild)
        return [command.name for command in await bot.tree.sync(guild=guild)]
    finally:
        await bot.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guild", type=int, default=None, help="sync into this guild only (instant)")
    args = parser.parse_args()

    names = asyncio.run(sync(args.guild))
    where = f"guild {args.guild}" if args.guild is not None else "globally"
    print(f"Synced {len(names)} command(s) {where}: {', '.join(names) or '-'}")


if __name__ == "__main__":
    main()
