#!/usr/bin/env python
"""D99 gate: a game's vocabulary is written only inside that game's module.

Core code (every runtime root outside ``backend/shared/disciplines/<code>/`` and ``frontend/src/disciplines/<code>/``)
reads games through the registry and their declarations, so a string literal naming a game, its roles, its catalog
labels, its identity provider, its stat codes or its asset folders is a hidden game assumption: an Overwatch fallback, an
unknown-role -> "damage" default, a class -> role inference. This scans the string tokens of the runtime roots -- Python
through ``ast``, TS/TSX/Go/JSON through a small lexer that skips comments and regex literals -- and fails on every token
outside its module that ``discipline_literal_exceptions.json`` does not name exactly.

Token sets come from ``shared.disciplines.DISCIPLINES`` at scan time, so a new module's vocabulary is guarded the day it
is registered. Whole-literal rules match a literal (or a template/f-string without substitutions) equal to a token;
contains/prefix rules match every chunk of a template/f-string. Concatenation (``"over" + "watch"``) is not followed:
behaviour tests own computed fallbacks. Tests, migrations, generated artifacts and message bundles are out of scope by
root, never by exception.

Usage (from ``backend/``): ``uv run python scripts/check_discipline_literals.py``. One line per finding
(``path:line rule token context``) or broken exception; exit 1 on any.
"""

from __future__ import annotations

import ast
import bisect
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from shared.disciplines import CATALOG_KINDS, DISCIPLINES, DisciplineSpec  # noqa: E402

EXCEPTIONS = BACKEND / "scripts" / "discipline_literal_exceptions.json"
SCAN_DIRS = ("backend", "frontend/src", "gateway")
ENTRYPOINTS = re.compile(r"backend/shared/disciplines/__init__\.py|frontend/src/disciplines/registry/[^/]+\.ts")
MODULE_DIR = re.compile(r"(?:backend/shared/disciplines|frontend/src/disciplines|frontend/public/disciplines)/([^/]+)/")
SERVICE_ROOT = re.compile(r"backend/[^/]+-service/(?:src|scripts)/")
#: Test files, exactly as the zone gate's exemption: ``*.test.ts(x)`` (``*.behavior.test.tsx`` included). Shared test
#: support is the ``frontend/src/test/`` root; harnesses and fixtures elsewhere are runtime-scanned.
TS_TEST = re.compile(r"\.test\.tsx?$")

ROLE_STOP = frozenset({"top", "mid", "bot", "position", "Top", "Mid", "Bot", "Position"})
# Generic words before they are a game's stat codes: "level" (log levels), "denies" (access control), "damage" (a
# role, which role-vocabulary already guards), "snapshot" (a function name).
STAT_STOP = frozenset(
    {"score", "deaths", "assists", "kills", "kill", "kd", "kda", "performance", "level", "denies", "damage", "snapshot"}
)
CATALOG_LABELS = ("hero", "heroes", "hero_id", "hero_ids", "gamemode", "gamemode_id", "gamemodes")
IDENTITY_TOKENS = (
    "battle_tag",
    "battle_tag_normalized",
    "battle_tags",
    "smurf_tags",
    "smurf_tags_json",
    "captain_battle_tag",
)

HINTS = {
    "discipline-code": "take the game from the owner/registry; never default or branch on a code",
    "role-vocabulary": "read roles from the owner's ontology (metadata/catalog.role)",
    "catalog-label": "use the generic catalog kinds/fields (character, map, mode, entity)",
    "identity": "use the owner provider's identity (identity_provider / PlayerIdentityRead)",
    "ow-prefix": "move game-specific names into the game's module",
    "stat-code": "read stat/event definitions from the discipline's metadata",
    "asset-path": "serve game assets from the module (role attrs / disciplines/<code>/)",
}


@dataclass(frozen=True, slots=True)
class Literal:
    """One string token: its chunks between substitutions, and whether it had none."""

    offset: int
    chunks: tuple[str, ...]
    whole: bool


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    rule: str
    token: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line} {self.rule} {self.token} {self.text.strip()[:140]}"


#: ``literal -> (token, discipline owning it or None)`` for every match.
Matcher = Callable[[Literal], Iterable[tuple[str, str | None]]]


# --------------------------------------------------------------------------------------------------- rules


def _whole(tokens: Mapping[str, str | None]) -> Matcher:
    return lambda lit: [(lit.chunks[0], tokens[lit.chunks[0]])] if lit.whole and lit.chunks[0] in tokens else []


def _delimited(tokens: Mapping[str, str | None]) -> Matcher:
    patterns = [(re.compile(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])"), t, o) for t, o in tokens.items()]
    return lambda lit: [(t, o) for rx, t, o in patterns if any(rx.search(chunk) for chunk in lit.chunks)]


def _prefix(pattern: str) -> Matcher:
    rx = re.compile(pattern)
    return lambda lit: [(chunk, None) for chunk in lit.chunks if rx.match(chunk)]


def build_rules(disciplines: Mapping[str, DisciplineSpec] = DISCIPLINES) -> dict[str, Matcher]:
    specs = list(disciplines.values())
    roles: dict[str, str | None] = {}
    for spec in specs:
        for dimension in spec.dimensions:
            roles[dimension.code] = None
            for role in dimension.roles:
                roles[role.code] = roles[role.name] = None
    labels = {label for spec in specs for label in spec.kinds.values() if label.lower() not in CATALOG_KINDS}
    providers = {str(spec.identity_provider) for spec in specs if spec.identity_provider}
    stats = {d.code for spec in specs for d in (*spec.stat_defs, *spec.event_types)}
    codes = _delimited({spec.code: spec.code for spec in specs})
    names = _whole({spec.name: spec.code for spec in specs})
    return {
        "discipline-code": lambda lit: [*codes(lit), *names(lit)],
        "role-vocabulary": _whole(dict.fromkeys(roles.keys() - ROLE_STOP)),
        "catalog-label": _whole(dict.fromkeys((*CATALOG_LABELS, *labels))),
        "identity": _whole(dict.fromkeys((*IDENTITY_TOKENS, *providers))),
        "ow-prefix": _prefix(r"(?:ow|OW)[_-]"),
        "stat-code": _whole(dict.fromkeys(stats - STAT_STOP)),
        "asset-path": _prefix(r"/(?:roles|divisions)/"),
    }


# ------------------------------------------------------------------------------------------------- lexers


def _python_literals(source: str) -> Iterator[Literal]:
    tree = ast.parse(source)
    starts = [0]
    starts.extend(i + 1 for i, c in enumerate(source) if c == "\n")

    def at(node: ast.expr) -> int:
        return starts[node.lineno - 1]

    def visit(node: ast.AST) -> Iterator[Literal]:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return  # docstrings and bare string statements are prose
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield Literal(at(node), (node.value,), True)
            return
        if isinstance(node, ast.JoinedStr):
            parts = [part.value for part in node.values if isinstance(part, ast.Constant)]
            subs = [part for part in node.values if isinstance(part, ast.FormattedValue)]
            yield Literal(at(node), tuple(parts) or ("",), not subs)
            for sub in subs:  # the expressions, not the format specs
                yield from visit(sub.value)
            return
        for child in ast.iter_child_nodes(node):
            yield from visit(child)

    yield from visit(tree)


_REGEX_AFTER = frozenset("(,=:[!&|?{};\n")
_REGEX_KEYWORDS = frozenset(
    {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "yield", "await"}
)
_WORD = re.compile(r"[A-Za-z0-9_$]+")


_ESCAPE = re.compile(r"\\(u\{[0-9A-Fa-f]+\}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|x[0-9A-Fa-f]{2}|[0-7]{1,3}|\r?\n|.)", re.S)
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}


def _escape_value(match: re.Match[str]) -> str:
    body = match.group(1)
    if body[0] in "uUx" and len(body) > 1:
        point = int(body.strip("uUx{}"), 16)
        return chr(point) if point <= 0x10FFFF else match.group()
    if body[0] in "01234567":
        return chr(int(body, 8))
    if body[0] in "\r\n":
        return ""  # a line continuation
    return _SIMPLE_ESCAPES.get(body, body)


def _unescape(raw: str) -> str:
    """The string value of a TS/Go literal body: ``"\\u006fverwatch"`` is ``overwatch``, not a spelling that evades."""
    text = _ESCAPE.sub(_escape_value, raw)
    try:  # join UTF-16 surrogate pairs (``\\uD83D\\uDE00``) into their code point
        return text.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeDecodeError:
        return text


def _quoted(src: str, i: int) -> tuple[str, int]:
    """The value of the ``'``/``"`` string opening at ``i`` and the index after it; ends at the line (JSX text)."""
    quote, start, i = src[i], i + 1, i + 1
    while i < len(src) and src[i] not in (quote, "\n"):
        i += 2 if src[i] == "\\" else 1
    return _unescape(src[start:i]), i + 1


def _js_literals(source: str) -> Iterator[Literal]:
    src, n = source, len(source)
    found: list[Literal] = []

    def code(i: int, in_template: bool) -> int:
        depth, prev = 0, "\n"
        while i < n:
            c = src[i]
            if c in " \t\r":
                i += 1
            elif c == "\n":
                prev, i = "\n", i + 1
            elif src.startswith("//", i):
                i = src.find("\n", i) % (n + 1)
            elif src.startswith("/*", i):
                end = src.find("*/", i + 2)
                i = n if end < 0 else end + 2
            elif c == "/" and src[i + 1 : i + 2] != ">" and (prev in _REGEX_AFTER or prev in _REGEX_KEYWORDS):
                i, in_class = i + 1, False
                while i < n and src[i] != "\n" and (src[i] != "/" or in_class):
                    in_class = (in_class or src[i] == "[") and src[i] != "]"
                    i += 2 if src[i] == "\\" else 1
                i, prev = i + 1, ")"
            elif c in "'\"":
                start = i
                text, i = _quoted(src, i)
                found.append(Literal(start, (text,), True))
                prev = ")"
            elif c == "`":
                i, prev = template(i), ")"
            elif c == "{":
                depth, prev, i = depth + 1, c, i + 1
            elif c == "}":
                if in_template and depth == 0:
                    return i + 1
                depth, prev, i = depth - 1, c, i + 1
            elif word := _WORD.match(src, i):
                prev, i = word.group(), word.end()
            else:
                prev, i = c, i + 1
        return n

    def template(i: int) -> int:
        start, chunks, buf, subs, i = i, [], [], False, i + 1
        while i < n and src[i] != "`":
            if src[i] == "\\":
                buf.append(src[i : i + 2])
                i += 2
            elif src.startswith("${", i):
                chunks.append(_unescape("".join(buf)))
                buf, subs = [], True
                i = code(i + 2, True)
            else:
                buf.append(src[i])
                i += 1
        chunks.append(_unescape("".join(buf)))
        found.append(Literal(start, tuple(chunks), not subs))
        return i + 1

    code(0, False)
    yield from found


def _go_literals(source: str) -> Iterator[Literal]:
    src, n, i = source, len(source), 0
    while i < n:
        if src.startswith("//", i):
            i = src.find("\n", i) % (n + 1)
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif src[i] == "`":
            end = src.find("`", i + 1)
            end = n if end < 0 else end
            yield Literal(i, (src[i + 1 : end],), True)
            i = end + 1
        elif src[i] in "\"'":
            start = i
            text, i = _quoted(src, i)
            if src[start] == '"':
                yield Literal(start, (text,), True)
        else:
            i += 1


def _json_literals(source: str) -> Iterator[Literal]:
    for match in re.finditer(r'"(?:[^"\\\n]|\\.)*"', source):
        yield Literal(match.start(), (json.loads(match.group()),), True)


LEXERS = {"py": _python_literals, "ts": _js_literals, "go": _go_literals, "json": _json_literals}


# ---------------------------------------------------------------------------------------------- scanning


def language(path: str) -> str | None:
    """The lexer for a repo-relative path inside the runtime roots, else ``None`` (out of scope by root)."""
    name = path.rsplit("/", 1)[-1]
    if path.endswith(".py"):
        if "/tests/" in path or name.startswith("test_"):
            return None
        if path.startswith(("backend/shared/testing/", "backend/migrations/", "backend/scripts/")):
            return None
        return "py" if path.startswith("backend/shared/") or SERVICE_ROOT.match(path) else None
    if path.startswith("frontend/src/"):
        if path.startswith(("frontend/src/i18n/", "frontend/src/test/")) or ".generated." in name:
            return None
        if TS_TEST.search(name):
            return None
        if name.endswith((".ts", ".tsx")):
            return "ts"
        return "json" if name.endswith(".json") else None
    if path.startswith("gateway/") and path.endswith(".go"):
        return None if name.endswith("_test.go") or path.startswith("gateway/internal/openapi/") else "go"
    return None


def scan_text(path: str, source: str, rules: Mapping[str, Matcher], codes: Iterable[str]) -> list[Finding]:
    lang = language(path)
    if lang is None:
        return []
    module = MODULE_DIR.match(path)
    owner = module.group(1) if module and module.group(1) in set(codes) else None
    entrypoint = ENTRYPOINTS.fullmatch(path) is not None
    starts = [0]
    starts.extend(i + 1 for i, c in enumerate(source) if c == "\n")
    lines = source.split("\n")
    findings = []
    for literal in LEXERS[lang](source):
        for rule, match in rules.items():
            for token, token_owner in dict(match(literal)).items():
                if owner is not None and not (rule == "discipline-code" and token_owner != owner):
                    continue
                if entrypoint and rule == "discipline-code":
                    continue
                line = bisect.bisect_right(starts, literal.offset)
                findings.append(Finding(path, line, rule, token, lines[line - 1]))
    return findings


def runtime_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *SCAN_DIRS],
        cwd=REPO,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return sorted({p for p in out.split("\0") if p and language(p) and (REPO / p).is_file()})


# -------------------------------------------------------------------------------------------- exceptions

_EXCEPTION_KEYS = ("path", "rule", "token", "context", "count", "reason", "owner", "remove_when")


def check_manifest(manifest: Mapping[str, object], root: Path = REPO) -> list[str]:
    """Shape errors: every entry names one existing file, one rule, one token, a context and a positive count."""
    if manifest.get("version") != 1 or not isinstance(manifest.get("exceptions"), list):
        return ['manifest: expected {"version": 1, "exceptions": [...]}']
    errors = []
    for index, entry in enumerate(manifest["exceptions"]):
        where = f"exception #{index}"
        if not isinstance(entry, dict) or set(entry) != set(_EXCEPTION_KEYS):
            errors.append(f"{where}: keys must be exactly {', '.join(_EXCEPTION_KEYS)}")
            continue
        if any(not isinstance(entry[key], str) or not entry[key] for key in _EXCEPTION_KEYS if key != "count"):
            errors.append(f"{where}: every field except count is a non-empty string")
            continue
        if not isinstance(entry["count"], int) or isinstance(entry["count"], bool) or entry["count"] < 1:
            errors.append(f"{where}: count must be a positive integer")
        # ``[`` stays legal: Next route folders are literally ``[id]``.
        if any(c in entry["path"] for c in "*?") or not (root / entry["path"]).is_file():
            errors.append(f"{where}: path {entry['path']!r} must name one existing file (no globs, no directories)")
    return errors


def apply_exceptions(findings: list[Finding], entries: list[Mapping[str, object]]) -> tuple[list[Finding], list[str]]:
    """Findings no entry covers, and every entry whose matches differ from its ``count`` (stale / too-broad).

    A finding counts against the entry with the longest matching context, so a short context never steals the
    findings of a more specific one on the same file and token."""
    used = [0] * len(entries)
    left = []
    for finding in findings:
        matches = [
            index
            for index, entry in enumerate(entries)
            if (entry["path"], entry["rule"], entry["token"]) == (finding.path, finding.rule, finding.token)
            and str(entry["context"]) in finding.text
        ]
        if matches:
            used[max(matches, key=lambda index: len(str(entries[index]["context"])))] += 1
        else:
            left.append(finding)
    broken = [
        f"{e['path']} {e['rule']} {e['token']} {e['context']!r}: "
        f"{'too-broad' if n > e['count'] else 'stale'} exception (matches {n}, declares {e['count']})"
        for e, n in zip(entries, used, strict=True)
        if n != e["count"]
    ]
    return left, broken


def main() -> int:
    rules = build_rules()
    findings = [
        finding
        for path in runtime_files()
        for finding in scan_text(path, (REPO / path).read_text(encoding="utf-8"), rules, DISCIPLINES)
    ]
    manifest = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
    errors = check_manifest(manifest)
    if errors:
        print("\n".join(errors))
        return 1
    left, broken = apply_exceptions(findings, manifest["exceptions"])
    for finding in left:
        print(finding)
    for line in broken:
        print(line)
    if left:
        print("\nWhere it belongs:")
        for rule in sorted({f.rule for f in left}):
            print(f"  {rule}: {HINTS[rule]}")
    if left or broken:
        print(f"\n{len(left)} finding(s), {len(broken)} broken exception(s). A game's vocabulary lives in its module")
        print(f"(backend/shared/disciplines/<code>/, frontend/src/disciplines/<code>/); exceptions: {EXCEPTIONS.name}")
        return 1
    print(f"discipline literals: clean ({len(manifest['exceptions'])} exceptions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
