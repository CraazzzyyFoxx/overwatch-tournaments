"""Uploads the bot's application emoji: ``python -m src.tools.emoji_sync [--dry-run]``.

Publishers name an emoji and the bot resolves it (``shared.domain.discord_ui``,
``src.interactions.emoji``); until one is uploaded every surface falls back to
Unicode. This fills the application's emoji slots from ``assets/emoji/`` -- the
set ``frontend/scripts/gen-discord-emoji.mjs`` renders (tinted role icons and
lucide icons) -- plus the division badges the site already ships.

``--grids`` adds the badges that are *not* in the repo: a workspace that built
its own division grid in the admin UI stores each tier's picture as a URL, and
without this pass every custom tier renders as a blank in the seat panel. The
tiers are read straight from the database and their icons downloaded from the
site, so the tool needs the service env it already needs for the bot token.

Run it once per application (dev and prod are different applications with
different emoji ids, which is exactly why no id is ever hard-coded); rerun it
with ``--grids`` after a workspace publishes a new grid.

Existing names are left alone: Discord has no "replace", so re-uploading one
means deleting it first, and a deleted emoji blanks out every message already
posted with it. Delete it by hand in the developer portal if a picture must
change.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import discord
import httpx

from shared.domain.discord_ui import EMOJI, EMOJI_PREFIX, division_emoji
from shared.repository import DivisionGridRepository
from src.core.config import Settings
from src.core.db import async_session_maker

#: ``backend/discord-service/src/tools/emoji_sync.py`` -> the repo root. Resolved
#: from this file, not from the shell's CWD: the tool is run from wherever.
_SERVICE = Path(__file__).resolve().parents[2]
_REPO = _SERVICE.parents[1]

_DIVISIONS = _REPO / "frontend" / "public" / "divisions"
_ASSETS = _SERVICE / "assets" / "emoji"

_SUFFIXES = (".png", ".gif", ".webp")

#: Discord's own cap on an emoji upload.
_MAX_BYTES = 256 * 1024

#: Discord's cap on application emoji. Blowing through it fails every upload
#: past the limit, so the plan says so before a single one is attempted.
_MAX_EMOJI = 2000


def _collect(extra_dirs: Sequence[Path]) -> dict[str, Path]:
    """Emoji name -> the picture to upload for it.

    Later sources win: a file in ``assets/emoji`` (or a ``--dir``) named like a
    division badge replaces the site's picture, which is the point of the
    directory. The site's own role icons are not a source: they are white and
    vanish on Discord's light theme; ``assets/emoji`` holds tinted ones.
    """
    found: dict[str, Path] = {}
    for path in sorted(_DIVISIONS.glob("*.png")):
        # The numeric files are the same badges under their database ids; the
        # slug ones carry the name ``division_emoji`` builds.
        if not path.stem.isdigit():
            found["div_" + path.stem.lower().replace("-", "_")] = path
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


@dataclass(frozen=True, slots=True)
class GridBadge:
    """One division tier as the bot will know it: emoji name and where its picture lives."""

    name: str
    url: str
    grid_id: int


def badge_name(slug: str) -> str:
    """``gold-3`` -> ``div_gold_3``: the very name the cards ask for.

    Derived from :func:`shared.domain.discord_ui.division_emoji` rather than
    re-implementing its normalisation -- a second copy of that regex is a badge
    that silently never resolves.
    """
    shortcode = division_emoji(slug)
    return shortcode[1:-1].removeprefix(EMOJI_PREFIX) if shortcode else ""


def plan_badges(tiers: Iterable[tuple[int, str, str]], existing: set[str]) -> tuple[list[GridBadge], list[str]]:
    """``(grid_id, slug, icon_url)`` rows -> what to upload, and why the rest is not.

    One emoji name per tier slug, first occurrence wins. Two *versions* of one
    grid normally repeat every slug, which is not worth a word; two different
    grids claiming one slug is, because the second grid's tiers will render the
    first grid's badge and nobody would guess why.
    """
    uploads: list[GridBadge] = []
    notes: list[str] = []
    claimed: dict[str, int] = {}
    for grid_id, slug, icon_url in tiers:
        name = badge_name(slug)
        if not name or not icon_url:
            notes.append(f"skip grid {grid_id} tier {slug!r}: no slug or no icon")
            continue
        owner = claimed.get(name)
        if owner is not None:
            if owner != grid_id:
                notes.append(f"skip {name}: grid {grid_id} reuses the slug grid {owner} already claimed")
            continue
        claimed[name] = grid_id
        if name in existing:
            notes.append(f"skip {name}: already uploaded")
            continue
        uploads.append(GridBadge(name=name, url=icon_url, grid_id=grid_id))
    return uploads, notes


async def _grid_tiers() -> list[tuple[int, str, str]]:
    """Every tier of every grid version, oldest grid first, as ``(grid_id, slug, icon_url)``."""
    async with async_session_maker() as session:
        grids, _total = await DivisionGridRepository().list(session)
        return [
            (grid.id, tier.slug, tier.icon_url)
            for grid in sorted(grids, key=lambda g: g.id)
            for version in grid.versions
            for tier in version.tiers
        ]


async def _download(client: httpx.AsyncClient, badge: GridBadge, site_url: str) -> bytes | None:
    """The badge's picture, or ``None`` with a printed reason.

    No proxy: that one is the egress route to Discord, and these URLs are the
    platform's own site. A grid built in the admin UI stores a site-relative
    path, so it is joined to ``PUBLIC_SITE_URL``.
    """
    url = urljoin(site_url.rstrip("/") + "/", badge.url)
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"failed {badge.name}: {url} ({exc})")
        return None
    media_type = response.headers.get("content-type", "").split(";")[0].strip()
    if not media_type.startswith("image/"):
        # An HTML error page or a JSON 404 body: Discord would refuse it anyway,
        # and the refusal would not say which tier was wrong.
        print(f"skip {badge.name}: {url} answered {media_type or 'nothing'}, not an image")
        return None
    if len(response.content) > _MAX_BYTES:
        print(f"skip {badge.name}: {len(response.content) // 1024} KiB is over Discord's 256 KiB ({url})")
        return None
    return response.content


async def _upload_badges(
    client: discord.Client, badges: Sequence[GridBadge], site_url: str, *, dry_run: bool
) -> tuple[int, int]:
    """Download each badge from the site and hand it to Discord: ``(uploaded, refused)``."""
    if not badges:
        return 0, 0
    uploaded = refused = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(30), follow_redirects=True) as http:
        for badge in badges:
            url = urljoin(site_url.rstrip("/") + "/", badge.url)
            if dry_run:
                print(f"would upload {EMOJI_PREFIX}{badge.name} from {url} (grid {badge.grid_id})")
                continue
            image = await _download(http, badge, site_url)
            if image is None:
                continue
            try:
                await client.create_application_emoji(name=EMOJI_PREFIX + badge.name, image=image)
            except discord.HTTPException as exc:
                print(f"failed {EMOJI_PREFIX}{badge.name}: HTTP {exc.status} {exc.text}")
                refused += 1
                continue
            uploaded += 1
            print(f"uploaded {EMOJI_PREFIX}{badge.name} from {url}")
    return uploaded, refused


async def _run(*, dry_run: bool, extra_dirs: Sequence[Path], grids: bool) -> int:
    """Upload what is missing; how many steps failed (refused uploads, an unreadable grid table)."""
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
        badges: list[GridBadge] = []
        failed_reads = 0
        if grids:
            try:
                tiers = await _grid_tiers()
            except Exception as exc:  # noqa: BLE001 -- any DB fault: the file set still goes up
                # The shipped set does not depend on the database; one unreachable
                # Postgres must not leave the bot on Unicode. Still a failed run.
                print(f"failed --grids: could not read the division grids ({exc!r}); custom-grid badges skipped")
                failed_reads = 1
            else:
                # Planned against the names the file pass already claims, so a tier
                # whose badge ships in the repo is not fetched twice.
                badges, badge_notes = plan_badges(tiers, existing | {name for name, _ in uploads})
                notes += badge_notes
        for note in notes:
            print(note)
        planned = len(uploads) + len(badges)
        if len(existing) + planned > _MAX_EMOJI:
            print(
                f"warning: {len(existing)} + {planned} is over Discord's {_MAX_EMOJI}-emoji cap for one "
                f"application; the uploads past it will be refused"
            )
        uploaded, refused = 0, failed_reads
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
        badge_uploads, badge_refusals = await _upload_badges(client, badges, settings.public_site_url, dry_run=dry_run)
        uploaded += badge_uploads
        refused += badge_refusals
        verb = "would upload" if dry_run else "uploaded"
        print(
            f"{len(existing)} already in the application, {verb} {planned if dry_run else uploaded}, refused {refused}"
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
    parser.add_argument(
        "--grids",
        action="store_true",
        help="also upload a badge per division-grid tier in the database (needs DB access)",
    )
    args = parser.parse_args()
    # Non-zero when Discord refused an upload, so a one-shot container run of
    # this tool shows up as failed instead of exiting clean over a half set.
    return 1 if asyncio.run(_run(dry_run=args.dry_run, extra_dirs=args.dirs, grids=args.grids)) else 0


if __name__ == "__main__":
    sys.exit(main())
