"""Statistics transfer preparation and reviewed native raw-source verification.

Legacy preparation targets frozen P3 SQL. Native verification uses repository
writes and stats.raw_verification evidence. Stop writers before either apply.
Reports are proposals, not approval: add a nonempty review and independently
review the exact manifest SHA-256 before --apply-native-raw.

Capture the initial stats01 receipt BEFORE native classification. The native
proposal includes target database/revision and exact job/observation state SHA.
Review a copy, set its review string, then apply that copy with its reviewed SHA.

Optional --inventory JSON is {format: "stats01-native-raw-inventory/1",
target: <proposal target>, objects: <proposal objects>}; it must cover every key.
Optional --source-evidence JSON is {format: "stats01-native-raw-source/1",
target: <proposal target>, evidence: <nonempty explanation>, ...}. It supplements,
never replaces, byte inspection. Both inputs require their independent SHA flags;
apply requires the same input digests as the reviewed proposal. Old inventories
without this exact target binding are intentionally refused.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

# Direct `python scripts/stats01_prepare.py` has scripts/, not backend/, on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.core.config import BaseServiceSettings

BATCH = 100


class Settings(BaseServiceSettings):
    # Frozen parser AppConfig default; same MAX_MATCH_LOG_BYTES environment setting.
    max_match_log_bytes: int = 25 * 1024 * 1024


class PreparationBlocked(Exception):
    def __init__(self, reason: str, row_id: int):
        self.reason, self.row_id = reason, row_id
        super().__init__(f"{reason}: row {row_id}; review source evidence and regenerate the manifest before retrying")


def canonical(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(v) for v in value]
    return value


def fingerprint(snapshot):
    return hashlib.sha256(
        json.dumps(
            canonical(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def rows(conn, sql, **params):
    return [canonical(dict(row)) for row in conn.execute(sa.text(sql), params).mappings()]


def one(conn, sql, row_id, **params):
    result = rows(conn, sql, **params)
    if len(result) != 1:
        raise PreparationBlocked("missing_or_ambiguous_owner", row_id)
    return result[0]


def raw_key(tournament_id, filename, row_id):
    if not isinstance(filename, str):
        raise PreparationBlocked("missing_raw_reference", row_id)
    base = f"logs/{tournament_id}/"
    bare = filename.removeprefix(base).removeprefix("logs/")
    if ".." in bare or bare.startswith("/") or not bare:
        raise PreparationBlocked("unsafe_raw_key", row_id)
    key = base + bare
    if len(key) > 512 or len(filename) > 500:
        raise PreparationBlocked("overlong_raw_key", row_id)
    return key


async def object_hash(s3, key, row_id, max_bytes):
    if s3 is None:
        raise PreparationBlocked("storage_access_unavailable", row_id)
    try:
        raw = await s3.get_object(key)
    except Exception:
        raise PreparationBlocked("storage_access_unavailable", row_id) from None
    if raw is None:
        raise PreparationBlocked("missing_raw_object", row_id)
    if not raw:
        raise PreparationBlocked("empty_raw_object", row_id)
    if len(raw) > max_bytes:
        raise PreparationBlocked("oversize_raw_object", row_id)
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError, AttributeError:
        raise PreparationBlocked("unprocessable_raw_object", row_id) from None
    if not decoded.strip() or "\x00" in decoded:
        raise PreparationBlocked("unprocessable_raw_object", row_id)
    return hashlib.sha256(raw).hexdigest()


RECORD = """SELECT r.id,r.created_at,r.updated_at,r.tournament_id,r.filename,
 r.content_hash,r.status::text,r.source::text,r.uploader_id,r.attached_encounter_id,
 r.attempts,CASE WHEN r.error_message IS NULL THEN NULL ELSE
 encode(sha256(convert_to(r.error_message,'UTF8')),'hex') END AS error_message_sha256,
 r.started_at,r.finished_at FROM log_processing.record r"""
MATCH = """SELECT m.id,m.created_at,m.updated_at,m.encounter_id,m.map_id,m.map_index,
 m.home_team_id,m.away_team_id,m.home_score,m.away_score,m.time,m.log_name,
 m.log_record_id,m.source::text,m.code,e.tournament_id,e.workspace_id,e.discipline
 FROM matches.match m JOIN encounter.encounter e ON e.id=m.encounter_id"""
# Exactly two removeprefix operations, NOT replace(), basename(), or normalization.
BARE = """CASE WHEN left(r.filename,length('logs/'||r.tournament_id||'/')) = 'logs/'||r.tournament_id||'/'
 THEN substr(r.filename,length('logs/'||r.tournament_id||'/')+1) ELSE r.filename END"""
KEY = f"('logs/'||r.tournament_id||'/'||CASE WHEN left(({BARE}),5)='logs/' THEN substr(({BARE}),6) ELSE ({BARE}) END)"


async def inspect_raw(conn, s3, *, record_id=None, match_id=None, max_bytes=25 * 1024 * 1024):
    row_id = match_id or record_id or 0
    match = one(conn, MATCH + " WHERE m.id=:id", row_id, id=match_id) if match_id else None
    record = one(conn, RECORD + " WHERE r.id=:id", row_id, id=record_id) if record_id else None
    if not match and not record:
        raise PreparationBlocked("missing_raw_owner", row_id)
    tournament_id = match["tournament_id"] if match else record["tournament_id"]
    owner = one(
        conn, "SELECT id,workspace_id,discipline FROM tournament.tournament WHERE id=:id", row_id, id=tournament_id
    )
    if owner["discipline"] != "overwatch" or (
        match and (match["workspace_id"] != owner["workspace_id"] or match["discipline"] != owner["discipline"])
    ):
        raise PreparationBlocked("foreign_raw_owner", row_id)
    if record and record["tournament_id"] != tournament_id:
        raise PreparationBlocked("foreign_raw_owner", row_id)
    key = raw_key(tournament_id, record["filename"] if record else match["log_name"], row_id)
    if match and match["log_name"] is not None and raw_key(tournament_id, match["log_name"], row_id) != key:
        raise PreparationBlocked("raw_reference_conflict", row_id)
    actual_hash = await object_hash(s3, key, row_id, max_bytes)
    candidates = rows(
        conn, RECORD + f" WHERE r.tournament_id=:tid AND {KEY}=:key ORDER BY r.id", tid=tournament_id, key=key
    )
    links = []
    for candidate in candidates:
        raw_key(tournament_id, candidate["filename"], candidate["id"])
        if candidate["content_hash"] is not None and candidate["content_hash"] != actual_hash:
            raise PreparationBlocked("raw_hash_conflict", candidate["id"])
        links.extend(rows(conn, MATCH + " WHERE m.log_record_id=:id ORDER BY m.id", id=candidate["id"]))
        if candidate["attached_encounter_id"] is not None:
            attached = one(
                conn,
                "SELECT tournament_id FROM encounter.encounter WHERE id=:id",
                row_id,
                id=candidate["attached_encounter_id"],
            )
            if attached["tournament_id"] != tournament_id or (
                match and candidate["attached_encounter_id"] != match["encounter_id"]
            ):
                raise PreparationBlocked("inconsistent_record_encounter", row_id)
    if len(links) > 1 or any(
        link["tournament_id"] != tournament_id or (match and link["id"] != match["id"]) for link in links
    ):
        raise PreparationBlocked("inconsistent_record_match", row_id)
    if match and match["log_record_id"] is not None and match["log_record_id"] not in [r["id"] for r in candidates]:
        raise PreparationBlocked("foreign_or_different_linked_record", row_id)
    return {
        "record": record,
        "match": match,
        "owner": owner,
        "raw_ref": key,
        "content_hash": actual_hash,
        "candidate_record_ids": [r["id"] for r in candidates],
        "candidates": candidates,
        "linked_matches": links,
    }


def inspect_game(conn, match_id):
    match = one(conn, MATCH + " WHERE m.id=:id", match_id, id=match_id)
    encounter = one(
        conn,
        """SELECT id,workspace_id,discipline,tournament_id,custom_game_id,status::text,
        result_status::text,result_source,result_version,confirmed_at,current_game_position,
        scoring_rule_id,best_of,slot_count FROM encounter.encounter WHERE id=:id""",
        match_id,
        id=match["encounter_id"],
    )
    games = rows(
        conn,
        """SELECT id,encounter_id,position,map_id,map_kind,state::text,result_source::text,
        result_version,confirmed_at,created_at,updated_at FROM encounter.game WHERE encounter_id=:id ORDER BY id""",
        id=match["encounter_id"],
    )
    teams = rows(
        conn,
        """SELECT id,created_at,updated_at,encounter_id,tournament_id,slot,team_id,
        name,seed,active,score,placement FROM encounter.team WHERE encounter_id=:id ORDER BY id""",
        id=match["encounter_id"],
    )
    results = rows(
        conn,
        """SELECT gt.game_id,gt.encounter_id,gt.encounter_team_id,gt.score,gt.placement,
        gt.column_values,gt.starting_side,gt.replay_code FROM encounter.game_team gt
        WHERE gt.encounter_id=:id ORDER BY gt.game_id,gt.encounter_team_id""",
        id=match["encounter_id"],
    )
    history = rows(conn, MATCH + " WHERE m.encounter_id=:id ORDER BY m.created_at,m.id", id=match["encounter_id"])
    entity = rows(conn, "SELECT id,discipline,kind FROM catalog.entity WHERE id=:id", id=match["map_id"])
    return {
        "match": match,
        "encounter": encounter,
        "games": games,
        "teams": teams,
        "results": results,
        "history": history,
        "map": entity,
    }


def official_results(conn, match_ids):
    """Capture official outcomes once per parent; observations are never authority."""
    result = []
    seen = set()
    for mid in sorted(set(match_ids)):
        eid = one(conn, "SELECT encounter_id FROM matches.match WHERE id=:id", mid, id=mid)["encounter_id"]
        if eid not in seen:
            snapshot = inspect_game(conn, mid)
            result.append({key: snapshot[key] for key in ("encounter", "teams", "games", "results")})
            seen.add(eid)
    return result


SOURCES = """SELECT 'statistics' AS kind,match_id,user_id AS player_id FROM matches.statistics
 UNION SELECT 'kill_actor',match_id,killer_id FROM matches.kill_feed
 UNION SELECT 'kill_target',match_id,victim_id FROM matches.kill_feed
 UNION SELECT 'event_actor',match_id,user_id FROM matches.event WHERE user_id IS NOT NULL
 UNION SELECT 'event_target',match_id,related_user_id FROM matches.event WHERE related_user_id IS NOT NULL"""


def inspect_member(conn, player_id, workspace_id):
    player = one(conn, 'SELECT id,name,auth_user_id FROM players."user" WHERE id=:id', player_id, id=player_id)
    workspace = one(conn, "SELECT id FROM workspace WHERE id=:id", player_id, id=workspace_id)
    members = rows(
        conn,
        "SELECT id,workspace_id,player_id,display_name,removed_at,created_at,updated_at FROM workspace_member WHERE workspace_id=:wid AND player_id=:pid ORDER BY id",
        wid=workspace_id,
        pid=player_id,
    )
    sources = rows(
        conn,
        f"""SELECT DISTINCT s.kind,s.match_id,s.player_id,m.encounter_id,e.workspace_id
        FROM ({SOURCES}) s JOIN matches.match m ON m.id=s.match_id
        JOIN encounter.encounter e ON e.id=m.encounter_id
        WHERE s.player_id=:pid AND e.workspace_id=:wid ORDER BY s.kind,s.match_id""",
        pid=player_id,
        wid=workspace_id,
    )
    identities = rows(
        conn,
        """SELECT id,user_id,provider,username,username_normalized,provider_user_id,is_verified,is_primary
        FROM players.social_account WHERE user_id=:pid ORDER BY id""",
        pid=player_id,
    )
    return {"player": player, "workspace": workspace, "members": members, "sources": sources, "identities": identities}


def validate_item(kind, item):
    row_id = item.get("match_id") or item.get("record_id") or item.get("player_id") or 0
    if (
        not isinstance(item.get("evidence"), str)
        or not item["evidence"].strip()
        or not isinstance(item.get("snapshot"), dict)
        or item.get("expected") != fingerprint(item["snapshot"])
    ):
        raise PreparationBlocked("invalid_review_evidence", row_id)
    required = {
        "raw": {"action", "record_id", "match_id", "tournament_id", "filename", "log_name", "raw_ref", "content_hash"},
        "games": {"match_id", "encounter_id", "position", "map_id", "encounter_team_ids"},
        "members": {"player_id", "workspace_id", "source_ids"},
    }
    optional = {
        "raw": {"reuse_record_id", "create"},
        "games": {"game_id", "create"},
        "members": {"member_id", "create"},
    }
    if (
        kind not in required
        or not required[kind] <= item.keys()
        or set(item) - required[kind] - optional[kind] - {"snapshot", "expected", "evidence"}
    ):
        raise PreparationBlocked("invalid_manifest_fields", row_id)
    for key, value in item.items():
        if key.endswith("_id") and not (kind == "raw" and key in {"record_id", "match_id"} and value is None):
            if type(value) is not int or value <= 0:
                raise PreparationBlocked("invalid_manifest_identity", row_id)
    snapshot_fields = {
        "raw": {
            "record",
            "match",
            "owner",
            "raw_ref",
            "content_hash",
            "candidate_record_ids",
            "candidates",
            "linked_matches",
        },
        "games": {"match", "encounter", "games", "teams", "results", "history", "map"},
        "members": {"player", "workspace", "members", "sources", "identities"},
    }
    if set(item["snapshot"]) != snapshot_fields[kind]:
        raise PreparationBlocked("invalid_snapshot_fields", row_id)
    if kind == "raw":
        if item.get("action") not in {"verify_record", "fill_hash", "link_match"} or not re.fullmatch(
            r"[0-9a-f]{64}", str(item.get("content_hash", ""))
        ):
            raise PreparationBlocked("invalid_raw_manifest", row_id)
        if item["action"] == "link_match" and (
            (item.get("create") is True) == (type(item.get("reuse_record_id")) is int)
        ):
            raise PreparationBlocked("explicit_record_decision_required", row_id)
        if item["action"] != "link_match" and ("create" in item or "reuse_record_id" in item or not item["record_id"]):
            raise PreparationBlocked("invalid_record_action", row_id)
        if item["action"] == "link_match" and (
            not item["match_id"] or item["record_id"] is not None or ("create" in item and item["create"] is not True)
        ):
            raise PreparationBlocked("invalid_link_action", row_id)
        if not isinstance(item["raw_ref"], str):
            raise PreparationBlocked("invalid_raw_reference", row_id)
    elif kind == "games":
        if (
            type(item.get("position")) is not int
            or item["position"] < 1
            or (isinstance(item.get("create"), dict) == (type(item.get("game_id")) is int))
        ):
            raise PreparationBlocked("invalid_game_manifest", row_id)
        if item.get("create") is not None and item["create"] != {"state": "planned"}:
            raise PreparationBlocked("only_planned_game_creation_allowed", row_id)
        teams = item.get("encounter_team_ids")
        if (
            not isinstance(teams, list)
            or len(teams) < 2
            or any(type(t) is not int for t in teams)
            or len(set(teams)) != len(teams)
        ):
            raise PreparationBlocked("invalid_game_participants", row_id)
    elif kind == "members":
        if (isinstance(item.get("create"), dict) and item["create"].get("removed") is True) == (
            type(item.get("member_id")) is int
        ):
            raise PreparationBlocked("explicit_historical_member_decision_required", row_id)
        if "create" in item and item["create"] != {"removed": True}:
            raise PreparationBlocked("only_removed_member_creation_allowed", row_id)
    else:
        raise PreparationBlocked("unknown_manifest_class", row_id)


def load_signed_json(path, expected_sha256):
    data = Path(path).read_bytes()
    if (
        not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        or hashlib.sha256(data).hexdigest() != expected_sha256
    ):
        raise PreparationBlocked("manifest_sha256_mismatch", 0)

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PreparationBlocked("duplicate_manifest_key", 0)
            result[key] = value
        return result

    manifest = json.loads(data, object_pairs_hook=unique_pairs)
    return manifest


def load_manifest(path, expected_sha256):
    manifest = load_signed_json(path, expected_sha256)
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("version")) is not int
        or manifest["version"] != 1
        or set(manifest) != {"version", "raw", "games", "members"}
    ):
        raise PreparationBlocked("invalid_manifest_version_or_sections", 0)
    for kind in ("raw", "games", "members"):
        if not isinstance(manifest[kind], list):
            raise PreparationBlocked("invalid_manifest_section", 0)
        seen = set()
        for item in manifest[kind]:
            if not isinstance(item, dict):
                raise PreparationBlocked("invalid_manifest_item", 0)
            validate_item(kind, item)
            key = (
                (item.get("match_id"), item.get("record_id"))
                if kind == "raw"
                else ((item.get("workspace_id"), item.get("player_id")) if kind == "members" else item.get("match_id"))
            )
            if key in seen:
                raise PreparationBlocked("duplicate_manifest_item", 0)
            seen.add(key)
    return manifest


def lock(conn, namespace, identity):
    conn.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"stats01.prepare/{namespace}/{identity}"},
    )


def assert_expected(current, item, resumed=None):
    if fingerprint(current) != item["expected"] and (resumed is None or fingerprint(resumed) != item["expected"]):
        raise PreparationBlocked(
            "fingerprint_drift", item.get("match_id") or item.get("record_id") or item.get("player_id")
        )


async def apply_raw(conn, s3, item, max_bytes):
    mid, rid = item.get("match_id"), item.get("record_id")
    original = item["snapshot"]
    # Lock parent first, then observations, then exact object key and candidate rows.
    encounters = {m["encounter_id"] for m in original["linked_matches"]}
    if original["match"]:
        encounters.add(original["match"]["encounter_id"])
    for eid in sorted(encounters):
        conn.execute(sa.text("SELECT id FROM encounter.encounter WHERE id=:id FOR UPDATE"), {"id": eid})
    match_ids = {m["id"] for m in original["linked_matches"]}
    if mid:
        match_ids.add(mid)
    for match_id in sorted(match_ids):
        conn.execute(sa.text("SELECT id FROM matches.match WHERE id=:id FOR UPDATE"), {"id": match_id})
    lock(conn, "raw", f"{item['tournament_id']}/{item['raw_ref']}")
    conn.execute(
        sa.text(
            f"SELECT r.id FROM log_processing.record r WHERE r.tournament_id=:tid AND {KEY}=:key ORDER BY r.id FOR UPDATE"
        ),
        {"tid": item["tournament_id"], "key": item["raw_ref"]},
    )
    current = await inspect_raw(conn, s3, record_id=rid, match_id=mid, max_bytes=max_bytes)
    if (
        item["tournament_id"] != current["owner"]["id"]
        or item["raw_ref"] != current["raw_ref"]
        or item["content_hash"] != current["content_hash"]
        or item.get("filename") != (original["record"]["filename"] if original["record"] else None)
        or item.get("log_name") != (original["match"]["log_name"] if original["match"] else None)
    ):
        raise PreparationBlocked("raw_manifest_identity_conflict", mid or rid)
    action = item["action"]
    normalized = deepcopy(current)
    if action == "fill_hash":
        if not rid or original["record"]["content_hash"] is not None:
            raise PreparationBlocked("fill_requires_null_hash", mid or rid)
        normalized["record"]["content_hash"] = None
        for candidate in normalized["candidates"]:
            if candidate["id"] == rid:
                candidate["content_hash"] = None
    elif action == "link_match":
        if not mid or original["match"]["log_record_id"] is not None:
            raise PreparationBlocked("link_requires_unlinked_match", mid or rid)
        if len(current["candidates"]) > 1:
            raise PreparationBlocked("ambiguous_raw_candidates", mid)
        linked = current["match"]["log_record_id"]
        if linked is not None:
            candidate = current["candidates"][0]
            if item.get("create") is True:
                if (
                    original["candidate_record_ids"]
                    or candidate["status"] != "done"
                    or candidate["source"] != "manual"
                    or candidate["uploader_id"] is not None
                    or candidate["attached_encounter_id"] is not None
                    or candidate["started_at"] is not None
                    or candidate["finished_at"] is not None
                    or candidate["attempts"] != 0
                    or candidate["error_message_sha256"] is not None
                    or candidate["updated_at"] is not None
                    or candidate["filename"] != current["raw_ref"].removeprefix(f"logs/{item['tournament_id']}/")
                ):
                    raise PreparationBlocked("created_record_postcondition_conflict", mid)
                normalized["candidate_record_ids"] = []
                normalized["candidates"] = []
            elif linked != item.get("reuse_record_id"):
                raise PreparationBlocked("linked_record_postcondition_conflict", mid)
            if candidate["content_hash"] != item["content_hash"]:
                raise PreparationBlocked("raw_hash_conflict", mid)
            normalized["match"]["log_record_id"] = None
            normalized["linked_matches"] = [m for m in normalized["linked_matches"] if m["id"] != mid]
    assert_expected(current, item, normalized)
    before = current
    official_before = official_results(conn, match_ids)
    if action == "fill_hash":
        conn.execute(
            sa.text("UPDATE log_processing.record SET content_hash=:hash WHERE id=:id AND content_hash IS NULL"),
            {"id": rid, "hash": current["content_hash"]},
        )
    elif action == "verify_record":
        if not rid or current["record"]["content_hash"] != current["content_hash"]:
            raise PreparationBlocked("record_hash_not_verified", mid or rid)
    elif current["match"]["log_record_id"] is None:
        candidates = current["candidates"]
        if item.get("create") is True:
            if candidates:
                raise PreparationBlocked("existing_record_requires_reviewed_reuse", mid)
            rid = conn.execute(
                sa.text("""INSERT INTO log_processing.record
                (tournament_id,filename,content_hash,status,source,uploader_id,attempts)
                VALUES (:tid,:name,:hash,'done','manual',NULL,0) RETURNING id"""),
                {
                    "tid": item["tournament_id"],
                    "name": current["raw_ref"].removeprefix(f"logs/{item['tournament_id']}/"),
                    "hash": current["content_hash"],
                },
            ).scalar_one()
        else:
            if (
                len(candidates) != 1
                or candidates[0]["id"] != item["reuse_record_id"]
                or candidates[0]["content_hash"] != current["content_hash"]
            ):
                raise PreparationBlocked("reuse_requires_one_verified_record", mid)
            rid = candidates[0]["id"]
        conn.execute(sa.text("UPDATE matches.match SET log_record_id=:rid WHERE id=:id"), {"rid": rid, "id": mid})
    after = await inspect_raw(conn, s3, record_id=item.get("record_id"), match_id=mid, max_bytes=max_bytes)
    official_after = official_results(conn, match_ids)
    if official_after != official_before:
        raise PreparationBlocked("official_results_changed", mid or rid)
    return {
        "before": before,
        "after": after,
        "official_before": official_before,
        "official_after": official_after,
        "provenance": "reviewed stats01 preparation; real object bytes; no uploader or processing timestamps synthesized",
    }


def apply_game(conn, item):
    mid, eid = item["match_id"], item["encounter_id"]
    conn.execute(sa.text("SELECT id FROM encounter.encounter WHERE id=:id FOR UPDATE"), {"id": eid})
    conn.execute(sa.text("SELECT id FROM matches.match WHERE encounter_id=:id ORDER BY id FOR UPDATE"), {"id": eid})
    conn.execute(sa.text("SELECT id FROM encounter.game WHERE encounter_id=:id ORDER BY id FOR UPDATE"), {"id": eid})
    current = inspect_game(conn, mid)
    match, encounter = current["match"], current["encounter"]
    if (
        match["encounter_id"] != eid
        or encounter["discipline"] != "overwatch"
        or encounter["tournament_id"] is None
        or match["source"] != "log_parser"
        or match["code"] is not None
        or item["map_id"] != match["map_id"]
        or current["map"] != [{"id": item["map_id"], "discipline": "overwatch", "kind": "map"}]
    ):
        raise PreparationBlocked("foreign_or_invalid_game_owner", mid)
    teams = [t["id"] for t in current["teams"] if t["team_id"] in (match["home_team_id"], match["away_team_id"])]
    if (
        match["home_team_id"] == match["away_team_id"]
        or len(teams) != 2
        or sorted(teams) != sorted(item["encounter_team_ids"])
    ):
        raise PreparationBlocked("game_participant_conflict", mid)
    live = [g for g in current["games"] if g["state"] != "cancelled" and g["position"] == item["position"]]
    target = (
        next((g for g in current["games"] if g["id"] == item.get("game_id")), None)
        if "game_id" in item
        else (live[0] if len(live) == 1 else None)
    )
    normalized = deepcopy(current)
    normalized["match"]["map_index"] = item["snapshot"]["match"]["map_index"]
    for historical in normalized["history"]:
        if historical["id"] == mid:
            historical["map_index"] = item["snapshot"]["match"]["map_index"]
    if target is not None:
        participants = [r for r in current["results"] if r["game_id"] == target["id"]]
        if (
            target["state"] == "cancelled"
            or target["position"] != item["position"]
            or target["map_id"] != item["map_id"]
            or sorted(r["encounter_team_id"] for r in participants) != sorted(teams)
        ):
            raise PreparationBlocked("game_target_conflict", mid)
        if "create" in item:
            if (
                target["id"] in {g["id"] for g in item["snapshot"]["games"]}
                or target["state"] != "planned"
                or target["result_version"] != 0
                or target["result_source"] is not None
                or target["confirmed_at"] is not None
                or any(
                    r["score"] is not None
                    or r["placement"] is not None
                    or r["column_values"] != {}
                    or r["starting_side"] is not None
                    or r["replay_code"] is not None
                    for r in participants
                )
            ):
                raise PreparationBlocked("created_game_postcondition_conflict", mid)
            normalized["games"] = [g for g in normalized["games"] if g["id"] != target["id"]]
            normalized["results"] = [r for r in normalized["results"] if r["game_id"] != target["id"]]
    elif "create" not in item:
        raise PreparationBlocked("foreign_or_missing_game", mid)
    if live and (target is None or live[0]["id"] != target["id"]):
        raise PreparationBlocked("occupied_game_position", mid)
    # Same frozen resolution rule as stats01, applied to EVERY other match.
    for other in current["history"]:
        if other["id"] == mid:
            continue
        explicit = [g for g in current["games"] if g["state"] != "cancelled" and g["position"] == other["map_index"]]
        fallback = [g for g in current["games"] if g["state"] != "cancelled" and g["map_id"] == other["map_id"]]
        resolved = explicit or (fallback if len(fallback) == 1 else [])
        if (
            (target and resolved and resolved[0]["id"] == target["id"])
            or other["map_index"] == item["position"]
            or (target is None and not explicit and not fallback and other["map_id"] == item["map_id"])
        ):
            raise PreparationBlocked("duplicate_game_claim", mid)
    # A resume is valid only after the intended match position was actually written.
    assert_expected(current, item, normalized if match["map_index"] == item["position"] else None)
    if target is None:
        gid = conn.execute(
            sa.text("""INSERT INTO encounter.game (encounter_id,position,map_id,map_kind,state,result_source,result_version,confirmed_at)
            VALUES (:eid,:position,:map,'map','planned',NULL,0,NULL) RETURNING id"""),
            {"eid": eid, "position": item["position"], "map": item["map_id"]},
        ).scalar_one()
        for team_id in sorted(teams):
            conn.execute(
                sa.text("""INSERT INTO encounter.game_team (game_id,encounter_id,encounter_team_id,score,placement,column_values)
                VALUES (:gid,:eid,:tid,NULL,NULL,'{}'::jsonb)"""),
                {"gid": gid, "eid": eid, "tid": team_id},
            )
    conn.execute(
        sa.text("UPDATE matches.match SET map_index=:position WHERE id=:id"), {"position": item["position"], "id": mid}
    )
    after = inspect_game(conn, mid)
    old_ids = {g["id"] for g in current["games"]}
    if (
        after["encounter"] != current["encounter"]
        or after["teams"] != current["teams"]
        or [g for g in after["games"] if g["id"] in old_ids] != current["games"]
        or [r for r in after["results"] if r["game_id"] in old_ids] != current["results"]
    ):
        raise PreparationBlocked("official_results_changed", mid)
    return {"before": current, "after": after}


def apply_member(conn, item):
    pid, wid = item["player_id"], item["workspace_id"]
    conn.execute(sa.text("SELECT id FROM workspace WHERE id=:id FOR UPDATE"), {"id": wid})
    conn.execute(sa.text('SELECT id FROM players."user" WHERE id=:id FOR UPDATE'), {"id": pid})
    conn.execute(
        sa.text("SELECT id FROM workspace_member WHERE workspace_id=:wid AND player_id=:pid ORDER BY id FOR UPDATE"),
        {"wid": wid, "pid": pid},
    )
    conn.execute(sa.text("SELECT id FROM players.social_account WHERE user_id=:id ORDER BY id FOR UPDATE"), {"id": pid})
    for eid in sorted({source["encounter_id"] for source in item["snapshot"]["sources"]}):
        conn.execute(sa.text("SELECT id FROM encounter.encounter WHERE id=:id FOR UPDATE"), {"id": eid})
    current = inspect_member(conn, pid, wid)
    if not current["sources"] or item.get("source_ids") != current["sources"]:
        raise PreparationBlocked("member_source_identity_conflict", pid)
    normalized = deepcopy(current)
    if "create" in item and current["members"]:
        member = current["members"][0]
        if (
            len(current["members"]) != 1
            or member["removed_at"] is None
            or member["removed_at"] != member["created_at"]
            or member["display_name"] is not None
            or member["updated_at"] is not None
            or item["snapshot"]["members"]
        ):
            raise PreparationBlocked("historical_member_postcondition_conflict", pid)
        normalized["members"] = []
    assert_expected(current, item, normalized)
    match_ids = [source["match_id"] for source in current["sources"]]
    official_before = official_results(conn, match_ids)
    if "member_id" in item:
        if len(current["members"]) != 1 or current["members"][0]["id"] != item["member_id"]:
            raise PreparationBlocked("foreign_or_conflicting_member", pid)
    elif not current["members"]:
        conn.execute(
            sa.text("""INSERT INTO workspace_member (workspace_id,player_id,created_at,removed_at)
            VALUES (:wid,:pid,statement_timestamp(),statement_timestamp())"""),
            {"wid": wid, "pid": pid},
        )
    official_after = official_results(conn, match_ids)
    if official_after != official_before:
        raise PreparationBlocked("official_results_changed", pid)
    return {
        "before": current,
        "after": inspect_member(conn, pid, wid),
        "official_before": official_before,
        "official_after": official_after,
        "provenance": "historical identity only; removed_at is preparation time, not a historical removal claim; no access granted",
    }


async def apply_item(conn, s3, kind, item, *, max_bytes=25 * 1024 * 1024):
    """Apply one reviewed item; caller MUST roll back on any exception and commit on success."""
    validate_item(kind, item)
    # Lock/snapshot code must never interpret malformed nested evidence as permission.
    original = item["snapshot"]
    if kind == "raw":
        if not isinstance(original["owner"], dict) or not all(
            isinstance(original[k], list) for k in ("candidates", "candidate_record_ids", "linked_matches")
        ):
            raise PreparationBlocked("invalid_raw_snapshot", item.get("match_id") or item.get("record_id") or 0)
        if (
            original["match"] is not None
            and not isinstance(original["match"], dict)
            or original["record"] is not None
            and not isinstance(original["record"], dict)
        ):
            raise PreparationBlocked("invalid_raw_snapshot", item.get("match_id") or item.get("record_id") or 0)
    try:
        if kind == "raw":
            return await apply_raw(conn, s3, item, max_bytes)
        if kind == "games":
            return apply_game(conn, item)
        return apply_member(conn, item)
    except KeyError, TypeError, ValueError:
        raise PreparationBlocked(
            "malformed_manifest_snapshot", item.get("match_id") or item.get("record_id") or item.get("player_id") or 0
        ) from None


def diagnostic(reason, row_id, **fields):
    fixes = {
        "storage_access_unavailable": "Restore S3_ACCESS_KEY/S3_SECRET_KEY/S3_ENDPOINT_URL and object read permission; rerun --check.",
        "missing_raw_object": "Locate the original object in retained storage/backups; do not substitute bytes or invent a hash.",
        "raw_hash_conflict": "Recover the historical bytes matching the stored hash; never overwrite the existing hash to bless a replacement object.",
        "ambiguous_raw_candidates": "Investigate every reported candidate; do not select one by id or recency. Resolve provenance before requesting a new review.",
        "manifest_sha256_mismatch": "Use the exact reviewed manifest bytes and the SHA-256 supplied by its reviewer.",
        "fingerprint_drift": "Rerun --check and obtain a new review of the changed source snapshot; do not rebase the old approval.",
        "database_item_rolled_back": "This item's transaction was rolled back. Inspect local database constraints/access, then resume with the reviewed artifact.",
    }
    return {
        "reason": reason,
        "row_id": row_id,
        "fix": fixes.get(
            reason,
            "Review historical evidence; correct the source or approve a fresh fingerprinted manifest item, then rerun --check.",
        ),
        **fields,
    }


async def check(conn, s3, *, max_bytes=25 * 1024 * 1024):
    """Read-only inventory. Object bytes are fetched one at a time; SQL keysets are <=100."""
    report = {"version": 1, "raw": [], "games": [], "members": [], "blockers": [], "sizing": []}
    for kind, table in (("record", "log_processing.record"), ("match", "matches.match")):
        last = -1
        while True:
            ids = (
                conn.execute(
                    sa.text(f"SELECT id FROM {table} WHERE id>:last ORDER BY id LIMIT :batch"),
                    {"last": last, "batch": BATCH},
                )
                .scalars()
                .all()
            )
            if not ids:
                break
            for row_id in ids:
                try:
                    if kind == "match":
                        match = one(conn, MATCH + " WHERE m.id=:id", row_id, id=row_id)
                        if match["log_name"] is None and match["log_record_id"] is None:
                            continue
                        snapshot = await inspect_raw(
                            conn, s3, match_id=row_id, record_id=match["log_record_id"], max_bytes=max_bytes
                        )
                    else:
                        snapshot = await inspect_raw(conn, s3, record_id=row_id, max_bytes=max_bytes)
                    entry = {
                        "record_id": snapshot["record"]["id"] if snapshot["record"] else None,
                        "match_id": snapshot["match"]["id"] if snapshot["match"] else None,
                        "snapshot": snapshot,
                        "expected": fingerprint(snapshot),
                    }
                    report["raw"].append(entry)
                    if snapshot["record"] and snapshot["record"]["content_hash"] is None:
                        report["blockers"].append(diagnostic("missing_raw_hash", row_id, owner_kind=kind))
                    if snapshot["match"] and snapshot["match"]["log_record_id"] is None:
                        reason = (
                            "ambiguous_raw_candidates"
                            if len(snapshot["candidates"]) > 1
                            else "recordless_raw_reference"
                        )
                        report["blockers"].append(diagnostic(reason, row_id, owner_kind=kind))
                except PreparationBlocked as exc:
                    source = one(
                        conn,
                        (MATCH + " WHERE m.id=:id") if kind == "match" else (RECORD + " WHERE r.id=:id"),
                        row_id,
                        id=row_id,
                    )
                    name = source["log_name"] if kind == "match" else source["filename"]
                    try:
                        resolved = raw_key(source["tournament_id"], name, row_id)
                    except PreparationBlocked:
                        resolved = None
                    report["blockers"].append(
                        diagnostic(
                            exc.reason,
                            exc.row_id,
                            owner_kind=kind,
                            source_row_id=row_id,
                            tournament_id=source["tournament_id"],
                            legacy_reference=name,
                            resolved_key=resolved,
                        )
                    )
            last = ids[-1]
    last = -1
    while True:
        ids = (
            conn.execute(
                sa.text("SELECT id FROM matches.match WHERE id>:last ORDER BY id LIMIT :batch"),
                {"last": last, "batch": BATCH},
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        for mid in ids:
            snapshot = inspect_game(conn, mid)
            m = snapshot["match"]
            live = [g for g in snapshot["games"] if g["state"] != "cancelled"]
            explicit = [g for g in live if g["position"] == m["map_index"]]
            fallback = [g for g in live if g["map_id"] == m["map_id"]]
            target = explicit or (fallback if len(fallback) == 1 else [])
            reason = None
            if not target:
                reason = "unresolved_game"
            elif target[0]["map_id"] != m["map_id"]:
                reason = "explicit_position_map_mismatch"
            else:
                claimed = []
                for other in snapshot["history"]:
                    direct = [g for g in live if g["position"] == other["map_index"]]
                    by_map = [g for g in live if g["map_id"] == other["map_id"]]
                    selected = direct or (by_map if len(by_map) == 1 else [])
                    if selected and selected[0]["id"] == target[0]["id"]:
                        claimed.append(other["id"])
                if len(claimed) > 1:
                    reason = "duplicate_game_claim"
                expected_teams = [
                    t["id"] for t in snapshot["teams"] if t["team_id"] in (m["home_team_id"], m["away_team_id"])
                ]
                actual_teams = [r["encounter_team_id"] for r in snapshot["results"] if r["game_id"] == target[0]["id"]]
                if len(expected_teams) != 2 or sorted(expected_teams) != sorted(actual_teams):
                    reason = "game_participant_conflict"
            if (
                m["discipline"] != "overwatch"
                or m["tournament_id"] is None
                or m["source"] != "log_parser"
                or m["code"] is not None
            ):
                reason = "foreign_or_invalid_game_owner"
            if reason:
                report["games"].append(
                    {
                        "match_id": mid,
                        "snapshot": snapshot,
                        "expected": fingerprint(snapshot),
                        "reason": reason,
                        "historical_evidence": "history preserves source created_at/id and explicit map_index; ordering is evidence only, never approval",
                    }
                )
                report["blockers"].append(diagnostic(reason, mid))
            counts = one(
                conn,
                """SELECT (SELECT count(*) FROM matches.statistics WHERE match_id=:id) AS statistics,
                (SELECT count(*) FROM matches.kill_feed WHERE match_id=:id) AS kill_feed,
                (SELECT count(*) FROM matches.event WHERE match_id=:id) AS events""",
                mid,
                id=mid,
            )
            report["sizing"].append({"match_id": mid, **counts})
        last = ids[-1]
    last_wid, last_pid = -1, -1
    while True:
        missing = rows(
            conn,
            f"""SELECT DISTINCT e.workspace_id,s.player_id FROM ({SOURCES}) s
            JOIN matches.match m ON m.id=s.match_id JOIN encounter.encounter e ON e.id=m.encounter_id
            WHERE s.player_id IS NOT NULL AND (e.workspace_id,s.player_id)>(:wid,:pid)
            AND NOT EXISTS (SELECT 1 FROM workspace_member wm WHERE wm.workspace_id=e.workspace_id AND wm.player_id=s.player_id)
            ORDER BY e.workspace_id,s.player_id LIMIT :batch""",
            wid=last_wid,
            pid=last_pid,
            batch=BATCH,
        )
        if not missing:
            break
        for member in missing:
            snapshot = inspect_member(conn, member["player_id"], member["workspace_id"])
            report["members"].append(
                {**member, "snapshot": snapshot, "expected": fingerprint(snapshot), "source_ids": snapshot["sources"]}
            )
            report["blockers"].append(
                diagnostic("missing_historical_member", member["player_id"], workspace_id=member["workspace_id"])
            )
        last_wid, last_pid = missing[-1]["workspace_id"], missing[-1]["player_id"]
    uncertainty = {
        "missing_raw_hash",
        "recordless_raw_reference",
        "ambiguous_raw_candidates",
        "missing_raw_object",
        "raw_hash_conflict",
        "empty_raw_object",
        "oversize_raw_object",
        "unprocessable_raw_object",
        "unresolved_game",
        "explicit_position_map_mismatch",
        "duplicate_game_claim",
        "game_participant_conflict",
    }
    report["warnings"] = [row for row in report["blockers"] if row["reason"] in uncertainty]
    report["blockers"] = [row for row in report["blockers"] if row["reason"] not in uncertainty]
    report["counts"] = {}
    for blocker in report["blockers"]:
        reason = blocker["reason"]
        report["counts"][reason] = report["counts"].get(reason, 0) + 1
    return report


NATIVE_FORMAT = "stats01-native-raw/1"
NATIVE_INVENTORY = "stats01-native-raw-inventory/1"
NATIVE_SOURCE_EVIDENCE = "stats01-native-raw-source/1"


async def native_state(session):
    """Bind inspection metadata to this database's exact job and observation rows."""
    await session.execute(sa.text("SET LOCAL TIME ZONE 'UTC'"))
    jobs = list((await session.scalars(sa.text("SELECT to_jsonb(j) FROM stats.ingest_job j ORDER BY id"))).all())
    matches = list((await session.scalars(sa.text("SELECT to_jsonb(m) FROM stats.match m ORDER BY id"))).all())
    identity = {
        "database_name": await session.scalar(sa.text("SELECT current_database()")),
        "revision": list(
            (await session.scalars(sa.text("SELECT version_num FROM alembic_version ORDER BY version_num"))).all()
        ),
    }
    return native_target(identity, jobs, matches), jobs, matches


def native_target(identity, jobs, matches):
    return {
        **{key: identity[key] for key in ("database_name", "revision")},
        "jobs_count": len(jobs),
        "observations_count": len(matches),
        "state_sha256": fingerprint({"jobs": jobs, "observations": matches}),
    }


def native_snapshots(jobs, matches):
    sources = {job["id"]: job["raw_ref"] for job in jobs}
    observations = {}
    for match in matches:
        key = sources.get(match["ingest_job_id"])
        if key is not None:
            observations.setdefault(key, []).append(match)
    return {job["id"]: {"job": job, "observations": observations.get(job["raw_ref"], [])} for job in jobs}


def native_inputs(target, inventory, source_evidence):
    for value, format_name in ((inventory, NATIVE_INVENTORY), (source_evidence, NATIVE_SOURCE_EVIDENCE)):
        if value is not None and (
            not isinstance(value, dict) or value.get("format") != format_name or value.get("target") != target
        ):
            raise PreparationBlocked("native_input_target_mismatch", 0)
    if source_evidence is not None and (
        not isinstance(source_evidence.get("evidence"), str) or not source_evidence["evidence"].strip()
    ):
        raise PreparationBlocked("invalid_review_evidence", 0)
    objects = {}
    if inventory is not None:
        if not isinstance(inventory.get("objects"), list):
            raise PreparationBlocked("invalid_native_inventory", 0)
        for obj in inventory["objects"]:
            if (
                not isinstance(obj, dict)
                or not {"raw_ref", "status", "sha256", "bytes", "processable", "inspected_at"} <= obj.keys()
                or not isinstance(obj.get("raw_ref"), str)
                or not obj["raw_ref"]
                or obj["raw_ref"] in objects
                or obj.get("status") not in {"ok", "missing"}
                or not isinstance(obj.get("inspected_at"), str)
            ):
                raise PreparationBlocked("invalid_native_inventory", 0)
            stamp = datetime.fromisoformat(obj["inspected_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise PreparationBlocked("invalid_native_inventory", 0)
            if obj["status"] == "ok":
                if (
                    not re.fullmatch(r"[0-9a-f]{64}", str(obj.get("sha256", "")))
                    or type(obj.get("bytes")) is not int
                    or obj["bytes"] < 0
                    or type(obj.get("processable")) is not bool
                ):
                    raise PreparationBlocked("invalid_native_inventory", 0)
            elif obj["sha256"] is not None or obj["bytes"] is not None or obj["processable"] is not False:
                raise PreparationBlocked("invalid_native_inventory", 0)
            objects[obj["raw_ref"]] = obj
    return objects


async def inspect_native_object(s3, raw_ref, row_id, max_bytes):
    if s3 is None:
        raise PreparationBlocked("storage_access_unavailable", row_id)
    try:
        raw = await s3.get_object(raw_ref)
    except Exception:
        raise PreparationBlocked("storage_access_unavailable", row_id) from None
    result = {"raw_ref": raw_ref, "inspected_at": datetime.now(UTC).isoformat()}
    if raw is None:
        return {**result, "status": "missing", "sha256": None, "bytes": None, "processable": False}
    try:
        text = raw.decode("utf-8")
        processable = bool(text.strip()) and "\x00" not in text and len(raw) <= max_bytes
    except UnicodeDecodeError:
        processable = False
    return {
        **result,
        "status": "ok",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "processable": processable,
    }


def classify_native_raw(snapshot, obj, *, max_bytes=25 * 1024 * 1024):
    job = snapshot["job"]
    if len(snapshot["observations"]) > 1:
        return "unverified", "ambiguous_shared_source"
    if obj["status"] == "missing":
        return "missing", "object_not_found"
    if job["content_hash"] is not None and job["content_hash"].lower() != obj["sha256"]:
        return "conflict", "known_hash_differs"
    if not obj["processable"] or not 0 < obj["bytes"] <= max_bytes:
        return "unverified", "unprocessable_raw_object"
    return "available", "inspected_exact_bytes"


async def verify_native_raw(session, s3, *, inventory=None, source_evidence=None, max_bytes=25 * 1024 * 1024):
    """Dry run. Optional signed inventory uses this report's objects and exact target."""
    target, jobs, matches = await native_state(session)
    objects = native_inputs(target, inventory, source_evidence)
    snapshots = native_snapshots(jobs, matches)
    keys = {job["raw_ref"] for job in jobs}
    if inventory is not None and set(objects) != keys:
        raise PreparationBlocked("incomplete_native_inventory", 0)
    report = {
        "format": NATIVE_FORMAT,
        "target": target,
        "review": "",
        "raw": [],
        "objects": [],
        "blockers": [],
        "inputs": {"inventory_sha256": None, "source_evidence_sha256": None},
    }
    failed = set()
    for job in jobs:
        key, job_id = job["raw_ref"], job["id"]
        if key not in objects and key not in failed:
            try:
                objects[key] = await inspect_native_object(s3, key, job_id, max_bytes)
            except PreparationBlocked as exc:
                failed.add(key)
                report["blockers"].append(diagnostic(exc.reason, job_id, raw_ref=key))
        if key in failed:
            continue
        snapshot, obj = snapshots[job_id], objects[key]
        status, reason = classify_native_raw(snapshot, obj, max_bytes=max_bytes)
        report["raw"].append(
            {
                "job_id": job_id,
                "workspace_id": job["workspace_id"],
                "snapshot": snapshot,
                "expected": fingerprint(snapshot),
                "raw_status": status,
                "inspected_sha256": obj["sha256"],
                "reason": reason,
            }
        )
    report["objects"] = [objects[key] for key in sorted(objects)]
    return report


async def apply_native_raw(
    session, s3, manifest, *, manifest_sha256, inventory=None, source_evidence=None, max_bytes=25 * 1024 * 1024
):
    """One atomic reviewed application; exact repeats do not create audit rows."""
    from shared import models
    from shared.repository.stats import IngestJobRepository
    from shared.services.stats_evidence import (
        capture_stats_evidence,
        owner_scopes,
        stage_stats_evidence,
        state_equal,
        verified_content_hash,
    )

    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != NATIVE_FORMAT
        or manifest.get("blockers") != []
        or not isinstance(manifest.get("raw"), list)
        or not isinstance(manifest.get("review"), str)
        or not manifest["review"].strip()
        or not re.fullmatch(r"[0-9a-f]{64}", str(manifest_sha256))
    ):
        raise PreparationBlocked("incomplete_native_verification", 0)
    await session.execute(sa.text("SET LOCAL lock_timeout='5s'"))
    # Inspection and audit must see one stable provenance/observation set. Read
    # traffic is allowed; this operator is only run with writers drained.
    await session.execute(sa.text("LOCK TABLE stats.ingest_job,stats.match IN SHARE ROW EXCLUSIVE MODE"))
    target, jobs, matches = await native_state(session)
    snapshots = native_snapshots(jobs, matches)
    originals = {}
    for item in manifest["raw"]:
        if not isinstance(item, dict) or type(item.get("job_id")) is not int:
            raise PreparationBlocked("invalid_native_manifest", 0)
        job_id = item["job_id"]
        original = item.get("snapshot")
        if (
            job_id in originals
            or job_id not in snapshots
            or not isinstance(original, dict)
            or set(original) != {"job", "observations"}
            or not isinstance(original["job"], dict)
            or set(original["job"]) != set(snapshots[job_id]["job"])
            or not isinstance(original["observations"], list)
            or item.get("expected") != fingerprint(original)
            or original["job"].get("id") != job_id
            or original["job"].get("workspace_id") != item.get("workspace_id")
        ):
            raise PreparationBlocked("invalid_native_manifest", job_id)
        expected = deepcopy(original)
        expected["job"]["raw_status"] = item.get("raw_status")
        expected["job"]["content_hash"] = verified_content_hash(
            original["job"]["content_hash"], item.get("raw_status"), item.get("inspected_sha256")
        )
        if snapshots[job_id] != original and snapshots[job_id] != expected:
            raise PreparationBlocked("native_target_drift", job_id)
        originals[job_id] = original["job"]
    if set(originals) != {job["id"] for job in jobs}:
        raise PreparationBlocked("incomplete_native_verification", 0)
    original_target = native_target(target, [originals[job["id"]] for job in jobs], matches)
    if original_target != manifest.get("target"):
        raise PreparationBlocked("native_target_drift", 0)
    objects = native_inputs(original_target, inventory, source_evidence)
    if inventory is not None and set(objects) != {job["raw_ref"] for job in jobs}:
        raise PreparationBlocked("incomplete_native_inventory", 0)
    inputs = manifest.get("inputs", {})
    repo = IngestJobRepository()
    applied = []
    for item in manifest["raw"]:
        job_id, snapshot = item["job_id"], item["snapshot"]
        key = snapshot["job"]["raw_ref"]
        if key not in objects:
            objects[key] = await inspect_native_object(s3, key, job_id, max_bytes)
        obj = objects[key]
        if (
            classify_native_raw(snapshot, obj, max_bytes=max_bytes)[0] != item["raw_status"]
            or obj["sha256"] != item["inspected_sha256"]
        ):
            raise PreparationBlocked("native_inspection_drift", job_id)
        scopes = owner_scopes("job", (job_id,))
        before = await capture_stats_evidence(session, scopes=scopes)
        await repo.verify_raw_source(
            session,
            job_id=job_id,
            workspace_id=item["workspace_id"],
            raw_status=models.RawSourceStatus(item["raw_status"]),
            inspected_sha256=item["inspected_sha256"],
        )
        after = await capture_stats_evidence(session, scopes=scopes)
        if all(state_equal(a, b) for a, b in zip(before, after, strict=True)):
            continue
        audit = await stage_stats_evidence(
            session,
            operation="stats.raw_verification",
            before=before,
            after=after,
            workspace_id=item["workspace_id"],
            entity_type="ingest_job",
            entity_id=job_id,
            raw_verification=[{"job_id": job_id, "raw_ref": key, "inspected_sha256": obj["sha256"]}],
        )
        audit.after_json = {
            **audit.after_json,
            "native_raw_verification": {
                "manifest_sha256": manifest_sha256,
                "target": original_target,
                "review": manifest["review"],
                "inputs": inputs,
                "inspection": obj,
            },
        }
        await session.flush()
        applied.append(job_id)
    return {"format": NATIVE_FORMAT, "target": original_target, "applied": applied, "blockers": []}


def parser():
    cli = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  uv run python scripts/stats01_prepare.py --check --report preparation.json\n  uv run python scripts/stats01_prepare.py --apply --manifest reviewed.json --manifest-sha256 SHA256 --report applied.json\n  uv run python scripts/stats01_prepare.py --verify-native-raw --report native-proposal.json\n  uv run python scripts/stats01_prepare.py --apply-native-raw --manifest native-reviewed.json --manifest-sha256 SHA256 --report native-applied.json\nExit: 0 no blockers; 1 blocked/failed; 2 invalid command. Stop writers and review evidence before apply.",
    )
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only inventory (the default)")
    mode.add_argument("--apply", action="store_true", help="Apply only reviewed manifest items, one transaction each")
    mode.add_argument("--verify-native-raw", action="store_true", help="Inspect native raw bytes without writes")
    mode.add_argument(
        "--apply-native-raw", action="store_true", help="Atomically apply a reviewed native inspection manifest"
    )
    cli.add_argument("--manifest", type=Path, help="Reviewed legacy repair or native verification JSON")
    cli.add_argument("--manifest-sha256", help="Expected SHA-256 supplied independently by the reviewer")
    cli.add_argument("--inventory", type=Path, help="Signed native object inspection JSON instead of live GET")
    cli.add_argument("--inventory-sha256", help="Independently reviewed inventory SHA-256")
    cli.add_argument("--source-evidence", type=Path, help="Signed supporting evidence bound to the native target")
    cli.add_argument("--source-evidence-sha256", help="Independently reviewed source evidence SHA-256")
    cli.add_argument("--report", type=Path, help="Write JSON evidence here; default stdout")
    return cli


async def run_native_cli(args, settings):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    inventory = load_signed_json(args.inventory, args.inventory_sha256) if args.inventory else None
    evidence = load_signed_json(args.source_evidence, args.source_evidence_sha256) if args.source_evidence else None
    manifest = load_signed_json(args.manifest, args.manifest_sha256) if args.apply_native_raw else None
    inputs = {"inventory_sha256": args.inventory_sha256, "source_evidence_sha256": args.source_evidence_sha256}
    if manifest is not None and (not isinstance(manifest, dict) or manifest.get("inputs") != inputs):
        raise PreparationBlocked("native_input_digest_mismatch", 0)
    engine = create_async_engine(settings.db_url_asyncpg, isolation_level="REPEATABLE READ", poolclass=sa.pool.NullPool)
    s3 = None
    try:
        if inventory is None and settings.s3_access_key and settings.s3_secret_key and settings.s3_endpoint_url:
            from shared.clients.s3 import S3Client

            s3 = S3Client.from_settings(settings)
            await s3.start()
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            if args.apply_native_raw:
                report = await apply_native_raw(
                    session,
                    s3,
                    manifest,
                    manifest_sha256=args.manifest_sha256,
                    inventory=inventory,
                    source_evidence=evidence,
                    max_bytes=settings.max_match_log_bytes,
                )
            else:
                await session.execute(sa.text("SET TRANSACTION READ ONLY"))
                report = await verify_native_raw(
                    session,
                    s3,
                    inventory=inventory,
                    source_evidence=evidence,
                    max_bytes=settings.max_match_log_bytes,
                )
            report["inputs"] = inputs
            report["mode"] = "apply-native-raw" if args.apply_native_raw else "verify-native-raw"
        return report, int(bool(report["blockers"]))
    finally:
        if s3 is not None:
            await s3.close()
        await engine.dispose()


async def run_cli(args):
    settings = Settings()
    if args.verify_native_raw or args.apply_native_raw:
        return await run_native_cli(args, settings)
    manifest = load_manifest(args.manifest, args.manifest_sha256) if args.apply else None
    engine = sa.create_engine(settings.db_url, pool_pre_ping=True)
    s3 = None
    try:
        from shared.clients.s3 import S3Client

        if settings.s3_access_key and settings.s3_secret_key and settings.s3_endpoint_url:
            s3 = S3Client.from_settings(settings)
            await s3.start()
        applied, failures = [], []
        if manifest:
            # Member/game changes precede raw evidence only if the reviewer uses
            # separate manifests: no hidden rebasing of any approved fingerprint.
            for kind in ("raw", "games", "members"):
                for item in manifest[kind]:
                    try:
                        with engine.begin() as conn:
                            conn.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                            result = await apply_item(conn, s3, kind, item, max_bytes=settings.max_match_log_bytes)
                        applied.append(
                            {"class": kind, "expected": item["expected"], "evidence": item["evidence"], **result}
                        )
                    except PreparationBlocked as exc:
                        failures.append(diagnostic(exc.reason, exc.row_id, item_class=kind))
                    except sa.exc.SQLAlchemyError:
                        failures.append(
                            diagnostic(
                                "database_item_rolled_back",
                                item.get("match_id") or item.get("record_id") or item.get("player_id"),
                                item_class=kind,
                            )
                        )
        try:
            with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                report = await check(conn, s3, max_bytes=settings.max_match_log_bytes)
        except PreparationBlocked, sa.exc.SQLAlchemyError:
            # Preserve committed-item evidence even when the final inventory fails.
            report = {
                "version": 1,
                "blockers": [diagnostic("final_inventory_failed", 0)],
                "fix": "Keep this apply report; restore database/source access and rerun --check before any further repair.",
            }
        report.update(
            mode="apply" if args.apply else "check",
            applied=applied,
            apply_failures=failures,
            manifest_sha256=args.manifest_sha256 if args.apply else None,
        )
        return report, int(bool(report["blockers"] or failures))
    finally:
        if s3 is not None:
            await s3.close()
        engine.dispose()


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    applying = args.apply or args.apply_native_raw
    native = args.verify_native_raw or args.apply_native_raw
    if applying and (args.manifest is None or not args.manifest_sha256):
        cli.error("apply requires --manifest and the reviewer's --manifest-sha256")
    if not applying and (args.manifest is not None or args.manifest_sha256):
        cli.error("manifest flags require --apply or --apply-native-raw")
    for flag in ("inventory", "source_evidence"):
        path, digest = getattr(args, flag), getattr(args, flag + "_sha256")
        if bool(path) != bool(digest) or ((path or digest) and not native):
            cli.error(f"--{flag.replace('_', '-')} and its --sha256 require a native verification mode")
    if args.report and any(
        path and path.resolve() == args.report.resolve()
        for path in (args.manifest, args.inventory, args.source_evidence)
    ):
        cli.error("--report must not overwrite an input evidence artifact")
    try:
        report, status = asyncio.run(run_cli(args))
    except PreparationBlocked as exc:
        report, status = {"blockers": [diagnostic(exc.reason, exc.row_id)]}, 1
    except OSError, ValueError, sa.exc.SQLAlchemyError:
        # Driver/settings errors can embed URLs, passwords or payloads: do not print them.
        report, status = (
            {
                "blockers": [diagnostic("configuration_or_database_unavailable", 0)],
                "fix": "Check existing POSTGRES_*/S3_* settings, local file access and the P3 schema; retry --check. No secret-bearing exception text is exported.",
            },
            1,
        )
    output = json.dumps(canonical(report), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.report:
        try:
            args.report.write_text(output, encoding="utf-8")
        except OSError:
            print(
                "Cannot write report; choose a writable --report path. Committed apply items remain committed; resume using the same reviewed manifest.",
                file=sys.stderr,
            )
            return 1
    else:
        print(output, end="")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
