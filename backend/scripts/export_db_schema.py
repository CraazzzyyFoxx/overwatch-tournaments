"""Dump SQLAlchemy metadata to docs/schema.dbml and docs/schema.sql."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.elements import TextClause

import shared.models  # noqa: F401 — register every table
from shared.core.db import Base

ROOT = Path(__file__).resolve().parents[1] / "docs"
DIALECT = postgresql.dialect()


def qname(table) -> str:
    return f"{table.schema}.{table.name}" if table.schema else table.name


def ident(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and name.lower() not in {
        "table",
        "ref",
        "enum",
        "indexes",
        "note",
        "user",
        "order",
        "group",
        "index",
    }:
        return name
    return f'"{name}"'


def compile_default(col) -> str | None:
    if col.server_default is None:
        return None
    arg = col.server_default.arg
    raw = str(arg.text) if isinstance(arg, TextClause) else str(arg)
    raw = raw.strip()
    if raw.upper() in {"TRUE", "FALSE", "NULL"}:
        return raw.lower()
    if re.fullmatch(r"-?\d+(\.\d+)?", raw):
        return raw
    if raw.upper().startswith("NEXTVAL"):
        return None
    return f"`{raw}`"


def sa_type(col) -> str:
    enum = getattr(col.type, "enums", None)
    name = getattr(col.type, "name", None)
    if enum and name:
        return ident(name)
    compiled = col.type.compile(dialect=DIALECT).replace('"', "")
    return {
        "TIMESTAMP WITH TIME ZONE": "timestamptz",
        "TIMESTAMP WITHOUT TIME ZONE": "timestamp",
        "DOUBLE PRECISION": "float8",
        "CHARACTER VARYING": "varchar",
        "BIGINT": "bigint",
        "INTEGER": "int",
        "SMALLINT": "smallint",
        "BOOLEAN": "boolean",
        "TEXT": "text",
        "JSON": "json",
        "JSONB": "jsonb",
        "UUID": "uuid",
        "BYTEA": "bytea",
        "FLOAT": "float",
    }.get(compiled, compiled)


def column_line(col) -> str:
    bits = [f"  {ident(col.name)} {sa_type(col)}"]
    attrs: list[str] = []
    if col.primary_key:
        attrs.append("pk")
        if not col.foreign_keys and (col.autoincrement is True or col.autoincrement == "auto"):
            attrs.append("increment")
    if not col.nullable and not col.primary_key:
        attrs.append("not null")
    if col.unique and not col.primary_key:
        attrs.append("unique")
    default = compile_default(col)
    if default:
        attrs.append(f"default: {default}")
    # FKs are emitted as standalone Ref: lines — delete: is invalid in column settings.
    if attrs:
        bits.append(" [" + ", ".join(attrs) + "]")
    return "".join(bits)


def table_indexes(table) -> list[str]:
    lines: list[str] = []
    seen: set[tuple] = set()
    for const in table.constraints:
        if isinstance(const, UniqueConstraint) and const.columns:
            cols = tuple(c.name for c in const.columns)
            if len(cols) == 1 and table.c[cols[0]].unique:
                continue
            seen.add(cols)
            col_s = ", ".join(ident(c) for c in cols)
            name = f', name: "{const.name}"' if const.name else ""
            lines.append(f"    ({col_s}) [unique{name}]")
    # ``Table.indexes`` is a set: iteration order changes with the interpreter's
    # hash seed, so an unsorted walk rewrites these committed artifacts with
    # pure reordering noise on every run. Sort by name (unnamed last).
    for idx in sorted(table.indexes, key=lambda i: i.name or ""):
        cols = tuple(c.name for c in idx.columns)
        if cols in seen:
            continue
        col_s = ", ".join(ident(c.name) for c in idx.columns)
        flags = []
        if idx.unique:
            flags.append("unique")
        if idx.name:
            flags.append(f'name: "{idx.name}"')
        suffix = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"    ({col_s}){suffix}")
    return lines


def emit_refs(tables) -> list[str]:
    lines: list[str] = []
    for table in tables:
        for col in table.columns:
            for fk in col.foreign_keys:
                src = f"{qname(table)}.{ident(col.name)}"
                dst = f"{qname(fk.column.table)}.{ident(fk.column.name)}"
                if fk.ondelete:
                    lines.append(f"Ref: {src} > {dst} [delete: {fk.ondelete.lower()}]")
                else:
                    lines.append(f"Ref: {src} > {dst}")
    return lines


def emit_dbml(tables) -> str:
    by_schema: dict[str, list] = defaultdict(list)
    for table in tables:
        by_schema[table.schema or "public"].append(table)

    enums: dict[str, list[str]] = {}
    for table in tables:
        for col in table.columns:
            enum = getattr(col.type, "enums", None)
            name = getattr(col.type, "name", None)
            if enum and name and name not in enums:
                enums[name] = list(enum)

    out: list[str] = [
        "// Anak Tournaments — PostgreSQL schema dumped from SQLAlchemy metadata.",
        "// Open in VS Code (DBML extension) or paste into https://dbdiagram.io",
        f"// Tables: {len(tables)}",
        "",
        "Project anak_tournaments {",
        '  database_type: "PostgreSQL"',
        "  Note: 'Source of truth is backend/shared/models. Regenerate: python scripts/export_db_schema.py'",
        "}",
        "",
    ]

    for name, values in sorted(enums.items()):
        out.append(f"Enum {ident(name)} {{")
        for value in values:
            out.append(f"  {ident(value)}")
        out.append("}")
        out.append("")

    for schema in sorted(by_schema):
        out.append(f"// ----- {schema} -----")
        out.append("")
        for table in sorted(by_schema[schema], key=lambda t: t.name):
            out.append(f"Table {qname(table)} {{")
            for col in table.columns:
                out.append(column_line(col))
            idx = table_indexes(table)
            if idx:
                out.append("  indexes {")
                out.extend(idx)
                out.append("  }")
            out.append("}")
            out.append("")
        out.append(f"TableGroup {ident(schema)} {{")
        for table in sorted(by_schema[schema], key=lambda t: t.name):
            out.append(f"  {qname(table)}")
        out.append("}")
        out.append("")
    refs = emit_refs(tables)
    if refs:
        out.append("// ----- refs -----")
        out.append("")
        out.extend(refs)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def emit_sql(tables) -> str:
    out = [
        "-- Anak Tournaments — PostgreSQL DDL compiled from SQLAlchemy metadata.",
        "-- Open in any SQL editor (DataGrip, DBeaver, VS Code).",
        f"-- Tables: {len(tables)}",
        "-- Source of truth is backend/shared/models. Regenerate: python scripts/export_db_schema.py",
        "",
    ]
    schemas = sorted({t.schema for t in tables if t.schema})
    for schema in schemas:
        out.append(f"CREATE SCHEMA IF NOT EXISTS {schema};")
    if schemas:
        out.append("")

    emitted_enums: set[str] = set()
    for table in tables:
        for col in table.columns:
            enum = getattr(col.type, "enums", None)
            name = getattr(col.type, "name", None)
            schema = getattr(col.type, "schema", None)
            if not (enum and name) or name in emitted_enums:
                continue
            emitted_enums.add(name)
            qn = f"{schema}.{name}" if schema else name
            vals = ", ".join("'" + v.replace("'", "''") + "'" for v in enum)
            out.append(f"CREATE TYPE {qn} AS ENUM ({vals});")
    if emitted_enums:
        out.append("")

    for table in tables:
        ddl = str(CreateTable(table).compile(dialect=DIALECT)).strip()
        out.append(ddl + ";")
        out.append("")
        for idx in sorted(table.indexes, key=lambda i: i.name or ""):  # set: sort, see table_indexes
            # UniqueConstraints already land inside CREATE TABLE.
            if idx.unique and frozenset(c.name for c in idx.columns) in {
                frozenset(c.name for c in const.columns)
                for const in table.constraints
                if isinstance(const, UniqueConstraint)
            }:
                continue
            out.append(str(CreateIndex(idx).compile(dialect=DIALECT)).strip() + ";")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    tables = sorted(Base.metadata.tables.values(), key=lambda t: (t.schema or "public", t.name))
    ROOT.mkdir(parents=True, exist_ok=True)
    dbml = ROOT / "schema.dbml"
    sql = ROOT / "schema.sql"
    dbml.write_text(emit_dbml(tables), encoding="utf-8")
    sql.write_text(emit_sql(tables), encoding="utf-8")
    print(f"{len(tables)} tables -> {dbml} {sql}")


if __name__ == "__main__":
    main()
