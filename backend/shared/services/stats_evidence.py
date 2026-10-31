"""Bounded native-state evidence in the caller's existing audit transaction.

Callers lock game/parent rows before creating absent owners, enumerate descendants
before cascades, and retain the locks until commit. This module never commits.
The operator uses the same frozen projections without taking write locks.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.impact import CONTRIBUTION_STATS
from shared.models.identity.auth_user import AuthUser
from shared.models.platform.audit import AuditLog
from shared.services.audit import AuditSource, record_audit

CODEC = "stats01-semantic/2"
OWNER_BATCH = 100
ROW_BATCH = 1000
DERIVED_CODES = (
    "first_picks",
    "first_deaths",
    "ultimate_kills",
    "support_kills",
    "impact_points",
    "impact_rank",
    "overperformance_score",
    "overperformance_badge",
    *(stat.value for stat in CONTRIBUTION_STATS.values()),
)
PARTITIONS = {
    "match": (
        "header",
        "lifecycle",
        "updated_at",
        "duration",
        "teams",
        "players",
        "segments",
        "team_scores",
        "raw_facts",
        *(f"derived/{code}" for code in DERIVED_CODES),
        "event_body",
        "event_fight",
    ),
    "job": ("identity", "hints", "lifecycle"),
    "member": ("identity",),
    "baseline": ("rows",),
    "channel": ("row",),
    "alias": ("job_ref",),
    "evaluation": ("match_ref",),
    "override": ("match_ref",),
    "rule": ("depends_on",),
    "outbox": ("changed_tables",),
    "vocabulary": ("definition",),
    "mv": ("derived_row",),
}
OPERATIONS = {
    "stats.reparse": {"match": set(PARTITIONS["match"]) - {"header"}},
    "stats.job_transition": {"job": {"lifecycle"}},
    "stats.job_hint": {"job": {"hints"}},
    "stats.raw_verification": {"job": {"identity"}},
    "stats.derived_backfill": {"match": {*(f"derived/{code}" for code in DERIVED_CODES), "event_fight"}},
    "stats.score_edit": {"match": {"team_scores"}},
    "stats.match_edit": {"match": {"duration", "updated_at"}},
    "stats.baseline_recompute": {"baseline": {"rows"}},
    "stats.member_create": {"member": {"identity"}},
    "stats.member_merge": {
        "match": {"players", "raw_facts", *(f"derived/{c}" for c in DERIVED_CODES), "event_body", "event_fight"},
        "job": {"hints"},
        "member": {"identity"},
    },
    "stats.owner_delete": {k: set(v) for k, v in PARTITIONS.items() if k not in {"mv", "vocabulary", "baseline"}},
    "stats.reference_update": {
        k: set(PARTITIONS[k]) for k in ("channel", "alias", "evaluation", "override", "rule", "outbox")
    },
    "stats.vocabulary_project": {"vocabulary": {"definition"}},
}
Scope = tuple[str, tuple[int | str, ...], str]


class EvidenceError(ValueError):
    """Missing or contradictory evidence; never a timestamp-based exemption."""


def verified_content_hash(content_hash: str | None, raw_status: str, inspected_sha256: str | None) -> str | None:
    """Validate an actual inspection result without rewriting a known source hash."""
    if raw_status not in {"available", "missing", "conflict", "unverified"}:
        raise EvidenceError("unknown raw source status")
    if inspected_sha256 is not None and (
        not isinstance(inspected_sha256, str)
        or len(inspected_sha256) != 64
        or any(c not in "0123456789abcdef" for c in inspected_sha256)
    ):
        raise EvidenceError("inspection requires a real SHA-256 digest")
    if raw_status == "missing" and inspected_sha256 is not None:
        raise EvidenceError("missing raw source cannot have inspected bytes")
    if raw_status in {"available", "conflict"}:
        if inspected_sha256 is None:
            raise EvidenceError("raw verification requires inspected bytes")
        if content_hash is not None and (
            not isinstance(content_hash, str)
            or len(content_hash) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in content_hash)
        ):
            raise EvidenceError("known source hash is not SHA-256")
        matches = content_hash is not None and content_hash.lower() == inspected_sha256
        if raw_status == "available":
            if content_hash is not None and not matches:
                raise EvidenceError("known source hash is immutable")
            return content_hash if content_hash is not None else inspected_sha256
        if content_hash is None or matches:
            raise EvidenceError("conflict requires different bytes from a known source hash")
    return content_hash


def encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EvidenceError("non-finite semantic value")
        return {"$float": value.hex()}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise EvidenceError("naive semantic timestamp")
        return {"$timestamp": value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")}
    if isinstance(value, (list, tuple)):
        return [encode_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        encoded = {key: encode_value(item) for key, item in value.items()}
        # A real JSON object must never impersonate a numeric/timestamp tag.
        return {"$object": encoded} if {"$float", "$timestamp", "$object"} & value.keys() else encoded
    raise EvidenceError(f"unsupported semantic type: {type(value).__name__}")


def semantic_bytes(value: Any) -> bytes:
    return json.dumps(
        encode_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def scope_key(scope: Scope) -> tuple[str, str, str]:
    return scope[0], json.dumps(list(scope[1]), ensure_ascii=False), scope[2]


def state_scope(state: dict) -> Scope:
    try:
        scope = (state["owner_kind"], tuple(state["owner_key"]), state["subset"])
        kind, key, subset = scope
        if kind not in PARTITIONS or subset not in PARTITIONS[kind]:
            raise EvidenceError("unknown owner partition")
        size = 3 if kind in {"vocabulary", "mv"} else 2 if kind == "baseline" else 1
        if len(key) != size or any(type(x) not in (str, int) for x in key):
            raise EvidenceError("invalid owner key")
        if kind == "vocabulary" and key[1] not in ("stat", "event"):
            raise EvidenceError("invalid vocabulary kind")
        return scope
    except (KeyError, TypeError) as exc:
        raise EvidenceError("malformed evidence state") from exc


def owner_scopes(kind: str, key: Sequence[int | str]) -> list[Scope]:
    return [(kind, tuple(key), subset) for subset in PARTITIONS[kind]]


def _hasher(scope: Scope):
    digest = hashlib.sha256()
    raw = semantic_bytes([CODEC, scope[0], list(scope[1]), scope[2]])
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)
    return digest


def semantic_digest(scope: Scope, rows: Iterable[Sequence], *, encoded: bool = False) -> tuple[int, str]:
    digest = _hasher(scope)
    count = 0
    for row in rows:
        raw = (
            json.dumps(list(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
            if encoded
            else semantic_bytes(list(row))
        )
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        count += 1
    return count, digest.hexdigest()


def empty_state(scope: Scope) -> dict:
    return {
        "owner_kind": scope[0],
        "owner_key": list(scope[1]),
        "subset": scope[2],
        "owner_exists": False,
        "row_count": 0,
        "sha256": semantic_digest(scope, ())[1],
        "identity_sha256": None,
    }


def _mapping(identity_map: Sequence[dict]) -> tuple[dict, ...]:
    result = []
    seen = set()
    global_pair = None
    for entry in identity_map:
        if set(entry) == {"source_user_id", "target_user_id"}:
            if (
                global_pair is not None
                or any(type(value) is not int or value <= 0 for value in entry.values())
                or entry["source_user_id"] == entry["target_user_id"]
            ):
                raise EvidenceError("invalid or duplicate global player mapping")
            global_pair = dict(entry)
            result.append(global_pair)
            continue
        required = {"workspace_id", "source_member_id", "target_member_id", "mode", "source_user_id", "target_user_id"}
        if set(entry) != required or entry["mode"] not in {"retain", "move"}:
            raise EvidenceError("incomplete merge identity mapping")
        if any(type(entry[k]) is not int or entry[k] <= 0 for k in required - {"mode"}):
            raise EvidenceError("invalid merge identity id")
        if entry["source_user_id"] == entry["target_user_id"]:
            raise EvidenceError("merge source equals target")
        if (entry["mode"] == "move") != (entry["source_member_id"] == entry["target_member_id"]):
            raise EvidenceError("merge mode contradicts member ids")
        source = (entry["workspace_id"], entry["source_member_id"])
        if source in seen:
            raise EvidenceError("duplicate merge mapping")
        seen.add(source)
        result.append(dict(entry))
    if len(result) > OWNER_BATCH:
        raise EvidenceError("merge mapping exceeds owner batch")
    members = [entry for entry in result if "workspace_id" in entry]
    targets = {(x["workspace_id"], x["target_member_id"]) for x in members}
    if any((x["workspace_id"], x["source_member_id"]) in targets for x in members if x["mode"] == "retain"):
        raise EvidenceError("chained merge mapping is ambiguous")
    if len({(entry["source_user_id"], entry["target_user_id"]) for entry in result}) > 1:
        raise EvidenceError("one merge cannot name contradictory global player pairs")
    return tuple(sorted(result, key=lambda x: (x.get("workspace_id", -1), x.get("source_member_id", -1))))


@dataclass(frozen=True)
class Projection:
    source: str
    where: str
    columns: tuple[tuple[str, str], ...]
    control: bool = False

    def sql(self) -> str:
        columns = ", ".join(f"{expr} AS c{i}" for i, (expr, _) in enumerate(self.columns))
        scalars = [i for i, (_, kind) in enumerate(self.columns) if kind != "json"]
        jsons = [i for i, (_, kind) in enumerate(self.columns) if kind == "json"]
        order = []
        for i in scalars + jsons:
            kind = self.columns[i][1]
            cast = "::text" if kind == "json" else ""
            collate = ' COLLATE "C"' if kind in {"text", "json"} else ""
            order.append(f"p.c{i}{cast}{collate} NULLS FIRST")
        # PostgreSQL compares -0.0 equal to 0.0; the float.hex codec does not.
        order.extend(
            f"encode(float8send(p.c{i}),'hex') COLLATE \"C\" NULLS FIRST"
            for i, (_, kind) in enumerate(self.columns)
            if kind == "float"
        )
        selected = ", ".join(f"p.c{i}" for i in range(len(self.columns)))
        return f"SELECT {selected} FROM (SELECT {columns} FROM {self.source} WHERE {self.where}) p ORDER BY {', '.join(order)}"


def _cols(names: str, *, text: Sequence[str] = (), jsons: Sequence[str] = ()) -> tuple[tuple[str, str], ...]:
    floats = {"m.duration_s", "r.value", "r.t", "r.mean", "r.std", "r.best_value", "r.avg"}
    return tuple(
        (name, "text" if name in text else "json" if name in jsons else "float" if name in floats else "scalar")
        for name in names.split()
    )


def projection(scope: Scope, identity_map: Sequence[dict] = ()) -> tuple[Projection, dict]:
    """All SQL identifiers are closed literals; only owner ids/mappings are bound."""
    kind, key, subset = scope
    state_scope({"owner_kind": kind, "owner_key": key, "subset": subset})
    params: dict[str, Any] = {f"k{i}": value for i, value in enumerate(key)}

    def mapped(column: str, *, player: bool = False, workspace: str = "m.workspace_id") -> str:
        if not identity_map:
            return column
        cases = []
        for i, entry in enumerate(identity_map):
            if "workspace_id" not in entry and not player:
                continue
            for name, value in entry.items():
                params[f"map{i}_{name}"] = value
            source = "source_user_id" if player else "source_member_id"
            target = "target_user_id" if player else "target_member_id"
            authority = f"{workspace}=:map{i}_workspace_id AND " if "workspace_id" in entry else ""
            cases.append(f"WHEN {authority}{column}=:map{i}_{source} THEN :map{i}_{target}")
        return "CASE " + " ".join(cases) + f" ELSE {column} END" if cases else column

    if kind == "match":
        where = "m.id=:k0"
        headers = {
            "header": _cols(
                "m.id m.created_at m.workspace_id m.discipline m.encounter_game_id m.map_entity_id m.map_kind "
                "m.encounter_id m.source_map_index",
                text=("m.discipline", "m.map_kind"),
            ),
            "lifecycle": _cols("m.revision m.ingest_job_id"),
            "updated_at": _cols("m.updated_at"),
            "duration": _cols("m.duration_s m.played_at"),
        }
        if subset in headers:
            return Projection("stats.match m", where, headers[subset], True), params
        if subset == "teams":
            return Projection(
                "stats.match_team r JOIN stats.match m ON m.id=r.match_id",
                where,
                _cols("r.match_id r.encounter_id r.encounter_team_id r.source_position"),
            ), params
        if subset == "players":
            cols = (
                _cols("r.match_id r.encounter_team_id")
                + ((mapped("r.workspace_member_id"), "scalar"),)
                + _cols("r.handle_snapshot r.observed_role_id", text=("r.handle_snapshot",))
            )
            return Projection("stats.match_player r JOIN stats.match m ON m.id=r.match_id", where, cols), params
        if subset == "segments":
            return Projection(
                "stats.segment r JOIN stats.match m ON m.id=r.match_id",
                where,
                _cols("r.match_id r.segment r.kind r.attrs", text=("r.kind",), jsons=("r.attrs",)),
            ), params
        if subset in {"team_scores", "raw_facts"} or subset.startswith("derived/"):
            source = "stats.fact r JOIN stats.match m ON m.id=r.match_id LEFT JOIN stats.stat_def d ON d.id=r.stat_id"
            scores = "(r.segment=0 AND r.workspace_member_id IS NULL AND r.entity_id IS NULL AND d.code='score')"
            codes = ",".join(f"'{code}'" for code in DERIVED_CODES)
            if subset == "team_scores":
                where += f" AND {scores}"
            elif subset == "raw_facts":
                where += f" AND NOT COALESCE({scores},false) AND (d.code IS NULL OR d.code NOT IN ({codes}))"
            else:
                params["code"] = subset.removeprefix("derived/")
                where += " AND d.code=:code"
            cols = (
                _cols("r.match_id r.segment r.encounter_team_id")
                + ((mapped("r.workspace_member_id"), "scalar"),)
                + _cols(
                    "r.entity_id r.entity_kind r.stat_id d.discipline d.code r.value",
                    text=("r.entity_kind", "d.discipline", "d.code"),
                )
            )
            return Projection(source, where, cols, subset == "team_scores"), params
        cols = _cols("r.match_id r.segment r.t r.type_id d.discipline d.code", text=("d.discipline", "d.code"))
        cols += (
            (mapped("r.actor_member_id"), "scalar"),
            ("r.actor_team_id", "scalar"),
            (mapped("r.target_member_id"), "scalar"),
        )
        cols += _cols("r.target_team_id r.entity_id r.related_entity_id r.entity_kind", text=("r.entity_kind",))
        cols += (
            ("r.data IS NULL", "scalar"),
            ("CASE WHEN jsonb_typeof(r.data)='object' THEN r.data - 'fight' ELSE r.data END", "json"),
        )
        if subset == "event_fight":
            cols += (
                ("COALESCE(jsonb_typeof(r.data)='object' AND r.data ? 'fight',false)", "scalar"),
                ("CASE WHEN jsonb_typeof(r.data)='object' THEN r.data->'fight' END", "json"),
            )
        return Projection(
            "stats.event r JOIN stats.match m ON m.id=r.match_id LEFT JOIN stats.event_type d ON d.id=r.type_id",
            where,
            cols,
        ), params
    if kind == "job":
        cols = {
            "identity": _cols(
                "j.id j.created_at j.workspace_id j.discipline j.source_kind j.external_id j.content_hash "
                "j.filename j.raw_ref j.api_key_id j.raw_status",
                text=(
                    "j.discipline",
                    "j.source_kind",
                    "j.external_id",
                    "j.content_hash",
                    "j.filename",
                    "j.raw_ref",
                    "j.raw_status",
                ),
            ),
            "hints": ((mapped("j.uploader_user_id", player=True, workspace="j.workspace_id"), "scalar"),)
            + _cols("j.hint_tournament_id j.hint_encounter_id j.hint_encounter_game_id"),
            "lifecycle": _cols(
                "j.status j.attempts j.error_message j.started_at j.finished_at j.updated_at j.document_ref",
                text=("j.status", "j.error_message", "j.document_ref"),
            ),
        }
        return Projection("stats.ingest_job j", "j.id=:k0", cols[subset], subset != "lifecycle"), params
    if kind == "member":
        return Projection("workspace_member r", "r.id=:k0", _cols("r.id r.workspace_id r.player_id"), True), params
    if kind == "baseline":
        return Projection(
            "stats.stat_baseline r JOIN stats.stat_def d ON d.id=r.stat_id JOIN catalog.role role ON role.id=r.role_id JOIN catalog.role_dimension dim ON dim.id=role.dimension_id",
            "d.discipline=:k0 AND r.formula_version=:k1",
            _cols(
                "r.id r.formula_version r.role_id dim.discipline dim.code r.rank_bucket r.stat_id r.entity_id d.discipline r.mean r.std r.meta r.computed_at",
                text=("r.formula_version", "dim.discipline", "dim.code", "d.discipline"),
                jsons=("r.meta",),
            )
            + (("r.meta IS NULL", "scalar"),),
        ), params
    if kind == "channel":
        return Projection(
            "stats.discord_channel r",
            "r.id=:k0",
            _cols(
                "r.id r.created_at r.updated_at r.tournament_id r.channel_id r.channel_name r.is_active",
                text=("r.channel_name",),
            ),
            True,
        ), params
    if kind == "vocabulary":
        table = "stat_def" if key[1] == "stat" else "event_type"
        names = "r.id r.discipline r.code r.name"
        if key[1] == "stat":
            names += " r.value_format r.aggregation r.stat_group r.active r.sort_order"
        else:
            names += " r.active"
        return Projection(
            f"stats.{table} r",
            "r.discipline=:k0 AND r.code=:k2",
            _cols(names, text=("r.discipline", "r.code", "r.name", "r.value_format", "r.aggregation", "r.stat_group")),
            True,
        ), params
    if kind == "mv":
        return Projection(
            "stats.mv_entity_global_stats r",
            "r.discipline=:k0 AND r.stat_id=:k1 AND r.entity_id=:k2",
            _cols(
                "r.discipline r.stat_id r.entity_id r.best_value r.avg r.metadata",
                text=("r.discipline",),
                jsons=("r.metadata",),
            ),
            True,
        ), params
    refs = {
        "alias": ("catalog.alias_miss", _cols("r.id r.last_ingest_job_id")),
        "evaluation": ("achievements.evaluation_result", _cols("r.id r.match_id")),
        "override": ("achievements.override", _cols("r.id r.match_id")),
        "rule": ("achievements.rule", _cols("r.id r.depends_on", jsons=("r.depends_on",))),
        "outbox": (
            "event_outbox",
            (
                ("r.id", "scalar"),
                ("r.payload_json::jsonb ? 'changed_tables'", "scalar"),
                ("r.payload_json::jsonb->'changed_tables'", "json"),
            ),
        ),
    }
    table, cols = refs[kind]
    # Some of these columns are JSON, not JSONB.
    cols = tuple((f"{expr}::jsonb" if typ == "json" and "->" not in expr else expr, typ) for expr, typ in cols)
    return Projection(f"{table} r", "r.id=:k0", cols, True), params


OWNER_QUERIES = {
    "match": "SELECT jsonb_build_array(id) AS key FROM stats.match",
    "job": "SELECT jsonb_build_array(id) AS key FROM stats.ingest_job",
    "member": "SELECT jsonb_build_array(id) AS key FROM workspace_member",
    "baseline": "SELECT DISTINCT jsonb_build_array(d.discipline,r.formula_version) AS key FROM stats.stat_baseline r JOIN stats.stat_def d ON d.id=r.stat_id",
    "channel": "SELECT jsonb_build_array(id) AS key FROM stats.discord_channel",
    "alias": "SELECT jsonb_build_array(id) AS key FROM catalog.alias_miss",
    "evaluation": "SELECT jsonb_build_array(id) AS key FROM achievements.evaluation_result",
    "override": "SELECT jsonb_build_array(id) AS key FROM achievements.override",
    "rule": "SELECT jsonb_build_array(id) AS key FROM achievements.rule",
    "outbox": "SELECT jsonb_build_array(id) AS key FROM event_outbox WHERE payload_json::jsonb ? 'changed_tables'",
    "vocabulary": "SELECT jsonb_build_array(discipline,'stat',code) AS key FROM stats.stat_def UNION ALL SELECT jsonb_build_array(discipline,'event',code) FROM stats.event_type",
    "mv": "SELECT jsonb_build_array(discipline,stat_id,entity_id) AS key FROM stats.mv_entity_global_stats",
}
OWNER_TABLES = {
    "match": "stats.match",
    "job": "stats.ingest_job",
    "member": "workspace_member",
    "channel": "stats.discord_channel",
    "alias": "catalog.alias_miss",
    "evaluation": "achievements.evaluation_result",
    "override": "achievements.override",
    "rule": "achievements.rule",
    "outbox": "event_outbox",
}


def owner_exists(conn, kind: str, key: tuple) -> bool:
    if kind in OWNER_TABLES:
        return bool(
            conn.scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {OWNER_TABLES[kind]} WHERE id=:id)"), {"id": key[0]})
        )
    query = OWNER_QUERIES[kind]
    return bool(
        conn.scalar(
            sa.text(f"SELECT EXISTS(SELECT 1 FROM ({query}) owners WHERE key=CAST(:key AS jsonb))"),
            {"key": json.dumps(key)},
        )
    )


def _lock_owners(session, owners: Sequence[tuple[str, tuple]]) -> None:
    # Same ordering for every writer, including the two vocabulary repositories.
    for kind, key in sorted(owners, key=lambda item: scope_key((item[0], item[1], ""))):
        if kind in {"baseline", "vocabulary"}:
            lock = f"stats:vocabulary:{key[0]}" if kind == "vocabulary" else f"stats:baseline:{key[0]}:{key[1]}"
            session.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock})
        if kind == "vocabulary":
            table = "stat_def" if key[1] == "stat" else "event_type"
            session.execute(
                sa.text(f"SELECT id FROM stats.{table} WHERE discipline=:discipline AND code=:code FOR UPDATE"),
                {"discipline": key[0], "code": key[2]},
            )
        elif kind in OWNER_TABLES:
            session.execute(sa.text(f"SELECT id FROM {OWNER_TABLES[kind]} WHERE id=:id FOR UPDATE"), {"id": key[0]})
        elif kind == "mv":
            raise EvidenceError("materialized rows are not mutable evidence owners")


class CapturedEvidence(list):
    """A list of public states plus bounded, named scalar evidence for staging."""

    def __init__(self, transaction=None):
        super().__init__()
        self.transaction = transaction
        self.values: list[dict] = []
        self.sealed: bytes | None = None


def capture_native(conn, *, scopes: Sequence[Scope], identity_map: Sequence[dict] = ()) -> CapturedEvidence:
    mapping = _mapping(identity_map)
    scopes = sorted(scopes, key=scope_key)
    if len(set(scopes)) != len(scopes):
        raise EvidenceError("duplicate scope")
    owners = {(kind, key) for kind, key, _ in scopes}
    if len(owners) > OWNER_BATCH:
        raise EvidenceError("capture exceeds 100 owners")
    existence = {owner: owner_exists(conn, *owner) for owner in owners}
    result = CapturedEvidence()
    for scope in scopes:
        query, params = projection(scope)
        controls = []

        def rows(query=query, params=params, controls=controls):
            with conn.execute(sa.text(query.sql()).execution_options(yield_per=ROW_BATCH), params) as cursor:
                for partition in cursor.partitions(ROW_BATCH):
                    for row in partition:
                        if query.control:
                            if len(controls) >= ROW_BATCH:
                                raise EvidenceError("scalar evidence exceeds 1000 rows; split the owner operation")
                            controls.append(encode_value(list(row)))
                        yield row

        count, digest = semantic_digest(scope, rows())
        invariant = None
        if mapping and (
            (
                scope[0] == "match"
                and any("workspace_id" in entry for entry in mapping)
                and scope[2] in OPERATIONS["stats.member_merge"]["match"]
            )
            or (scope[0] == "job" and scope[2] == "hints")
        ):
            rewritten, rewrite_params = projection(scope, mapping)
            with conn.execute(
                sa.text(rewritten.sql()).execution_options(yield_per=ROW_BATCH), rewrite_params
            ) as cursor:
                rewritten_count, invariant = semantic_digest(scope, cursor)
            if rewritten_count != count:
                raise EvidenceError("identity projection changed multiplicity")
        result.append(
            {
                "owner_kind": scope[0],
                "owner_key": list(scope[1]),
                "subset": scope[2],
                "owner_exists": existence[scope[:2]],
                "row_count": count,
                "sha256": digest,
                "identity_sha256": invariant,
            }
        )
        if query.control:
            result.values.append(
                {"owner_kind": scope[0], "owner_key": list(scope[1]), "subset": scope[2], "rows": controls}
            )
    result.sealed = semantic_bytes([result, result.values])
    return result


async def capture_stats_evidence(
    session: AsyncSession, *, scopes: Sequence[Scope], identity_map: Sequence[dict] = ()
) -> list[dict]:
    def capture(sync_session):
        owners = {(kind, tuple(key)) for kind, key, _ in scopes}
        if len(owners) > OWNER_BATCH:
            raise EvidenceError("capture exceeds 100 owners")
        with sync_session.no_autoflush:
            _lock_owners(sync_session, owners)
            result = capture_native(sync_session.connection(), scopes=scopes, identity_map=identity_map)
            result.transaction = sync_session.get_transaction()
            return result

    return await session.run_sync(capture)


def state_equal(left: dict, right: dict) -> bool:
    return all(left[field] == right[field] for field in ("owner_exists", "row_count", "sha256"))


def _states(states: Sequence[dict]) -> dict[Scope, dict]:
    result = {}
    owners = defaultdict(set)
    exists = {}
    for state in states:
        scope = state_scope(state)
        if scope in result:
            raise EvidenceError("duplicate evidence state")
        if (
            type(state.get("owner_exists")) is not bool
            or type(state.get("row_count")) is not int
            or state["row_count"] < 0
        ):
            raise EvidenceError("invalid evidence count/existence")
        for field in ("sha256", "identity_sha256"):
            value = state.get(field)
            if value is None and field == "identity_sha256":
                continue
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise EvidenceError("invalid evidence digest")
        if not state["owner_exists"] and not state_equal(state, empty_state(scope)):
            raise EvidenceError("absent owner has rows")
        owner = scope[:2]
        if owner in exists and exists[owner] != state["owner_exists"]:
            raise EvidenceError("inconsistent owner existence")
        exists[owner] = state["owner_exists"]
        owners[owner].add(scope[2])
        result[scope] = state
    if len(owners) > OWNER_BATCH:
        raise EvidenceError("evidence exceeds 100 owners")
    for (kind, _), subsets in owners.items():
        if subsets != set(PARTITIONS[kind]):
            raise EvidenceError("missing owner subset complement")
    return result


def _values(values: Sequence[dict], states: dict[Scope, dict]) -> dict[Scope, list]:
    result = {}
    for value in values:
        scope = state_scope(value)
        rows = value.get("rows")
        if scope in result or scope not in states or not isinstance(rows, list) or len(rows) > ROW_BATCH:
            raise EvidenceError("invalid scalar evidence")
        count, digest = semantic_digest(scope, rows, encoded=True)
        if (count, digest) != (states[scope]["row_count"], states[scope]["sha256"]):
            raise EvidenceError("scalar evidence does not match state digest")
        result[scope] = rows
    return result


def validate_transition(
    operation: str,
    before: Sequence[dict],
    after: Sequence[dict],
    *,
    identity_map: Sequence[dict] = (),
    before_values: Sequence[dict] = (),
    after_values: Sequence[dict] = (),
    raw_verification: Sequence[dict] = (),
) -> bool:
    if operation not in OPERATIONS:
        raise EvidenceError("unsupported stats operation")
    old, new = _states(before), _states(after)
    if not old or old.keys() != new.keys():
        raise EvidenceError("unequal or empty evidence scope sets")
    mapping = _mapping(identity_map)
    if bool(mapping) != (operation == "stats.member_merge"):
        raise EvidenceError("identity mapping is required only for merge")
    member_mapping = [entry for entry in mapping if "workspace_id" in entry]
    if mapping and not member_mapping and any(scope[0] != "job" for scope in old):
        raise EvidenceError("player-only merge mapping authorizes job uploader hints only")
    old_values, new_values = _values(before_values, old), _values(after_values, new)
    inspections = {}
    for inspection in raw_verification:
        if (
            not isinstance(inspection, dict)
            or set(inspection) != {"job_id", "raw_ref", "inspected_sha256"}
            or type(inspection["job_id"]) is not int
            or inspection["job_id"] <= 0
            or inspection["job_id"] in inspections
            or not isinstance(inspection["raw_ref"], str)
            or not inspection["raw_ref"]
        ):
            raise EvidenceError("invalid raw inspection evidence")
        inspections[inspection["job_id"]] = inspection
    if bool(inspections) != (operation == "stats.raw_verification"):
        raise EvidenceError("raw inspection evidence is required only for raw verification")
    if inspections and set(inspections) != {key[0] for kind, key, _ in old if kind == "job"}:
        raise EvidenceError("raw inspection evidence does not cover the job owners")

    def scalar(scope, side):
        values = old_values if side == "before" else new_values
        if scope not in values:
            raise EvidenceError("missing named scalar evidence")
        return values[scope]

    changed = False
    for scope, prior in old.items():
        current = new[scope]
        kind, key, subset = scope
        if kind not in OPERATIONS[operation]:
            raise EvidenceError("operation includes foreign owner kind")
        difference = not state_equal(prior, current)
        changed |= difference
        if operation != "stats.member_merge" and (
            prior.get("identity_sha256") is not None or current.get("identity_sha256") is not None
        ):
            raise EvidenceError("unexpected identity invariant")
        if operation == "stats.raw_verification" and subset == "identity":
            a, b = scalar(scope, "before"), scalar(scope, "after")
            if (
                len(a) != 1
                or len(b) != 1
                or len(a[0]) != 11
                or len(b[0]) != 11
                or any(x != y for i, (x, y) in enumerate(zip(a[0], b[0], strict=True)) if i not in {6, 10})
            ):
                raise EvidenceError("raw verification changed source identity")
            inspection = inspections[key[0]]
            if inspection["raw_ref"] != a[0][8]:
                raise EvidenceError("raw inspection names another source")
            expected_hash = verified_content_hash(a[0][6], b[0][10], inspection["inspected_sha256"])
            if b[0][6] != expected_hash:
                raise EvidenceError("raw verification changed a known hash or invented bytes")
        if not difference:
            continue
        created = not prior["owner_exists"] and current["owner_exists"]
        deleted = prior["owner_exists"] and not current["owner_exists"]
        creation_allowed = operation in {
            "stats.reparse",
            "stats.job_transition",
            "stats.baseline_recompute",
            "stats.member_create",
            "stats.reference_update",
            "stats.vocabulary_project",
        }
        if created and not creation_allowed:
            raise EvidenceError("operation cannot create this owner")
        if deleted and operation not in {
            "stats.owner_delete",
            "stats.reference_update",
            "stats.baseline_recompute",
            "stats.member_merge",
        }:
            raise EvidenceError("operation cannot delete this owner")
        if subset not in OPERATIONS[operation][kind] and not created:
            raise EvidenceError(f"operation changed complement: {kind}/{subset}")
        if operation == "stats.member_create" and not created:
            raise EvidenceError("member creation cannot change an existing identity")
        if operation == "stats.vocabulary_project" and not created:
            if scalar(scope, "before")[0][:3] != scalar(scope, "after")[0][:3]:
                raise EvidenceError("vocabulary identity changed")
        if operation in {"stats.match_edit", "stats.score_edit"}:
            scalar(scope, "before")
            scalar(scope, "after")
        if operation == "stats.owner_delete" and not deleted:
            allowed_nulls = {
                ("match", "header"): {4},
                ("match", "lifecycle"): {1},
                ("job", "identity"): {9},
                ("job", "hints"): {0, 1, 2, 3},
                ("alias", "job_ref"): {1},
            }
            nullable = allowed_nulls.get((kind, subset))
            if nullable is None:
                raise EvidenceError("delete changed surviving non-reference data")
            a, b = scalar(scope, "before"), scalar(scope, "after")
            if (
                len(a) != 1
                or len(b) != 1
                or len(a[0]) != len(b[0])
                or any(
                    x != y and (i not in nullable or y is not None)
                    for i, (x, y) in enumerate(zip(a[0], b[0], strict=True))
                )
            ):
                raise EvidenceError("owner delete is not SET NULL-only")
        if operation == "stats.member_merge" and kind != "member":
            if (
                prior["row_count"] != current["row_count"]
                or not prior.get("identity_sha256")
                or prior["identity_sha256"] != current.get("identity_sha256")
            ):
                raise EvidenceError("merge changed non-identity semantics or multiplicity")
    if operation == "stats.baseline_recompute" and len({scope[:2] for scope in old}) != 1:
        raise EvidenceError("baseline recompute must name one discipline/version")
    if operation == "stats.member_merge":
        member_ids = {key[0] for kind, key, _ in old if kind == "member"}
        required_members = {entry[k] for entry in member_mapping for k in ("source_member_id", "target_member_id")}
        if not member_ids <= required_members:
            raise EvidenceError("merge includes an unmapped member identity")
        for entry in member_mapping:
            source = ("member", (entry["source_member_id"],), "identity")
            target = ("member", (entry["target_member_id"],), "identity")
            expected_before = [[entry["source_member_id"], entry["workspace_id"], entry["source_user_id"]]]
            expected_after = [[entry["target_member_id"], entry["workspace_id"], entry["target_user_id"]]]
            if source in old:
                if scalar(source, "before") != expected_before:
                    raise EvidenceError("merge contradicts original source member identity")
                if entry["mode"] == "retain" and new[source]["owner_exists"]:
                    raise EvidenceError("retain-member merge did not remove source membership")
            if target in old:
                if scalar(target, "after") != expected_after:
                    raise EvidenceError("merge contradicts target member identity")
                if entry["mode"] == "retain" and scalar(target, "before") != expected_after:
                    raise EvidenceError("retain-member merge changed target membership")
        for scope, prior in old.items():
            if scope[0] != "member" and scope[2] in OPERATIONS[operation][scope[0]]:
                if not prior.get("identity_sha256") or prior["identity_sha256"] != new[scope].get("identity_sha256"):
                    raise EvidenceError("missing mapped identity invariant")
    # Observation-only chunks of a same-member-id merge have equal raw hashes;
    # original UserMergeAudit binds them to the chunk containing the identity move.
    return changed or bool(member_mapping and any(s["row_count"] and s.get("identity_sha256") for s in before))


async def stage_stats_evidence(
    session: AsyncSession,
    *,
    operation: str,
    before: Sequence[dict],
    after: Sequence[dict],
    workspace_id: int | None,
    entity_type: str,
    entity_id: int | None,
    source: AuditSource = "system",
    actor: AuthUser | None = None,
    audit: AuditLog | None = None,
    identity_map: Sequence[dict] = (),
    raw_verification: Sequence[dict] = (),
) -> AuditLog:
    if not isinstance(before, CapturedEvidence) or not isinstance(after, CapturedEvidence):
        raise EvidenceError("stage requires captures from this transaction")
    for captured in (before, after):
        if captured.transaction is not session.sync_session.get_transaction():
            raise EvidenceError("stage requires captures from this transaction")
        if captured.sealed != semantic_bytes([captured, captured.values]):
            raise EvidenceError("capture was modified after reading native rows")
    changed = validate_transition(
        operation,
        before,
        after,
        identity_map=identity_map,
        before_values=before.values,
        after_values=after.values,
        raw_verification=raw_verification,
    )
    if not changed:
        raise EvidenceError("true no-op must not stage an audit row")
    if audit is not None:
        inspected = sa.inspect(audit)
        if not inspected.pending or audit.id is not None or inspected.session is not session.sync_session:
            raise EvidenceError("cannot retrofit evidence onto allocated or committed audit")
        if (audit.before_json or {}).get("stats_evidence") or (audit.after_json or {}).get("stats_evidence"):
            raise EvidenceError("audit already contains stats evidence")
    else:
        audit = await record_audit(
            session,
            action=operation,
            source=source,
            actor=actor,
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    mapping = list(_mapping(identity_map))
    audit.before_json = {
        **(audit.before_json or {}),
        "stats_evidence": {
            "version": 2,
            "operation": operation,
            "states": list(before),
            "identity_map": mapping,
            "raw_verification": list(raw_verification),
        },
        "stats_values": before.values,
    }
    audit.after_json = {
        **(audit.after_json or {}),
        "stats_evidence": {
            "version": 2,
            "operation": operation,
            "states": list(after),
            "identity_map": mapping,
            "raw_verification": list(raw_verification),
        },
        "stats_values": after.values,
    }
    await session.flush()
    return audit
