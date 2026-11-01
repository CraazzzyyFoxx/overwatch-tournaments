"""What a discipline module offers canonical ingest: raw-byte decoders and post-binding derivations.

A decoder is pure CPU: ``decode(raw, ctx) -> MatchDoc``. It never sees a session, S3 client or roster callback, and it
never creates an alias, a player or a row; a name it cannot resolve is handed on verbatim so the one semantic validator
reports every miss. ``derive_match`` runs after the core bound the document to an encounter game: it may read shared
data (baselines) but cannot commit or write encounter/roster rows, and it returns a new document that is validated
again.

``INGESTORS`` is assembled by ``shared.disciplines`` from every spec's ``ingestors`` (``(discipline, source kind)``
pairs) and rejects a duplicate pair; an unknown pair is the caller's ``unsupported_ingestor``, never a fallback.

A ``MatchFetcher`` is the only IO a module offers ingest: ``fetch(external_id) -> raw bytes`` for a source kind its
decoder reads. Stats core owns the pending row, the retries and the job; the fetcher raises ``MatchFetchNotReady``
while the source does not serve the match yet and ``MatchFetchFailed`` when it never will. A ``MatchSearcher`` of the
same kind answers the source's matches a pickup mix round's players played in a time window (``MatchCandidate``);
stats core decides which one is the round's and fetches it by its id. It raises the same two exceptions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from shared.disciplines.spec import DisciplineSpec
    from shared.schemas.match_doc import MatchDoc, MatchHint, MatchSource

__all__ = (
    "INGESTORS",
    "BoundMatch",
    "BoundParticipant",
    "DecodeContext",
    "DecodeError",
    "Decoder",
    "DeriveMatch",
    "MatchCandidate",
    "MatchFetchFailed",
    "MatchFetchNotReady",
    "MatchFetcher",
    "MatchQuery",
    "MatchSearcher",
    "assemble_ingestors",
)


@dataclass(frozen=True, slots=True)
class DecodeContext:
    """Everything a decoder may read besides the bytes; immutable and free of IO handles."""

    discipline: str
    source: MatchSource
    hint: MatchHint | None
    #: When the producer handed the bytes over: the played-at of a log that carries no usable timestamp.
    received_at: datetime
    #: A character as a log spells it (canonical name or alias) -> canonical code.
    characters: Mapping[str, str] = field(default_factory=dict)
    #: ``(mode name or alias, map name or alias)`` -> canonical map code; a log names both.
    maps: Mapping[tuple[str, str], str] = field(default_factory=dict)
    #: Pairs naming more than one map (an alias or name shared inside a mode): refused, never resolved to the first.
    ambiguous_maps: frozenset[tuple[str, str]] = frozenset()
    #: Character code -> catalog ``attrs``, in catalog id order (the order the formulas have always summed in).
    attrs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: Mode names/aliases whose log writes a 0:0 end whoever won (Push/Clash): the log carries no result for them.
    objectiveless_modes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class BoundParticipant:
    """A document participant after the core bound it to a workspace member and an encounter seat."""

    member_id: int
    user_id: int
    encounter_team_id: int
    #: The roster role code the seat was filled as; the fallback when a log shows no playtime to observe one.
    role: str | None


@dataclass(frozen=True, slots=True)
class BoundMatch:
    """The binding ``derive_match`` reads: owner, game, team seats and every participant by document key.

    ``team_ids`` maps each document team key to its ``encounter.team`` id; ``participants`` (member ids, filled once
    identities are materialized) is empty while the binding is still only a candidate.
    """

    workspace_id: int
    encounter_id: int
    encounter_game_id: int
    participants: Mapping[str, BoundParticipant]
    discipline: str = ""
    team_ids: Mapping[str, int] = field(default_factory=dict)
    #: ``encounter.game.result_version`` read under the game lock the evidence is published under.
    basis_game_result_version: int = 0


class DecodeError(ValueError):
    """The bytes are not a finishable log of this discipline; ``code`` is stable, ``misses`` feed the core diagnostics."""

    def __init__(self, code: str, message: str, *, misses: Mapping[str, tuple[str, ...]] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self._misses = dict(misses or {})

    def misses(self) -> dict[str, tuple[str, ...]]:
        """Names the catalog could not resolve by kind, shaped like ``DocumentRejected.misses()``."""
        return dict(self._misses)


Decoder = Callable[[bytes, DecodeContext], "MatchDoc"]
#: ``(session, doc, binding) -> doc``: baseline/rank-context-dependent facts, after binding.
DeriveMatch = Callable[["AsyncSession", "MatchDoc", BoundMatch], Awaitable["MatchDoc"]]
#: ``fetch(external_id) -> raw bytes`` of one match from the source kind's producer (the bytes an upload would carry).
MatchFetcher = Callable[[str], Awaitable[bytes]]


@dataclass(frozen=True, slots=True)
class MatchQuery:
    """What a pickup mix round tells a source about its match: its seated players' identities (the discipline's
    ``identity_provider`` ids) and when the match must have started."""

    identities: frozenset[str]
    started_from: datetime
    started_until: datetime


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """One match a source found: its external id and each side's participant identities, anonymous ones left out."""

    external_id: str
    teams: tuple[frozenset[str], ...]


#: ``search(query) -> candidates``: every match the source knows any of the identities played in the window.
MatchSearcher = Callable[[MatchQuery], Awaitable[Sequence[MatchCandidate]]]


class MatchFetchNotReady(Exception):
    """The source does not serve the match yet (not found, rate limited, down): stats core retries later."""


class MatchFetchFailed(Exception):
    """The source will never serve this match (refused, malformed id or payload): stats core stops retrying."""


#: ``(discipline, source kind) -> decoder``, filled by ``shared.disciplines`` when the registry is imported.
INGESTORS: dict[tuple[str, str], Decoder] = {}


def assemble_ingestors(specs: Iterable[DisciplineSpec]) -> dict[tuple[str, str], Decoder]:
    ingestors: dict[tuple[str, str], Decoder] = {}
    for spec in specs:
        for kind, decoder in spec.ingestors.items():
            key = (spec.code, kind)
            if key in ingestors:
                raise ValueError(f"duplicate ingestor {key!r}")
            ingestors[key] = decoder
    return ingestors
