#!/usr/bin/env python
"""Regenerate the entity diagrams in docs/database_erd.md from SQLAlchemy metadata.

The ERD used to be written by hand. It drifted: by the time this script was
added it was missing 32 of 124 tables -- every custom-game table, the whole
pick/ban engine, team registration, encounter reports, ``member_rank``,
``audit_log`` -- and pinned an Alembic head (``catalias0001``) that no longer
exists in ``backend/migrations/versions`` at all. A 60 KB hand-maintained mirror
of the schema, with nothing gating it, can only rot.

So the *entities* are generated and the *prose* is not. Each domain section of
the document carries a marker pair::

    <!-- ERD:auto identity -->
    ```mermaid
    erDiagram
    ...
    ```
    <!-- /ERD:auto -->

Everything between the markers is owned by this script; everything outside them
-- the intro, the per-domain explanations, the reading notes, the change history
-- is owned by whoever writes the document. Adding a model therefore cannot
silently leave the ERD behind, and rewording an explanation cannot be clobbered
by a regeneration.

Grouping is derived, never configured: a table belongs to the package its model
class lives in (``shared.models.<package>``), which is the same grouping the
document's own introduction describes. An association table with no mapped class
follows the tables it references. One diagram per package: the document's section
structure therefore tracks the code's package structure with nothing to maintain.

``--check`` rewrites nothing and exits non-zero when the committed document does
not match what the models would produce -- the CI gate in
.github/workflows/lint-backend.yml, next to the OpenAPI manifest and OW ladder
gates.

The same diagrams also go to ``frontend/src/app/(site)/docs/schema.generated.json``,
which the site's schema page renders. It used to hand-copy the Mermaid blocks out
of this document and was a dozen migrations behind within two days; now both are
written by one run and checked by one gate.

Usage:
  uv run python scripts/export_erd.py            # write
  uv run python scripts/export_erd.py --check    # CI staleness gate
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(SCRIPTS))

from export_db_schema import sa_type  # noqa: E402  -- one type-name table, not two

import shared.models  # noqa: E402, F401  -- importing registers every table
from shared.core.db import Base  # noqa: E402

DOCUMENT = BACKEND.parent / "docs" / "database_erd.md"
ARTIFACT = BACKEND.parent / "frontend" / "src" / "app" / "(site)" / "docs" / "schema.generated.json"
MIGRATIONS = BACKEND / "migrations" / "versions"


#: An empty marker pair -- the two comments on consecutive lines -- is how a new
#: section is authored, so the body must be allowed to be nothing at all. The
#: newlines around the generated content are supplied by the replacement, not
#: matched here; requiring them made an empty pair fail to match and the previous
#: pair swallow everything up to the next closing marker.
BLOCK_RE = re.compile(
    r"(?P<open><!-- ERD:auto (?P<key>[\w./-]+) -->)(?P<body>.*?)(?P<close><!-- /ERD:auto -->)",
    re.DOTALL,
)


# --------------------------------------------------------------------------- #
# grouping
# --------------------------------------------------------------------------- #


def package_of_module(module: str) -> str:
    """``shared.models.tournament.pick_ban`` -> ``tournament``.

    Models that live directly in ``shared.models`` (``casual``, ``custom_game``)
    are their own group, named after the module.
    """
    tail = module.removeprefix("shared.models.")
    return tail.split(".", 1)[0]


def table_groups() -> dict[str, list]:
    """Map every table to the model package it is defined in.

    One group per package, and therefore one diagram per package. Deliberately
    not one per Postgres schema and not one per module: the first puts 35 tables
    in a single graph because they share a namespace, the second produces a dozen
    single-entity graphs. The package is the unit the code already groups by, so
    the document's sections track the code's layout with nothing to maintain. If
    a package grows too large to read, the fix is to split the package -- and the
    document follows on the next run.
    """
    module_of: dict[str, str] = {}
    for mapper in Base.registry.mappers:
        module_of[mapper.class_.__table__.key] = mapper.class_.__module__

    # Association tables have no mapped class. They belong with whatever they
    # join; the first foreign key decides, which for a join table is always a
    # table in the same domain.
    for table in Base.metadata.tables.values():
        if table.key in module_of:
            continue
        for fk in (fk for col in table.columns for fk in col.foreign_keys):
            referenced = module_of.get(fk.column.table.key)
            if referenced:
                module_of[table.key] = referenced
                break

    orphans = [t.key for t in Base.metadata.tables.values() if t.key not in module_of]
    if orphans:
        raise SystemExit(
            "ERROR: these tables have neither a mapped class nor a resolvable "
            f"foreign key, so they cannot be placed in a diagram: {orphans}"
        )

    groups: dict[str, list] = defaultdict(list)
    for table in Base.metadata.tables.values():
        groups[package_of_module(module_of[table.key])].append(table)
    for tables in groups.values():
        tables.sort(key=lambda t: (t.schema or "public", t.name))
    return dict(sorted(groups.items()))


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def entity(table) -> str:
    """``SCHEMA_TABLE`` — the document's stated naming convention.

    Qualifying is not decoration: ``user`` exists in three schemas, ``team`` and
    ``tournament`` in two each.
    """
    return f"{(table.schema or 'public')}_{table.name}".upper()


def mermaid_type(column) -> str:
    """A Mermaid-safe type token.

    Mermaid's attribute grammar accepts word characters, brackets and parens
    only, so an enum name arriving quoted or a type carrying a collation has to
    be reduced to one token.
    """
    raw = sa_type(column).replace('"', "")
    if not getattr(column.type, "enums", None):
        # sa_type only lower-cases the names it has a mapping for, so anything
        # carrying a length or precision comes back as VARCHAR(80). Enum names
        # keep their own casing; they are identifiers, not type keywords.
        raw = raw.lower()
    cleaned = re.sub(r"[^A-Za-z0-9_()\[\], ]", "_", raw).strip()
    return cleaned.replace(" ", "_") or "unknown"


def keys_of(table, column) -> str:
    marks = []
    if column.primary_key:
        marks.append("PK")
    if column.foreign_keys:
        marks.append("FK")
    if not column.primary_key and (
        column.unique
        or any(
            len(c.columns) == 1 and column.name in c.columns
            for c in table.constraints
            if c.__class__.__name__ == "UniqueConstraint"
        )
    ):
        marks.append("UK")
    return ",".join(marks)


def render_entity(table) -> list[str]:
    lines = [f"    {entity(table)} {{"]
    for column in table.columns:
        marks = keys_of(table, column)
        suffix = f" {marks}" if marks else ""
        nullable = ' "nullable"' if column.nullable and not column.primary_key else ""
        lines.append(f"        {mermaid_type(column)} {column.name}{suffix}{nullable}")
    lines.append("    }")
    return lines


def render_relations(tables) -> list[str]:
    """One line per foreign key, including edges that leave the block.

    An edge to a table in another domain is kept and its target rendered as a
    bare node: dropping it would hide exactly the cross-domain coupling a reader
    opens an ERD to find.
    """
    local = {t.key for t in tables}
    seen: set[str] = set()
    lines: list[str] = []
    for table in tables:
        for column in table.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table
                # Emit an inbound edge only once, from the child's own block.
                if table.key not in local:
                    continue
                unique = "UK" in keys_of(table, column) or column.primary_key
                left = "|o" if column.nullable else "||"
                right = "o|" if unique else "o{"
                line = f'    {entity(parent)} {left}--{right} {entity(table)} : "{column.name}"'
                if line not in seen:
                    seen.add(line)
                    lines.append(line)
    return sorted(lines)


def unique_keys(tables) -> list[tuple[str, list[str]]]:
    """Multi-column unique constraints, which Mermaid cannot express.

    Marking each member column ``UK`` would be a lie -- neither column is unique
    on its own -- and dropping them loses real invariants the domain depends on,
    such as one membership per workspace per player. So they are listed under the
    diagram instead.
    """
    keys: list[tuple[str, list[str]]] = []
    for table in tables:
        # ``table.constraints`` is a SET, so iteration order follows object
        # hashes and changes from process to process. Sorting on the name alone
        # was not enough: two constraints on the same table can share a name (or
        # both be unnamed), and the stable sort then preserved that random
        # order -- which made `--check` fail on an unchanged tree roughly half
        # the time. The column tuple is what disambiguates them.
        for constraint in sorted(
            table.constraints,
            key=lambda c: (c.name or "", tuple(column.name for column in c.columns)),
        ):
            if constraint.__class__.__name__ != "UniqueConstraint":
                continue
            columns = [c.name for c in constraint.columns]
            if len(columns) < 2:
                continue
            keys.append((entity(table), columns))
    return keys


def render_diagram(tables) -> str:
    body = ["erDiagram"]
    for table in tables:
        body.extend(render_entity(table))
    relations = render_relations(tables)
    if relations:
        body.append("")
        body.extend(relations)
    return "\n".join(body)


def render_block(tables) -> str:
    body = ["```mermaid", render_diagram(tables), "```"]
    uniques = unique_keys(tables)
    if uniques:
        body.append("")
        body.append("Composite unique keys:")
        body.append("")
        body.extend(f"- `{name}` unique on ({', '.join(f'`{c}`' for c in columns)})" for name, columns in uniques)
    return "\n".join(body)


def alembic_head() -> str:
    """The single head of the migration chain, or an explanation of why not."""
    revisions: dict[str, str | None] = {}
    for path in sorted(MIGRATIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r"^revision:\s*str\s*=\s*\"([^\"]+)\"", text, re.M)
        if not revision:
            continue
        down = re.search(r"^down_revision:[^=]*=\s*\"([^\"]+)\"", text, re.M)
        revisions[revision.group(1)] = down.group(1) if down else None
    parents = {d for d in revisions.values() if d}
    heads = sorted(r for r in revisions if r not in parents)
    if len(heads) != 1:
        raise SystemExit(f"ERROR: expected exactly one Alembic head, found {heads}")
    return heads[0]


def render_head_block() -> str:
    return (
        f"Alembic head: **`{alembic_head()}`** "
        f"({len(list(MIGRATIONS.glob('*.py')))} revisions in "
        "`backend/migrations/versions/`)."
    )


def render_artifact(blocks: dict[str, list]) -> str:
    """The schema page's data: one entry per package, same grouping as the document.

    ``sort_keys`` + fixed indent keep the output stable across runs. Newlines are
    LF here and the file is written as bytes, so a Windows checkout does not
    turn the artifact into CRLF -- ``--check`` reads it back as text, which
    normalises either way.
    """
    document = {
        "_generated_by": "backend/scripts/export_erd.py -- do not edit by hand",
        "alembic_head": alembic_head(),
        "packages": [
            {
                "key": key,
                "schemas": sorted({t.schema or "public" for t in tables}),
                "tables": [f"{t.schema or 'public'}.{t.name}" for t in tables],
                "mermaid": render_diagram(tables),
                "unique_keys": [{"table": name, "columns": columns} for name, columns in unique_keys(tables)],
            }
            for key, tables in blocks.items()
        ],
    }
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- #
# splice
# --------------------------------------------------------------------------- #


def render_document(current: str, blocks: dict[str, list]) -> str:
    expected = {"_alembic_head": render_head_block()}
    expected.update({key: render_block(tables) for key, tables in blocks.items()})

    found: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group("key")
        found.add(key)
        if key not in expected:
            raise SystemExit(
                f"ERROR: {DOCUMENT.name} has an <!-- ERD:auto {key} --> block, but no "
                "model package or module produces it. Remove the block, or rename it "
                f"to one of: {', '.join(sorted(expected))}"
            )
        return f"{match.group('open')}\n{expected[key]}\n{match.group('close')}"

    updated = BLOCK_RE.sub(replace, current)

    missing = sorted(set(expected) - found)
    if missing:
        raise SystemExit(
            f"ERROR: {len(missing)} generated block(s) have nowhere to go in "
            f"{DOCUMENT.name}: {', '.join(missing)}.\n"
            "A new model package needs a section in the document. Add a heading, a "
            "sentence saying what the domain is for, and then:\n"
            f"    <!-- ERD:auto {missing[0]} -->\n    <!-- /ERD:auto -->"
        )
    return updated


def main(argv: list[str]) -> int:
    if argv and argv != ["--check"]:
        print(f"usage: {Path(__file__).name} [--check]", file=sys.stderr)
        return 2

    blocks = table_groups()
    current = DOCUMENT.read_text(encoding="utf-8")
    updated = render_document(current, blocks)
    artifact = render_artifact(blocks)
    committed_artifact = ARTIFACT.read_text(encoding="utf-8") if ARTIFACT.exists() else ""

    if argv == ["--check"]:
        stale = [
            path.relative_to(BACKEND.parent).as_posix()
            for path, fresh in ((DOCUMENT, current == updated), (ARTIFACT, committed_artifact == artifact))
            if not fresh
        ]
        if not stale:
            print(f"{DOCUMENT.name} and {ARTIFACT.name} are up to date", file=sys.stderr)
            return 0
        print(
            f"ERROR: {', '.join(stale)} STALE — the models moved on but the ERD was "
            "not regenerated.\n"
            "Fix: cd backend && uv run python scripts/export_erd.py && "
            f"git add {' '.join(f'../{p}' for p in stale)}",
            file=sys.stderr,
        )
        return 1

    for path, fresh, content in (
        (DOCUMENT, current == updated, updated),
        (ARTIFACT, committed_artifact == artifact, artifact),
    ):
        if fresh:
            print(f"{path.name} already up to date", file=sys.stderr)
            continue
        path.write_bytes(content.encode("utf-8"))
        print(f"wrote {path} ({len(content)} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
