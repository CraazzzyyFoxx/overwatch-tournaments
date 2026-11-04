"""A bot lobby's callback: the one-time token's digest, the match id the game source reports, and its secret check.

Pure: the service hands in what the RPC received. The sender of the callback is closed source, so the body is read
defensively and anything unrecognised is "no match id", never an error the sender could learn from.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from shared.disciplines.lobby import IngestStatus

__all__ = ("PARTY_TTL", "POLL_WINDOW", "merge_ingest_status", "parse_match_id", "secret_matches", "token_sha256")

#: The game source's bot leaves the party this long after creating it, whatever the match does.
PARTY_TTL = timedelta(minutes=15)
#: How long after creation a party's match id is still waited for (the source keeps its callback and answer ~20 min).
POLL_WINDOW = timedelta(minutes=20)

_EPOCH = datetime.min.replace(tzinfo=UTC)
_MATCH_ID = re.compile(r"[1-9][0-9]{0,18}")


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse_match_id(raw: str) -> str | None:
    """The match id out of a callback body: a JSON number or string, a JSON object with ``match_id``, or plain digits."""
    text = raw.strip()
    try:
        value = json.loads(text)
    except ValueError:
        value = text
    if isinstance(value, dict):
        value = value.get("match_id")
    if isinstance(value, bool):
        return None
    candidate = str(value).strip() if isinstance(value, int | str) else ""
    return candidate if _MATCH_ID.fullmatch(candidate) else None


def secret_matches(stored: str | None, sent: str | None) -> bool:
    """A sender that names a secret must name the party's: a missing header is left to the path token, which already
    is a 256-bit capability, so a source or hop that never forwards the header still works."""
    if not stored or not sent:
        return True
    return hmac.compare_digest(stored.encode(), sent.encode())


def merge_ingest_status(statuses: Sequence[IngestStatus | None]) -> IngestStatus | None:
    """One player's status over their accounts: an active one wins (the newest upload); otherwise the player is
    inactive only if every account answered, and unknown (``None``) as soon as one did not."""
    known = [status for status in statuses if status is not None]
    best = max(known, key=lambda status: (status.active, status.last_upload_at or _EPOCH), default=None)
    return best if best is not None and (best.active or len(known) == len(statuses)) else None
