"""Locust draft-room scenario — the 2026-09-30 overload pattern.

A separate locustfile on purpose: the driver WRITES (admin autopick), so it
must never ride along with the read-only public suite in ``locustfile.py``.

What it reproduces (docs/incidents/2026-09-30, "A · Перегрузка драфта"):
every captain and organizer sitting in the room re-reads the server
derivations of the board after every pick, so one pick costs
``viewers x (fit + queue)`` snapshot loads inside the 15 s cache window.

Traffic model — mirrors ``frontend/src/hooks/useDraftData.ts``:

* ``DraftDriver`` (exactly one) reads the board, fires an admin autopick every
  ``OWT_DRAFT_PICK_INTERVAL`` seconds, and bumps an in-process event counter.
  That counter stands in for the ``pick_made`` + ``pick_started`` burst the
  server publishes on ``tournament:{id}:draft`` — locust runs every user as a
  greenlet in one process, so a shared counter is the whole WS feed without a
  websocket client.
* ``DraftViewer`` — one per draft team. Wakes on the counter, waits out the
  250 ms coalescing window the room uses (``DERIVED_FLUSH_MS``), then re-reads
  fit + queue for ITS team once per burst, never once per event. The first
  ``OWT_DRAFT_ORGANIZERS`` of them also re-read feasibility. Every viewer
  polls the board on the room's 120 s safety-net interval.

Reads are grouped per endpoint, so the report's p50/p95 columns are the
per-burst latency of fit / queue / feasibility / board.

Run (see README.md):
    cd loadtests
    OWT_DRAFT_TOURNAMENT_ID=117 OWT_DRAFT_TOKEN=<organizer jwt> \\
      uv run locust -f draft_locustfile.py --headless -u 26 -r 26 -t 3m
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from typing import Any

import gevent
import requests
from locust import HttpUser, constant, events, task

import config

logger = logging.getLogger("owt.draft")

#: One re-read per burst, not per event: `DERIVED_FLUSH_MS` in useDraftData.ts.
FLUSH_SECONDS = 0.25

#: The room's safety-net board poll while the socket is up
#: (`BOARD_POLL_CONNECTED_MS`).
BOARD_POLL_SECONDS = 120.0

#: Idle step of the viewer loop — how fast a viewer notices a new burst.
TICK_SECONDS = 0.05

# Request groups. Same "[id] stands for the path parameter" convention as the
# public suite, so the stats table reads one row per draft endpoint.
NAME_TOURNAMENT_BOARD = "/api/v1/balancer/draft/tournaments/[id]/draft"
NAME_FIT = "/api/v1/balancer/draft/sessions/[id]/teams/[id]/fit"
NAME_QUEUE = "/api/v1/balancer/draft/sessions/[id]/teams/[id]/queue"
NAME_FEASIBILITY = "/api/v1/balancer/draft/sessions/[id]/feasibility"
NAME_AUTOPICK = "/api/v1/balancer/draft/picks/[id]/autopick"


class DraftRoom:
    """Board facts every simulated seat needs, plus the stand-in event feed."""

    def __init__(self, session_id: int, team_ids: list[int]) -> None:
        self.session_id = session_id
        self.team_ids = team_ids
        #: Bumped once per pick the driver lands; a viewer re-reads when it moves.
        self.generation = 0
        self._seats = itertools.count()

    def take_seat(self) -> tuple[int, int] | None:
        """Hand out the next (index, team_id); viewers past team count wrap around."""
        if not self.team_ids:
            return None
        index = next(self._seats)
        return index, self.team_ids[index % len(self.team_ids)]


_lock = threading.Lock()
_room: DraftRoom | None = None


def _board(host: str) -> dict[str, Any]:
    """Read the target tournament's board once, outside the locust statistics."""
    if config.DRAFT_TOURNAMENT_ID is None:
        raise RuntimeError("OWT_DRAFT_TOURNAMENT_ID is required by draft_locustfile.py")
    if not config.DRAFT_TOKEN:
        raise RuntimeError("OWT_DRAFT_TOKEN (or OWT_AUTH_TOKEN) is required: fit/queue/feasibility are AuthRequired")
    url = f"{host}/api/v1/balancer/draft/tournaments/{config.DRAFT_TOURNAMENT_ID}/draft"
    resp = requests.get(url, timeout=config.SEED_TIMEOUT)
    # A tournament with no draft answers 200 with a `null` body (the gateway
    # drops the body for null data) — not an error status, just no room.
    board = resp.json() if resp.content else None
    if resp.status_code != 200 or not isinstance(board, dict):
        raise RuntimeError(f"no draft board for tournament {config.DRAFT_TOURNAMENT_ID}: HTTP {resp.status_code}")
    return board


def ensure_room(host: str) -> DraftRoom:
    """Resolve the session + its teams exactly once per process."""
    global _room
    if _room is not None:
        return _room
    with _lock:
        if _room is None:
            board = _board(host.rstrip("/"))
            session = board.get("session") or {}
            status = session.get("status")
            if status != "live":
                logger.warning(
                    "draft session %s is '%s', not 'live' — the driver cannot autopick a pick that is not on the clock",
                    session.get("id"),
                    status,
                )
            _room = DraftRoom(int(session["id"]), [int(team["id"]) for team in board.get("teams", [])])
            logger.info(
                "draft room: session=%d teams=%d players=%d picks=%d",
                _room.session_id,
                len(_room.team_ids),
                len(board.get("players", [])),
                len(board.get("picks", [])),
            )
    return _room


@events.test_start.add_listener
def _resolve_room_once(environment, **_: Any) -> None:
    """Fail the run up front with one readable line instead of per-user tracebacks."""
    try:
        ensure_room(environment.host or "")
    except (RuntimeError, requests.RequestException, KeyError, ValueError) as exc:
        logger.error("draft scenario cannot start: %s", exc)
        environment.runner.quit()


class DraftUser(HttpUser):
    """Shared plumbing: the room, the bearer token, a tolerant GET."""

    abstract = True
    wait_time = constant(0)  # pacing comes from the event feed, not think time

    def on_start(self) -> None:
        self.room = ensure_room(self.host or "")
        self.client.headers["Authorization"] = f"Bearer {config.DRAFT_TOKEN}"

    def get(self, path: str, name: str) -> dict[str, Any] | None:
        with self.client.get(path, name=name, catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return None
            resp.success()
            try:
                return resp.json()
            except ValueError:
                return None

    def read_board(self) -> dict[str, Any] | None:
        return self.get(
            f"/api/v1/balancer/draft/tournaments/{config.DRAFT_TOURNAMENT_ID}/draft",
            NAME_TOURNAMENT_BOARD,
        )


class DraftViewer(DraftUser):
    """One captain/organizer seat: fit + queue for its team after every burst."""

    def on_start(self) -> None:
        super().on_start()
        seat = self.room.take_seat()
        if seat is None:
            logger.error("draft session %d has no teams", self.room.session_id)
            self.stop(force=True)
            return
        index, self.team_id = seat
        # Organizers hold the feasibility panel open; captains do not see it.
        self.is_organizer = index < config.DRAFT_ORGANIZERS
        self.seen_generation = self.room.generation
        self.next_board_poll = 0.0  # opening the room reads the board

    @task
    def room_loop(self) -> None:
        now = time.monotonic()
        if now >= self.next_board_poll:
            self.next_board_poll = now + BOARD_POLL_SECONDS
            self.read_board()
            return
        if self.room.generation == self.seen_generation:
            gevent.sleep(TICK_SECONDS)
            return
        # One re-read per burst: whatever else lands inside the window is
        # folded into this same pass, exactly like the room's coalescer.
        gevent.sleep(FLUSH_SECONDS)
        self.seen_generation = self.room.generation
        session_id = self.room.session_id
        self.get(f"/api/v1/balancer/draft/sessions/{session_id}/teams/{self.team_id}/fit", NAME_FIT)
        self.get(f"/api/v1/balancer/draft/sessions/{session_id}/teams/{self.team_id}/queue", NAME_QUEUE)
        if self.is_organizer:
            self.get(f"/api/v1/balancer/draft/sessions/{session_id}/feasibility", NAME_FEASIBILITY)


class DraftDriver(DraftUser):
    """The admin producing the pick events: one autopick per interval."""

    fixed_count = 1

    def on_start(self) -> None:
        super().on_start()
        self.drained = False

    @task
    def make_pick(self) -> None:
        board = self.read_board()
        pick = (board or {}).get("current_pick")
        if not pick:
            if not self.drained:
                self.drained = True
                logger.info("no pick on the clock — the draft is over or not started; driver idles")
            gevent.sleep(config.DRAFT_PICK_INTERVAL)
            return
        self.drained = False
        if self.autopick(int(pick["id"]), int(pick["version"])):
            self.room.generation += 1
        gevent.sleep(config.DRAFT_PICK_INTERVAL)

    def autopick(self, pick_id: int, version: int) -> bool:
        """True when a pick resolved — ours, or the server clock's."""
        with self.client.post(
            f"/api/v1/balancer/draft/picks/{pick_id}/autopick",
            name=NAME_AUTOPICK,
            json={"expected_version": version, "reason": "admin"},
            catch_response=True,
        ) as resp:
            # 409: the service's own clock fired first. The event the viewers
            # react to happened either way, so it is not a failure of the edge.
            if resp.status_code in (200, 409):
                resp.success()
                return True
            resp.failure(f"HTTP {resp.status_code}")
            return False
