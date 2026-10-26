"""Opt-in live-stack fixture: real subprocesses against real PostgreSQL, RabbitMQ, Redis and an S3-compatible store.

Reusable by later phases. Nothing here runs unless the caller asks for it (``RUN_P5_LIVE_SMOKE=1`` in
``test_ingest_live_smoke.py``, ``RUN_P8_LIVE_SMOKE=1`` in ``test_two_game_live_scenarios.py``). Every dependency is
loopback-only and the fixture owns exactly the resources whose
generated names it created:

* PostgreSQL: the administrative connection is the committed ``anak_test`` DSN (``is_ephemeral_test_dsn``) used only to
  ``CREATE``/``DROP`` the scratch database ``test_p5_ingest_<uuid4 hex>``, migrated to head. ``anak_test`` itself is never
  touched.
* RabbitMQ: a ``p5smoke_<hex>`` vhost created and deleted through the local management API.
* S3: a ``p5-smoke-<hex>`` bucket created/emptied/deleted through the repository's ``S3Client``.
* Redis: one empty logical database of the configured server, flushed on exit.

Child processes (``subprocess.Popen``, explicit cwd/env, output to a temp directory) are the real entry points: stats
``serve_rpc`` and ``serve_worker``, identity ``serve``, tournament ``serve`` (outbox drain + evidence consumer) and the
built Go gateway, plus app ``serve`` and balancer ``serve`` when :func:`bring_up` is asked for them. Readiness is
observed (broker consumers, ``/health``, answered RPC), never slept.

:func:`bring_up` is the shared world both live smokes start from: the P5 identity/grid/case world seeded into a fresh
stack, wrapped in :class:`Live` (the HTTP and SQL client the tests drive it with).
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql

from shared.clients.s3 import S3Client
from shared.messaging.config import MATCH_INGESTED_TOURNAMENT_QUEUE, ingest_queue
from shared.testing.db import is_ephemeral_test_dsn, postgres_env

if TYPE_CHECKING:
    from tests.ingest_seed import IngestCase

STATS = Path(__file__).resolve().parents[1]
BACKEND = STATS.parent
REPO = BACKEND.parent
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
DB_NAME = re.compile(r"test_p5_ingest_[0-9a-f]{32}")
VHOST_NAME = re.compile(r"p5smoke_[0-9a-f]{16}")
BUCKET_NAME = re.compile(r"p5-smoke-[0-9a-f]{16}")
REQUIRED = (
    "P5_SMOKE_RABBITMQ_URL",
    "P5_SMOKE_RABBITMQ_MANAGEMENT_URL",
    "P5_SMOKE_REDIS_URL",
    "P5_SMOKE_S3_ENDPOINT_URL",
    "P5_SMOKE_S3_ACCESS_KEY",
    "P5_SMOKE_S3_SECRET_KEY",
)
REDIS_OWNER_KEY = "p5smoke:owner"
JWT_SECRET = "p5-live-smoke-secret-" + "x" * 24
SECRET_PATTERNS = (
    re.compile(r"owt_sk_[A-Za-z0-9_\-]+"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"),
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"(?i)(amqps?|redis|postgres(?:ql)?(?:\+\w+)?)://[^\s/@]*:[^\s/@]*@"),
)


def jwt_public_key(secret: str) -> str:
    """The gateway's ``JWT_PUBLIC_KEY`` for identity's ``JWT_SECRET_KEY``: the raw Ed25519 public key, base64url
    without padding. Uses identity's own ``key_derivation`` (stdlib-only), loaded by path: ``src`` here is stats'."""
    path = BACKEND / "identity-service" / "src" / "core" / "key_derivation.py"
    spec = importlib.util.spec_from_file_location("_identity_key_derivation", path)
    assert spec is not None and spec.loader is not None
    key_derivation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(key_derivation)
    raw = Ed25519PrivateKey.from_private_bytes(key_derivation.jwt_signing_seed(secret)).public_key().public_bytes_raw()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def require_loopback(url: str, what: str) -> None:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host not in LOOPBACK:
        pytest.fail(f"{what} must be a loopback address, got host {host!r}")


def free_port() -> int:
    """A currently free loopback port; re-checked by the caller right before use via :func:`assert_port_free`."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def assert_port_free(port: int) -> None:
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            pytest.fail(f"port {port} is already in use")


def wait_until(predicate: Callable[[], Any], what: str, *, timeout: float = 90.0, interval: float = 0.25) -> Any:
    """Poll ``predicate`` until truthy within a bounded deadline; the failure names what never happened."""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except Exception as exc:  # not up yet
            last = repr(exc)
        else:
            if last:
                return last
        time.sleep(interval)
    pytest.fail(f"timed out after {timeout:.0f}s waiting for {what}; last observation: {last!r}")


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    raw: bytes

    def json(self) -> Any:
        return json.loads(self.raw) if self.raw else None


def http(
    method: str, url: str, *, body: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 30
) -> Response:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        return Response(exc.code, dict(exc.headers), exc.read())


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("***", text)
    return text


@dataclass
class Proc:
    name: str
    argv: list[str]
    cwd: str
    popen: subprocess.Popen
    log: Path
    started_at: float
    exit_code: int | None = None
    tree: list[int] = field(default_factory=list)
    #: Set once the process and its descendants are confirmed gone: cached pids are then never acted on again
    #: (an OS may have reused them for an unrelated process).
    reaped: bool = False
    #: pid -> creation identity captured with the tree: a pid is only ever signalled or declared gone by identity.
    identities: dict[int, int | None] = field(default_factory=dict)

    def snapshot(self) -> list[int]:
        self.tree = process_tree(self.pid)
        self.identities = {pid: process_identity(pid) for pid in self.tree}
        return self.tree

    @property
    def pid(self) -> int:
        return self.popen.pid

    def alive(self) -> bool:
        return self.popen.poll() is None


def _alive_windows(pid: int) -> bool:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def process_identity(pid: int) -> int | None:
    """The process's creation time (Windows FILETIME / Linux start ticks): with the pid it identifies one process.

    ``None`` when it cannot be read (no such process, or no /proc): the caller must then treat the pid as unverifiable.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, other = wintypes.FILETIME(), [wintypes.FILETIME() for _ in range(3)]
            if not ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(created), *map(ctypes.byref, other)):
                return None
            return (created.dwHighDateTime << 32) | created.dwLowDateTime
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat.rsplit(")", 1)[1].split()[19])  # field 22: starttime, after the parenthesised comm
    except (OSError, ValueError, IndexError):
        return None


def _alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def process_tree(pid: int) -> list[int]:
    """``pid`` and every live descendant.

    On Windows a venv's ``python.exe`` is a launcher that spawns the real interpreter, so ``Popen.pid`` alone is not the
    process under test: pausing or waiting on it must cover the whole tree.
    """
    if os.name != "nt":
        found = [pid]
        for child in subprocess.run(
            ["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False
        ).stdout.split():
            found.extend(process_tree(int(child)))
        return found
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel = ctypes.windll.kernel32
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    parents: dict[int, list[int]] = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = kernel.Process32First(snapshot, ctypes.byref(entry))
        while more:
            parents.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            more = kernel.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    found, queue = [], [pid]
    while queue:
        current = queue.pop(0)
        found.append(current)
        queue.extend(child for child in parents.get(current, []) if child not in found)
    return [p for p in found if p == pid or _alive_windows(p)]


def _suspend_windows(pid: int, suspend: bool) -> None:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if not handle:
        raise OSError(f"cannot open process {pid}")
    try:
        status = (ctypes.windll.ntdll.NtSuspendProcess if suspend else ctypes.windll.ntdll.NtResumeProcess)(handle)
        if status:
            raise OSError(f"NtSuspend/ResumeProcess({pid}) failed with {status:#x}")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


@dataclass
class Evidence:
    """What the run proves, written outside tracked source: no key, token or raw identity content."""

    directory: Path
    data: dict[str, Any] = field(
        default_factory=lambda: {
            "commands": [],
            "process_pids": {},
            "ready_checks": [],
            "job_ids": {},
            "status_transitions": {},
            "match_ids": {},
            "revisions": {},
            "observation_counts": {},
            "outbox_event_ids": {},
            "receipt_outcomes": {},
            "exit_codes": {},
            # P8: the two-game scenarios' own evidence.
            "run": {},
            "http_operations": [],
            "sql_invariants": {},
            "source_positions": {},
            "unsupported_requests": [],
            "source": {},
            "scenario_ids": {},
            "errors": [],
        }
    )

    def record(self, section: str, key: str, value: Any) -> None:
        self.data[section][key] = value

    def append(self, section: str, value: Any) -> None:
        self.data[section].append(value)

    def write(self) -> Path:
        path = self.directory / "evidence.json"
        path.write_text(json.dumps(self.data, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return path


class LiveStack:
    """Provisions the owned resources, then starts/stops/kills/pauses the real processes against them."""

    def __init__(self, evidence_dir: Path | None = None) -> None:
        missing = [name for name in REQUIRED if not os.environ.get(name)]
        if missing:
            pytest.fail(
                f"the live smoke needs {', '.join(missing)} (see docs/releases/2026-10-15-multi-game-p5-ingest.md)"
            )
        self.amqp = os.environ["P5_SMOKE_RABBITMQ_URL"]
        self.mgmt_url = os.environ["P5_SMOKE_RABBITMQ_MANAGEMENT_URL"].rstrip("/")
        self.redis_url = os.environ["P5_SMOKE_REDIS_URL"]
        self.s3_endpoint = os.environ["P5_SMOKE_S3_ENDPOINT_URL"]
        self.s3_access = os.environ["P5_SMOKE_S3_ACCESS_KEY"]
        self.s3_secret = os.environ["P5_SMOKE_S3_SECRET_KEY"]
        for url, what in (
            (self.amqp, "P5_SMOKE_RABBITMQ_URL"),
            (self.mgmt_url, "P5_SMOKE_RABBITMQ_MANAGEMENT_URL"),
            (self.redis_url, "P5_SMOKE_REDIS_URL"),
            (self.s3_endpoint, "P5_SMOKE_S3_ENDPOINT_URL"),
        ):
            require_loopback(url, what)
        # The administrative connection is the committed ephemeral test server; the scratch database is generated here.
        if not is_ephemeral_test_dsn():
            pytest.fail(
                "refusing: POSTGRES_* is not the committed ephemeral test PostgreSQL (127.0.0.1:55432/anak_test)"
            )
        self.pg = postgres_env()
        require_loopback(f"//{self.pg['host']}", "POSTGRES_HOST")
        suffix = uuid.uuid4().hex
        self.db = f"test_p5_ingest_{suffix}"
        self.vhost = f"p5smoke_{suffix[:16]}"
        self.bucket = f"p5-smoke-{suffix[16:32]}"
        assert DB_NAME.fullmatch(self.db) and VHOST_NAME.fullmatch(self.vhost) and BUCKET_NAME.fullmatch(self.bucket)
        amqp = urllib.parse.urlsplit(self.amqp)
        self.amqp_user, self.amqp_password = (
            urllib.parse.unquote(amqp.username or ""),
            urllib.parse.unquote(amqp.password or ""),
        )
        self.vhost_url = amqp._replace(path="/" + urllib.parse.quote(self.vhost, safe="")).geturl()
        self.redis_db: int | None = None
        self.redis_token = uuid.uuid4().hex
        self.directory = Path(evidence_dir or tempfile.mkdtemp(prefix="p5-live-smoke-"))
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "logs").mkdir(exist_ok=True)
        self.evidence = Evidence(self.directory)
        self.procs: dict[str, Proc] = {}
        self.ports: dict[str, int] = {}
        self._created: dict[str, bool] = {"db": False, "vhost": False, "bucket": False, "redis": False}
        self.gateway_binary: Path | None = None
        # Private identities a scenario seeds (handles, emails, logins): redacted from logs and errors like secrets.
        self.identities: set[str] = set()

    # -- resources --------------------------------------------------------------------------------------------

    @property
    def db_url(self) -> str:
        return f"postgresql+psycopg://{self.pg['user']}:{self.pg['password']}@{self.pg['host']}:{self.pg['port']}/{self.db}"

    @property
    def redis(self) -> str:
        return f"{self._redis_root()}/{self.redis_db}"

    def _admin(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.pg["host"],
            port=int(self.pg["port"]),
            user=self.pg["user"],
            password=self.pg["password"],
            dbname="postgres",
            autocommit=True,
        )

    def connect(self) -> psycopg.Connection:
        assert DB_NAME.fullmatch(self.db)
        return psycopg.connect(
            host=self.pg["host"],
            port=int(self.pg["port"]),
            user=self.pg["user"],
            password=self.pg["password"],
            dbname=self.db,
            autocommit=True,
        )

    def query(self, statement: str, params: tuple | dict | None = None) -> list[tuple]:
        with self.connect() as connection:
            return connection.execute(statement, params).fetchall()

    def scalar(self, statement: str, params: tuple | dict | None = None) -> Any:
        rows = self.query(statement, params)
        return rows[0][0] if rows else None

    def mgmt(self, path: str, *, method: str = "GET", body: dict | None = None) -> Response:
        token = base64.b64encode(f"{self.amqp_user}:{self.amqp_password}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
        return http(
            method,
            f"{self.mgmt_url}/api/{path}",
            body=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            timeout=10,
        )

    def queue(self, name: str) -> dict | None:
        response = self.mgmt(f"queues/{urllib.parse.quote(self.vhost, safe='')}/{urllib.parse.quote(name, safe='')}")
        return response.json() if response.status == 200 else None

    def consumers(self, name: str) -> int:
        queue = self.queue(name)
        return int(queue.get("consumers", 0)) if queue else 0

    def provision(self) -> None:
        migrated_env = {
            **os.environ,
            "DATABASE_URL": self.db_url,
            "OWT_APPLY_ENCOUNTER_LAYER_DROP": "1",
            "OWT_APPLY_LEGACY_DROP": "1",
        }
        # Every dependency is awaited (bounded) before anything is created in it.
        wait_until(lambda: self.mgmt("overview").status == 200, "RabbitMQ management API", timeout=120)
        wait_until(lambda: self._redis_client(0).ping(), "Redis to answer PING", timeout=60)
        wait_until(lambda: asyncio.run(self._s3_ready()), "the S3 endpoint to list buckets", timeout=60)
        quoted = urllib.parse.quote(self.vhost, safe="")
        assert self.mgmt(f"vhosts/{quoted}", method="PUT", body={}).status in (201, 204)
        self._created["vhost"] = True
        grant = {"configure": ".*", "write": ".*", "read": ".*"}
        assert self.mgmt(
            f"permissions/{quoted}/{urllib.parse.quote(self.amqp_user, safe='')}", method="PUT", body=grant
        ).status in (201, 204)
        self.evidence.append("ready_checks", {"check": "rabbitmq vhost created", "vhost": self.vhost})

        # Exclusive reservation: an atomic SET NX of an ownership key. An empty DBSIZE alone would let two sessions
        # claim the same database; here only one SET NX wins, a database holding foreign data is released again and
        # skipped, and cleanup flushes a database only after re-reading its own token.
        for candidate in range(1, 16):
            client = self._redis_client(candidate)
            if not client.set(REDIS_OWNER_KEY, self.redis_token, nx=True):
                continue
            if client.dbsize() == 1:
                self.redis_db = candidate
                self._created["redis"] = True
                break
            client.delete(REDIS_OWNER_KEY)
        else:
            pytest.fail("no unreserved, empty Redis logical database (1-15) available for the smoke")
        self.evidence.append("ready_checks", {"check": "redis database claimed", "db": self.redis_db})

        asyncio.run(self._create_bucket())
        self._created["bucket"] = True
        self.evidence.append("ready_checks", {"check": "s3 bucket created", "bucket": self.bucket})

        with self._admin() as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.db)))
        self._created["db"] = True
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=migrated_env,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        self.evidence.append(
            "commands", {"cmd": "alembic upgrade head", "database": self.db, "exit": result.returncode}
        )
        if result.returncode:
            pytest.fail(f"migration failed:\n{result.stdout[-2000:]}\n{result.stderr[-3000:]}")
        self.evidence.append("ready_checks", {"check": "database migrated to head", "database": self.db})

    def _redis_client(self, db: int):
        import redis

        return redis.Redis.from_url(f"{self._redis_root()}/{db}", socket_timeout=5, socket_connect_timeout=5)

    async def _s3_ready(self) -> bool:
        client = self.s3()
        await client.start()
        async with client._client() as raw:
            await raw.list_buckets()
        return True

    def _redis_root(self) -> str:
        parts = urllib.parse.urlsplit(self.redis_url)
        return parts._replace(path="", query="", fragment="").geturl().rstrip("/")

    def s3(self) -> S3Client:
        return S3Client(self.s3_access, self.s3_secret, self.s3_endpoint, self.bucket)

    async def _create_bucket(self) -> None:
        client = self.s3()
        await client.start()
        async with client._client() as raw:
            await raw.create_bucket(Bucket=self.bucket)

    async def _drop_bucket(self) -> None:
        client = self.s3()
        await client.start()
        for key in await client.list_objects(""):
            await client.delete_object(key)
        async with client._client() as raw:
            await raw.delete_bucket(Bucket=self.bucket)

    # -- processes --------------------------------------------------------------------------------------------

    def env(self, **extra: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            POSTGRES_DB=self.db,
            POSTGRES_HOST=self.pg["host"],
            POSTGRES_PORT=str(self.pg["port"]),
            POSTGRES_USER=self.pg["user"],
            POSTGRES_PASSWORD=self.pg["password"],
            RABBITMQ_URL=self.vhost_url,
            RABBITMQ_MANAGEMENT_URL=self.mgmt_url,
            RABBITMQ_MANAGEMENT_USER=self.amqp_user,
            RABBITMQ_MANAGEMENT_PASSWORD=self.amqp_password,
            REDIS_URL=self.redis,
            S3_ENDPOINT_URL=self.s3_endpoint,
            S3_ACCESS_KEY=self.s3_access,
            S3_SECRET_KEY=self.s3_secret,
            S3_BUCKET_NAME=self.bucket,
            # Path-style, on loopback: the catalog sync's image mirror answers with public URLs.
            S3_PUBLIC_URL=f"{self.s3_endpoint.rstrip('/')}/{self.bucket}",
            JWT_SECRET_KEY=JWT_SECRET,
            LOGS_ROOT_PATH=str(self.directory / "logs"),
            JSON_LOGGING="false",
            LOG_LEVEL="info",
            QUOTA_ENABLED="false",
            PYTHONPATH=str(BACKEND),
            TRACING_ENABLED="false",
            SENTRY_DSN="",
            # Nothing may leave the machine: the rank collector's schedule is admin-gated and off in a fresh database, and
            # its base URL points at a closed loopback port as a second guard.
            OVERFAST_BASE_URL="http://127.0.0.1:9",
        )
        env.pop("STATS_DISCIPLINES", None)
        env.update(extra)
        return env

    @property
    def secrets(self) -> list[str]:
        # Longest first: a handle is replaced whole before its game-name part.
        return [
            self.amqp_password,
            self.s3_secret,
            JWT_SECRET,
            self.pg["password"],
            *sorted(self.identities, key=len, reverse=True),
        ]

    def start(self, name: str, argv: list[str], *, cwd: Path, env: dict[str, str]) -> Proc:
        assert name not in self.procs or not self.procs[name].alive(), f"{name} is already running"
        log = self.directory / f"{name}.raw.log"
        handle = open(log, "wb")  # noqa: SIM115 - owned by the child for its lifetime
        popen = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        proc = Proc(name, argv, str(cwd), popen, log, time.monotonic())
        self.procs[name] = proc
        self.evidence.record("process_pids", name, popen.pid)
        self.evidence.append(
            "commands",
            {
                "process": name,
                "cwd": str(cwd.relative_to(REPO)),
                "argv": [Path(argv[0]).name, *argv[1:]],
                "pid": popen.pid,
            },
        )
        return proc

    def faststream(self, name: str, service: str, module: str, *, port: int, **extra: str) -> Proc:
        assert_port_free(port)
        self.ports[name] = port
        return self.start(
            name,
            [sys.executable, "-m", "faststream", "run", f"{module}:app"],
            cwd=BACKEND / service,
            env=self.env(WORKER_METRICS_PORT=str(port), **extra),
        )

    def worker_env(self, disciplines: str | None) -> dict[str, str]:
        # A short, test-only reaper: a claim older than 12s is reclaimed on the next 2s tick, and a request that was
        # delivered to a frozen consumer is re-requested after 15s (production keeps the pending window above the
        # 5-minute queue TTL; claim fencing is what makes a double delivery safe).
        extra = {
            "LOG_REAPER_TICK_SECONDS": "2",
            "LOG_REAPER_PROCESSING_AFTER_SECONDS": "12",
            "LOG_REAPER_PENDING_AFTER_SECONDS": "15",
        }
        if disciplines is not None:
            extra["STATS_DISCIPLINES"] = disciplines
        return extra

    def build_gateway(self) -> Path:
        binary = self.directory / ("gateway.exe" if os.name == "nt" else "gateway")
        result = subprocess.run(
            ["go", "build", "-o", str(binary), "./cmd/gateway"],
            cwd=REPO / "gateway",
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        self.evidence.append("commands", {"cmd": "go build ./cmd/gateway", "exit": result.returncode})
        if result.returncode:
            pytest.fail(f"gateway build failed:\n{result.stderr[-2000:]}")
        self.gateway_binary = binary
        return binary

    def start_gateway(self) -> Proc:
        binary = self.gateway_binary or self.build_gateway()
        port, metrics = free_port(), free_port()
        assert_port_free(port)
        assert_port_free(metrics)
        self.ports["gateway"], self.ports["gateway_metrics"] = port, metrics
        env = self.env(
            GATEWAY_PORT=str(port),
            GATEWAY_METRICS_PORT=str(metrics),
            GATEWAY_ENV="development",
            LOG_FILE=str(self.directory / "logs" / "gateway.log"),
            GATEWAY_API_KEY_RATE_LIMIT="10000",
            JWT_PUBLIC_KEY=jwt_public_key(JWT_SECRET),
            GATEWAY_AUTH_RATE_LIMIT="10000",
            GATEWAY_ANON_RATE_LIMIT="0",
        )
        return self.start("gateway", [str(binary)], cwd=REPO / "gateway", env=env)

    @property
    def gateway(self) -> str:
        return f"http://127.0.0.1:{self.ports['gateway']}"

    def health(self, name: str) -> tuple[int, str]:
        response = (
            http("GET", f"http://127.0.0.1:{self.ports[name]}/health", timeout=5)
            if name != "gateway"
            else http("GET", f"{self.gateway}/health", timeout=5)
        )
        return response.status, response.raw.decode(errors="replace")

    def ready(self, name: str, what: str, predicate: Callable[[], Any], *, timeout: float = 120) -> Any:
        proc = self.procs[name]

        def check() -> Any:
            if not proc.alive():
                pytest.fail(
                    f"{name} exited with {proc.popen.returncode} before becoming ready ({what}); see {proc.log.name}"
                )
            return predicate()

        result = wait_until(check, f"{name}: {what}", timeout=timeout)
        proc.snapshot()
        self.evidence.record("process_pids", name, proc.tree)
        self.evidence.append(
            "ready_checks",
            {
                "process": name,
                "pid": proc.pid,
                "tree": proc.tree,
                "check": what,
                "seconds": round(time.monotonic() - proc.started_at, 1),
            },
        )
        return result

    def rpc(self, subject: str, payload: dict, *, timeout: float = 30) -> dict:
        from faststream.rabbit import RabbitBroker

        from shared.messaging.rpc import request_dict

        async def call() -> dict:
            broker = RabbitBroker(self.vhost_url)
            await broker.start()
            try:
                return await request_dict(broker, payload, subject, timeout=timeout)
            finally:
                await broker.stop()

        return asyncio.run(call())

    def stop(self, name: str, *, grace: float = 45) -> int | None:
        """Ask the process (and its whole group) to stop; anything left after ``grace`` is killed."""
        proc = self.procs[name]
        if proc.popen.poll() is None:
            proc.snapshot()
            proc.reaped = False
            if os.name == "nt":
                proc.popen.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.popen.terminate()
            try:
                proc.popen.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                self.kill(name)
        self._reap_tree(proc)
        proc.exit_code = proc.popen.returncode
        self.evidence.record("exit_codes", name, proc.exit_code)
        return proc.exit_code

    def kill(self, name: str) -> int | None:
        """Hard-kill the process tree (no graceful shutdown): what a crashed worker looks like."""
        proc = self.procs[name]
        launcher_alive = proc.popen.poll() is None
        tree = proc.snapshot() if launcher_alive else []
        if launcher_alive:
            proc.reaped = False
        if not launcher_alive:
            pass  # the launcher is gone: its pid may be reused, so nothing is signalled by pid
        elif os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
        else:
            for pid in reversed(tree):
                os.kill(pid, signal.SIGKILL)
        proc.popen.wait(timeout=30)
        self._reap_tree(proc)
        proc.exit_code = proc.popen.returncode
        self.evidence.record("exit_codes", name, proc.exit_code)
        return proc.exit_code

    def _reap_tree(self, proc: Proc) -> None:
        """A launcher can exit before the interpreter it spawned: nothing of a stopped process may keep running.

        Only a pid whose creation identity still matches the one recorded with the tree counts as ours: a different
        identity means the pid was reused (it is gone and is never signalled). A live pid whose identity cannot be
        verified is neither killed nor declared gone: it is reported as a teardown failure. Verified survivors get a
        short grace, then are force-killed; one that still lives is an error too.
        """

        def alive(pid: int) -> bool:
            return _alive_windows(pid) if os.name == "nt" else _alive_posix(pid)

        def ours(pid: int) -> bool:
            expected = proc.identities.get(pid)
            return expected is not None and process_identity(pid) == expected

        if proc.reaped:
            return
        live = [pid for pid in proc.tree if pid != proc.pid and alive(pid)]
        unverifiable = [pid for pid in live if proc.identities.get(pid) is None or process_identity(pid) is None]
        survivors = [pid for pid in live if pid not in unverifiable and ours(pid)]
        deadline = time.monotonic() + 10
        while survivors and time.monotonic() < deadline:
            time.sleep(0.25)
            survivors = [pid for pid in survivors if alive(pid) and ours(pid)]
        for pid in survivors:
            if not ours(pid):
                continue
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
            else:
                os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while survivors and time.monotonic() < deadline:
            time.sleep(0.25)
            survivors = [pid for pid in survivors if alive(pid) and ours(pid)]
        if survivors or unverifiable:
            raise RuntimeError(
                f"{proc.name}: verified processes {survivors} survived a forced kill; "
                f"processes {unverifiable} are alive but their identity cannot be verified (left untouched)"
            )
        proc.tree, proc.identities, proc.reaped = [], {}, True

    def pause(self, name: str) -> None:
        """Freeze every process of the tree (SIGSTOP / NtSuspendProcess): a worker stuck inside a job."""
        proc = self.procs[name]
        for pid in proc.snapshot():
            if os.name == "nt":
                _suspend_windows(pid, True)
            else:
                os.kill(pid, signal.SIGSTOP)

    def resume(self, name: str) -> None:
        proc = self.procs[name]
        for pid in reversed(proc.tree):
            if os.name == "nt":
                _suspend_windows(pid, False)
            else:
                os.kill(pid, signal.SIGCONT)

    def log_text(self, name: str) -> str:
        return redact(self.procs[name].log.read_text(errors="replace"), self.secrets)

    # -- subprocess helpers that live in another service's ``src`` package --------------------------------------

    def run_script(self, script: str, service: str, marker: str, *, stdin: dict | None = None) -> dict:
        service_dir = BACKEND / service
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name(script)), str(service_dir)],
            cwd=service_dir,
            env=self.env(),
            input=json.dumps(stdin) if stdin is not None else None,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        line = next((x for x in result.stdout.splitlines() if x.startswith(marker)), None)
        if result.returncode or line is None:
            pytest.fail(
                f"{script} failed:\n{redact(result.stdout[-2500:], self.secrets)}\n{redact(result.stderr[-3500:], self.secrets)}"
            )
        self.evidence.append("commands", {"script": script, "service": service, "exit": result.returncode})
        return json.loads(line.removeprefix(marker))

    # -- teardown ---------------------------------------------------------------------------------------------

    def close(self) -> Path:
        """Stop what is still running, drop only what this fixture created, redact logs, write the evidence."""
        problems: list[str] = []
        for name, proc in self.procs.items():
            try:
                if not proc.reaped:
                    self.stop(name)
            except Exception as exc:  # one stuck process must not leave the database, bucket or vhost behind
                problems.append(f"stop {name}: {exc!r}")
                try:
                    self.kill(name)
                except Exception as again:
                    problems.append(f"kill {name}: {again!r}")
        steps: list[tuple[str, Callable[[], None]]] = []
        if self._created["db"]:
            steps.append(("database", self._drop_database))
        if self._created["bucket"]:
            steps.append(("bucket", lambda: asyncio.run(self._drop_bucket())))
        if self._created["redis"]:
            steps.append(("redis", self._flush_redis))
        if self._created["vhost"]:
            steps.append(("vhost", self._delete_vhost))
        for what, step in steps:
            try:
                step()
            except Exception as exc:  # report every leftover, never mask the first failure
                problems.append(f"{what}: {exc!r}")
        try:
            for proc in self.procs.values():
                if proc.log.exists():
                    target = self.directory / "logs" / f"{proc.name}.log"
                    target.write_text(redact(proc.log.read_text(errors="replace"), self.secrets), encoding="utf-8")
                    proc.log.unlink()
            # The services also write their own file logs under LOGS_ROOT_PATH: redact those in place too.
            for log in (self.directory / "logs").glob("*.log"):
                log.write_text(redact(log.read_text(errors="replace"), self.secrets), encoding="utf-8")
            if self.gateway_binary and self.gateway_binary.exists():
                self.gateway_binary.unlink()
        except Exception as exc:
            problems.append(f"logs: {exc!r}")
        self.evidence.append(
            "ready_checks", {"check": "teardown", "dropped": [what for what, _ in steps], "problems": problems}
        )
        path = self.evidence.write()
        if problems:
            pytest.fail("teardown left resources behind: " + "; ".join(problems))
        return path

    def _drop_database(self) -> None:
        assert DB_NAME.fullmatch(self.db)
        with self._admin() as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(self.db)))

    def _flush_redis(self) -> None:
        client = self._redis_client(self.redis_db)
        if client.get(REDIS_OWNER_KEY) != self.redis_token.encode():
            raise RuntimeError(f"Redis database {self.redis_db} is not owned by this session; not flushing it")
        client.flushdb()

    def _delete_vhost(self) -> None:
        assert VHOST_NAME.fullmatch(self.vhost)
        response = self.mgmt(f"vhosts/{urllib.parse.quote(self.vhost, safe='')}", method="DELETE")
        assert response.status in (204, 404), response.status


# == the live client and the shared bring-up ===========================================================================

TERMINAL = {"done", "awaiting_link", "failed"}
JSON_HEADERS = {"Content-Type": "application/json"}


def canonical(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


class Live:
    """The running stack plus everything seeded for it."""

    def __init__(self, stack: LiveStack, world: dict, grids: dict, cases: dict[str, IngestCase], workshop) -> None:
        self.stack, self.world, self.grids, self.cases, self.workshop = stack, world, grids, cases, workshop

    # -- HTTP ---------------------------------------------------------------------------------------------------
    def key(self, label: str) -> str:
        return self.world["keys"][label]["key"]

    def post(self, label: str | None, body: bytes, *, content_type: str = "application/json") -> Response:
        headers = {"Content-Type": content_type}
        if label:
            headers["Authorization"] = f"Bearer {self.key(label)}"
        return http("POST", f"{self.stack.gateway}/api/v1/stats/matches", body=body, headers=headers)

    def get_job(self, label: str, job_id: int) -> Response:
        return http(
            "GET",
            f"{self.stack.gateway}/api/v1/stats/ingest-jobs/{job_id}",
            headers={"Authorization": f"Bearer {self.key(label)}"},
        )

    def admin_token(self) -> str:
        owner = self.world["owner"]
        response = http(
            "POST",
            f"{self.stack.gateway}/api/v1/auth/login",
            body=json.dumps({"email": owner["email"], "password": owner["password"]}).encode(),
            headers=JSON_HEADERS,
        )
        assert response.status == 200, response.raw[:300]
        return response.json()["access_token"]

    def admin(self, method: str, path: str, payload: dict | None = None) -> Response:
        headers = {"Authorization": f"Bearer {self.admin_token()}", **JSON_HEADERS}
        return http(
            method,
            f"{self.stack.gateway}{path}",
            body=None if payload is None else json.dumps(payload).encode(),
            headers=headers,
        )

    def settle(self, label: str, job_id: int, *, timeout: float = 90, until=TERMINAL) -> tuple[dict, list[str]]:
        """Poll the real status endpoint until the job reaches one of ``until``; every observed status is evidence."""
        seen: list[str] = []

        def poll():
            response = self.get_job(label, job_id)
            assert response.status == 200, (response.status, response.raw[:300])
            job = response.json()
            if not seen or seen[-1] != job["status"]:
                seen.append(job["status"])
            return job if job["status"] in until else None

        job = wait_until(poll, f"ingest job {job_id} to reach {sorted(until)}", timeout=timeout, interval=0.2)
        self.stack.evidence.record("status_transitions", f"{label}:{job_id}", seen)
        return job, seen

    # -- SQL ----------------------------------------------------------------------------------------------------
    def q(self, statement: str, *params):
        return self.stack.query(statement, params or None)

    def s(self, statement: str, *params):
        return self.stack.scalar(statement, params or None)

    def job(self, job_id: int) -> dict:
        row = self.q(
            "SELECT status, attempts, discipline, external_id, error_message, started_at FROM stats.ingest_job WHERE id=%s",
            job_id,
        )[0]
        return dict(
            zip(("status", "attempts", "discipline", "external_id", "error_message", "started_at"), row, strict=True)
        )

    def match(self, game_id: int) -> dict | None:
        rows = self.q("SELECT id, revision, ingest_job_id FROM stats.match WHERE encounter_game_id=%s", game_id)
        return dict(zip(("id", "revision", "ingest_job_id"), rows[0], strict=True)) if rows else None

    def children(self, match_id: int) -> dict[str, int]:
        return {
            table: self.s(f"SELECT count(*) FROM stats.{table} WHERE match_id=%s", match_id)
            for table in ("match_team", "match_player", "segment", "fact", "event")
        }

    def drain(self, *, timeout: float = 60) -> None:
        """The tournament process publishes outbox rows once a second: wait until none is left unpublished."""
        wait_until(
            lambda: self.s("SELECT count(*) FROM public.event_outbox WHERE status IN ('pending','failed')") == 0,
            "outbox drained",
            timeout=timeout,
        )

    def receipts(self, encounter_id: int) -> list[dict]:
        rows = self.q(
            "SELECT data FROM encounter.room_event WHERE encounter_id=%s AND action='match_ingested' ORDER BY id",
            encounter_id,
        )
        return [row[0] for row in rows]

    def wait_receipts(self, encounter_id: int, count: int) -> list[dict]:
        self.drain()
        wait_until(
            lambda: len(self.receipts(encounter_id)) >= count,
            f"{count} receipt(s) on encounter {encounter_id}",
            timeout=60,
        )
        return self.receipts(encounter_id)

    def game(self, game_id: int) -> dict:
        state, version, source = self.q(
            "SELECT state, result_version, result_source FROM encounter.game WHERE id=%s", game_id
        )[0]
        return {"state": state, "result_version": version, "result_source": source}

    def baseline(self) -> dict[str, int]:
        return {
            "jobs": self.s("SELECT count(*) FROM stats.ingest_job"),
            "outbox": self.s("SELECT count(*) FROM public.event_outbox"),
            "matches": self.s("SELECT count(*) FROM stats.match"),
        }

    def submit_ok(self, label: str, doc: dict, *, expect: int | tuple[int, ...] = (200, 202)) -> dict:
        response = self.post(label, canonical(doc))
        assert response.status in ((expect,) if isinstance(expect, int) else expect), (
            response.status,
            response.raw[:500],
        )
        return response.json()


def err(response: Response) -> str | None:
    """The stable machine code of an error body: the field-level code when present, else the flat ``code``."""
    body = response.json() or {}
    fields = body.get("fields") or []
    return fields[0]["code"] if fields else body.get("code")


def bring_up(stack: LiveStack, *, apps: bool = False) -> Live:
    """Build and provision ``stack``, seed the P5 world into it and start every process; the caller closes the stack.

    ``apps`` adds app-service and balancer-service (the P8 scenarios' tournament, registration, balance, draft and
    mix surfaces).
    """
    from tests.live_smoke_world import project_catalog, seed_world

    stack.build_gateway()
    stack.provision()
    asyncio.run(project_catalog(stack.db_url))
    world = stack.run_script("_live_world.py", "identity-service", "__WORLD__")
    grids = stack.run_script("_live_grids.py", "app-service", "__GRIDS__", stdin={"workspaces": world["workspaces"]})
    cases, workshop = asyncio.run(seed_world(stack.db_url, world["workspaces"], grids))
    live = Live(stack, world, grids, cases, workshop)
    start_processes(live, apps=apps)
    return live


def start_processes(live: Live, *, apps: bool = False) -> None:
    stack = live.stack
    identity = stack.faststream("identity", "identity-service", "serve", port=free_port())
    stack.faststream("tournament", "tournament-service", "serve", port=free_port())
    stack.faststream("stats_rpc", "stats-service", "serve_rpc", port=free_port())
    stack.faststream(
        "worker_overwatch", "stats-service", "serve_worker", port=free_port(), **stack.worker_env("overwatch")
    )
    stack.faststream("worker_lol", "stats-service", "serve_worker", port=free_port(), **stack.worker_env("lol"))
    if apps:
        # One balancer process hosts its RPC, the balance-job consumer and the draft clock.
        stack.faststream("app", "app-service", "serve", port=free_port())
        stack.faststream("balancer", "balancer-service", "serve", port=free_port())
    stack.ready(
        "identity",
        "rpc.identity.validate_token has a consumer",
        lambda: stack.consumers("rpc.identity.validate_token") >= 1,
    )
    answer = stack.ready(
        "identity",
        "validate_token answers for a real API key",
        lambda: (r := stack.rpc("rpc.identity.validate_token", {"token": live.key("off_ok")}, timeout=10))
        and r.get("ok")
        and r,
    )
    assert (
        answer["data"]["api_key_workspace_id"] == live.world["workspaces"]["OFF"]
        if "api_key_workspace_id" in answer["data"]
        else True
    )
    del identity
    stack.ready(
        "tournament",
        "match.ingested evidence consumer",
        lambda: stack.consumers(MATCH_INGESTED_TOURNAMENT_QUEUE.name) >= 1,
    )
    stack.ready("stats_rpc", "/health 200", lambda: stack.health("stats_rpc")[0] == 200)
    stack.ready(
        "stats_rpc", "rpc.stats.ingest.submit has a consumer", lambda: stack.consumers("rpc.stats.ingest.submit") >= 1
    )
    stack.ready(
        "stats_rpc",
        "RPC answered (rpc.stats.rank.user_current)",
        lambda: stack.rpc("rpc.stats.rank.user_current", {"id": "1"}, timeout=10).get("ok") is True,
    )
    for name, slug in (("worker_overwatch", "overwatch"), ("worker_lol", "lol")):
        stack.ready(name, "/health 200", lambda name=name: stack.health(name)[0] == 200)
        stack.ready(
            name,
            f"consuming {ingest_queue(slug).name}",
            lambda slug=slug: stack.consumers(ingest_queue(slug).name) >= 1,
        )
    if apps:
        stack.ready("app", "/health 200", lambda: stack.health("app")[0] == 200)
        stack.ready(
            "balancer",
            "rpc.balancer.players.list has a consumer",
            lambda: stack.consumers("rpc.balancer.players.list") >= 1,
        )
    stack.start_gateway()
    stack.ready("gateway", "/health 200", lambda: stack.health("gateway")[0] == 200)
    stack.ready("gateway", "login through identity RPC", lambda: live.admin_token())
