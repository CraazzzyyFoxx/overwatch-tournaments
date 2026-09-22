#!/usr/bin/env python
"""Generate frontend/src/lib/divisions/ow-ladder.generated.json from the Python ladder.

The ladder is written down exactly once, in ``shared.domain.ow_ladder.LADDER``.
Every Python consumer imports it. The frontend cannot -- and cannot fetch it
either: the default division grid has to resolve synchronously during SSR and the
first client render, because the workspace store persists only
``currentWorkspaceId`` and fetches the workspace (which carries the real grid) in
a client effect. An API round-trip cannot fill that window.

So the frontend gets a generated artifact instead of a hand-written mirror. It is
committed (like ``gateway/internal/openapi/schemas.json``) and ``--check``
byte-compares it, so a ladder change that skips this script fails CI
(.github/workflows/lint-backend.yml). Nothing about the ladder is written twice,
so there is nothing left to drift.

Everything DERIVED is exported -- the 45 resolved tiers and the full native
division+tier -> rank_value table -- so ``ow-ladder.ts`` performs lookups only.
Re-deriving tier offsets or the open-ended top in TypeScript is exactly the
duplication this replaces.

Usage:
  uv run python backend/scripts/export_ow_ladder.py            # write
  uv run python backend/scripts/export_ow_ladder.py --check    # CI staleness gate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from shared.domain import ow_ladder  # noqa: E402

ARTIFACT = BACKEND.parent / "frontend" / "src" / "lib" / "divisions" / "ow-ladder.generated.json"


def build_document() -> dict:
    """The ladder, resolved to everything the frontend reads."""
    return {
        "_generated_by": "backend/scripts/export_ow_ladder.py -- do not edit by hand",
        "_source": "backend/shared/domain/ow_ladder.py",
        "tiers_per_division": ow_ladder.TIERS_PER_DIVISION,
        "tier_span": ow_ladder.TIER_SPAN,
        "division_icon_base": ow_ladder.DIVISION_ICON_BASE,
        # Native OverFast division names, highest first. The admin rank-mapping
        # grid lists these, so it cannot offer a division the parser rejects.
        "ow_divisions_desc": [division.ow_division.value for division in ow_ladder.LADDER],
        "tiers": [
            {
                "number": tier.number,
                "slug": tier.slug,
                "name": tier.name,
                "rank_min": tier.rank_min,
                "rank_max": tier.rank_max,
                "icon_url": tier.icon_url,
            }
            for tier in ow_ladder.iter_tiers()
        ],
        # "{ow_division}-{tier}" -> rank_value, i.e. the parser's
        # ``build_default_lookup`` flattened. Exported so the admin mapping grid
        # does no rank arithmetic of its own.
        "ow_rank_values": {
            f"{division.ow_division.value}-{tier}": ow_ladder.tier_rank_min(division.base, tier)
            for division in ow_ladder.LADDER
            for tier in range(1, ow_ladder.TIERS_PER_DIVISION + 1)
        },
    }


def render() -> bytes:
    """The artifact's exact bytes.

    ``sort_keys`` + fixed indent make the output stable across runs, and the
    newline is forced to LF: ``write_text`` would translate it to CRLF on Windows,
    so the committed artifact -- and therefore ``--check`` -- would depend on who
    generated it. Prettier (``bun run format`` covers ``**/*.json``) also
    normalizes to LF, and a reformat of a generated file would fail this gate.
    """
    document = json.dumps(build_document(), indent=2, sort_keys=True) + "\n"
    return document.encode("utf-8")


def main(argv: list[str]) -> int:
    if argv and argv != ["--check"]:
        print(f"usage: {Path(__file__).name} [--check]", file=sys.stderr)
        return 2

    document = render()
    relative = ARTIFACT.relative_to(BACKEND.parent)

    if argv == ["--check"]:
        committed = ARTIFACT.read_bytes() if ARTIFACT.exists() else b""
        if committed == document:
            print(f"{ARTIFACT.name} is up to date ({len(document)} bytes)", file=sys.stderr)
            return 0
        print(f"ERROR: {relative} is STALE.", file=sys.stderr)
        print("shared.domain.ow_ladder moved on but the artifact was not regenerated.", file=sys.stderr)
        print(
            f"Fix: uv run python backend/scripts/export_ow_ladder.py && git add {relative}",
            file=sys.stderr,
        )
        return 1

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_bytes(document)
    print(f"wrote {relative} ({len(document)} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
