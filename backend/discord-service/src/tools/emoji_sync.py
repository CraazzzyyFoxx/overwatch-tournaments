"""Uploads the bot's application emoji: ``python -m src.tools.emoji_sync [--dry-run]``.

Publishers name an emoji and the bot resolves it (``shared.domain.discord_ui``,
``src.interactions.emoji``); until one is uploaded every surface falls back to
Unicode. This fills the application's emoji slots from ``assets/emoji/`` -- the
set ``frontend/scripts/gen-discord-emoji.mjs`` renders (tinted role icons and
lucide icons) -- plus the Overwatch rank badges in the repo's ``static/divisions``
(``gold-3.png`` -> ``div_gold_3``), the ranks the seat panel badges with.

Run it once per application (dev and prod are different applications with
different emoji ids, which is exactly why no id is ever hard-coded); normally
the one-shot ``discord-emoji`` compose service does.

Existing names are left alone: Discord has no "replace", so re-uploading one
means deleting it first, and a deleted emoji blanks out every message already
posted with it. Delete it by hand in the developer portal if a picture must
change.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

import discord

from shared.domain.discord_ui import EMOJI, EMOJI_PREFIX, division_emoji
from src.core.config import Settings

#: ``backend/discord-service/src/tools/emoji_sync.py`` -> the repo root. Resolved
#: from this file, not from the shell's CWD: the tool is run from wherever. In
#: the image the service sits at ``/app/discord-service``, so the root is ``/``
#: and the compose service mounts the checkout's ``static/divisions`` there.
_SERVICE = Path(__file__).resolve().parents[2]
_REPO = _SERVICE.parents[1]

_DIVISIONS = _REPO / "static" / "divisions"
_ASSETS = _SERVICE / "assets" / "emoji"

_SUFFIXES = (".png", ".gif", ".webp")

#: Discord's own cap on an emoji upload.
_MAX_BYTES = 256 * 1024

#: Discord's cap on application emoji. Blowing through it fails every upload
#: past the limit, so the plan says so before a single one is attempted.
_MAX_EMOJI = 2000


def badge_name(slug: str) -> str:
    """``gold-3`` -> ``div_gold_3``: the very name the cards ask for.

    Derived from :func:`shared.domain.discord_ui.division_emoji` rather than
    re-implementing its normalisation -- a second copy of that regex is a badge
    that silently never resolves.
    """
    shortcode = division_emoji(slug)
    return shortcode[1:-1].removeprefix(EMOJI_PREFIX) if shortcode else ""


def _collect(extra_dirs: Sequence[Path]) -> dict[str, Path]:
    """Emoji name -> the picture to upload for it.

    Later sources win: a file in ``assets/emoji`` (or a ``--dir``) named like a
    rank badge replaces the repo's picture, which is the point of the
    directory. The site's own role icons are not a source: they are white and
    vanish on Discord's light theme; ``assets/emoji`` holds tinted ones.
    """
    found: dict[str, Path] = {}
    for path in sorted(_DIVISIONS.glob("*.png")):
        found[badge_name(path.stem)] = path
    for directory in (_ASSETS, *extra_dirs):
        for path in sorted(directory.glob("*")):
            if path.is_file() and path.suffix.lower() in _SUFFIXES:
                found[path.stem.lower()] = path
    return found


def _plan(extra_dirs: Sequence[Path], existing: set[str]) -> tuple[list[tuple[str, Path]], list[str]]:
    """What to upload, and one line per name that is not uploaded and why."""
    uploads: list[tuple[str, Path]] = []
    notes: list[str] = []
    for name, path in sorted(_collect(extra_dirs).items()):
        if name not in EMOJI and not name.startswith("div_"):
            notes.append(f"skip {name}: not an emoji any publisher can name ({path})")
        elif name in existing:
            notes.append(f"skip {name}: already uploaded")
        elif path.stat().st_size > _MAX_BYTES:
            notes.append(f"skip {name}: {path.stat().st_size // 1024} KiB is over Discord's 256 KiB ({path})")
        else:
            uploads.append((name, path))
    return uploads, notes


async def _run(*, dry_run: bool, extra_dirs: Sequence[Path]) -> int:
    """Upload what is missing; the number of uploads Discord refused (0 = all good)."""
    settings = Settings()
    # Through the egress proxy, like the bot itself: the production host does not
    # reach Discord directly.
    client = discord.Client(intents=discord.Intents.none(), proxy=settings.proxy_url)
    # REST only: login fills in the application id, which is all the emoji
    # endpoints need. No gateway session, so running this next to the live bot
    # does not disturb it.
    await client.login(settings.discord_token)
    try:
        # The registry keys emoji by bare name; the application knows them with
        # the ``owt_`` prefix. Other emoji in the application are not ours.
        existing = {
            item.name[len(EMOJI_PREFIX) :]
            for item in await client.fetch_application_emojis()
            if item.name.startswith(EMOJI_PREFIX)
        }
        uploads, notes = _plan(extra_dirs, existing)
        for note in notes:
            print(note)
        if len(existing) + len(uploads) > _MAX_EMOJI:
            print(
                f"warning: {len(existing)} + {len(uploads)} is over Discord's {_MAX_EMOJI}-emoji cap for one "
                f"application; the uploads past it will be refused"
            )
        uploaded = refused = 0
        for name, path in uploads:
            if dry_run:
                print(f"would upload {EMOJI_PREFIX}{name} from {path}")
                continue
            try:
                await client.create_application_emoji(name=EMOJI_PREFIX + name, image=path.read_bytes())
            except discord.HTTPException as exc:
                print(f"failed {EMOJI_PREFIX}{name}: HTTP {exc.status} {exc.text}")
                refused += 1
                continue
            uploaded += 1
            print(f"uploaded {EMOJI_PREFIX}{name} from {path}")
        verb = "would upload" if dry_run else "uploaded"
        print(
            f"{len(existing)} already in the application, {verb} {len(uploads) if dry_run else uploaded}, "
            f"refused {refused}"
        )
        return refused
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, upload nothing")
    parser.add_argument(
        "--dir",
        dest="dirs",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="another directory of <name>.png|gif|webp files (repeatable)",
    )
    args = parser.parse_args()
    # Non-zero when Discord refused an upload, so a one-shot container run of
    # this tool shows up as failed instead of exiting clean over a half set.
    return 1 if asyncio.run(_run(dry_run=args.dry_run, extra_dirs=args.dirs)) else 0


if __name__ == "__main__":
    sys.exit(main())
