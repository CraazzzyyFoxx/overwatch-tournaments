"""Opt-in live run of both games end to end on the shared live stack (P8 Task 4, plan Task 3 folded in).

Skipped unless ``RUN_P8_LIVE_SMOKE=1`` (a skipped run is not evidence). The stack is
``live_smoke_support.bring_up(stack, apps=True)``: P5's processes plus app-service and balancer-service ``serve``, the
built gateway, and the P5 world (workspace ``OFF`` = A {overwatch, lol}, ``ON`` = B {overwatch}, P5 grids/cases/
Workshop). ``seed_p8`` adds prerequisites only (``_live_p8_world.py``: logins, roles, workspace C, handles of people no
scenario registers; the LoL catalog through the superuser admin routes, or the real Data Dragon sync with
``RUN_P8_SOURCE_SMOKE=1``). Everything a scenario asserts is created through its real HTTP route.

Optional env: ``RUN_P8_SOURCE_SMOKE=1`` (the only intentional egress), ``P8_SMOKE_BROWSER_HOLD=1`` (fixture teardown
keeps every process serving until ``<evidence dir>/release`` exists), ``P8_SMOKE_EVIDENCE_DIR``, ``P8_SMOKE_BUILD_ID``,
plus the P5 recipe's ``P5_SMOKE_*`` and ``POSTGRES_*``. From ``backend/``:
``RUN_P8_LIVE_SMOKE=1 uv run pytest stats-service/tests/test_two_game_live_scenarios.py -v -s -p no:cacheprovider``.

P9 contract: every scenario is a module-level ``def <name>(live: Live, ids: dict[str, Any]) -> None`` that never
creates or drops infrastructure; its prerequisites come from idempotent helpers cached in ``ids``. ``ids`` keys:

* ``workspaces`` -- ``{"A", "B", "C"}`` ids (C = Overwatch only); ``tag`` -- this run's handle tag
* ``users`` -- label -> ``{auth_user_id, player_id, members}``; ``logins`` -- label -> ``{email, password}`` (``org`` =
  admin of A/B/C, ``root`` = superuser; never written to evidence); ``handles`` -- label -> ``{provider: handle}``
* ``roles`` -- game -> registrant label -> role code; ``dup_players`` -- two unlinked owners of one Riot handle
* ``catalog`` -- game -> slug -> catalog id (read back, never hard-coded)
* filled lazily: ``events`` (tournaments + registrations), ``balanced``, ``drafts``, ``encounters``, ``mixes``,
  ``matches``, ``jobs``, ``grids``
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from shared.messaging.config import MATCH_INGESTED_TOURNAMENT_DLQ, ingest_dlq, ingest_replay_dlq
from tests.live_smoke_support import (
    JSON_HEADERS,
    Live,
    LiveStack,
    Response,
    bring_up,
    canonical,
    err,
    http,
    redact,
    wait_until,
)
from tests.live_smoke_world import async_session_factory, document, with_unknown_identities
from tests.test_ow_decoder_reference_capture import DIRECTORY, observe

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_P8_LIVE_SMOKE") != "1", reason="live two-game scenarios: set RUN_P8_LIVE_SMOKE=1"
)

SOURCE = os.environ.get("RUN_P8_SOURCE_SMOKE") == "1"
HOLD = os.environ.get("P8_SMOKE_BROWSER_HOLD") == "1"
OW, LOL = "overwatch", "lol"
GAMES = (OW, LOL)
DIMENSION = {OW: "player_role", LOL: "position"}
PROVIDER = {OW: "battlenet", LOL: "riot"}
ANSWER_KEY = {OW: "identity_battlenet", LOL: "identity_riot"}
PRESET = {OW: "role_queue_5v5", LOL: "positions_5v5"}
POSITIONS = ("top", "jungle", "mid", "bot", "support")
FORMAT = {OW: {"tank": 1, "damage": 2, "support": 2}, LOL: dict.fromkeys(POSITIONS, 1)}
BASE_RANK = {OW: {"tank": 2600, "damage": 2500, "support": 2400}, LOL: dict.fromkeys(POSITIONS, 1500)}
CHAMPIONS = (
    ("Ahri", "ahri", "Mage"),
    ("Garen", "garen", "Fighter"),
    ("Jinx", "jinx", "Marksman"),
    ("Leona", "leona", "Tank"),
    ("Thresh", "thresh", "Support"),
    ("Zed", "zed", "Assassin"),
)
RIFT = "summoners_rift"
LEGACY_RIFT = "summoner-s-rift"
OW_HERO, OW_MAP = "ingest-ana", "ingest-ilios"
DATA_DRAGON = "https://ddragon.leagueoflegends.com"
FORM = {
    "schema_version": 1,
    "sections": [
        {
            "key": "accounts",
            "fields": [
                {"key": "identity_battlenet", "kind": "builtin", "editable": True},
                {"key": "identity_riot", "kind": "builtin", "editable": True},
            ],
        }
    ],
}
TIER = {
    "id": None,
    "slug": "p8-lol-tier",
    "name": "P8 LoL tier",
    "number": 7,
    "sort_order": 0,
    "rank_min": 0,
    "rank_max": None,
    "icon_url": "/tier.png",
    "native_rank_min": None,
    "native_rank_max": None,
}

_TOKENS: dict[str, tuple[str, float]] = {}
_SCENARIO = ["seed"]


# == HTTP / SQL helpers ================================================================================================


def token(live: Live, ids: dict[str, Any], who: str, *, fresh: bool = False) -> str:
    cached = _TOKENS.get(who)
    if cached and not fresh and time.monotonic() - cached[1] < 240:
        return cached[0]
    login = ids["logins"][who]
    response = http(
        "POST",
        f"{live.stack.gateway}/api/v1/auth/login",
        body=json.dumps({"email": login["email"], "password": login["password"]}).encode(),
        headers=JSON_HEADERS,
    )
    assert response.status == 200, (who, response.status, response.raw[:200])
    _TOKENS[who] = (response.json()["access_token"], time.monotonic())
    return _TOKENS[who][0]


def code_of(response: Response) -> str | None:
    try:
        return err(response)
    except (ValueError, AttributeError, KeyError, TypeError, IndexError):
        return None


def detail(response: Response) -> str:
    try:
        return str((response.json() or {}).get("detail") or "")
    except ValueError:
        return ""


def call(
    live: Live,
    ids: dict[str, Any],
    who: str | None,
    method: str,
    route: str,
    body: Any = None,
    *,
    query: dict[str, Any] | None = None,
    expect: int | tuple[int, ...] | None = None,
    **params: Any,
) -> Response:
    """One real request; the route template, caller label, status and error code are evidence (never a token)."""
    path = route.format(**params)
    if query:
        path += "?" + urllib.parse.urlencode(query, doseq=True)
    headers = dict(JSON_HEADERS)
    if who is not None:
        headers["Authorization"] = f"Bearer {token(live, ids, who)}"
    response = http(
        method,
        f"{live.stack.gateway}{path}",
        body=None if body is None else json.dumps(body).encode(),
        headers=headers,
    )
    entry: dict[str, Any] = {
        "scenario": _SCENARIO[0],
        "who": who or "anonymous",
        "method": method,
        "route": route,
        "status": response.status,
    }
    if response.status >= 400:
        entry["code"] = code_of(response)
    live.stack.evidence.append("http_operations", entry)
    if expect is not None:
        allowed = expect if isinstance(expect, tuple) else (expect,)
        assert response.status in allowed, (method, route, params, response.status, response.raw[:800])
    return response


def refused(response: Response, status: int, *, code: str | None = None, contains: str | None = None) -> None:
    assert response.status == status, (status, response.status, response.raw[:600])
    if code is not None:
        assert code_of(response) == code, (code, response.raw[:600])
    if contains is not None:
        assert contains in detail(response) or contains in response.raw.decode(errors="replace"), response.raw[:600]


def ingest(live: Live, label: str | None, doc: dict | bytes) -> Response:
    response = live.post(label, doc if isinstance(doc, bytes) else canonical(doc))
    entry = {"scenario": _SCENARIO[0], "who": label or "anonymous", "method": "POST", "route": "/api/v1/stats/matches"}
    entry["status"] = response.status
    if response.status >= 400:
        entry["code"] = code_of(response)
    live.stack.evidence.append("http_operations", entry)
    return response


def invariant(live: Live, key: str, value: Any) -> Any:
    live.stack.evidence.record("sql_invariants", f"{_SCENARIO[0]}:{key}", value)
    return value


def scenario_ids(live: Live, **values: Any) -> None:
    live.stack.evidence.data["scenario_ids"].setdefault(_SCENARIO[0], {}).update(values)


def member_of(live: Live, ids: dict[str, Any], label: str, ws: str = "A") -> int | None:
    return live.s(
        "SELECT id FROM public.workspace_member WHERE workspace_id=%s AND player_id=%s AND removed_at IS NULL "
        "AND NOT observed_only",
        ids["workspaces"][ws],
        ids["users"][label]["player_id"],
    )


def label_of_player(ids: dict[str, Any], player_id: int | None) -> str | None:
    return next((label for label, user in ids["users"].items() if user.get("player_id") == player_id), None)


def labels_by_member(live: Live, ids: dict[str, Any]) -> dict[int, str]:
    out: dict[int, str] = {}
    for label, user in ids["users"].items():
        if "player_id" not in user:
            continue
        for (member_id,) in live.q(
            "SELECT id FROM public.workspace_member WHERE workspace_id=%s AND player_id=%s",
            ids["workspaces"]["A"],
            user["player_id"],
        ):
            out[member_id] = label
    return out


def _ids_only(ids: dict[str, Any]) -> dict[str, Any]:
    """A detached, ID-only projection of ``ids``: what may be printed or written to evidence (no login, handle, name)."""
    projection = {
        "tag": ids["tag"],
        "workspaces": ids["workspaces"],
        "users": {
            label: {key: user[key] for key in ("auth_user_id", "player_id", "members") if key in user}
            for label, user in ids["users"].items()
        },
        "dup_players": ids["dup_players"],
        "catalog": ids["catalog"],
        "events": {
            key: {"tournament_id": event["tournament_id"], "registrations": event["registrations"]}
            for key, event in ids["events"].items()
        },
        "balanced": {
            game: {key: out[key] for key in ("tournament_id", "job_id", "balance_id", "teams")}
            for game, out in ids["balanced"].items()
        },
        "drafts": ids["drafts"],
        "encounters": {
            key: {k: v for k, v in enc.items() if k != "captains"} for key, enc in ids["encounters"].items()
        },
        **{key: ids[key] for key in ("mixes", "matches", "jobs", "grids")},
    }
    return json.loads(json.dumps(projection, default=str))  # a copy: later ``ids`` growth never reaches the evidence


def _private(live: Live, *values: str) -> None:
    """Register private identities for redaction: the value, its game-name part (before ``#``), both lowercased too."""
    for value in values:
        for part in {value, value.split("#")[0]}:
            live.stack.identities.update((part, part.lower()))


# == fixture (G3) ======================================================================================================


@pytest.fixture(scope="module")
def _p8():
    directory = os.environ.get("P8_SMOKE_EVIDENCE_DIR")
    stack = LiveStack(Path(directory) if directory else None)
    credentials: Path | None = None
    exits: list[str] = []
    try:
        stack.evidence.record("run", "build_id", os.environ.get("P8_SMOKE_BUILD_ID"))
        stack.evidence.record("run", "started_at", datetime.now(UTC).isoformat())
        stack.evidence.record("run", "source_smoke", SOURCE)
        stack.evidence.record("run", "browser_hold", HOLD)
        live = bring_up(stack, apps=True)
        ids = seed_p8(live)
        yield live, ids
        # Teardown, in order: the optional browser hold (every process still serving), then each process stopped in
        # reverse start order, then close() (exact-resource cleanup, redaction, evidence.json).
        if HOLD:
            handle, name = tempfile.mkstemp(prefix="p8-browser-logins-", suffix=".json")
            credentials = Path(name)  # owned before the wait: an interrupted hold still deletes it
            _hold(live, ids, handle, credentials)
        for name in reversed(list(stack.procs)):
            if stack.procs[name].reaped:
                continue
            code = stack.stop(name)
            if code != 0:
                exits.append(f"{name} exited with {code}")
        stack.evidence.record("run", "finished_at", datetime.now(UTC).isoformat())
    finally:
        try:
            path = stack.close()
            print(f"\nP8 two-game scenarios evidence: {path}")
        finally:
            if credentials is not None:
                credentials.unlink(missing_ok=True)
    if exits:
        pytest.fail("; ".join(exits))


@pytest.fixture(scope="module")
def live(_p8) -> Live:
    return _p8[0]


@pytest.fixture(scope="module")
def p8_ids(_p8) -> dict[str, Any]:
    return _p8[1]


def _hold(live: Live, ids: dict[str, Any], handle: int, credentials: Path) -> None:
    """Keep the stack serving for the controller's browser pass; logins go to a private file outside the evidence."""
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump({"gateway": live.stack.gateway, "logins": ids["logins"]}, out)
    os.chmod(credentials, 0o600)
    release = live.stack.directory / "release"
    print(f"\nP8 BROWSER HOLD: gateway {live.stack.gateway}")
    print(json.dumps(_ids_only(ids))[:20000])
    print(f"logins (private): {credentials}\ncreate {release} to release the stack", flush=True)
    while not release.exists():  # an operator's hold, not a success condition
        time.sleep(2)


# == seeding (prerequisites only) =====================================================================================


def seed_p8(live: Live) -> dict[str, Any]:
    world = live.stack.run_script(
        "_live_p8_world.py",
        "identity-service",
        "__P8WORLD__",
        stdin={"workspaces": live.world["workspaces"], "owner_auth_user_id": live.world["owner"]["auth_user_id"]},
    )
    password = world["password"]
    users = {label: {k: v for k, v in user.items() if k != "email"} for label, user in world["users"].items()}
    users["org"] = {"auth_user_id": live.world["owner"]["auth_user_id"]}
    users["root"] = {"auth_user_id": live.world["root"]["auth_user_id"]}
    logins = {label: {"email": user["email"], "password": password} for label, user in world["users"].items()}
    logins["org"] = {"email": live.world["owner"]["email"], "password": live.world["owner"]["password"]}
    logins["root"] = {"email": live.world["root"]["email"], "password": live.world["root"]["password"]}
    # Every handle, email, account name and password of the seeded people is redacted from logs and errors.
    _private(
        live,
        *(handle for person in world["handles"].values() for handle in person.values()),
        *(f"p8_{label}_{world['tag'].lower()}" for label in world["users"]),
        *(login[key] for login in logins.values() for key in ("email", "password")),
    )
    ids: dict[str, Any] = {
        "tag": world["tag"],
        "workspaces": {"A": world["workspaces"]["OFF"], "B": world["workspaces"]["ON"], "C": world["workspaces"]["C"]},
        "users": users,
        "logins": logins,
        "handles": world["handles"],
        "roles": {OW: world["ow_roles"], LOL: world["lol_roles"]},
        "dup_players": world["dup_players"],
        "catalog": {},
        "events": {},
        "balanced": {},
        "drafts": {},
        "encounters": {},
        "mixes": {},
        "matches": {},
        "jobs": {},
        "grids": {},
    }
    # A member of A removed through the real route (its observation later must not revive it). A workspace admin never
    # holds ``workspace_member.delete`` (``AuthUser.has_permission``), so the superuser removes it.
    call(
        live,
        ids,
        "root",
        "DELETE",
        "/api/v1/workspaces/{ws}/members/{auth_user_id}",
        expect=(200, 204),
        ws=ids["workspaces"]["A"],
        auth_user_id=users["removed"]["auth_user_id"],
    )
    if SOURCE:
        live.stack.evidence.record("source", "first_sync", _source_sync(live, ids))
    else:
        for name, slug, class_ in CHAMPIONS:
            call(
                live,
                ids,
                "root",
                "POST",
                "/api/v1/admin/catalog/{d}/{kind}",
                {"name": name, "slug": slug, "attrs": {"class": class_}, "active": True, "image_path": None},
                expect=200,
                d=LOL,
                kind="character",
            )
        call(
            live,
            ids,
            "root",
            "POST",
            "/api/v1/admin/catalog/{d}/{kind}",
            {"name": "Summoner's Rift", "slug": RIFT, "attrs": {}, "active": True, "image_path": None},
            expect=200,
            d=LOL,
            kind="map",
        )
    ids["catalog"][LOL] = {
        **{slug: _catalog_id(live, ids, LOL, "character", name, slug) for name, slug, _ in CHAMPIONS},
        RIFT: _catalog_id(live, ids, LOL, "map", "Summoner", RIFT),
    }
    ids["catalog"][OW] = {
        OW_HERO: _catalog_id(live, ids, OW, "character", "Ingest Ana", OW_HERO),
        OW_MAP: _catalog_id(live, ids, OW, "map", "Ingest Ilios", OW_MAP),
    }
    live.stack.evidence.record("scenario_ids", "seed", _ids_only(ids))
    return ids


def _catalog_id(live: Live, ids: dict[str, Any], discipline: str, kind: str, search: str, slug: str) -> int:
    rows = call(
        live,
        ids,
        None,
        "GET",
        "/api/v1/catalog/{d}/{kind}",
        query={"search": search, "per_page": 100},
        expect=200,
        d=discipline,
        kind=kind,
    ).json()["results"]
    row = next((row for row in rows if row["slug"] == slug), None)
    assert row is not None, (discipline, kind, slug, [r["slug"] for r in rows])
    return row["id"]


# == prerequisite helpers (idempotent, cached in ids) ==================================================================


def _rank(game: str, role: str, index: int) -> int:
    return BASE_RANK[game][role] + 7 * index


def _ref(game: str, role: str) -> dict[str, Any]:
    return {"dimension": DIMENSION[game], "role": role, "parent": None}


def _role_row(game: str, role: str, rank: int) -> dict[str, Any]:
    return {
        "role": _ref(game, role),
        "is_primary": True,
        "priority": 0,
        "rank_value": rank,
        "is_active": True,
        "top_characters": None,
    }


def _tournament_body(ids: dict[str, Any], ws: str, game: str, name: str, **extra: Any) -> dict[str, Any]:
    today = date.today()
    return {
        "workspace_id": ids["workspaces"][ws],
        "discipline": game,
        "name": f"P8 {name} {ids['tag']}",
        "start_date": str(today - timedelta(days=1)),
        "end_date": str(today + timedelta(days=30)),
        # The 30 s auto_transition_tournaments job must never move a scenario tournament mid-run.
        "auto_transitions_enabled": False,
        **extra,
    }


def _event(live: Live, ids: dict[str, Any], game: str, purpose: str) -> dict[str, Any]:
    key = f"{game}:{purpose}"
    if key in ids["events"]:
        return ids["events"][key]
    created = call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/tournaments",
        _tournament_body(ids, "A", game, f"{purpose} {game}"),
        expect=201,
    ).json()
    tid = created["id"]
    assert created["discipline"] == game and created["division_grid_version_id"] is not None
    now = datetime.now(UTC)
    call(
        live,
        ids,
        "org",
        "PUT",
        "/api/v1/admin/tournaments/{tid}/schedule",
        {
            "schedule": [
                {
                    "status": "registration",
                    "starts_at": (now - timedelta(days=1)).isoformat(),
                    "ends_at": (now + timedelta(days=14)).isoformat(),
                }
            ]
        },
        expect=200,
        tid=tid,
    )
    call(
        live,
        ids,
        "org",
        "PUT",
        "/api/v1/admin/balancer/tournaments/{tid}/registration-form",
        {"form_schema": FORM, "auto_approve": False},
        expect=200,
        tid=tid,
    )
    form = call(live, ids, None, "GET", "/api/v1/tournaments/{tid}/registration/form", expect=200, tid=tid).json()
    assert form["is_open"] is True and form["discipline"] == game, form
    event = {"tournament_id": tid, "form_version_id": form["version_id"], "registrations": {}, "ranks": {}}
    ids["events"][key] = event
    return event


def _registered(live: Live, ids: dict[str, Any], game: str, purpose: str) -> dict[str, Any]:
    """A tournament in A with the ten registrants of ``game`` (the dual-handle person through the public routes)."""
    event = _event(live, ids, game, purpose)
    if event["registrations"]:
        return event
    tid = event["tournament_id"]
    for index, (label, role) in enumerate(ids["roles"][game].items()):
        rank = _rank(game, role, index)
        if label == "dual":
            body = {
                "form_version_id": event["form_version_id"],
                "answers": {
                    key: [ids["handles"]["dual"][provider]]
                    for provider, key in (
                        (PROVIDER[OW], ANSWER_KEY[OW]),
                        (PROVIDER[LOL], ANSWER_KEY[LOL]),
                    )
                },
            }
            read = call(live, ids, "dual", "POST", "/api/v1/tournaments/{tid}/registration", body, expect=201, tid=tid)
            rid = read.json()["id"]
            # The owner's game names the handle; the other game's handle is never shown here.
            assert read.json()["primary_handle"] == ids["handles"]["dual"][PROVIDER[game]], read.raw[:400]
            call(live, ids, "dual", "PATCH", "/api/v1/tournaments/{tid}/registration/me", body, expect=200, tid=tid)
            call(
                live,
                ids,
                "org",
                "PATCH",
                "/api/v1/admin/balancer/registrations/{rid}",
                {"roles": [_role_row(game, role, rank)]},
                expect=200,
                rid=rid,
            )
            call(live, ids, "org", "PATCH", "/api/v1/admin/balancer/registrations/{rid}/approve", expect=200, rid=rid)
            # ``ready`` is derived from the ranks (never set directly): the organizer adds the row to the pool.
            included = call(
                live, ids, "org", "POST", "/api/v1/admin/balancer/registrations/{rid}/include", expect=200, rid=rid
            ).json()
            assert included["balancer_status"] == "ready", included
        else:
            made = call(
                live,
                ids,
                "org",
                "POST",
                "/api/v1/admin/balancer/tournaments/{tid}/registrations",
                {
                    "auth_user_id": ids["users"][label]["auth_user_id"],
                    "answers": {ANSWER_KEY[game]: [ids["handles"][label][PROVIDER[game]]]},
                    "roles": [_role_row(game, role, rank)],
                },
                expect=201,
                tid=tid,
            ).json()
            rid = made["id"]
            assert made["primary_handle"] == ids["handles"][label][PROVIDER[game]], made
        event["registrations"][label] = rid
        event["ranks"][label] = rank
    return event


def _balanced(live: Live, ids: dict[str, Any], game: str) -> dict[str, Any]:
    if game in ids["balanced"]:
        return ids["balanced"][game]
    event = _registered(live, ids, game, "bal")
    tid = event["tournament_id"]
    job = call(live, ids, "org", "POST", "/api/v1/balancer/tournaments/{tid}/balance", {}, expect=202, tid=tid).json()
    job_id = job["job_id"]

    def finished():
        status = call(live, ids, "org", "GET", "/api/v1/balancer/jobs/{job_id}", expect=200, job_id=job_id).json()
        return status if status["status"] in ("succeeded", "failed") else None

    status = wait_until(finished, f"the {game} balance job", timeout=240, interval=1)
    assert status["status"] == "succeeded", status
    variant = call(live, ids, "org", "GET", "/api/v1/balancer/jobs/{job_id}/result", expect=200, job_id=job_id).json()[
        "variants"
    ][0]
    saved = call(
        live,
        ids,
        "org",
        "PUT",
        "/api/v1/balancer/tournaments/{tid}/balance",
        {"result_json": variant, "config_json": None},
        expect=200,
        tid=tid,
    ).json()
    exported = call(
        live, ids, "org", "POST", "/api/v1/balancer/balances/{bid}/export", expect=200, bid=saved["id"]
    ).json()
    teams = [row[0] for row in live.q("SELECT id FROM tournament.team WHERE tournament_id=%s ORDER BY id", tid)]
    captains: dict[int, str | None] = {}
    captain_set_by_export: dict[int, bool] = {}
    for team_id in teams:
        captain = live.s("SELECT captain_id FROM tournament.team WHERE id=%s", team_id)
        captain_set_by_export[team_id] = captain is not None
        if captain is None:
            # The organizer names a captain through the real team route when the export left none.
            captain = live.s(
                "SELECT u.id FROM tournament.player p JOIN public.workspace_member m ON m.id=p.workspace_member_id "
                "JOIN players.user u ON u.id=m.player_id WHERE p.team_id=%s AND u.auth_user_id IS NOT NULL "
                "ORDER BY p.id LIMIT 1",
                team_id,
            )
            call(live, ids, "org", "PATCH", "/api/v1/admin/teams/{team_id}", {"captain_id": captain}, team_id=team_id)
        captains[team_id] = label_of_player(ids, captain)
    out = {
        "tournament_id": tid,
        "job_id": job_id,
        "balance_id": saved["id"],
        "variant": variant,
        "export": exported,
        "teams": teams,
        "captains": captains,
        "captain_set_by_export": captain_set_by_export,
    }
    ids["balanced"][game] = out
    return out


def _frozen_format(live: Live, custom_game_id: int) -> dict[str, Any]:
    """A mix's frozen team format, exactly: its one format row, every dimension row, every role rule with its bounds."""
    ((format_id, *head),) = live.q(
        "SELECT id, preset_code, name, starter_min, starter_max, substitute_min, substitute_max "
        "FROM roster.team_format WHERE custom_game_id=%s",
        custom_game_id,
    )
    dimensions = live.q(
        "SELECT d.code, f.mode, f.player_min_assignments, f.player_max_assignments FROM roster.team_format_dimension f "
        "JOIN catalog.role_dimension d ON d.id=f.dimension_id WHERE f.team_format_id=%s ORDER BY d.code",
        format_id,
    )
    rules = live.q(
        "SELECT c.code, r.hard_min, r.hard_max, r.recommended_min, r.recommended_max, r.include_descendants "
        "FROM roster.format_role_rule r JOIN catalog.role c ON c.id=r.role_id WHERE r.team_format_id=%s ORDER BY c.code",
        format_id,
    )
    return {"format": head, "dimensions": [list(row) for row in dimensions], "rules": [list(row) for row in rules]}


def _mix_detail(live: Live, ids: dict[str, Any], gid: int) -> dict[str, Any]:
    return call(
        live,
        ids,
        None,
        "GET",
        "/api/v1/balancer/custom-games/{gid}",
        query={"workspace_id": ids["workspaces"]["A"]},
        expect=200,
        gid=gid,
    ).json()


def _slot_role(bucket: str) -> str | None:
    """The role a mix round freezes for a roster bucket (``role_slot_code``); an open (flex) seat freezes none."""
    code = bucket.strip().lower()
    return None if code == "flex" else code


def _b_lol_grid(live: Live, ids: dict[str, Any]) -> int:
    """B's own tiered LoL grid through the grid routes (create, save, publish, activate)."""
    if "B:lol" in ids["grids"]:
        return ids["grids"]["B:lol"]
    ws = ids["workspaces"]["B"]
    grid = call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/division-grids/by-workspace/{ws}",
        {"name": f"P8 B LoL {ids['tag']}", "slug": f"p8-b-lol-{ids['tag'].lower()}", "discipline": LOL},
        expect=201,
        ws=ws,
    ).json()
    saved = call(
        live,
        ids,
        "org",
        "PUT",
        "/api/v1/division-grids/by-workspace/{ws}/grid",
        {"grid_id": grid["id"], "name": f"P8 B LoL {ids['tag']}", "tiers": [TIER]},
        expect=200,
        ws=ws,
    ).json()
    version = saved["saved_version_id"]
    # The save publishes (and activates when ready) already; the explicit routes stay idempotent or say why not.
    call(live, ids, "org", "POST", "/api/v1/division-grids/versions/{vid}/publish", vid=version)
    call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/division-grids/by-workspace/{ws}/versions/{vid}/activate",
        ws=ws,
        vid=version,
    )
    default = live.s(
        "SELECT version_id FROM public.workspace_division_grid_default WHERE workspace_id=%s AND discipline=%s",
        ws,
        LOL,
    )
    assert default == version, (default, version, saved)
    ids["grids"]["B:lol"] = version
    return version


def _b_lol_enabled(live: Live, ids: dict[str, Any]) -> None:
    ws = ids["workspaces"]["B"]
    enabled = live.s("SELECT disciplines_enabled FROM public.workspace WHERE id=%s", ws)
    if LOL not in enabled:
        call(
            live,
            ids,
            "root",
            "PATCH",
            "/api/v1/workspaces/{id}",
            {"disciplines_enabled": [OW, LOL]},
            expect=200,
            id=ws,
        )
    _b_lol_grid(live, ids)


# -- encounters -------------------------------------------------------------------------------------------------------


def _preset(live: Live, ids: dict[str, Any]) -> dict[str, Any]:
    catalog = call(
        live, ids, None, "GET", "/api/v1/pick-ban-rules/catalog", query={"discipline": LOL}, expect=200
    ).json()
    preset = next(row for row in catalog["presets"] if row["id"] == "lol_side_selection")
    assert preset["first_ban_rotation"] == "result_loser_first", preset
    return preset


def _step(step_id: str, *, action: str = "ban", actors: str = "first", timer: int | None = None) -> dict[str, Any]:
    return {
        "id": step_id,
        "action": action,
        "actors": actors,
        "count": 1,
        "min": None,
        "blind": False,
        "target": None,
        "lifetime": 1 if action == "ban" else None,
        "timer_seconds": timer,
        "on_timeout": None,
        "dispute": {"enabled": False, "max": 0},
        "eligible": {},
        "constraints": [],
    }


def _ruleset(*phases: dict[str, Any], timer: int | None = None) -> dict[str, Any]:
    return {"version": 2, "timer_seconds": timer, "on_timeout": "random_fill", "phases": list(phases)}


def _phase(phase_id: str, steps: list[dict[str, Any]], when: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": phase_id, "name": None, "when": when or {}, "pool_filter": {}, "generator": None, "steps": steps}


def _config(ids: dict[str, Any], ruleset: dict[str, Any], rotation: str = "result_loser_first") -> dict[str, Any]:
    return {
        "kind": "hero",
        "mode": "pool",
        "ruleset": ruleset,
        "first_ban_rotation": rotation,
        "item_ids": [ids["catalog"][LOL][slug] for _, slug, _ in CHAMPIONS],
    }


def _encounter(
    live: Live, ids: dict[str, Any], game: str, label: str, *, config: dict[str, Any] | None = None, best_of: int = 3
) -> dict[str, Any]:
    """One stage of the exported teams -> one encounter (the stage-level pick-ban config, if any, saved first)."""
    key = f"{game}:{label}"
    if key in ids["encounters"]:
        return ids["encounters"][key]
    balanced = _balanced(live, ids, game)
    tid = balanced["tournament_id"]
    stage = call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/stages/tournament/{tid}",
        {
            "name": f"P8 {label}",
            "stage_type": "single_elimination",
            "order": len(ids["encounters"]) + 1,
            "max_rounds": 1,
            "best_of": {"default": best_of, "final": best_of, "by_round": {}},
        },
        expect=201,
        tid=tid,
    ).json()
    item = call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/stages/{sid}/items",
        {"name": "Bracket", "type": "single_bracket", "order": 0},
        expect=201,
        sid=stage["id"],
    ).json()
    for slot, team_id in enumerate(balanced["teams"], 1):
        call(
            live,
            ids,
            "org",
            "POST",
            "/api/v1/admin/stages/items/{item_id}/inputs",
            {"slot": slot, "input_type": "final", "team_id": team_id},
            expect=201,
            item_id=item["id"],
        )
    if config is not None:
        call(
            live,
            ids,
            "org",
            "PUT",
            "/api/v1/admin/tournaments/{tid}/pick-ban-configs",
            {**config, "stage_id": stage["id"], "round": None},
            expect=200,
            tid=tid,
        )
    call(live, ids, "org", "POST", "/api/v1/admin/stages/{sid}/activate-and-generate", expect=202, sid=stage["id"])
    eid = wait_until(
        lambda: live.s("SELECT encounter_id FROM tournament.bracket_encounter WHERE stage_id=%s", stage["id"]),
        f"the {label} stage's encounter",
        timeout=120,
    )
    seats = [
        row[0] for row in live.q("SELECT id FROM encounter.team WHERE encounter_id=%s AND active ORDER BY slot", eid)
    ]
    captains = {
        seat: label_of_player(ids, captain)
        for seat, captain in live.q(
            "SELECT et.id, t.captain_id FROM encounter.team et JOIN tournament.team t ON t.id=et.team_id "
            "WHERE et.encounter_id=%s AND et.active",
            eid,
        )
    }
    g1 = wait_until(lambda: _game(live, eid, 1), f"the {label} encounter's game 1 (freeplay healer)", timeout=90)
    out = {"tournament_id": tid, "stage_id": stage["id"], "encounter_id": eid, "seats": seats, "captains": captains}
    out["inputs"] = dict(enumerate(balanced["teams"], 1))  # the stage item inputs, slot -> tournament team
    out["g1"] = g1
    ids["encounters"][key] = out
    scenario_ids(live, **{key: {k: v for k, v in out.items() if k != "captains"}})
    return out


def _game(live: Live, eid: int, position: int) -> int | None:
    return live.s(
        "SELECT id FROM encounter.game WHERE encounter_id=%s AND position=%s AND state <> 'cancelled' ORDER BY id DESC",
        eid,
        position,
    )


def _sides(live: Live, game_id: int) -> dict[int, str | None]:
    return dict(live.q("SELECT encounter_team_id, starting_side FROM encounter.game_team WHERE game_id=%s", game_id))


def _state(live: Live, ids: dict[str, Any], eid: int, who: str | None = None) -> dict[str, Any]:
    return call(
        live, ids, who, "GET", "/api/v1/encounters/{eid}/pick-ban/{kind}/state", expect=200, eid=eid, kind="hero"
    ).json()


def _ready(live: Live, ids: dict[str, Any], enc: dict[str, Any]) -> dict[str, Any]:
    for seat in enc["seats"]:
        call(
            live,
            ids,
            enc["captains"][seat],
            "POST",
            "/api/v1/encounters/{eid}/ready",
            expect=200,
            eid=enc["encounter_id"],
        )
    return wait_until(
        lambda: (state := _state(live, ids, enc["encounter_id"])).get("current_step") and state,
        "the hero room to open",
        timeout=60,
    )


def _acting(live: Live, ids: dict[str, Any], enc: dict[str, Any]) -> int:
    state = _state(live, ids, enc["encounter_id"])
    (seat,) = state["acting_team_ids"]
    return seat


def _seeded(live: Live, enc: dict[str, Any]) -> int:
    """The G1 opener the stage inputs decide: the seat of the slot-1 input's team (``resolve_seeds``, bracket slot)."""
    expected = live.s(
        "SELECT id FROM encounter.team WHERE encounter_id=%s AND team_id=%s AND active",
        enc["encounter_id"],
        enc["inputs"][1],
    )
    session = live.q(
        "SELECT first_team_id, seed_source FROM encounter.pick_ban_session WHERE encounter_id=%s AND kind='hero'",
        enc["encounter_id"],
    )
    assert [(first, str(source)) for first, source in session] == [(expected, "bracket_slot")], (session, expected)
    invariant(live, f"opener_{enc['encounter_id']}", {"first_team_id": expected, "seed_source": "bracket_slot"})
    return expected


def _drafts(state: dict[str, Any]) -> list[tuple]:
    """The room's visible submissions: (seat, state, items)."""
    return [(row["encounter_team_id"], row["state"], row["items"]) for row in state["submissions"]]


def _draft_rows(live: Live, eid: int, step_index: int) -> list[tuple]:
    """The hero room's live (non-voided) submission rows of one step: (seat, state, items_json)."""
    return live.q(
        "SELECT s.encounter_team_id, s.state, s.items_json FROM encounter.pick_ban_submission s "
        "JOIN encounter.pick_ban_session p ON p.id=s.session_id "
        "WHERE p.encounter_id=%s AND p.kind='hero' AND s.step_index=%s AND s.state <> 'voided'",
        eid,
        step_index,
    )


def _other(enc: dict[str, Any], seat: int) -> int:
    return next(other for other in enc["seats"] if other != seat)


def _side_pick(live: Live, ids: dict[str, Any], enc: dict[str, Any], seat: int, index: int, **kw: Any) -> Response:
    return call(
        live,
        ids,
        enc["captains"][seat],
        "POST",
        "/api/v1/encounters/{eid}/pick-ban/{kind}/act",
        {"item_id": index, "action": "side_pick", "target_player_id": None},
        eid=enc["encounter_id"],
        kind="hero",
        **kw,
    )


def _lines(enc: dict[str, Any], winner: int) -> list[dict[str, Any]]:
    return [
        {"encounter_team_id": seat, "score": 1 if seat == winner else 0, "placement": None, "column_values": {}}
        for seat in enc["seats"]
    ]


def _admin_result(live: Live, ids: dict[str, Any], enc: dict[str, Any], game_id: int, winner: int, **kw) -> Response:
    return call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/encounters/{eid}/games/{gid}/result",
        {"reason": "P8 live scenario", "results": _lines(enc, winner)},
        eid=enc["encounter_id"],
        gid=game_id,
        **kw,
    )


def _claim(live: Live, ids: dict[str, Any], enc: dict[str, Any], seat: int, game_id: int, winner: int) -> Response:
    version = live.s("SELECT result_version FROM encounter.game WHERE id=%s", game_id)
    return call(
        live,
        ids,
        enc["captains"][seat],
        "POST",
        "/api/v1/encounters/{eid}/games/{gid}/report",
        {"basis_version": version, "results": _lines(enc, winner)},
        eid=enc["encounter_id"],
        gid=game_id,
    )


def _undo(live: Live, ids: dict[str, Any], enc: dict[str, Any], seat: int, **kw: Any) -> Response:
    return call(
        live,
        ids,
        enc["captains"][seat],
        "POST",
        "/api/v1/encounters/{eid}/pick-ban/{kind}/undo",
        {"consent": True},
        eid=enc["encounter_id"],
        kind="hero",
        **kw,
    )


def _played(live: Live, ids: dict[str, Any], enc: dict[str, Any], game_id: int, winner: int) -> None:
    """The game is played on its map and both captains report the same result: confirmed by their agreement."""
    _on_map(live, ids, enc, LOL, game_id)
    for seat in enc["seats"]:
        claim = _claim(live, ids, enc, seat, game_id, winner)
        assert claim.status == 200, claim.raw[:400]
    wait_until(lambda: live.game(game_id)["state"] == "confirmed", f"game {game_id} confirmed by matching claims")
    assert live.game(game_id)["result_source"] == "captain_agreement", live.game(game_id)


def _history(live: Live, game_ids: list[int]) -> dict[int, dict[str, list]]:
    """What recovery (b) keeps on each retired game: its result, every seat's line and side, every claim line."""
    return {
        game_id: {
            "game": live.q(
                "SELECT position, map_id, result_source, result_version, confirmed_at FROM encounter.game WHERE id=%s",
                game_id,
            ),
            "lines": live.q(
                "SELECT encounter_team_id, score, placement, column_values, starting_side FROM encounter.game_team "
                "WHERE game_id=%s ORDER BY encounter_team_id",
                game_id,
            ),
            "claims": live.q(
                "SELECT c.claimant_team_id, c.basis_version, r.encounter_team_id, r.score, r.placement "
                "FROM encounter.game_claim c JOIN encounter.game_claim_result r ON r.claim_id=c.id "
                "WHERE c.game_id=%s ORDER BY c.claimant_team_id, r.encounter_team_id",
                game_id,
            ),
        }
        for game_id in game_ids
    }


def _result(live: Live, game_id: int) -> dict[str, Any]:
    """A game's durable official result: state, version, source and each seat's (score, placement, side)."""
    state, version, source = live.q(
        "SELECT state, result_version, result_source FROM encounter.game WHERE id=%s", game_id
    )[0]
    lines = live.q(
        "SELECT encounter_team_id, score, placement, starting_side FROM encounter.game_team WHERE game_id=%s "
        "ORDER BY encounter_team_id",
        game_id,
    )
    return {"state": state, "result_version": version, "result_source": source, "lines": [tuple(r) for r in lines]}


def _frozen(live: Live, eid: int) -> dict[str, Any]:
    """Every durable trace a refused correction must not leave.

    Read once the background follow-ups of the previous write (a confirmed series' computation job, its
    ``achievement_evaluate``/``cache_invalidated`` outbox rows) have stopped arriving: the outbox count is global.
    """
    seen: list[tuple] = []

    def quiet() -> bool:
        seen.append(
            (
                live.s("SELECT count(*) FROM public.event_outbox"),
                live.s("SELECT count(*) FROM tournament.computation_job WHERE status NOT IN ('succeeded', 'failed')"),
            )
        )
        return len(seen) > 1 and seen[-1] == seen[-2] and seen[-1][1] == 0

    wait_until(quiet, "the outbox and computation jobs to settle", timeout=60, interval=2)
    return {
        "lines": live.q(
            "SELECT g.id, g.state, g.result_version, gt.encounter_team_id, gt.score, gt.starting_side "
            "FROM encounter.game g JOIN encounter.game_team gt ON gt.game_id=g.id WHERE g.encounter_id=%s "
            "ORDER BY g.id, gt.encounter_team_id",
            eid,
        ),
        "submissions": live.s(
            "SELECT count(*) FROM encounter.pick_ban_submission s JOIN encounter.pick_ban_session p "
            "ON p.id=s.session_id WHERE p.encounter_id=%s",
            eid,
        ),
        "journal": live.s("SELECT count(*) FROM encounter.room_event WHERE encounter_id=%s", eid),
        "audit": live.s("SELECT count(*) FROM public.audit_log WHERE action='encounter.game_result'"),
        "outbox": live.s("SELECT count(*) FROM public.event_outbox"),
    }


def _round_opened(live: Live, eid: int) -> int:
    return live.s("SELECT count(*) FROM encounter.room_event WHERE encounter_id=%s AND action='round_opened'", eid)


def _wait_round(live: Live, ids: dict[str, Any], enc: dict[str, Any], number: int) -> dict[str, Any]:
    return wait_until(
        lambda: (state := _state(live, ids, enc["encounter_id"])).get("current_round") == number
        and state.get("acting_team_ids")
        and state,
        f"hero round {number} of encounter {enc['encounter_id']}",
        timeout=60,
    )


# -- documents --------------------------------------------------------------------------------------------------------


def _roster(live: Live, ids: dict[str, Any], enc: dict[str, Any]) -> dict[int, list[str]]:
    """Each seat's exported tournament roster (``tournament.player`` of the seat's team).

    Stage generation snapshots the same roster as the seat's line-up (``encounter.team_member``), which is what binds a
    document to the game by its participants' identities.
    """
    by_member = labels_by_member(live, ids)
    out: dict[int, list[str]] = {seat: [] for seat in enc["seats"]}
    for seat, member in live.q(
        "SELECT et.id, p.workspace_member_id FROM encounter.team et JOIN tournament.player p "
        "ON p.team_id=et.team_id AND p.tournament_id=et.tournament_id WHERE et.encounter_id=%s AND et.active",
        enc["encounter_id"],
    ):
        out[seat].append(by_member[member])
    return out


def _lol_doc(
    live: Live, ids: dict[str, Any], enc: dict[str, Any], external_id: str, *, value: int = 7, hint: int | None = None
) -> dict[str, Any]:
    """The contracts §6.4 document over the encounter's real registered Riot handles (alpha = slot 1)."""
    roster = _roster(live, ids, enc)
    roles = ids["roles"][LOL]
    participants = []
    for team, seat in (("alpha", enc["seats"][0]), ("beta", enc["seats"][1])):
        for label in sorted(roster[seat], key=lambda label: POSITIONS.index(roles[label])):
            participants.append(
                {
                    "key": f"p{len(participants) + 1}",
                    "team": team,
                    "identity": {"provider": PROVIDER[LOL], "id": ids["handles"][label][PROVIDER[LOL]]},
                    "role": {"dimension": DIMENSION[LOL], "role": roles[label]},
                }
            )
    doc: dict[str, Any] = {
        "protocol": "owt.match/1",
        "discipline": LOL,
        "source": {"kind": "external", "external_id": external_id},
        "played_at": "2026-10-15T12:00:00Z",
        "duration_s": 1834,
        "map": RIFT,
        "teams": [{"key": "alpha", "placement": 1}, {"key": "beta", "placement": 2}],
        "participants": participants,
        "segments": [],
        "facts": [
            {"participant": "p3", "entity": "ahri", "stat": "kills", "value": value},
            {"team": "alpha", "stat": "dragons", "value": 3},
        ],
        "events": [{"t": 312.4, "type": "kill", "actor": "p3", "target": "p8", "entity": "ahri"}],
    }
    if hint is not None:
        doc["hint"] = {"encounter_game_id": hint}
    return doc


def _ow_doc(
    live: Live, ids: dict[str, Any], enc: dict[str, Any], external_id: str, *, value: int = 3, hint: int | None = None
) -> dict[str, Any]:
    roster = _roster(live, ids, enc)
    roles = ids["roles"][OW]
    participants = []
    for team, seat in (("t1", enc["seats"][0]), ("t2", enc["seats"][1])):
        for label in sorted(roster[seat]):
            participants.append(
                {
                    "key": f"p{len(participants) + 1}",
                    "team": team,
                    "identity": {"provider": PROVIDER[OW], "id": ids["handles"][label][PROVIDER[OW]]},
                    "role": {"dimension": DIMENSION[OW], "role": roles[label]},
                }
            )
    doc: dict[str, Any] = {
        "protocol": "owt.match/1",
        "discipline": OW,
        "source": {"kind": "external", "external_id": external_id},
        "played_at": "2026-10-15T12:00:00Z",
        "duration_s": 600,
        "map": OW_MAP,
        "teams": [{"key": "t1", "placement": 1}, {"key": "t2", "placement": 2}],
        "participants": participants,
        "segments": [{"index": 1, "kind": "round", "attrs": {}}],
        "facts": [{"team": "t1", "stat": "score", "value": 2}, {"team": "t2", "stat": "score", "value": 1}]
        + [
            {"participant": p["key"], "stat": "eliminations", "value": value + i, "entity": OW_HERO}
            for i, p in enumerate(participants)
        ],
        "events": [{"t": 10, "type": "kill", "actor": "p1", "target": "p6", "entity": OW_HERO, "segment": 1}],
    }
    if hint is not None:
        doc["hint"] = {"encounter_game_id": hint}
    return doc


DOCS = {LOL: _lol_doc, OW: _ow_doc}
#: The varied value of each game's document (LoL: Ahri's kills; OW: p1's eliminations): first submission, correction.
CORRECTION = {LOL: (7, 8), OW: (3, 9)}


def _expected_read(live: Live, ids: dict[str, Any], enc: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """The native read a bound ``doc`` must produce: every fact/event at its grain and owners, segments, positions."""
    game = doc["discipline"]
    seat = {team["key"]: enc["seats"][index] for index, team in enumerate(doc["teams"])}
    owner = {ids["handles"][label][PROVIDER[game]]: label for label in ids["roles"][game]}
    label = {p["key"]: owner[p["identity"]["id"]] for p in doc["participants"]}
    member = {key: member_of(live, ids, who) for key, who in label.items()}
    team = {p["key"]: seat[p["team"]] for p in doc["participants"]}
    entity = {None: None, **ids["catalog"][game]}
    return {
        "participants": [
            {
                "encounter_team_id": seat[t["key"]],
                "source_position": position,
                "team_facts": {
                    f["stat"]: f["value"]
                    for f in doc["facts"]
                    if f.get("team") == t["key"] and not f.get("segment") and f.get("entity") is None
                },
            }
            for position, t in enumerate(doc["teams"], 1)
        ],
        "members": Counter(
            (
                team[p["key"]],
                member[p["key"]],
                ids["users"][label[p["key"]]]["player_id"],
                p["identity"]["id"],
                (p["role"]["dimension"], p["role"]["role"], None),
            )
            for p in doc["participants"]
        ),
        "segments": [{"segment": s["index"], "kind": s["kind"], "attrs": s["attrs"]} for s in doc["segments"]],
        "facts": Counter(
            (
                team[f["participant"]] if "participant" in f else seat[f["team"]],
                member.get(f.get("participant")),
                entity[f.get("entity")],
                f.get("segment", 0),
                f["stat"],
                f["value"],
            )
            for f in doc["facts"]
        ),
        "events": Counter(
            (
                e.get("segment", 0),
                e["t"],
                e["type"],
                member[e["actor"]],
                team[e["actor"]],
                member[e["target"]],
                team[e["target"]],
                entity[e.get("entity")],
            )
            for e in doc["events"]
        ),
    }


def _read_projection(read: dict[str, Any], feed: dict[str, Any]) -> dict[str, Any]:
    stats = read["statistics"]
    return {
        "participants": sorted(
            (
                {key: p[key] for key in ("encounter_team_id", "source_position", "team_facts")}
                for p in read["participants"]
            ),
            key=lambda p: p["encounter_team_id"],
        ),
        "members": Counter(
            (
                m["encounter_team_id"],
                m["workspace_member_id"],
                m["player_id"],
                m["handle_snapshot"],
                tuple((m["observed_role"] or {}).get(key) for key in ("dimension", "role", "parent")),
            )
            for m in stats["members"]
        ),
        "segments": sorted(stats["segments"], key=lambda s: s["segment"]),
        "facts": Counter(
            (f["encounter_team_id"], f["workspace_member_id"], f["entity_id"], f["segment"], f["stat_code"], f["value"])
            for f in stats["facts"]
        ),
        "events": Counter(
            (
                e["segment"],
                e["t"],
                e["type"],
                e["actor_member_id"],
                e["actor_team_id"],
                e["target_member_id"],
                e["target_team_id"],
                e["entity_id"],
            )
            for e in feed["events"]
        ),
    }


def _assert_read(live: Live, ids: dict[str, Any], enc: dict[str, Any], match_id: int, doc: dict[str, Any]) -> dict:
    """``GET /matches/{id}`` + ``/kill-feed`` equal ``doc`` exactly (bounded: reads ride a 30 s TTL, no invalidation)."""
    expected = _expected_read(live, ids, enc, doc)
    expected["participants"].sort(key=lambda p: p["encounter_team_id"])
    deadline = time.monotonic() + 45
    while True:
        read = call(live, ids, None, "GET", "/api/v1/matches/{id}", expect=200, id=match_id).json()
        feed = call(live, ids, None, "GET", "/api/v1/matches/{id}/kill-feed", expect=200, id=match_id).json()
        actual = _read_projection(read, feed)
        if actual == expected or time.monotonic() > deadline:
            break
        time.sleep(3)  # a bounded re-read past the cache TTL, never a success condition
    assert (read["discipline"], read["encounter_game_id"]) == (doc["discipline"], enc["g1"]), read
    assert actual == expected, (expected, actual)
    live.stack.evidence.record(
        "source_positions",
        f"match_{match_id}:{doc['source']['external_id']}",
        [(p["encounter_team_id"], p["source_position"]) for p in actual["participants"]],
    )
    return read


def _observed(live: Live, game_id: int) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        engine, factory = async_session_factory(live.stack.db_url)
        try:
            return await observe(SimpleNamespace(sf=factory, game=game_id))
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _multipart(fields: dict[str, str], filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[]"; filename="{filename}"\r\n'
        "Content-Type: text/csv\r\n\r\n".encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _settled(live: Live, label: str, job_id: int) -> dict[str, Any]:
    job, seen = live.settle(label, job_id, timeout=120)
    ids_seen = live.stack.evidence.data["job_ids"]
    ids_seen[f"{_SCENARIO[0]}:{job_id}"] = seen
    return job


def _on_map(live: Live, ids: dict[str, Any], enc: dict[str, Any], game: str, game_id: int) -> None:
    """The captain records the document's map (a hinted log binds only to a game on its map, P5 ``find_binding``)."""
    if live.s("SELECT map_id FROM encounter.game WHERE id=%s", game_id) is None:
        call(
            live,
            ids,
            enc["captains"][enc["seats"][0]],
            "POST",
            "/api/v1/encounters/{eid}/games/{gid}/map",
            {"map_id": ids["catalog"][game][RIFT if game == LOL else OW_MAP]},
            expect=200,
            eid=enc["encounter_id"],
            gid=game_id,
        )


def _bound(live: Live, job_id: int, game_id: int) -> dict:
    """The settled job of a document hinted at ``game_id``: the seat line-ups prove the binding, no operator needed."""
    job = _settled(live, "off_ok", job_id)
    assert job["status"] == "done" and job["binding"]["encounter_game_id"] == game_id, job
    return job


def _bind(
    live: Live, ids: dict[str, Any], job_id: int, game_id: int, teams: dict[str, int], revision: int, **kw: Any
) -> Response:
    """The organizer's admin bind of an ``awaiting_link`` job: one game, the full team map, the observed revision."""
    body = {"encounter_game_id": game_id, "teams": teams, "expected_revision": revision}
    return call(live, ids, "org", "POST", "/api/v1/admin/logs/{job_id}/bind", body, job_id=job_id, **kw)


# == scenarios (contracts §6.3, in file order) =========================================================================


def tournament_registration(live: Live, ids: dict[str, Any]) -> None:
    a, b, c = (ids["workspaces"][key] for key in ("A", "B", "C"))
    tournaments = live.s("SELECT count(*) FROM tournament.tournament")
    # A game the workspace has not enabled is refused before any write.
    refused(
        call(live, ids, "org", "POST", "/api/v1/admin/tournaments", _tournament_body(ids, "C", LOL, "lol in C")),
        422,
        contains="discipline_not_enabled",
    )
    # B: the organiser enables LoL themselves -- ``workspace.update`` is the whole gate.
    if LOL not in live.s("SELECT disciplines_enabled FROM public.workspace WHERE id=%s", b):
        call(live, ids, "org", "PATCH", "/api/v1/workspaces/{id}", {"disciplines_enabled": [OW, LOL]}, expect=200, id=b)
    assert LOL in invariant(
        live, "B_enabled", live.s("SELECT disciplines_enabled FROM public.workspace WHERE id=%s", b)
    )
    assert live.s("SELECT count(*) FROM tournament.tournament") == tournaments
    version = _b_lol_grid(live, ids)
    created = call(
        live, ids, "org", "POST", "/api/v1/admin/tournaments", _tournament_body(ids, "B", LOL, "lol in B"), expect=201
    ).json()
    assert created["division_grid_version_id"] == version and created["discipline"] == LOL
    # A foreign workspace's grid and another game's grid are refused before any write.
    before = live.s("SELECT count(*) FROM tournament.tournament")
    refused(
        call(
            live,
            ids,
            "org",
            "POST",
            "/api/v1/admin/tournaments",
            _tournament_body(ids, "A", LOL, "foreign grid", division_grid_version_id=version),
        ),
        400,
        contains="does not belong",
    )
    refused(
        call(
            live,
            ids,
            "org",
            "POST",
            "/api/v1/admin/tournaments",
            _tournament_body(ids, "A", LOL, "ow grid", division_grid_version_id=live.grids["OFF"]["default"][OW]),
        ),
        422,
        contains="division_grid_discipline_mismatch",
    )
    assert live.s("SELECT count(*) FROM tournament.tournament") == before
    # The owner's game is immutable: an update naming another game leaves it.
    call(
        live,
        ids,
        "org",
        "PATCH",
        "/api/v1/admin/tournaments/{tid}",
        {"discipline": OW, "description": "P8 discipline is the owner's"},
        tid=created["id"],
    )
    assert live.s("SELECT discipline FROM tournament.tournament WHERE id=%s", created["id"]) == LOL
    scenario_ids(live, b_lol_tournament=created["id"], b_lol_grid_version=version)

    for game in GAMES:
        event = _registered(live, ids, game, "bal")
        tid = event["tournament_id"]
        mine = call(live, ids, "dual", "GET", "/api/v1/tournaments/{tid}/registration/me", expect=200, tid=tid).json()
        assert mine["primary_handle"] == ids["handles"]["dual"][PROVIDER[game]], mine
        rows = call(
            live, ids, "org", "GET", "/api/v1/admin/balancer/tournaments/{tid}/registrations", expect=200, tid=tid
        ).json()
        by_id = {row["id"]: row for row in rows}
        assert set(by_id) == set(event["registrations"].values())
        for label, rid in event["registrations"].items():
            row = by_id[rid]
            assert [r["role"]["dimension"] for r in row["roles"] if r["is_active"]] == [DIMENSION[game]], row["roles"]
            assert [r["rank_value"] for r in row["roles"] if r["is_active"]] == [event["ranks"][label]], row["roles"]
            assert row["primary_handle"] == ids["handles"][label][PROVIDER[game]]
        call(live, ids, None, "GET", "/api/v1/tournaments/{tid}/registration/list", expect=200, tid=tid)
        team_format = call(
            live, ids, "org", "GET", "/api/v1/admin/tournaments/{tid}/team-format", expect=200, tid=tid
        ).json()
        assert team_format["preset_code"] == PRESET[game], team_format
        invariant(live, f"{game}_registrations", len(rows))

    lol_event = ids["events"][f"{LOL}:bal"]
    count = live.s("SELECT count(*) FROM registration.registration WHERE tournament_id=%s", lol_event["tournament_id"])
    # A child role of B's (a real B sub-role of ``top``) is not A's to use.
    child = call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/player-sub-roles",
        {
            "workspace_id": b,
            "discipline": LOL,
            "role": "top",
            "label": "P8 B child",
            "slug": f"p8_b_{ids['tag'].lower()}",
        },
        expect=201,
    ).json()
    child_code = live.s("SELECT code FROM catalog.role WHERE id=%s AND workspace_id=%s", child["id"], b)
    # One role row of an otherwise valid manual registration changes: another game's role, B's child role. Both are
    # refused before any write, with the stable ``<family>:`` prefix of the role resolver.
    base = {
        "auth_user_id": ids["users"]["target_u"]["auth_user_id"],
        "answers": {ANSWER_KEY[LOL]: [ids["handles"]["target_u"][PROVIDER[LOL]]]},
    }
    foreign_child = {
        **_role_row(LOL, "top", 2000),
        "role": {"dimension": DIMENSION[LOL], "role": child_code, "parent": None},
    }
    for request, role, family in (
        ("another game's role", _role_row(OW, "tank", 2000), "role_dimension_mismatch"),
        ("another workspace's child role", foreign_child, "unknown_role"),
    ):
        response = call(
            live,
            ids,
            "org",
            "POST",
            "/api/v1/admin/balancer/tournaments/{tid}/registrations",
            {**base, "roles": [role]},
            tid=lol_event["tournament_id"],
        )
        refused(response, 422, contains=f"{family}:")
        live.stack.evidence.append(
            "unsupported_requests",
            {"scenario": _SCENARIO[0], "request": request, "status": 422, "code": code_of(response), "family": family},
        )
    assert (
        live.s("SELECT count(*) FROM registration.registration WHERE tournament_id=%s", lol_event["tournament_id"])
        == count
    )
    # A malformed Riot ID is refused at its field; nothing is written.
    malformed = call(
        live,
        ids,
        "target_u",
        "POST",
        "/api/v1/tournaments/{tid}/registration",
        {"form_version_id": lol_event["form_version_id"], "answers": {ANSWER_KEY[LOL]: ["P8 no tag line"]}},
        tid=lol_event["tournament_id"],
    )
    refused(malformed, 422, code="invalid_format")
    assert (
        live.s("SELECT count(*) FROM registration.registration WHERE tournament_id=%s", lol_event["tournament_id"])
        == count
    )
    live.stack.evidence.append(
        "unsupported_requests", {"scenario": _SCENARIO[0], "request": "malformed riot", "code": code_of(malformed)}
    )


def identity_journeys(live: Live, ids: dict[str, Any]) -> None:
    for game in GAMES:
        _registered(live, ids, game, "bal")
    a, c = ids["workspaces"]["A"], ids["workspaces"]["C"]
    route = "/api/v1/balancer/workspaces/{ws}/players"

    def upsert(who: str, body: dict[str, Any], ws: int = a) -> Response:
        return call(live, ids, who, "POST", route, body, ws=ws)

    def counts() -> tuple:
        return (
            live.s("SELECT count(*) FROM players.social_account"),
            live.s("SELECT count(*) FROM players.user"),
            live.s("SELECT count(*) FROM public.workspace_member"),
            live.s("SELECT count(*) FROM auth.user_roles"),
        )

    typed, off_game = f"Typed Host {ids['tag']}#EUW", f"Off Game {ids['tag']}#EUW"
    _private(live, typed, off_game)  # before the first request: a failing refusal publishes its response
    before = counts()
    mismatch = upsert("host", {"discipline": LOL, "identity": {"provider": PROVIDER[OW], "handle": "Mismatch#1234"}})
    refused(mismatch, 422, code="identity.provider_mismatch")
    assert mismatch.json()["fields"][0]["field"] == "identity.provider"
    malformed = upsert("host", {"discipline": LOL, "identity": {"provider": PROVIDER[LOL], "handle": "no tag here"}})
    refused(malformed, 422, code="identity.riot.format")
    assert malformed.json()["fields"][0]["field"] == "identity.handle"
    owners = upsert(
        "host",
        {"discipline": LOL, "identity": {"provider": PROVIDER[LOL], "handle": ids["handles"]["dup"][PROVIDER[LOL]]}},
    )
    refused(owners, 409, code="identity_conflict")
    disabled = upsert(
        "host",
        {"discipline": LOL, "identity": {"provider": PROVIDER[LOL], "handle": off_game}},
        ws=c,
    )
    refused(disabled, 422, contains="discipline_not_enabled")
    old_wire = upsert("host", {"discipline": OW, "battle_tag": "Old#1234"})
    assert old_wire.status == 422, old_wire.raw[:300]
    assert counts() == before, (before, counts())

    added = upsert("host", {"discipline": LOL, "identity": {"provider": PROVIDER[LOL], "handle": typed}})
    assert added.status == 200, added.raw[:400]
    assert added.json()["identity"] == {"provider": PROVIDER[LOL], "handle": typed}
    assert added.json()["auth_user_id"] is None
    verified, subject, linked = live.q(
        "SELECT s.is_verified, s.provider_user_id, u.auth_user_id FROM players.social_account s "
        "JOIN players.user u ON u.id=s.user_id WHERE s.provider=%s AND s.username=%s",
        PROVIDER[LOL],
        typed,
    )[0]
    assert (verified, subject, linked) == (False, None, None)
    renamed = upsert(
        "host", {"discipline": LOL, "identity": {"provider": PROVIDER[LOL], "handle": typed}, "display_name": "Renamed"}
    )
    refused(renamed, 403, code="forbidden")

    # Registration never moves an owned handle: the joiner typing an account holder's Riot ID (target U's) or an
    # unlinked roster player's (the host's typed one) is refused at that answer; nobody's ownership, auth link,
    # verification, visibility, roles or membership moves.
    lol_event = ids["events"][f"{LOL}:bal"]
    people = [ids["users"]["joiner"]["player_id"], ids["users"]["target_u"]["player_id"], added.json()["player_id"]]
    accounts = [ids["users"]["joiner"]["auth_user_id"], ids["users"]["target_u"]["auth_user_id"]]

    def ownership() -> dict[str, Any]:
        return {
            "social": live.q(
                "SELECT id, user_id, provider, username, username_normalized, is_verified, provider_user_id, is_primary "
                "FROM players.social_account WHERE user_id = ANY(%s) ORDER BY id",
                people,
            ),
            "visibility": live.q(
                "SELECT v.account_id, v.workspace_id FROM players.social_account_visibility v "
                "JOIN players.social_account s ON s.id=v.account_id WHERE s.user_id = ANY(%s) ORDER BY 1, 2",
                people,
            ),
            "users": live.q("SELECT id, auth_user_id, name FROM players.user WHERE id = ANY(%s) ORDER BY id", people),
            "members": live.q(
                "SELECT id, workspace_id, player_id, removed_at, observed_only FROM public.workspace_member "
                "WHERE player_id = ANY(%s) ORDER BY id",
                people,
            ),
            "roles": live.q(
                "SELECT user_id, role_id FROM auth.user_roles WHERE user_id = ANY(%s) ORDER BY 1, 2", accounts
            ),
            "registrations": live.s(
                "SELECT count(*) FROM registration.registration WHERE tournament_id=%s", lol_event["tournament_id"]
            ),
        }

    owned = ownership()
    for request, handle in (
        ("account holder's handle", ids["handles"]["target_u"][PROVIDER[LOL]]),
        ("roster player's handle", typed),
    ):
        conflict = call(
            live,
            ids,
            "joiner",
            "POST",
            "/api/v1/tournaments/{tid}/registration",
            {"form_version_id": lol_event["form_version_id"], "answers": {ANSWER_KEY[LOL]: [handle]}},
            tid=lol_event["tournament_id"],
        )
        refused(conflict, 409, code="game_identity_conflict")
        assert conflict.json()["fields"][0]["field"] == ANSWER_KEY[LOL], conflict.raw[:400]
        assert (now := ownership()) == owned, (request, owned, now)
        live.stack.evidence.append(
            "unsupported_requests",
            {
                "scenario": _SCENARIO[0],
                "request": f"registration typing another {request}",
                "status": 409,
                "code": "game_identity_conflict",
            },
        )

    # The same text under two providers stays two people.
    twin_bn = upsert(
        "org",
        {"discipline": OW, "identity": {"provider": PROVIDER[OW], "handle": ids["handles"]["twin_bn"][PROVIDER[OW]]}},
    )
    twin_riot = upsert(
        "org",
        {
            "discipline": LOL,
            "identity": {"provider": PROVIDER[LOL], "handle": ids["handles"]["twin_riot"][PROVIDER[LOL]]},
        },
    )
    assert twin_bn.status == twin_riot.status == 200, (twin_bn.raw[:300], twin_riot.raw[:300])
    assert twin_bn.json()["player_id"] == ids["users"]["twin_bn"]["player_id"]
    assert twin_riot.json()["player_id"] == ids["users"]["twin_riot"]["player_id"]
    assert twin_bn.json()["player_id"] != twin_riot.json()["player_id"]
    # The dual-handle person's roster row names the owner game's handle.
    dual_member = member_of(live, ids, "dual")
    for game in GAMES:
        row, page = None, 1
        while row is None:  # the roster list caps ``per_page`` at 100
            rows = call(
                live,
                ids,
                "org",
                "GET",
                route,
                query={"discipline": game, "per_page": 100, "page": page},
                expect=200,
                ws=a,
            ).json()
            row = next((row for row in rows["results"] if row["member_id"] == dual_member), None)
            assert row is not None or page * rows["per_page"] < rows["total"], (dual_member, rows["total"])
            page += 1
        assert row["identity"] == {"provider": PROVIDER[game], "handle": ids["handles"]["dual"][PROVIDER[game]]}, row

    # R5: a mix host cannot admit an account holder; the target's private read stays refused before and after.
    target = ids["users"]["target_u"]
    members = "/api/v1/workspaces/{ws}/members"
    refused(call(live, ids, "target_u", "GET", members, ws=a), 403)
    host_add = upsert(
        "host",
        {
            "discipline": LOL,
            "identity": {"provider": PROVIDER[LOL], "handle": ids["handles"]["target_u"][PROVIDER[LOL]]},
        },
    )
    refused(host_add, 403, code="forbidden")
    assert host_add.json()["fields"][0]["field"] == "identity.handle"
    token(live, ids, "target_u", fresh=True)
    refused(call(live, ids, "target_u", "GET", members, ws=a), 403)
    assert (
        live.s(
            "SELECT count(*) FROM public.workspace_member WHERE workspace_id=%s AND player_id=%s",
            a,
            target["player_id"],
        )
        == 0
    )
    assert (
        live.s(
            "SELECT count(*) FROM auth.user_roles ur JOIN auth.roles r ON r.id=ur.role_id WHERE ur.user_id=%s AND r.workspace_id=%s",
            target["auth_user_id"],
            a,
        )
        == 0
    )
    admitted = upsert(
        "org",
        {
            "discipline": LOL,
            "identity": {"provider": PROVIDER[LOL], "handle": ids["handles"]["target_u"][PROVIDER[LOL]]},
        },
    )
    assert admitted.status == 200, admitted.raw[:300]
    assert member_of(live, ids, "target_u") == admitted.json()["member_id"]
    roles = {
        row[0]
        for row in live.q(
            "SELECT r.name FROM auth.user_roles ur JOIN auth.roles r ON r.id=ur.role_id WHERE ur.user_id=%s AND r.workspace_id=%s",
            target["auth_user_id"],
            a,
        )
    }
    assert "player" in invariant(live, "target_roles_after_admission", sorted(roles)), roles

    # An observation of a foreign (B) member and of a removed A member grants neither of them access.
    for label in ("b_member", "removed"):
        refused(call(live, ids, label, "GET", members, ws=a), 403)
    case = live.cases["lol"]
    doc = with_unknown_identities(document(case, f"p8-observe-{ids['tag']}"))
    doc["participants"][0]["identity"]["id"] = ids["handles"]["b_member"][PROVIDER[LOL]]
    doc["participants"][1]["identity"]["id"] = ids["handles"]["removed"][PROVIDER[LOL]]
    response = ingest(live, "off_ok", doc)
    assert response.status in (200, 202), response.raw[:400]
    job_id = response.json()["id"]
    job = _settled(live, "off_ok", job_id)
    assert job["status"] == "awaiting_link", job
    observation = call(
        live, ids, "org", "GET", "/api/v1/admin/logs/games/{gid}/observation", expect=200, gid=case.game_id
    ).json()
    teams = {team["key"]: seat for team, seat in zip(doc["teams"], case.team_ids, strict=True)}
    call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/logs/{job_id}/bind",
        {"encounter_game_id": case.game_id, "teams": teams, "expected_revision": observation["revision"]},
        expect=200,
        job_id=job_id,
    )
    for label in ("b_member", "removed"):
        token(live, ids, label, fresh=True)
        refused(call(live, ids, label, "GET", members, ws=a), 403)
    removed = live.q(
        "SELECT removed_at IS NOT NULL, observed_only FROM public.workspace_member WHERE workspace_id=%s AND player_id=%s",
        a,
        ids["users"]["removed"]["player_id"],
    )
    assert removed and removed[0][0] is True, removed
    foreign = live.q(
        "SELECT observed_only FROM public.workspace_member WHERE workspace_id=%s AND player_id=%s",
        a,
        ids["users"]["b_member"]["player_id"],
    )
    assert all(row[0] for row in foreign), foreign
    scenario_ids(live, observation_job=job_id, observation_game=case.game_id)


def balance_and_draft(live: Live, ids: dict[str, Any]) -> None:
    for game in GAMES:
        event = _registered(live, ids, game, "bal")
        balanced = _balanced(live, ids, game)
        variant = balanced["variant"]
        assert len(variant["teams"]) == 2 and not variant.get("benched_players"), variant
        names = []
        for team in variant["teams"]:
            assert {role: len(players) for role, players in team["roster"].items() if players} == FORMAT[game], team[
                "roster"
            ]
            names += [player["name"] for players in team["roster"].values() for player in players]
        assert len(names) == len(set(names)) == 10, names
        # The export agrees with the solver's selection: the same teams, each member's assigned role (its
        # ``tournament.player_role`` row), registration rank and the owner game's handle.
        label_of_registration = {rid: label for label, rid in event["registrations"].items()}
        solver = {
            frozenset(
                (
                    label_of_registration[int(player["uuid"])],
                    _exported_row(event, ids, game, label_of_registration[int(player["uuid"])], role),
                )
                for role, players in team["roster"].items()
                for player in players
            )
            for team in variant["teams"]
        }
        exported = _exported(live, ids, balanced["tournament_id"])
        assert set(exported) == set(balanced["teams"]), (exported.keys(), balanced["teams"])
        assert {frozenset(team.items()) for team in exported.values()} == solver, (exported, solver)
        invariant(live, f"{game}_balance_export", {"teams": len(exported), "players": sum(map(len, exported.values()))})
        invariant(live, f"{game}_captain_set_by_export", balanced["captain_set_by_export"])
        live.stack.evidence.record("job_ids", f"balance_{game}", balanced["job_id"])

        drafted = _drafted(live, ids, game)
        scenario_ids(live, **{f"{game}_balance": balanced["balance_id"], f"{game}_draft": drafted["session_id"]})


def _exported_row(event: dict[str, Any], ids: dict[str, Any], game: str, label: str, role: str) -> tuple:
    """What the export must write for one selected member: rank, owner-game handle, rated dimension, assigned role."""
    return (event["ranks"][label], ids["handles"][label][PROVIDER[game]], DIMENSION[game], role)


def _exported(live: Live, ids: dict[str, Any], tid: int) -> dict[int, dict[str, tuple]]:
    """Each exported ``tournament.team`` of ``tid`` as label -> (rank, name, assignment dimension, assignment role)."""
    by_member = labels_by_member(live, ids)
    teams: dict[int, dict[str, tuple]] = {}
    for team_id, member, rank, name, dimension, role in live.q(
        "SELECT p.team_id, p.workspace_member_id, p.rank, p.name, d.code, r.code FROM tournament.player p "
        "LEFT JOIN tournament.player_role pr ON pr.player_id=p.id LEFT JOIN catalog.role r ON r.id=pr.role_id "
        "LEFT JOIN catalog.role_dimension d ON d.id=pr.dimension_id WHERE p.tournament_id=%s",
        tid,
    ):
        label = by_member[member]
        assert label not in teams.setdefault(team_id, {}), (label, team_id)  # one player row, one assignment
        teams[team_id][label] = (rank, name, dimension, role)
    return teams


def _drafted(live: Live, ids: dict[str, Any], game: str) -> dict[str, Any]:
    if game in ids["drafts"]:
        return ids["drafts"][game]
    event = _registered(live, ids, game, "draft")
    tid = event["tournament_id"]
    session = call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/balancer/draft/tournaments/{tid}/sessions",
        {
            "pool_source": "manual",
            "pick_time_seconds": 600,
            "overtime_seconds": 0,
            "autopick_strategy": "best_fit",
            "allow_admin_override": True,
            "source_balance_id": None,
            "settings": {},
        },
        expect=200,
        tid=tid,
    ).json()
    sid = session["id"]
    captains = {OW: ("ow1", "ow2"), LOL: ("lol1", "twin_riot")}[game]
    call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/balancer/draft/tournaments/{tid}/sessions/{sid}/seed",
        {
            "captain_order": "manual",
            "pool_captains": [
                {
                    "registration_id": event["registrations"][label],
                    "role": _ref(game, ids["roles"][game][label]),
                    "name": None,
                }
                for label in captains
            ],
            "preview_only": False,
            "seed": None,
            "source_balance_id": None,
            "expected_version": None,
        },
        expect=200,
        tid=tid,
        sid=sid,
    )
    # Outside the tournament's draft phase only a superuser starts it.
    call(
        live,
        ids,
        "root",
        "POST",
        "/api/v1/balancer/draft/sessions/{sid}/start",
        expect=200,
        sid=sid,
    )
    board_route = "/api/v1/balancer/draft/sessions/{sid}/board"
    for _ in range(30):
        board = call(live, ids, None, "GET", board_route, expect=200, sid=sid).json()
        pick = board["current_pick"]
        if pick is None:
            break
        mine = [p for p in board["players"] if p["drafted_by_team_id"] == pick["draft_team_id"]]
        need = Counter(FORMAT[game]) - Counter(p["primary_role"]["role"] for p in mine if p.get("primary_role"))
        choice = next(
            p
            for p in board["players"]
            if p["drafted_by_team_id"] is None
            and not p["is_captain"]
            and p.get("primary_role")
            and need[p["primary_role"]["role"]] > 0
        )
        call(
            live,
            ids,
            "org",
            "POST",
            "/api/v1/balancer/draft/picks/{pick_id}/select",
            {"expected_version": pick["version"], "player_id": choice["id"], "target_role": choice["primary_role"]},
            expect=200,
            pick_id=pick["id"],
        )
    board = call(live, ids, None, "GET", board_route, expect=200, sid=sid).json()
    assert board["session"]["status"] == "completed", board["session"]
    label_of_registration = {rid: label for label, rid in event["registrations"].items()}
    for player in board["players"]:
        handle = ids["handles"][label_of_registration[player["registration_id"]]][PROVIDER[game]]
        assert player["identity"] == {"provider": PROVIDER[game], "handle": handle}, player
    for team in board["teams"]:
        drafted = [p["primary_role"]["role"] for p in board["players"] if p["drafted_by_team_id"] == team["id"]]
        assert Counter(drafted) == Counter(FORMAT[game]), (team, drafted)
    call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/balancer/draft/tournaments/{tid}/sessions/{sid}/export",
        expect=200,
        tid=tid,
        sid=sid,
    )
    # The export agrees with the draft: each draft team became its ``exported_team_id`` with exactly the members it
    # drafted, each at the role it was drafted for (a captain at its seat role), the frozen rank and the owner's handle.
    board = call(live, ids, None, "GET", board_route, expect=200, sid=sid).json()
    drafted_role = {pick["picked_player_id"]: pick["target_role"]["role"] for pick in board["picks"]}
    expected: dict[int, dict[str, tuple]] = {}
    for player in board["players"]:
        label = label_of_registration[player["registration_id"]]
        role = player["captain_role"]["role"] if player["is_captain"] else drafted_role[player["id"]]
        team = next(t for t in board["teams"] if t["id"] == player["drafted_by_team_id"])
        expected.setdefault(team["exported_team_id"], {})[label] = _exported_row(event, ids, game, label, role)
    assert (exported := _exported(live, ids, tid)) == expected, (exported, expected)
    out = {"tournament_id": tid, "session_id": sid}
    ids["drafts"][game] = out
    return out


def frozen_mix(live: Live, ids: dict[str, Any]) -> None:
    a, b = ids["workspaces"]["A"], ids["workspaces"]["B"]
    base = "/api/v1/balancer/workspaces/{ws}/custom-games"
    defaults = {
        game: call(live, ids, "org", "GET", "/api/v1/workspaces/{ws}/team-formats/{d}", expect=200, ws=a, d=game).json()
        for game in GAMES
    }
    frozen: dict[str, dict[str, Any]] = {}
    try:
        for game in GAMES:
            _registered(live, ids, game, "bal")
            labels = list(ids["roles"][game])
            members = [member_of(live, ids, label) for label in labels]
            assert all(members), dict(zip(labels, members, strict=True))
            for index, (label, member) in enumerate(zip(labels, members, strict=True)):
                role = ids["roles"][game][label]
                call(
                    live,
                    ids,
                    "org",
                    "PUT",
                    "/api/v1/balancer/workspaces/{ws}/players/{member_id}/ranks",
                    {"discipline": game, "scope": "workspace", "ranks": {role: _rank(game, role, index)}},
                    expect=200,
                    ws=a,
                    member_id=member,
                )
            created = call(
                live,
                ids,
                "host",
                "POST",
                base,
                {
                    "name": f"P8 mix {game} {ids['tag']}",
                    "discipline": game,
                    "member_ids": members,
                    "team_format_preset": "open_5v5" if game == LOL else None,
                    "clone_from_game_id": None,
                },
                expect=200,
                ws=a,
            ).json()
            gid = created["id"]
            ids["mixes"][game] = gid
            frozen[game] = _frozen_format(live, gid)
            if game == LOL:
                # Open 5v5: five unconstrained slots, no Flex role and no position rule.
                assert frozen[game]["format"][0] == "open_5v5", frozen[game]
                assert {mode for _, mode, *_ in frozen[game]["dimensions"]} <= {"off"}, frozen[game]
                assert frozen[game]["rules"] == [], frozen[game]
            call(
                live,
                ids,
                "host",
                "PUT",
                base + "/{gid}/self-service",
                {"self_signup": "benched"},
                expect=200,
                ws=a,
                gid=gid,
            )
            call(live, ids, "joiner", "POST", base + "/{gid}/me", expect=200, ws=a, gid=gid)
            call(
                live,
                ids,
                "host",
                "POST",
                base + "/{gid}/balance",
                {"scope": "lobby", "lobby_index": 0},
                expect=200,
                ws=a,
                gid=gid,
            )
            call(
                live,
                ids,
                "host",
                "PUT",
                base + "/{gid}/variant",
                {"lobby_index": 0, "variant_index": 0},
                expect=200,
                ws=a,
                gid=gid,
            )
            map_id = ids["catalog"][game][RIFT if game == LOL else OW_MAP]
            call(
                live,
                ids,
                "host",
                "PUT",
                base + "/{gid}/next-map",
                {"lobby_index": 0, "map_id": map_id},
                expect=200,
                ws=a,
                gid=gid,
            )
            # The mix as the host left it: every member under the owner game's own handle and rank, the joiner
            # benched, variant 0 and the next map selected.
            detail = _mix_detail(live, ids, gid)
            rows = {row["workspace_member_id"]: row for row in detail["players"]}
            for index, (label, member) in enumerate(zip(labels, members, strict=True)):
                role = ids["roles"][game][label]
                assert rows[member]["identity"] == {
                    "provider": PROVIDER[game],
                    "handle": ids["handles"][label][PROVIDER[game]],
                }
                assert rows[member]["ranks"].get(role) == _rank(game, role, index), rows[member]
            (joined,) = (
                row
                for row in detail["players"]
                if row["identity"] == {"provider": PROVIDER[game], "handle": ids["handles"]["joiner"][PROVIDER[game]]}
            )
            assert joined["participation"] == "benched", joined
            lobby = next(row for row in detail["lobbies"] if row["lobby_index"] == 0)
            assert (lobby["selected_variant_index"], lobby["next_map_id"]) == (0, map_id), lobby
            # The selected variant's seats, as the round must freeze them: member, name, balance rating, role slot.
            players = lobby["balance_result"]["players"]
            seats = Counter(
                (
                    slot,
                    int(uuid),
                    players[str(uuid)].get("name") or f"#{uuid}",
                    int(players[str(uuid)]["ratings"].get(bucket, 0)),
                    _slot_role(bucket),
                )
                for slot, team in enumerate(lobby["balance_result"]["variants"][0]["teams"], 1)
                for bucket, uuids in team["roster"].items()
                for uuid in uuids
            )
            assert sum(seats.values()) == 10 and {seat[1] for seat in seats} <= set(members), seats
            # The host starts the lobby's match on the shown lineup and map, then records it with no sides at all.
            call(
                live,
                ids,
                "host",
                "POST",
                base + "/{gid}/match/start",
                {"lobby_index": 0},
                expect=200,
                ws=a,
                gid=gid,
            )
            call(
                live,
                ids,
                "host",
                "POST",
                base + "/{gid}/outcome",
                {"lobby_index": 0, "outcome": {"winner": 1}},
                expect=200,
                ws=a,
                gid=gid,
            )
            history = call(live, ids, None, "GET", base + "/{gid}/matches", expect=200, ws=a, gid=gid).json()
            assert "side" not in json.dumps(history), history
            assert [
                (
                    m["lobby_index"],
                    m["winner_slot"],
                    m["map_id"],
                    [(t["slot"], t["score"]) for t in m["teams"]],
                    m["recorded_by"],
                )
                for m in history
            ] == [(0, 1, map_id, [(1, 1), (2, 0)], ids["users"]["host"]["player_id"])], history
            # The round froze exactly the selected seats, the next map and the host's result.
            frozen_seats = Counter(
                tuple(row)
                for row in live.q(
                    "SELECT et.slot, tm.workspace_member_id, tm.display_name_snapshot, tm.rank, r.code "
                    "FROM encounter.encounter e JOIN encounter.team et ON et.encounter_id=e.id "
                    "JOIN encounter.team_member tm ON tm.encounter_team_id=et.id "
                    "LEFT JOIN encounter.team_member_role tr ON tr.team_member_id=tm.id "
                    "LEFT JOIN catalog.role r ON r.id=tr.role_id WHERE e.custom_game_id=%s",
                    gid,
                )
            )
            assert frozen_seats == seats, (frozen_seats, seats)
            assert live.q(
                "SELECT g.map_id, g.state, g.result_source, g.result_version FROM encounter.game g "
                "JOIN encounter.encounter e ON e.id=g.encounter_id WHERE e.custom_game_id=%s",
                gid,
            ) == [(map_id, "confirmed", "host", 1)]
            sides = live.q(
                "SELECT et.slot, gt.score, gt.starting_side, e.discipline FROM encounter.encounter e "
                "JOIN encounter.game_team gt ON gt.encounter_id=e.id "
                "JOIN encounter.team et ON et.id=gt.encounter_team_id WHERE e.custom_game_id=%s ORDER BY et.slot",
                gid,
            )
            assert sides == [(1, 1, None, game), (2, 0, None, game)], sides
            # A later edit of the workspace default leaves the mix's frozen format exactly as it was.
            edit = {k: v for k, v in defaults[game].items() if k not in ("roster_shape", "source", "discipline")}
            edit["name"] = f"P8 edited default {game}"
            edit["substitute_max"] = (edit.get("substitute_max") or 0) + 1
            call(live, ids, "org", "PUT", "/api/v1/workspaces/{ws}/team-formats/{d}", edit, expect=200, ws=a, d=game)
            assert _frozen_format(live, gid) == frozen[game]
        # Both defaults are edited now: each mix still holds exactly the format it froze.
        for game in GAMES:
            assert (after := _frozen_format(live, ids["mixes"][game])) == frozen[game], (frozen[game], after)
            invariant(live, f"{game}_mix_format", frozen[game])
        # Cross-workspace: an A host cannot open a mix in B, nor seat a B member in an A mix.
        refused(
            call(live, ids, "host", "POST", base, {"name": "P8 foreign", "discipline": OW, "member_ids": []}, ws=b), 403
        )
        # The OW roster again with one B member added: the same non-disclosing 404 as an unknown member, the roster
        # untouched.
        roster = "SELECT * FROM mix.player WHERE custom_game_id=%s ORDER BY id"
        kept = live.q(roster, ids["mixes"][OW])
        current = [row["workspace_member_id"] for row in _mix_detail(live, ids, ids["mixes"][OW])["players"]]
        foreign = call(
            live,
            ids,
            "host",
            "POST",
            base + "/{gid}/roster",
            {"member_ids": [*current, ids["users"]["b_member"]["members"]["ON"]]},
            ws=a,
            gid=ids["mixes"][OW],
        )
        refused(foreign, 404, code="not_found", contains="Workspace member not found")
        assert live.q(roster, ids["mixes"][OW]) == kept
        live.stack.evidence.append(
            "unsupported_requests",
            {"scenario": _SCENARIO[0], "request": "foreign roster member", "status": 404, "code": "not_found"},
        )
        # A clone whose game is no longer enabled in the workspace is refused.
        _b_lol_enabled(live, ids)
        source = call(
            live,
            ids,
            "org",
            "POST",
            base,
            {"name": f"P8 B lol {ids['tag']}", "discipline": LOL, "member_ids": []},
            expect=200,
            ws=b,
        ).json()
        call(live, ids, "root", "PATCH", "/api/v1/workspaces/{id}", {"disciplines_enabled": [OW]}, expect=200, id=b)
        try:
            mixes = live.s("SELECT count(*) FROM mix.custom_game WHERE workspace_id=%s", b)
            refused(
                call(
                    live,
                    ids,
                    "org",
                    "POST",
                    base,
                    {"name": "P8 clone", "discipline": LOL, "clone_from_game_id": source["id"]},
                    ws=b,
                ),
                422,
                contains="discipline_not_enabled",
            )
            assert live.s("SELECT count(*) FROM mix.custom_game WHERE workspace_id=%s", b) == mixes
        finally:
            call(
                live,
                ids,
                "root",
                "PATCH",
                "/api/v1/workspaces/{id}",
                {"disciplines_enabled": [OW, LOL]},
                expect=200,
                id=b,
            )
        scenario_ids(live, mixes=dict(ids["mixes"]), b_lol_mix=source["id"])
    finally:
        for game, current in defaults.items():
            restore = {k: v for k, v in current.items() if k not in ("roster_shape", "source", "discipline")}
            call(live, ids, "org", "PUT", "/api/v1/workspaces/{ws}/team-formats/{d}", restore, ws=a, d=game)


def encounter_pregame(live: Live, ids: dict[str, Any]) -> None:
    preset = _preset(live, ids)
    side_config = _config(ids, preset["ruleset"], preset["first_ban_rotation"])
    rift = ids["catalog"][LOL][RIFT]
    tid = _balanced(live, ids, LOL)["tournament_id"]

    # One foreign item added to an otherwise valid pool -- another game's champion, or a LoL map in the champion pool --
    # is refused before the config is written.
    configs = "SELECT * FROM tournament.pick_ban_config WHERE tournament_id=%s ORDER BY id"
    for request, item in (("ow champion in lol pool", ids["catalog"][OW][OW_HERO]), ("lol map in champion pool", rift)):
        before = live.q(configs, tid)
        foreign = call(
            live,
            ids,
            "org",
            "PUT",
            "/api/v1/admin/tournaments/{tid}/pick-ban-configs",
            {**side_config, "item_ids": [*side_config["item_ids"], item], "stage_id": None, "round": None},
            tid=tid,
        )
        refused(foreign, 422, code="pool_item_not_in_catalog", contains=f"Not a {LOL} hero catalog item")
        assert live.q(configs, tid) == before
        live.stack.evidence.append(
            "unsupported_requests",
            {"scenario": _SCENARIO[0], "request": request, "status": 422, "code": "pool_item_not_in_catalog"},
        )

    # -- OW is unchanged: no side step, results as before.
    ow = _encounter(live, ids, OW, "pregame-ow")
    state = _state(live, ids, ow["encounter_id"])
    assert state.get("sides", []) == [] and state.get("starting_sides", []) == [], state
    _admin_result(live, ids, ow, ow["g1"], ow["seats"][0], expect=200)
    assert live.game(ow["g1"])["state"] == "confirmed"

    # -- E1: the preset room, game by game.
    e1 = _encounter(live, ids, LOL, "pregame-main", config=side_config)
    eid, g1 = e1["encounter_id"], e1["g1"]
    before = live.game(g1)
    s1 = e1["seats"][0]
    refused(
        call(
            live,
            ids,
            e1["captains"][s1],
            "POST",
            "/api/v1/encounters/{eid}/games/{gid}/map",
            {"map_id": rift},
            eid=eid,
            gid=g1,
        ),
        409,
        code="side_pick_required",
    )
    refused(_claim(live, ids, e1, s1, g1, s1), 409, code="side_pick_required")
    refused(_admin_result(live, ids, e1, g1, s1), 409, code="side_pick_required")
    assert live.game(g1) == before and set(_sides(live, g1).values()) == {None}
    state = _ready(live, ids, e1)
    assert state["sides"] == ["blue", "red"] and state["current_step"]["action"] == "side_pick", state
    refused(
        call(
            live,
            ids,
            e1["captains"][s1],
            "POST",
            "/api/v1/encounters/{eid}/games/{gid}/map",
            {"map_id": rift},
            eid=eid,
            gid=g1,
        ),
        409,
        code="side_pick_pending",
    )
    refused(_claim(live, ids, e1, s1, g1, s1), 409, code="side_pick_pending")
    opener = _acting(live, ids, e1)
    assert opener == _seeded(live, e1), opener
    other = _other(e1, opener)
    _side_pick(live, ids, e1, opener, 0, expect=200)
    assert _sides(live, g1) == {opener: "blue", other: "red"}
    entry = next(e for e in _state(live, ids, eid)["starting_sides"] if e["game_id"] == g1)
    assert entry["position"] == 1 and entry["sides"] == {str(opener): "blue", str(other): "red"}, entry
    # An unplayed undo takes both rows back.
    _undo(live, ids, e1, opener, expect=200)
    _undo(live, ids, e1, other, expect=200)
    assert set(_sides(live, g1).values()) == {None} and _state(live, ids, eid)["submissions"] == []
    _side_pick(live, ids, e1, opener, 0, expect=200)
    # Admin reopen of the unplayed side step: an empty draft; the opposite index swaps the rows.
    call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/encounters/{eid}/pick-ban-reopen",
        {"kind": "hero"},
        expect=200,
        eid=eid,
    )
    reopened = _state(live, ids, eid)
    assert _drafts(reopened) == [(opener, "draft", [])] and reopened["acting_team_ids"] == [opener], reopened
    assert _draft_rows(live, eid, 0) == [(opener, "draft", [])]
    assert set(_sides(live, g1).values()) == {None}
    assert all(entry["game_id"] != g1 for entry in reopened["starting_sides"]), reopened["starting_sides"]
    _side_pick(live, ids, e1, opener, 1, expect=200)
    assert _sides(live, g1) == {opener: "red", other: "blue"}
    call(
        live,
        ids,
        e1["captains"][opener],
        "POST",
        "/api/v1/encounters/{eid}/games/{gid}/map",
        {"map_id": rift},
        expect=200,
        eid=eid,
        gid=g1,
    )
    # A claimed position's side is locked against undo and reopen.
    _claim(live, ids, e1, opener, g1, opener)
    locked = _sides(live, g1)
    refused(_undo(live, ids, e1, opener), 409, code="side_locked")
    refused(
        call(live, ids, "org", "POST", "/api/v1/admin/encounters/{eid}/pick-ban-reopen", {"kind": "hero"}, eid=eid),
        409,
        code="side_locked",
    )
    assert _sides(live, g1) == locked
    # G2 waits while G1 is pending: no round-2 step to act on, no game at position 2.
    pending = _state(live, ids, eid)
    assert (pending["current_round"], pending["acting_team_ids"], _game(live, eid, 2)) == (1, [], None), pending
    _claim(live, ids, e1, other, g1, opener)
    wait_until(lambda: live.game(g1)["state"] == "confirmed", "game 1 confirmed by matching claims", timeout=30)
    # G2 opens with G1's loser.
    state = _wait_round(live, ids, e1, 2)
    assert state["acting_team_ids"] == [other], state
    # Confirmed now: undo and reopen still refuse G1's side; the rows stay.
    refused(_undo(live, ids, e1, other), 409, code="side_locked")
    refused(
        call(live, ids, "org", "POST", "/api/v1/admin/encounters/{eid}/pick-ban-reopen", {"kind": "hero"}, eid=eid),
        409,
        code="side_locked",
    )
    assert _sides(live, g1) == locked
    g2 = wait_until(lambda: _game(live, eid, 2), "game 2", timeout=60)
    # An untouched G2 is rebuilt by a correction that changes the opener.
    opened = _round_opened(live, eid)
    _admin_result(live, ids, e1, g1, other, expect=200)
    state = _wait_round(live, ids, e1, 2)
    assert state["acting_team_ids"] == [opener] and _round_opened(live, eid) == opened + 1, state
    # A used G2 refuses the correction and writes nothing.
    _side_pick(live, ids, e1, opener, 0, expect=200)
    snapshot = _frozen(live, eid)
    refused(_admin_result(live, ids, e1, g1, opener), 409, code="dependent_round_started")
    assert (after := _frozen(live, eid)) == snapshot, (snapshot, after)
    # Recovery (a): the captains undo round 2, then the same correction rebuilds it.
    _undo(live, ids, e1, opener, expect=200)
    _undo(live, ids, e1, other, expect=200)
    assert set(_sides(live, g2).values()) == {None}
    _admin_result(live, ids, e1, g1, opener, expect=200)
    state = _wait_round(live, ids, e1, 2)
    assert state["acting_team_ids"] == [other], state
    invariant(live, "e1_journal", _frozen(live, eid)["journal"])

    # -- E2: index 1, a series both captains confirm by matching claims, then recovery (b).
    e2 = _encounter(live, ids, LOL, "pregame-index1", config=side_config)
    _ready(live, ids, e2)
    o2 = _acting(live, ids, e2)
    assert o2 == _seeded(live, e2), o2
    p2 = _other(e2, o2)
    _side_pick(live, ids, e2, o2, 1, expect=200)
    assert _sides(live, e2["g1"]) == {o2: "red", p2: "blue"}
    _played(live, ids, e2, e2["g1"], o2)
    state = _wait_round(live, ids, e2, 2)
    assert state["acting_team_ids"] == [p2], state
    _side_pick(live, ids, e2, p2, 0, expect=200)
    g2b = wait_until(lambda: _game(live, e2["encounter_id"], 2), "E2 game 2", timeout=60)
    _played(live, ids, e2, g2b, o2)
    snapshot = _frozen(live, e2["encounter_id"])
    refused(_admin_result(live, ids, e2, e2["g1"], p2), 409, code="dependent_round_started")
    assert (after := _frozen(live, e2["encounter_id"])) == snapshot, (snapshot, after)
    old_games = [e2["g1"], g2b]
    kept = _history(live, old_games)
    for game_id, side in ((e2["g1"], {o2: "red", p2: "blue"}), (g2b, {p2: "blue", o2: "red"})):
        lines = {seat: (score, starting) for seat, score, _placement, _values, starting in kept[game_id]["lines"]}
        assert lines == {o2: (1, side[o2]), p2: (0, side[p2])}, kept[game_id]
        assert len(kept[game_id]["claims"]) == 4, kept[game_id]  # two claims, two result lines each
    status = live.s("SELECT result_status FROM encounter.encounter WHERE id=%s", e2["encounter_id"])
    invariant(live, "e2_result_status_before_recovery", str(status))
    if str(status) == "confirmed":
        call(
            live,
            ids,
            "org",
            "POST",
            "/api/v1/admin/encounters/{eid}/result/reopen",
            {"reason": "P8 recovery"},
            expect=200,
            eid=e2["encounter_id"],
        )
    call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/encounters/{eid}/pick-ban-session/reset",
        {"kind": "map"},
        expect=200,
        eid=e2["encounter_id"],
    )
    call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/encounters/{eid}/pick-ban-session/reset",
        {"kind": "hero"},
        expect=200,
        eid=e2["encounter_id"],
    )
    # The retired games are history: cancelled, with their results, lines, sides and claims exactly as they were.
    assert [live.game(game_id)["state"] for game_id in old_games] == ["cancelled", "cancelled"]
    assert (retired := _history(live, old_games)) == kept, (kept, retired)
    replay = _acting(live, ids, e2)
    assert replay == o2 == _seeded(live, e2), (replay, o2)
    _side_pick(live, ids, e2, replay, 1, expect=200)
    g1_new = wait_until(lambda: _game(live, e2["encounter_id"], 1), "replacement game 1", timeout=60)
    assert g1_new not in old_games
    _admin_result(live, ids, e2, g1_new, p2, expect=200)
    state = _wait_round(live, ids, e2, 2)
    assert state["acting_team_ids"] == [o2], state
    scenario_ids(live, e2_replacement_g1=g1_new, e2_cancelled=old_games)

    # -- E3: a side pick, then a side:blue ban; reopen + opposite index -> the new blue holder bans.
    custom = _ruleset(
        _phase(
            "main", [_step("sp", action="side_pick"), _step("b1", actors="side:blue"), _step("b2", actors="side:red")]
        )
    )
    e3 = _encounter(live, ids, LOL, "pregame-sidebound", config=_config(ids, custom))
    _ready(live, ids, e3)
    o3 = _acting(live, ids, e3)
    q3 = _other(e3, o3)
    _side_pick(live, ids, e3, o3, 0, expect=200)
    call(
        live,
        ids,
        "org",
        "POST",
        "/api/v1/admin/encounters/{eid}/pick-ban-reopen",
        {"kind": "hero"},
        expect=200,
        eid=e3["encounter_id"],
    )
    reopened = _state(live, ids, e3["encounter_id"])
    assert _drafts(reopened) == [(o3, "draft", [])] and reopened["acting_team_ids"] == [o3], reopened
    assert _draft_rows(live, e3["encounter_id"], 0) == [(o3, "draft", [])]
    assert set(_sides(live, e3["g1"]).values()) == {None}
    _side_pick(live, ids, e3, o3, 1, expect=200)
    assert _sides(live, e3["g1"]) == {o3: "red", q3: "blue"}
    ban = {"item_id": ids["catalog"][LOL]["zed"], "action": "ban", "target_player_id": None}
    act = "/api/v1/encounters/{eid}/pick-ban/{kind}/act"
    wrong = call(live, ids, e3["captains"][o3], "POST", act, ban, eid=e3["encounter_id"], kind="hero")
    assert wrong.status in (400, 403), wrong.raw[:300]
    call(live, ids, e3["captains"][q3], "POST", act, ban, expect=200, eid=e3["encounter_id"], kind="hero")

    # -- E4: phased ruleset (side step only for map 1): G1 needs sides, G2 records without them.
    when = lambda op, value: {"type": "map_index", "params": {"op": op, "value": value}}  # noqa: E731
    phased = _ruleset(
        _phase(
            "first",
            [_step("sp", action="side_pick"), _step("b1", actors="side:blue"), _step("b2", actors="side:red")],
            when("==", 1),
        ),
        # Step ids are unique across the whole ruleset (``duplicate_step_id``).
        _phase("later", [_step("b3"), _step("b4", actors="second")], when(">=", 2)),
    )
    e4 = _encounter(live, ids, LOL, "pregame-phased", config=_config(ids, phased))
    refused(_admin_result(live, ids, e4, e4["g1"], e4["seats"][0]), 409, code="side_pick_required")
    _ready(live, ids, e4)
    o4 = _acting(live, ids, e4)
    _side_pick(live, ids, e4, o4, 0, expect=200)
    _admin_result(live, ids, e4, e4["g1"], o4, expect=200)
    g4b = wait_until(lambda: _game(live, e4["encounter_id"], 2), "E4 game 2", timeout=60)
    _admin_result(live, ids, e4, g4b, o4, expect=200)
    assert set(_sides(live, g4b).values()) == {None}

    # -- E5: a custom ruleset without side_pick records like OW.
    e5 = _encounter(
        live,
        ids,
        LOL,
        "pregame-noside",
        config=_config(ids, _ruleset(_phase("main", [_step("b1"), _step("b2", actors="second")]))),
    )
    _admin_result(live, ids, e5, e5["g1"], e5["seats"][0], expect=200)
    assert live.game(e5["g1"])["state"] == "confirmed" and set(_sides(live, e5["g1"]).values()) == {None}

    # -- E6: a short-timer side step is resolved by the due tick (coin flip). 5 s is the smallest timer (timer_range).
    timed = _ruleset(_phase("main", [_step("sp", action="side_pick", timer=5)]), timer=5)
    e6 = _encounter(live, ids, LOL, "pregame-timeout", config=_config(ids, timed))
    _ready(live, ids, e6)
    sides = wait_until(
        lambda: (s := _sides(live, e6["g1"])) and None not in s.values() and s, "the timed-out side pick", timeout=60
    )
    assert sorted(sides.values()) == ["blue", "red"], sides
    # A champion class never supplies a position (module roles only: B's sub-role of ``top`` is a workspace child).
    module_roles = live.q(
        "SELECT c.code FROM catalog.role c JOIN catalog.role_dimension d ON d.id=c.dimension_id "
        "WHERE d.discipline='lol' AND c.workspace_id IS NULL"
    )
    assert all(r[0] in POSITIONS for r in module_roles), module_roles


def canonical_ingest(live: Live, ids: dict[str, Any]) -> None:
    preset = _preset(live, ids)
    lol = _encounter(live, ids, LOL, "ingest", config=_config(ids, preset["ruleset"], preset["first_ban_rotation"]))
    if None in _sides(live, lol["g1"]).values():
        _ready(live, ids, lol)
        _side_pick(live, ids, lol, _acting(live, ids, lol), 0, expect=200)
    ow = _encounter(live, ids, OW, "ingest-ow")
    encounters = {LOL: lol, OW: ow}
    for game, enc in encounters.items():
        _on_map(live, ids, enc, game, enc["g1"])
    # The same lifecycle for each game; the other game's document is the cross-game idempotency probe.
    for game, enc in encounters.items():
        other = next(g for g in GAMES if g != game)
        probe = DOCS[other](live, ids, encounters[other], "probe", hint=encounters[other]["g1"])
        ids["matches"][game], ids["jobs"][game] = _ingest_lifecycle(live, ids, game, enc, probe)
    # Parity control: the Workshop golden upload decodes to the reference capture, untouched by the LoL traffic.
    shop = live.workshop
    raw = (DIRECTORY / "workshop.csv").read_bytes()
    payload, content_type = _multipart(
        {"tournament_id": str(shop.tournament_id), "encounter_id": str(shop.encounter_id)}, "workshop.csv", raw
    )
    upload = http(
        "POST",
        f"{live.stack.gateway}/api/v1/admin/logs/upload",
        body=payload,
        headers={"Authorization": f"Bearer {token(live, ids, 'org')}", "Content-Type": content_type},
    )
    assert upload.status == 200 and not upload.json()["errors"], upload.raw[:400]
    workshop_job = upload.json()["uploaded"][0]["record_id"]
    wait_until(lambda: live.job(workshop_job)["status"] in ("done", "failed"), "the Workshop job", timeout=120)
    assert live.job(workshop_job)["status"] == "done"
    expected = json.loads((DIRECTORY / "expected.json").read_bytes())
    actual = _observed(live, shop.game_id)
    for section in ("segments", "team_scores", "players", "events", "facts"):
        assert actual[section] == expected[section], section
    live.drain()
    scenario_ids(live, lol_match=ids["matches"][LOL], ow_match=ids["matches"][OW], workshop_job=workshop_job)


def _ingest_lifecycle(
    live: Live, ids: dict[str, Any], game: str, enc: dict[str, Any], probe: dict[str, Any]
) -> tuple[int, int]:
    """One game's canonical ingest (§6.3): concurrent identical bytes -> one job and revision; a changed document or
    another game's under the same key -> 409; keyless / scope-less / foreign key denied; exact native reads; a
    new-external-id correction -> the same match, revision + 1, observations replaced, the binding moved to it."""
    tag = ids["tag"]
    first, fixed = CORRECTION[game]
    external = f"p8-{game}-g1-{tag}"
    doc = DOCS[game](live, ids, enc, external, value=first, hint=enc["g1"])
    body = canonical(doc)
    barrier = threading.Barrier(6)

    def upload(index: int) -> Response:
        barrier.wait(timeout=60)
        return live.post("off_ok" if index % 2 else "off_ok2", body)

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(upload, range(6)))  # any uploader's exception is re-raised here
    assert len(responses) == 6, responses
    assert all(r.status in (200, 202) for r in responses), [(r.status, r.raw[:200]) for r in responses]
    (job_id,) = {r.json()["id"] for r in responses}
    job = _bound(live, job_id, enc["g1"])
    match = live.match(enc["g1"])
    assert match == {"id": job["binding"]["match_id"], "revision": 1, "ingest_job_id": job_id}, (match, job)
    assert live.s("SELECT count(*) FROM stats.ingest_job WHERE external_id=%s", external) == 1
    jobs = live.s("SELECT count(*) FROM stats.ingest_job")
    refused(ingest(live, "off_ok", {**doc, "duration_s": doc["duration_s"] + 1}), 409, code="idempotency_conflict")
    refused(ingest(live, "off_ok", {**probe, "source": doc["source"]}), 409, code="idempotency_conflict")
    assert ingest(live, None, doc).status == 401
    refused(ingest(live, "off_no_scope", doc), 403, code="scope_required")
    foreign = ingest(live, "on_ok", doc)
    assert foreign.status in (403, 404), foreign.raw[:300]
    assert live.s("SELECT count(*) FROM stats.ingest_job") == jobs
    observed = live.children(match["id"])
    _assert_read(live, ids, enc, match["id"], doc)
    fix = DOCS[game](live, ids, enc, f"p8-{game}-g1-fix-{tag}", value=fixed, hint=enc["g1"])
    fix_job = ingest(live, "off_ok", fix).json()["id"]
    _bound(live, fix_job, enc["g1"])
    corrected = live.match(enc["g1"])
    assert corrected == {"id": match["id"], "revision": 2, "ingest_job_id": fix_job}, corrected
    # Provenance: the first job stays done but no longer binds the match; the correction does.
    old = live.get_job("off_ok", job_id).json()
    assert old["status"] == "done" and old.get("binding") is None, old
    assert live.children(match["id"]) == observed  # replaced row for row, nothing residual
    _assert_read(live, ids, enc, match["id"], fix)
    live.stack.evidence.record("revisions", f"p8_{game}", [1, 2])
    live.stack.evidence.record("job_ids", f"p8_{game}", [job_id, fix_job])
    live.stack.evidence.record("match_ids", f"p8_{game}", match["id"])
    return match["id"], fix_job


def awaiting_link_and_official(live: Live, ids: dict[str, Any]) -> None:
    tag = ids["tag"]
    preset = _preset(live, ids)
    side_config = _config(ids, preset["ruleset"], preset["first_ban_rotation"])
    for game in GAMES:
        # Both teams play several encounters on the document's map: a hint-less document has more than one candidate.
        enc = _encounter(live, ids, game, "awaiting", config=side_config if game == LOL else None)
        twin = _encounter(live, ids, game, "awaiting-twin", config=side_config if game == LOL else None)
        for each in (enc, twin):
            if game == LOL:
                _ready(live, ids, each)
                _side_pick(live, ids, each, _acting(live, ids, each), 0, expect=200)
            # The bind checks the game's map against the document's (P5 ``process`` bind): the captain records it.
            _on_map(live, ids, each, game, each["g1"])
        doc = (_lol_doc if game == LOL else _ow_doc)(live, ids, enc, f"p8-{game}-awaiting-{tag}")
        job_id = ingest(live, "off_ok", doc).json()["id"]
        job = _settled(live, "off_ok", job_id)
        assert job["status"] == "awaiting_link", job
        assert live.s("SELECT count(*) FROM stats.match WHERE ingest_job_id=%s", job_id) == 0
        observation = call(
            live, ids, "org", "GET", "/api/v1/admin/logs/games/{gid}/observation", expect=200, gid=enc["g1"]
        ).json()
        keys = [team["key"] for team in doc["teams"]]
        stale = _bind(
            live, ids, job_id, enc["g1"], dict(zip(keys, enc["seats"], strict=True)), observation["revision"] + 5
        )
        assert stale.status == 409, stale.raw[:300]
        # Reversed, every participant is on the other seat's line-up: the map is refused and nothing is written.
        reversed_map = dict(zip(keys, reversed(enc["seats"]), strict=True))
        wrong = _bind(live, ids, job_id, enc["g1"], reversed_map, observation["revision"])
        live.stack.evidence.append(
            "unsupported_requests",
            {
                "scenario": _SCENARIO[0],
                "request": f"{game} wrong mapping",
                "status": wrong.status,
                "code": code_of(wrong),
            },
        )
        refused(wrong, 409, code="binding_mismatch")
        assert live.match(enc["g1"]) is None, wrong.raw[:300]
        teams = dict(zip(keys, enc["seats"], strict=True))
        disabled = _result(live, enc["g1"])
        bound = _bind(live, ids, job_id, enc["g1"], teams, observation["revision"], expect=200).json()
        assert bound["status"] == "done" and bound["binding"]["revision"] == 1, bound
        match = live.match(enc["g1"])
        live.drain()
        assert (
            live.s("SELECT status FROM public.event_outbox WHERE event_id=%s", f"match.ingested:{match['id']}:1")
            == "published"
        )
        receipts = live.wait_receipts(enc["encounter_id"], 1)
        assert [r["outcome"] for r in receipts] == ["logs_disabled"], receipts
        live.stack.evidence.record("receipt_outcomes", f"p8_{game}_awaiting", [r["outcome"] for r in receipts])
        assert _result(live, enc["g1"]) == disabled  # logs_official off: the evidence leaves the result alone

    # logs_official on, per game: the policy matrix of ``_official``.
    for game in GAMES:
        tid = _balanced(live, ids, game)["tournament_id"]
        call(live, ids, "org", "PATCH", "/api/v1/admin/tournaments/{tid}", {"logs_official": True}, expect=200, tid=tid)
        try:
            _official(live, ids, game, side_config if game == LOL else None)
        finally:
            call(
                live,
                ids,
                "org",
                "PATCH",
                "/api/v1/admin/tournaments/{tid}",
                {"logs_official": False},
                expect=200,
                tid=tid,
            )
    live.drain()


def _official(live: Live, ids: dict[str, Any], game: str, config: dict[str, Any] | None) -> None:
    """With ``logs_official`` on: eligible evidence is accepted once (placements only, sides kept); the same bytes are
    the same job and no second decision; a later contradicting revision and evidence for an admin-confirmed game are
    journaled ``result_locked`` and change nothing. LoL evidence binds only after the real side selection."""
    tag, build = ids["tag"], DOCS[game]
    enc = _encounter(live, ids, game, "official", config=config)
    eid, g1 = enc["encounter_id"], enc["g1"]
    if game == LOL:
        # Before the side selection the game cannot take a map (``side_pick_required``), so a hinted log cannot bind
        # to it at all (P5 ``find_binding``: a hinted game must be on the log's map): nothing becomes official.
        early = ingest(live, "off_ok", build(live, ids, enc, f"p8-{game}-official-early-{tag}", hint=g1)).json()["id"]
        early_job = _settled(live, "off_ok", early)
        assert early_job["status"] == "failed" and early_job["error"]["code"] == "binding_mismatch", early_job
        assert live.receipts(eid) == [] and live.game(g1)["state"] != "confirmed"
        live.stack.evidence.append(
            "unsupported_requests",
            {"scenario": _SCENARIO[0], "request": "lol official log before side selection", "code": "binding_mismatch"},
        )
        _ready(live, ids, enc)
        _side_pick(live, ids, enc, _acting(live, ids, enc), 0, expect=200)
    _on_map(live, ids, enc, game, g1)
    before = _result(live, g1)
    doc = build(live, ids, enc, f"p8-{game}-official-{tag}", hint=g1)
    accepted = ingest(live, "off_ok", doc).json()["id"]
    _bound(live, accepted, g1)
    assert [r["outcome"] for r in live.wait_receipts(eid, 1)] == ["accepted"]
    official = _result(live, g1)
    assert (official["state"], official["result_version"], official["result_source"]) == (
        "confirmed",
        before["result_version"] + 1,
        "admin_log",
    ), official
    placement = {enc["seats"][index]: team["placement"] for index, team in enumerate(doc["teams"])}
    side = {seat: starting for seat, _score, _placement, starting in before["lines"]}
    assert {seat: (p, s) for seat, _score, p, s in official["lines"]} == {
        seat: (placement[seat], side[seat]) for seat in enc["seats"]
    }, official
    # The same bytes again: the same job, no new revision, no second decision.
    again = ingest(live, "off_ok", doc)
    assert again.status in (200, 202) and again.json()["id"] == accepted, again.raw[:300]
    live.drain()
    assert len(live.receipts(eid)) == 1 and _result(live, g1) == official
    # A later contradicting revision: journaled, never applied (the first accepted evidence stands).
    late = build(live, ids, enc, f"p8-{game}-official-late-{tag}", hint=g1)
    late["teams"] = [{**team, "placement": 3 - team["placement"]} for team in late["teams"]]
    _bound(live, ingest(live, "off_ok", late).json()["id"], g1)
    outcomes = [r["outcome"] for r in live.wait_receipts(eid, 2)]
    assert outcomes == ["accepted", "result_locked"] and _result(live, g1) == official, outcomes
    # An organizer's own result stands: evidence that disagrees is journaled, never applied.
    locked = _encounter(live, ids, game, "official-admin", config=config)
    if game == LOL:
        _ready(live, ids, locked)
        _side_pick(live, ids, locked, _acting(live, ids, locked), 0, expect=200)
    _on_map(live, ids, locked, game, locked["g1"])
    _admin_result(live, ids, locked, locked["g1"], locked["seats"][1], expect=200)
    admin = _result(live, locked["g1"])
    assert (admin["state"], admin["result_source"]) == ("confirmed", "admin"), admin
    evidence = build(live, ids, locked, f"p8-{game}-official-admin-{tag}", hint=locked["g1"])  # alpha (slot 1) first
    _bound(live, ingest(live, "off_ok", evidence).json()["id"], locked["g1"])
    locked_outcomes = [r["outcome"] for r in live.wait_receipts(locked["encounter_id"], 1)]
    assert locked_outcomes == ["result_locked"] and _result(live, locked["g1"]) == admin, locked_outcomes
    live.stack.evidence.record("receipt_outcomes", f"p8_{game}_official", outcomes)
    live.stack.evidence.record("receipt_outcomes", f"p8_{game}_official_admin", locked_outcomes)


def readback_isolation(live: Live, ids: dict[str, Any]) -> None:
    if LOL not in ids["matches"]:
        canonical_ingest(live, ids)
    lol_match, ow_match = ids["matches"][LOL], ids["matches"][OW]
    a, b = ids["workspaces"]["A"], ids["workspaces"]["B"]
    lol = call(
        live, ids, None, "GET", "/api/v1/matches/{id}", query={"workspace_id": a}, expect=200, id=lol_match
    ).json()
    refused(call(live, ids, None, "GET", "/api/v1/matches/{id}", query={"workspace_id": b}, id=lol_match), 404)
    # Public ordering by encounter slot; handles of each game stay in that game.
    assert [p["slot"] for p in lol["participants"]] == sorted(p["slot"] for p in lol["participants"])
    ow = call(live, ids, None, "GET", "/api/v1/matches/{id}", expect=200, id=ow_match).json()
    # Each game resolves every handle to exactly its own registrant -- including the twin, one text that is a Riot ID
    # of one person and a BattleTag of another.
    for game, read in ((LOL, lol), (OW, ow)):
        owners = {m["handle_snapshot"]: m["player_id"] for m in read["statistics"]["members"]}
        expected = {
            ids["handles"][label][PROVIDER[game]]: ids["users"][label]["player_id"] for label in ids["roles"][game]
        }
        assert owners == expected, (game, owners, expected)
    twin = ids["handles"]["twin_riot"][PROVIDER[LOL]]
    assert twin == ids["handles"]["twin_bn"][PROVIDER[OW]]
    lol_twin = next(m["player_id"] for m in lol["statistics"]["members"] if m["handle_snapshot"] == twin)
    ow_twin = next(m["player_id"] for m in ow["statistics"]["members"] if m["handle_snapshot"] == twin)
    assert (lol_twin, ow_twin) == (ids["users"]["twin_riot"]["player_id"], ids["users"]["twin_bn"]["player_id"])
    for match_id, game in ((lol_match, LOL), (ow_match, OW)):
        disciplines = {
            row[0]
            for row in live.q(
                "SELECT DISTINCT d.discipline FROM stats.fact f JOIN stats.stat_def d ON d.id=f.stat_id WHERE f.match_id=%s "
                "UNION SELECT DISTINCT t.discipline FROM stats.event e JOIN stats.event_type t ON t.id=e.type_id WHERE e.match_id=%s",
                match_id,
                match_id,
            )
        }
        assert invariant(live, f"{game}_vocabulary_disciplines", sorted(disciplines)) == [game]
    encounter = call(
        live,
        ids,
        None,
        "GET",
        "/api/v1/encounters/{id}",
        query={"entities": "matches"},  # ``games`` ride the same switch (``encounter_entities``)
        expect=200,
        id=lol["encounter_id"],
    ).json()
    g1 = next(game for game in encounter["games"] if game["id"] == lol["encounter_game_id"])
    assert sorted(team["starting_side"] for team in g1["teams"]) == ["blue", "red"], g1
    ahri = ids["catalog"][LOL]["ahri"]
    entity = call(
        live, ids, None, "GET", "/api/v1/catalog/{d}/{kind}/{id}", expect=200, d=LOL, kind="character", id=ahri
    ).json()
    assert entity["slug"] == "ahri" and entity["discipline"] == LOL
    refused(
        call(
            live,
            ids,
            None,
            "GET",
            "/api/v1/catalog/{d}/{kind}/{id}",
            d=LOL,
            kind="character",
            id=ids["catalog"][OW][OW_HERO],
        ),
        404,
    )
    refused(
        call(live, ids, None, "GET", "/api/v1/catalog/{d}/{kind}", d=LOL, kind="mode"),
        404,
        code="catalog_kind_not_declared",
    )
    # OW golden still what it was after the LoL traffic.
    expected = json.loads((DIRECTORY / "expected.json").read_bytes())
    assert _observed(live, live.workshop.game_id)["events"] == expected["events"]
    # F3 is P9's: record what the LoL leaderboard actually answers, claim nothing.
    board = call(live, ids, None, "GET", "/api/v1/statistics/{d}/characters/{id}/leaderboard", d=LOL, id=ahri)
    live.stack.evidence.append(
        "unsupported_requests",
        {
            "scenario": _SCENARIO[0],
            "request": "lol character leaderboard (F3, P9)",
            "status": board.status,
            "code": code_of(board),
        },
    )


def unsupported_and_diagnostics(live: Live, ids: dict[str, Any]) -> None:
    meta = call(live, ids, None, "GET", "/api/v1/disciplines/{d}/metadata", expect=200, d=LOL).json()
    capabilities = meta["discipline"]["capabilities"]
    assert capabilities == {
        "catalog_sync": True,
        "native_rank_collection": True,
        "native_ladder": True,
        "match_fetch": False,
        "match_search": False,
        "lobby_bot": False,
        "ingest_status": False,
        "log_upload": False,
        "achievement_conditions": False,
        "analytics": False,
    }, capabilities
    assert {s["code"] for s in meta["stat_defs"]} == {"kills", "dragons"} and {
        e["code"] for e in meta["event_types"]
    } == {"kill"}
    types = call(
        live,
        ids,
        "org",
        "GET",
        "/api/v1/admin/ws/{ws}/achievements/rules/condition-types",
        query={"discipline": LOL},
        expect=200,
        ws=ids["workspaces"]["A"],
    )
    assert types.json() == [], types.raw[:300]  # G5: an empty registry is 200 [], never a refusal
    awards = live.s(
        "SELECT count(*) FROM achievements.evaluation_result r JOIN stats.match m ON m.id=r.match_id WHERE m.discipline='lol'"
    )
    assert invariant(live, "lol_match_awards", awards) == 0
    enc = _encounter(live, ids, LOL, "ingest", config=_config(ids, _preset(live, ids)["ruleset"]))
    # One field of an otherwise valid document per request: exactly one diagnostic, a failed job, an alias-miss row,
    # no observation, no success event and no dictionary row created.
    cases = (
        (
            "lol unknown stat",
            lambda doc: doc["facts"].append({"team": "alpha", "stat": "p8_unknown_stat", "value": 1}),
            (["facts", 2, "stat"], "unknown_stat", "stat", "p8_unknown_stat"),
        ),
        (
            "lol unknown event",
            lambda doc: doc["events"][0].update(type="p8_unknown_event"),
            (["events", 0, "type"], "unknown_event", "event", "p8_unknown_event"),
        ),
        (
            "lol unknown role",
            lambda doc: doc["participants"][0]["role"].update(role="p8_unknown_role"),
            (["participants", 0, "role"], "unknown_role", "role", f"{DIMENSION[LOL]}:p8_unknown_role"),
        ),
        (
            "ow character on a lol fact",
            lambda doc: doc["facts"][0].update(entity=OW_HERO),
            (["facts", 0, "entity"], "unknown_character", "character", OW_HERO),
        ),
        (
            "lol map on a character field",
            lambda doc: doc["facts"][0].update(entity=RIFT),
            (["facts", 0, "entity"], "unknown_character", "character", RIFT),
        ),
    )

    def durable() -> dict[str, int]:
        return {
            "stat_def": live.s("SELECT count(*) FROM stats.stat_def WHERE discipline='lol'"),
            "event_type": live.s("SELECT count(*) FROM stats.event_type WHERE discipline='lol'"),
            "role": live.s(
                "SELECT count(*) FROM catalog.role c JOIN catalog.role_dimension d ON d.id=c.dimension_id "
                "WHERE d.discipline='lol'"
            ),
            "entity": live.s("SELECT count(*) FROM catalog.entity WHERE discipline='lol'"),
            "matches": live.s("SELECT count(*) FROM stats.match"),
            "ingested": live.s("SELECT count(*) FROM public.event_outbox WHERE event_id LIKE %s", "match.ingested:%"),
        }

    def issues(rows: list[dict[str, Any]]) -> list[tuple]:
        return [(row["path"], row["code"], row.get("kind"), row.get("raw_name")) for row in rows]

    for index, (request, mutate, expected) in enumerate(cases):
        doc = _lol_doc(live, ids, enc, f"p8-lol-diagnostic-{index}-{ids['tag']}")
        mutate(doc)
        before = durable()
        response = ingest(live, "off_ok", doc)
        refused(response, 422, code="unknown_code")
        assert issues(response.json()["issues"]) == [expected], response.raw[:800]
        job_id = response.json()["ingest_job_id"]
        job = _settled(live, "off_ok", job_id)
        assert job["status"] == "failed" and job["error"]["code"] == "unknown_code", job
        assert issues(job["error"]["issues"]) == [expected], job["error"]
        misses = live.q(
            "SELECT kind, raw_name FROM catalog.alias_miss WHERE discipline='lol' AND last_ingest_job_id=%s", job_id
        )
        assert misses == [expected[2:]], misses
        assert live.s("SELECT count(*) FROM stats.match WHERE ingest_job_id=%s", job_id) == 0
        assert (after := durable()) == before, (request, before, after)
        live.stack.evidence.append(
            "unsupported_requests",
            {"scenario": _SCENARIO[0], "request": request, "status": 422, "code": "unknown_code", "issue": expected},
        )


def source_catalog(live: Live, ids: dict[str, Any]) -> None:
    """Contracts §6.5 / G6: the real Data Dragon sync twice, a fresh map11 row and both legacy image cases."""
    rift = ids["catalog"][LOL][RIFT]
    rows_before = live.q("SELECT id, slug, aliases FROM catalog.entity WHERE discipline='lol' ORDER BY id")
    fresh = call(
        live, ids, None, "GET", "/api/v1/catalog/{d}/{kind}/{id}", expect=200, d=LOL, kind="map", id=rift
    ).json()
    assert fresh["image_path"] and fresh["image_path"].endswith("assets/lol/map/summoners_rift.png"), fresh
    prefix = fresh["image_path"][: -len("summoners_rift.png")]
    # Legacy, already mirrored: the object exists under the old code; its path survives byte-identical.
    legacy_key = f"assets/lol/map/{LEGACY_RIFT}.png"
    asyncio.run(_put_object(live, legacy_key, b"p8-legacy-mirrored"))
    mirrored = prefix + f"{LEGACY_RIFT}.png"
    call(
        live,
        ids,
        "root",
        "PATCH",
        "/api/v1/admin/catalog/{d}/{kind}/{id}",
        {"slug": LEGACY_RIFT, "image_path": mirrored},
        expect=200,
        d=LOL,
        kind="map",
        id=rift,
    )
    second = _source_sync(live, ids)
    row = live.q("SELECT id, slug, image_path, aliases FROM catalog.entity WHERE id=%s", rift)[0]
    assert row[1] == RIFT and row[2] == mirrored and LEGACY_RIFT in row[3], row
    # Legacy, never mirrored: re-mirrored under the canonical code.
    call(
        live,
        ids,
        "root",
        "PATCH",
        "/api/v1/admin/catalog/{d}/{kind}/{id}",
        {"slug": LEGACY_RIFT, "image_path": "https://ddragon.leagueoflegends.com/legacy.png"},
        expect=200,
        d=LOL,
        kind="map",
        id=rift,
    )
    third = _source_sync(live, ids)
    row = live.q("SELECT id, slug, image_path FROM catalog.entity WHERE id=%s", rift)[0]
    assert row[1] == RIFT and row[2] == fresh["image_path"], row
    rows_after = live.q("SELECT id, slug FROM catalog.entity WHERE discipline='lol' ORDER BY id")
    assert [(r[0], r[1]) for r in rows_before] == [(r[0], r[1]) for r in rows_after]
    # FK references the scenarios created are intact.
    if "lol" in ids["matches"]:
        assert live.s("SELECT map_entity_id FROM stats.match WHERE id=%s", ids["matches"]["lol"]) == rift
    live.stack.evidence.record("source", "second_sync", second)
    live.stack.evidence.record("source", "third_sync", third)


async def _put_object(live: Live, key: str, data: bytes) -> None:
    client = live.stack.s3()
    await client.start()
    async with client._client() as raw:
        await raw.put_object(Bucket=live.stack.bucket, Key=key, Body=data)


async def _objects(live: Live, prefix: str) -> dict[str, str]:
    client = live.stack.s3()
    await client.start()
    out = {}
    async with client._client() as raw:
        for key in await client.list_objects(prefix):
            body = await raw.get_object(Bucket=live.stack.bucket, Key=key)
            out[key] = hashlib.sha256(await body["Body"].read()).hexdigest()
    return out


def _source_sync(live: Live, ids: dict[str, Any]) -> dict[str, Any]:
    """One real superuser sync plus the source facts it read (fetched again here, hashed)."""
    evidence: dict[str, Any] = {}
    try:
        versions_raw = urllib.request.urlopen(f"{DATA_DRAGON}/api/versions.json", timeout=30).read()
        version = json.loads(versions_raw)[0]
        evidence["version"] = version
        evidence["sources"] = {}
        for name, url in (
            ("versions.json", f"{DATA_DRAGON}/api/versions.json"),
            ("champion.json", f"{DATA_DRAGON}/cdn/{version}/data/en_US/champion.json"),
            ("map.json", f"{DATA_DRAGON}/cdn/{version}/data/en_US/map.json"),
        ):
            with urllib.request.urlopen(url, timeout=60) as response:
                raw = response.read()
                evidence["sources"][name] = {
                    "url": url,
                    "status": response.status,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                if name == "champion.json":
                    ahri = json.loads(raw)["data"]["Ahri"]
                    evidence["ahri"] = {"id": ahri["id"], "key": ahri["key"], "tags": ahri["tags"]}
                if name == "map.json":
                    evidence["map11"] = json.loads(raw)["data"]["11"]["MapName"]
    except OSError as exc:
        live.stack.evidence.record("source", "unavailable", repr(exc))
        pytest.fail(f"Data Dragon unavailable: unmet source evidence ({exc!r})")
    started = call(live, ids, "root", "POST", "/api/v1/admin/catalog-sync/{d}", d=LOL, expect=200).json()
    assert started["status"] == "running", started

    def finished() -> dict[str, Any] | None:
        # The sync runs in the background; its snapshot is null only if it never started or its worker died.
        state = call(live, ids, "root", "GET", "/api/v1/admin/catalog-sync/{d}", expect=200, d=LOL).json()
        return state if state["status"] != "running" else None

    evidence["sync"] = wait_until(finished, "the Data Dragon catalog sync", timeout=300, interval=2)
    assert evidence["sync"]["status"] == "done", evidence["sync"]
    evidence["rows"] = [
        list(row)
        for row in live.q(
            "SELECT id, kind, slug, attrs->>'class', aliases FROM catalog.entity WHERE discipline='lol' "
            "AND (slug IN ('ahri', %s) OR kind='map') ORDER BY id",
            RIFT,
        )
    ]
    evidence["objects"] = asyncio.run(_objects(live, "assets/lol/map/"))
    assert any(key.endswith(f"{RIFT}.png") for key in evidence["objects"]), evidence["objects"]
    return evidence


def nothing_dead_lettered(live: Live, ids: dict[str, Any]) -> None:
    """Non-destructive (G3): queues and jobs only; process exits are asserted in the fixture teardown."""
    stack = live.stack
    for game in GAMES:
        assert (stack.queue(ingest_dlq(game).name) or {}).get("messages", 0) == 0
        assert (stack.queue(ingest_replay_dlq(game).name) or {}).get("messages", 0) == 0
    assert (stack.queue(MATCH_INGESTED_TOURNAMENT_DLQ.name) or {}).get("messages", 0) == 0
    assert (stack.queue("achievement_evaluate.dlq") or {}).get("messages", 0) == 0
    assert live.s("SELECT count(*) FROM stats.ingest_job WHERE status='processing'") == 0
    stack.evidence.append(
        "ready_checks", {"check": "p8 final", "jobs": live.s("SELECT count(*) FROM stats.ingest_job")}
    )


# == tests (file order is the scenario order) =========================================================================


def _run(name: str, live: Live, ids: dict[str, Any], scenario) -> None:
    _SCENARIO[0] = name
    try:
        scenario(live, ids)
    except BaseException as exc:
        live.stack.evidence.append("errors", {"scenario": name, "error": redact(repr(exc)[:2000], live.stack.secrets)})
        raise


def test_tournament_registration(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("tournament_registration", live, p8_ids, tournament_registration)


def test_identity_journeys(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("identity_journeys", live, p8_ids, identity_journeys)


def test_balance_and_draft(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("balance_and_draft", live, p8_ids, balance_and_draft)


def test_frozen_mix(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("frozen_mix", live, p8_ids, frozen_mix)


def test_encounter_pregame(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("encounter_pregame", live, p8_ids, encounter_pregame)


def test_canonical_ingest(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("canonical_ingest", live, p8_ids, canonical_ingest)


def test_awaiting_link_and_official(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("awaiting_link_and_official", live, p8_ids, awaiting_link_and_official)


def test_readback_isolation(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("readback_isolation", live, p8_ids, readback_isolation)


def test_unsupported_and_diagnostics(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("unsupported_and_diagnostics", live, p8_ids, unsupported_and_diagnostics)


@pytest.mark.skipif(not SOURCE, reason="real Data Dragon evidence: set RUN_P8_SOURCE_SMOKE=1")
def test_source_catalog(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("source_catalog", live, p8_ids, source_catalog)


def test_nothing_dead_lettered(live: Live, p8_ids: dict[str, Any]) -> None:
    _run("nothing_dead_lettered", live, p8_ids, nothing_dead_lettered)
