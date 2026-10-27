"""Locust draft-room scenario: one live draft with its organizer, captains and spectators.

A separate locustfile on purpose: the driver WRITES (autopick, rollback, chat),
so it must never ride along with the read-only public suite in ``locustfile.py``.

The room comes from ``draft_seed.py`` (``OWT_DRAFT_ROOM``): its tournament and
session, the organizer's token, one token and team per captain, and the
logged-in spectators' tokens. Every seat is a real client of the room:

* ``DraftDriver`` (exactly one): the organizer's hands. Autopicks the pick on
  the clock every ``OWT_DRAFT_PICK_INTERVAL`` seconds; once, after
  ``OWT_DRAFT_ROLLBACK_AFTER`` picks, rolls the last pick back and resumes.
* ``DraftOrganizer`` (exactly one): the organizer's room, which also re-reads
  feasibility whenever a pick lands.
* ``DraftCaptain`` (one per seeded captain): re-reads its own fit and queue
  when an event moves its team, its pick options while it is on the clock,
  and posts to the room chat every ``OWT_DRAFT_CHAT_EVERY`` seconds.
* ``DraftSpectator`` (everyone else; as many of them as the room has spectator
  accounts log in, the rest stay anonymous): reads the room, then lives off
  the socket.

Every seat opens the page like ``frontend/src/app/draft/[id]/page.tsx``, holds
ONE WebSocket (``/api/v1/realtime/ws``) on the board and chat topics, folds
events like ``frontend/src/hooks/useDraftData.ts`` (``draftDerivedScope``,
``DERIVED_FLUSH_MS``, ``draftEventNeedsSnapshot``), polls the board while the
draft is live, and reconnects like ``frontend/src/services/realtime.service.ts``
(backoff, then a board re-read and a chat catch-up).

The socket rides locust's table as request type ``WS``: ``connect`` and
``subscribe <topic>`` latencies, ``recv <event_type>`` with the delivery delay
(receipt minus the event's ``occurred_at``; generator and stack share a clock),
``replay <event_type>`` for events a resubscribe caught up on, and a ``drop``
failure for every socket that closed under its client.

Run (the stack and the gateway restart: README.md):
    cd loadtests
    uv run python draft_seed.py --host http://127.0.0.1:8090 --teams 20 --spectator-accounts 40
    OWT_DRAFT_PICK_INTERVAL=3 OWT_DRAFT_ROLLBACK_AFTER=30 OWT_DRAFT_ORIGIN=http://localhost:8090 \\
      uv run locust -f draft_locustfile.py --host http://127.0.0.1:8090 --headless \\
      -u 182 -r 6 -t 5m --csv draft --csv-full-history --html draft.html
"""

from __future__ import annotations

import contextlib
import itertools
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import gevent
import websocket
from locust import HttpUser, constant, events, task

import config

logger = logging.getLogger("owt.draft")

#: One re-read of the derived reads per burst: trailing, no max wait (`DERIVED_FLUSH_MS`).
FLUSH_SECONDS = 0.25
#: The board's safety-net poll while the draft is live (`BOARD_POLL_CONNECTED_MS` / `_DISCONNECTED_MS`). An interval
#: timer, as React Query runs it: reads in between do not move it, a change of interval (socket up/down) or the
#: draft going live restarts it.
BOARD_POLL_CONNECTED = 120.0
BOARD_POLL_DISCONNECTED = 30.0
#: Client heartbeat; the gateway drops a socket that sent nothing for 60 s.
PING_SECONDS = 25.0
#: Idle step of a seat's loop: how fast it acts on what its socket queued.
TICK_SECONDS = 0.05

#: `draftEventNeedsSnapshot`: events the board cannot fold, so every client re-reads it.
SNAPSHOT_EVENTS = frozenset({"draft.rollback", "draft.session_updated", "draft.player_updated"})
#: `draftDerivedScope` -> null: events that move no derived read.
NO_DERIVED = frozenset({"draft.presence", "draft.overtime_started", "draft.clock_extended", "draft.paused"})
#: Events after which the captain on the clock re-reads its pick options (an active query of the current pick).
OPTIONS_EVENTS = frozenset({"draft.pick_started", "draft.resumed", "draft.overtime_started", "draft.clock_extended"})

#: `TournamentService.getPublicOverview`: the page shell's one tournament read.
OVERVIEW_QUERY = urlencode(
    [
        ("entities", entity)
        for entity in (
            "stages",
            "participants_count",
            "registrations_count",
            "teams_count",
            "links",
            "division_grid_version",
            "roster_shape",
            "rules",
        )
    ]
)

# Request groups: "[id]" stands for the path parameter, one stats row per endpoint.
NAME_ME = "/api/v1/auth/me"
NAME_WORKSPACES = "/api/v1/workspaces?scope=all"
NAME_WORKSPACE = "/api/v1/workspaces/[id]"
NAME_TOURNAMENT = "/api/v1/tournaments/[id]"
NAME_METADATA = "/api/v1/disciplines/[code]/metadata"
NAME_LOOKUP = "/api/v1/balancer/draft/tournaments/[id]/draft"
NAME_BOARD = "/api/v1/balancer/draft/sessions/[id]/board"
NAME_CHAT = "/api/v1/balancer/draft/sessions/[id]/chat"
NAME_CHAT_AFTER = "/api/v1/balancer/draft/sessions/[id]/chat?after_id"
NAME_CHAT_POST = "POST /api/v1/balancer/draft/sessions/[id]/chat"
NAME_FIT = "/api/v1/balancer/draft/sessions/[id]/teams/[id]/fit"
NAME_QUEUE = "/api/v1/balancer/draft/sessions/[id]/teams/[id]/queue"
NAME_FEASIBILITY = "/api/v1/balancer/draft/sessions/[id]/feasibility"
NAME_OPTIONS = "/api/v1/balancer/draft/picks/[id]/options"
NAME_DRIVER_BOARD = "driver: /api/v1/balancer/draft/sessions/[id]/board"
NAME_AUTOPICK = "POST /api/v1/balancer/draft/picks/[id]/autopick"
NAME_ROLLBACK = "POST /api/v1/balancer/draft/sessions/[id]/rollback"
NAME_RESUME = "POST /api/v1/balancer/draft/sessions/[id]/resume"


def _load_room() -> dict[str, Any]:
    path = Path(config.DRAFT_ROOM)
    if not path.is_file():
        raise SystemExit(f"{path} not found: seed a room first (uv run python draft_seed.py)")
    return json.loads(path.read_text(encoding="utf-8"))


ROOM = _load_room()
_captain_seats = itertools.count()
_spectator_seats = itertools.count()
_t0 = time.monotonic()


@events.test_start.add_listener
def _start_clock(**_: Any) -> None:
    global _t0
    _t0 = time.monotonic()


def at() -> str:
    """`@t+N s` (10 s buckets): failures.csv groups by message, so this places each failure in the run."""
    return f"@t+{int((time.monotonic() - _t0) // 10 * 10)}s"


def ws_metric(name: str, ms: float, *, length: int = 0, exc: BaseException | None = None) -> None:
    events.request.fire(
        request_type="WS", name=name, response_time=ms, response_length=length, exception=exc, context={}
    )


def since_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def delivery_ms(event: dict[str, Any]) -> float:
    occurred = event.get("occurred_at")
    if not occurred:
        return 0.0
    return max(0.0, (time.time() - datetime.fromisoformat(occurred).timestamp()) * 1000)


class Seat(HttpUser):
    """One browser tab in the room: the page's reads and its one socket."""

    abstract = True
    wait_time = constant(0)  # pacing comes from the room's events, not think time

    #: Reads its own team's fit and queue (a captain).
    holds_team = False
    #: Reads feasibility (an organizer).
    holds_feasibility = False

    token: str | None = None
    team_id: int | None = None

    def claim_seat(self) -> None:
        """Pick this tab's account: sets `token` (None = anonymous) and, for a captain, `team_id`."""

    def on_start(self) -> None:
        self.sid = int(ROOM["session_id"])
        self.tid = int(ROOM["tournament_id"])
        self.wsid = int(ROOM["workspace_id"])
        self.board_topic = f"draft:{self.sid}:board"
        self.chat_topic = f"draft:{self.sid}:chat"
        self.claim_seat()
        if self.token:
            self.client.headers["Authorization"] = f"Bearer {self.token}"

        self.ws: websocket.WebSocket | None = None
        self.closing = False
        self.reconnect_attempt = 0
        self.reconnect_at: float | None = None
        self.dropped = False
        self.pending_subscribe: dict[str, float] = {}

        self.last_event_id = 0
        self.live = False
        self.on_clock_team: int | None = None
        self.on_clock_pick: int | None = None
        self.chat_readable = False
        self.last_chat_id: int | None = None
        self.next_poll = 0.0

        # What the socket asked for; the reader never does I/O, this seat's loop does.
        self.need_board = False
        self.need_chat_catch_up = False
        self.need_options = False
        self.derived_teams = False
        self.derived_feasibility = False
        self.derived_due: float | None = None

        self.open_page()
        self.connect()

    def on_stop(self) -> None:
        self.closing = True
        if self.ws is not None:
            self.ws.close()

    # -- HTTP -------------------------------------------------------------

    def get(self, path: str, name: str, ok: tuple[int, ...] = (200,)) -> Any:
        with self.client.get(path, name=name, catch_response=True) as resp:
            if resp.status_code not in ok:
                resp.failure(f"HTTP {resp.status_code} {at()}")
                return None
            resp.success()
            if resp.status_code != 200 or not resp.content:
                return None
            try:
                return resp.json()
            except ValueError:
                return None

    def draft(self, path: str, **query: Any) -> str:
        """A balancer path: `apiFetch` adds the room's (entity) workspace to every live-domain call."""
        params = {"workspace_id": self.wsid, **{k: v for k, v in query.items() if v is not None}}
        return f"/api/v1/balancer/draft{path}?{urlencode(params)}"

    def open_page(self) -> None:
        # Anonymous tabs get the 401 the auth bootstrap expects.
        self.get(NAME_ME, NAME_ME, ok=(200, 401))
        self.get("/api/v1/workspaces?scope=all", NAME_WORKSPACES)
        self.get(f"/api/v1/tournaments/{self.tid}?{OVERVIEW_QUERY}", NAME_TOURNAMENT)
        # The lookup's snapshot seeds the room's own board query: one board read per page open.
        self.take_board(self.get(self.draft(f"/tournaments/{self.tid}/draft"), NAME_LOOKUP))
        self.get(f"/api/v1/disciplines/overwatch/metadata?workspace_id={self.wsid}", NAME_METADATA)
        self.get(f"/api/v1/workspaces/{self.wsid}", NAME_WORKSPACE)
        self.take_chat(self.get(self.draft(f"/sessions/{self.sid}/chat", limit=50), NAME_CHAT))
        # Derived queries mount with the room.
        self.derived_teams = self.holds_team
        self.derived_feasibility = self.holds_feasibility
        self.read_derived()
        if self.holds_team and self.on_clock_team == self.team_id:
            self.read_options()

    def take_board(self, board: dict[str, Any] | None) -> None:
        if not board:
            return
        self.last_event_id = max(self.last_event_id, int(board.get("last_event_id") or 0))
        live = board["session"]["status"] == "live"
        if live and not self.live:
            self.restart_poll()
        self.live = live
        current = board.get("current_pick")
        self.on_clock_team = current["draft_team_id"] if current else None
        self.on_clock_pick = current["id"] if current else None

    def read_board(self) -> None:
        self.take_board(self.get(self.draft(f"/sessions/{self.sid}/board"), NAME_BOARD))

    def restart_poll(self) -> None:
        self.next_poll = time.monotonic() + (BOARD_POLL_CONNECTED if self.ws is not None else BOARD_POLL_DISCONNECTED)

    def take_chat(self, envelope: dict[str, Any] | None) -> None:
        if not envelope:
            return
        viewer, settings = envelope.get("viewer") or {}, envelope.get("settings") or {}
        self.chat_readable = viewer.get("role") != "spectator" or bool(settings.get("spectators_can_read"))
        messages = envelope.get("messages") or []
        if messages:
            self.last_chat_id = max(int(m["id"]) for m in messages)

    def chat_catch_up(self) -> None:
        """`useRoomChat.refresh`: on every `subscribed` frame, re-read from the newest message on screen."""
        self.take_chat(
            self.get(self.draft(f"/sessions/{self.sid}/chat", after_id=self.last_chat_id, limit=50), NAME_CHAT_AFTER)
        )

    def read_derived(self) -> None:
        if self.derived_teams and self.team_id is not None:
            base = f"/sessions/{self.sid}/teams/{self.team_id}"
            self.get(self.draft(f"{base}/fit"), NAME_FIT)
            self.get(self.draft(f"{base}/queue"), NAME_QUEUE)
        if self.derived_feasibility:
            self.get(self.draft(f"/sessions/{self.sid}/feasibility"), NAME_FEASIBILITY)
        self.derived_teams = self.derived_feasibility = False

    def read_options(self) -> None:
        if self.on_clock_pick is not None:
            # 409: the pick resolved while the read was in flight; the next pick_started asks again.
            self.get(
                f"/api/v1/balancer/draft/picks/{self.on_clock_pick}/options?{urlencode({'workspace_id': self.wsid})}",
                NAME_OPTIONS,
                ok=(200, 409),
            )

    # -- socket -----------------------------------------------------------

    def connect(self) -> None:
        url = self.host.replace("http", "ws", 1).rstrip("/") + "/api/v1/realtime/ws"
        # The gateway reads the handshake credential from the header or cookie only (no `?token=`).
        header = [f"Authorization: Bearer {self.token}"] if self.token else None
        started = time.perf_counter()
        try:
            ws = websocket.create_connection(
                url, timeout=10, origin=config.DRAFT_ORIGIN or self.host, header=header, enable_multithread=True
            )
        except Exception as exc:  # noqa: BLE001 - every handshake failure is a failed connect
            ws_metric("connect", since_ms(started), exc=ConnectionError(f"{type(exc).__name__} {at()}"))
            self.schedule_reconnect()
            return
        ws_metric("connect", since_ms(started))
        ws.settimeout(None)
        self.ws = ws
        self.reconnect_attempt = 0
        self.restart_poll()
        gevent.spawn(self.read_loop, ws)
        gevent.spawn(self.ping_loop, ws)
        # A fresh tab subscribes live-only; a reconnect resumes from the cursor (`sendSubscribe`).
        self.subscribe(self.board_topic, after=self.last_event_id if self.dropped else None)
        if self.chat_readable:
            self.subscribe(self.chat_topic)
        if self.dropped:
            # `useDraftData`: reconnecting -> connected re-reads the board and every derived read.
            self.dropped = False
            self.need_board = True
            self.derived_teams = self.holds_team
            self.derived_feasibility = self.holds_feasibility
            self.derived_due = time.monotonic() + FLUSH_SECONDS

    def schedule_reconnect(self) -> None:
        """`realtime.service.ts`: min(1 s * 2^n, 30 s) x (0.5..1.0)."""
        delay = min(2.0**self.reconnect_attempt, 30.0) * random.uniform(0.5, 1.0)
        self.reconnect_attempt += 1
        self.reconnect_at = time.monotonic() + delay

    def subscribe(self, topic: str, after: int | None = None) -> None:
        frame: dict[str, Any] = {"op": "subscribe", "topic": topic}
        if after is not None:
            frame["after_event_id"] = after
        self.pending_subscribe[topic] = time.perf_counter()
        self.send(frame)

    def send(self, frame: dict[str, Any]) -> None:
        ws = self.ws
        if ws is None:
            return
        # A failed send means the socket is gone; its reader reports the drop.
        with contextlib.suppress(Exception):
            ws.send(json.dumps(frame))

    def ping_loop(self, ws: websocket.WebSocket) -> None:
        while True:
            gevent.sleep(PING_SECONDS)
            if ws is not self.ws:
                return
            self.send({"op": "ping"})

    def read_loop(self, ws: websocket.WebSocket) -> None:
        try:
            while True:
                raw = ws.recv()
                if not raw:
                    raise ConnectionError("socket closed")
                self.on_frame(json.loads(raw), len(raw))
        except Exception as exc:  # noqa: BLE001 - any read failure ends this socket
            if ws is self.ws and not self.closing:
                self.ws = None
                self.dropped = True
                self.restart_poll()
                ws_metric("drop", 0, exc=ConnectionError(f"{type(exc).__name__} {at()}"))
                self.schedule_reconnect()

    def on_frame(self, frame: dict[str, Any], size: int) -> None:
        op, topic = frame.get("op"), frame.get("topic") or ""
        if op == "event":
            event = frame.get("event") or {}
            kind = event.get("event_type", "?")
            if topic in self.pending_subscribe:
                # Delivered with the subscription ack: a catch-up, not live delivery.
                ws_metric(f"replay {kind}", 0, length=size)
            else:
                ws_metric(f"recv {kind}", delivery_ms(event), length=size)
            if topic == self.board_topic:
                self.on_board_event(kind, event)
        elif op == "subscribed":
            started = self.pending_subscribe.pop(topic, None)
            if started is not None:
                ws_metric(f"subscribe {topic.rsplit(':', 1)[-1]}", since_ms(started), length=size)
            if topic == self.chat_topic:
                self.need_chat_catch_up = True
        elif op == "error":
            ws_metric(f"error {frame.get('code')}", 0, exc=RuntimeError(f"{frame.get('message')} {at()}"))

    def on_board_event(self, kind: str, event: dict[str, Any]) -> None:
        if kind == "draft.presence":
            return
        data = event.get("data") or {}
        self.last_event_id = max(self.last_event_id, int(event.get("event_id") or 0))
        if kind in ("draft.pick_started", "draft.resumed"):
            if not self.live:
                self.restart_poll()
            self.live = True
            self.on_clock_team = data.get("draft_team_id", self.on_clock_team)
            self.on_clock_pick = data.get("pick_id", self.on_clock_pick)
        elif kind in ("draft.paused", "draft.rollback", "draft.blocked", "draft.completed", "draft.cancelled"):
            self.live = False
        if kind in SNAPSHOT_EVENTS or (kind == "draft.blocked" and data.get("blocked_reason") == "order_recalculated"):
            self.need_board = True
        if kind in OPTIONS_EVENTS and self.holds_team and self.on_clock_team == self.team_id:
            self.need_options = True
        if kind in NO_DERIVED:
            return
        if kind in ("draft.pick_made", "draft.autopicked"):
            team, feasibility = data.get("draft_team_id"), True
        elif kind in ("draft.pick_started", "draft.resumed"):
            team, feasibility = data.get("draft_team_id"), False
        else:
            team, feasibility = None, True  # every team
        if self.holds_team and team in (None, self.team_id):
            self.derived_teams = True
        if self.holds_feasibility and feasibility:
            self.derived_feasibility = True
        if self.derived_teams or self.derived_feasibility:
            self.derived_due = time.monotonic() + FLUSH_SECONDS  # trailing: every event pushes it

    # -- the tab's loop ---------------------------------------------------

    def chat_turn(self) -> bool:
        """A seat's own chat traffic; True when it spent this turn."""
        return False

    @task
    def room_loop(self) -> None:
        now = time.monotonic()
        if self.ws is None and self.reconnect_at is not None and now >= self.reconnect_at:
            self.reconnect_at = None
            self.connect()
        elif self.need_board:
            self.need_board = False
            self.read_board()
        elif self.need_chat_catch_up:
            self.need_chat_catch_up = False
            self.chat_catch_up()
        elif self.need_options:
            self.need_options = False
            self.read_options()
        elif self.derived_due is not None and now >= self.derived_due:
            self.derived_due = None
            self.read_derived()
        elif self.live and now >= self.next_poll:
            self.restart_poll()
            self.read_board()
        elif not self.chat_turn():
            gevent.sleep(TICK_SECONDS)


class DraftSpectator(Seat):
    """A viewer: logged in while the room has spectator accounts left, anonymous after."""

    def claim_seat(self) -> None:
        index = next(_spectator_seats)
        accounts = ROOM["spectators"]
        self.token = accounts[index]["token"] if index < len(accounts) else None


class DraftCaptain(Seat):
    """A captain: its own fit, queue and options, and some chat."""

    fixed_count = len(ROOM["captains"])
    holds_team = True

    def claim_seat(self) -> None:
        seat = ROOM["captains"][next(_captain_seats) % len(ROOM["captains"])]
        self.token, self.team_id = seat["token"], int(seat["team_id"])
        every = config.DRAFT_CHAT_EVERY
        self.next_chat = time.monotonic() + random.uniform(0, every) if every > 0 else None

    def chat_turn(self) -> bool:
        if self.next_chat is None or time.monotonic() < self.next_chat:
            return False
        self.next_chat = time.monotonic() + config.DRAFT_CHAT_EVERY
        with self.client.post(
            self.draft(f"/sessions/{self.sid}/chat"),
            name=NAME_CHAT_POST,
            json={"body": f"gl hf from team {self.team_id}"},
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code} {at()}")
        return True


class DraftOrganizer(Seat):
    """The organizer's room: everything a viewer reads, plus feasibility after every pick."""

    fixed_count = 1
    holds_feasibility = True

    def claim_seat(self) -> None:
        self.token = ROOM["organizer"]["token"]


class DraftDriver(HttpUser):
    """The organizer's hands: one autopick per interval, one rollback + resume if asked."""

    fixed_count = 1
    wait_time = constant(0)

    def on_start(self) -> None:
        self.client.headers["Authorization"] = f"Bearer {ROOM['organizer']['token']}"
        self.sid = int(ROOM["session_id"])
        self.picks = 0
        self.rolled_back = False
        self.drained = False

    def post(self, path: str, name: str, body: Any = None, ok: tuple[int, ...] = (200,)) -> bool:
        with self.client.post(path, name=name, json=body, catch_response=True) as resp:
            if resp.status_code in ok:
                resp.success()
                return True
            resp.failure(f"HTTP {resp.status_code} {at()}")
            return False

    @task
    def drive(self) -> None:
        gevent.sleep(config.DRAFT_PICK_INTERVAL)
        # The organizer's own action refetches its board (`onSettled: invalidate`).
        with self.client.get(
            f"/api/v1/balancer/draft/sessions/{self.sid}/board", name=NAME_DRIVER_BOARD, catch_response=True
        ) as resp:
            board = resp.json() if resp.status_code == 200 else None
        if board is None:
            return
        pick = board.get("current_pick")
        if board["session"]["status"] == "paused":
            self.post(f"/api/v1/balancer/draft/sessions/{self.sid}/resume", NAME_RESUME)
            return
        if not pick:
            if not self.drained:
                self.drained = True
                logger.info("no pick on the clock: the draft is over; the driver idles")
            return
        # 409: the server clock resolved the pick first; the room saw an event either way.
        if not self.post(
            f"/api/v1/balancer/draft/picks/{pick['id']}/autopick",
            NAME_AUTOPICK,
            {"expected_version": pick["version"], "reason": "admin"},
            ok=(200, 409),
        ):
            return
        self.picks += 1
        if (
            config.DRAFT_ROLLBACK_AFTER is not None
            and not self.rolled_back
            and self.picks >= config.DRAFT_ROLLBACK_AFTER
        ):
            self.rolled_back = True
            gevent.sleep(config.DRAFT_PICK_INTERVAL)
            # The draft stays paused after a rollback; the next turn resumes it.
            self.post(f"/api/v1/balancer/draft/sessions/{self.sid}/rollback", NAME_ROLLBACK)
