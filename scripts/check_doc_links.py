#!/usr/bin/env python3
"""Fail when a maintained Markdown document links to a file that does not exist.

Documentation links rot silently: a file gets renamed or deleted and the six
documents pointing at it keep rendering, just wrong. The only way this stays at
zero is a gate, so this runs in CI (.github/workflows/ci-docs.yml).

Only relative links are resolved. External URLs are not fetched -- a network
call in a lint job buys flakiness, not correctness.

Usage:
  python3 scripts/check_doc_links.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

LINK_RE = re.compile(r"\]\(\s*([^)\s]+?)(?:\s+\"[^\"]*\")?\s*\)")

#: A "link" carrying regex or format-string metacharacters is a code sample that
#: happens to look like Markdown, not a link. Checking it produces only noise.
NOT_A_PATH = re.compile(r"[\[\]\\^*+?{}|<>$]")

SKIP_SCHEME = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.IGNORECASE)


def tracked_markdown() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def broken_links(document: str) -> list[str]:
    text = (ROOT / document).read_text(encoding="utf-8", errors="replace")
    parent = Path(document).parent
    found: list[str] = []
    for match in LINK_RE.finditer(text):
        target = match.group(1)
        if SKIP_SCHEME.search(target) or NOT_A_PATH.search(target):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        resolved = ROOT / unquote(path.lstrip("/")) if path.startswith("/") else ROOT / parent / unquote(path)
        if not resolved.exists():
            found.append(target)
    return found


def main() -> int:
    failures: dict[str, list[str]] = {}

    for document in tracked_markdown():
        found = broken_links(document)
        if found:
            failures[document] = found

    if not failures:
        print("all documents link to files that exist")
        return 0

    total = sum(len(v) for v in failures.values())
    print(f"\nERROR: {total} broken link(s) in documentation:\n", file=sys.stderr)
    for document, targets in sorted(failures.items()):
        for target in targets:
            print(f"  {document} -> {target}", file=sys.stderr)
    print(
        "\nFix the link, or move the target back. If the target is genuinely gone, "
        "remove the link and keep the sentence true.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
