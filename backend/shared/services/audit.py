"""The single way to append to the platform audit log.

Every instrumented action records one row here, assembled by the caller from
*named* domain fields: the raw RPC payload is never captured, so a secret can
only reach the log if someone writes it in by hand, where a diff review can see
it.

Like ``record_result_transition``, this never commits. The row lands in the
caller's transaction, so a mutation that rolls back leaves no trail of having
happened, and a mutation that commits cannot be missing its row.

That makes call order part of the contract: ``record_audit`` belongs *before*
the flow's own ``await session.commit()``. Placed after it, the row goes into a
separate transaction and atomicity is silently gone — the naive test "a row
appeared" stays green while a rolled-back mutation keeps its audit trail.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.identity.auth_user import AuthUser
from shared.models.platform.audit import AuditLog
from shared.observability.correlation import get_correlation_id
from shared.repository import AuditLogRepository
from shared.rpc.identity import api_key_label, credential_type

__all__ = ("AuditSource", "json_safe", "record_audit", "record_admin_audit")

# Mirrors ``audit_log.source`` — a plain ``String(16)`` with no DB enum, the same
# shape ``FinalizeSource`` gives ``encounter_result_audit.source``.
AuditSource = Literal["admin", "api_key", "challonge", "discord", "scheduler", "system"]

# ``actor_label``, ``entity_label`` and ``user_agent`` are ``String(255)``;
# ``ip_address`` is ``String(45)``.
_LABEL_LIMIT = 255
_IP_LIMIT = 45

_logs = AuditLogRepository()


def _clip(value: str | None, limit: int) -> str | None:
    """Cut an externally supplied string down to what the column holds.

    Real User-Agent headers run well past 255 characters, and labels are
    snapshots of names nobody validated for length. Because the audit row shares
    the mutation's transaction, an overlong value would raise ``DataError`` and
    take the audited mutation down with it — the log would start *causing* the
    failures it exists to explain. Losing the tail of a label is strictly better
    than failing the action it describes.
    """
    if value is None:
        return None
    return value[:limit]


def _actor_label(actor: AuthUser | None, label: str | None) -> str | None:
    """Fold the credential the actor used into the label they are recorded under.

    ``actor_auth_user_id`` names the *account*, and an API key is owned by a real
    account, so a keyed mutation and that same person's browser session were
    landing as byte-identical rows. This is the whole of the fix: no new column,
    no migration, and nothing for the 100+ call sites to pass — the credential is
    already on the actor by the time it gets here (``shared.rpc.identity``).
    """
    credential = api_key_label(actor) if actor is not None else None
    if credential is None:
        return label
    if not label:
        return credential
    # Clip the name, never the credential: which key acted is the new
    # information the suffix exists to carry, and losing the tail of a long
    # username is already an accepted trade (see ``_clip``).
    suffix = f" ({credential})"
    return f"{_clip(label, _LABEL_LIMIT - len(suffix))}{suffix}"


def _source_for(actor: AuthUser | None, source: AuditSource) -> AuditSource:
    """API key is the request channel; callers still pass ``admin`` for operator writes."""
    if actor is not None and credential_type(actor) == "api_key":
        return "api_key"
    return source


def json_safe(value: Any) -> Any:
    """Coerce one value into something JSONB can hold.

    Same reasoning as ``_clip``, one layer up: the audit row shares the
    mutation's transaction, so a value asyncpg cannot encode — a bare
    ``datetime``, an ``Enum``, a ``Decimal`` — would raise on flush and take the
    audited mutation down with it. Every current call site already hands over
    JSON-ready primitives; this makes that a property of the primitive instead of
    a convention each new call site has to remember.

    ``Decimal`` becomes ``str``, never ``float``: an audited money value must not
    drift on the way in.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return str(value)


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    source: AuditSource,
    actor: AuthUser | None = None,
    actor_label: str | None = None,
    workspace_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    entity_label: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Append one audit row. ``actor=None`` means a machine actor.

    Never commits — see the module docstring for the two invariants that follow
    from it, including why this must run before the flow's own ``commit()``.

    ``workspace_id`` must be the workspace the mutation's own permission check
    ran against, reused rather than re-resolved: if the two ever disagree, the
    row claims an action was authorized in a workspace where it was not.

    ``actor_label`` is stored as given for a session actor; when the actor came
    in on an API key it gains a ``(api key: <public_id>)`` suffix, so the journal
    records which of the account's credentials acted.

    ``source`` is rewritten to ``api_key`` when the actor authenticated with one.
    Callers keep passing ``admin`` for operator writes; the credential already
    rides the actor, so the 100+ sites do not have to know.
    """
    row = AuditLog(
        workspace_id=workspace_id,
        actor_auth_user_id=actor.id if actor else None,
        actor_label=_clip(_actor_label(actor, actor_label), _LABEL_LIMIT),
        source=_source_for(actor, source),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=_clip(entity_label, _LABEL_LIMIT),
        before_json=json_safe(before),
        after_json=json_safe(after),
        reason=reason,
        ip_address=_clip(ip_address, _IP_LIMIT),
        user_agent=_clip(user_agent, _LABEL_LIMIT),
        # The caller is already inside ``observe_message_processing``, so this is
        # set; ``None`` outside a traced flow is fine and stays NULL.
        correlation_id=get_correlation_id(),
    )
    return _logs.add(session, row)


async def record_admin_audit(
    session: AsyncSession,
    *,
    action: str,
    actor: AuthUser,
    data: dict[str, Any],
    workspace_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    entity_label: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    source: AuditSource = "admin",
) -> AuditLog:
    """Operator write: ``source="admin"`` unless the actor came in on an API key."""
    return await record_audit(
        session,
        action=action,
        source=source,
        actor=actor,
        actor_label=actor.username,
        workspace_id=workspace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        before=before,
        after=after,
        reason=reason,
        ip_address=data.get("ip_address") if isinstance(data.get("ip_address"), str) else None,
        user_agent=data.get("user_agent") if isinstance(data.get("user_agent"), str) else None,
    )
