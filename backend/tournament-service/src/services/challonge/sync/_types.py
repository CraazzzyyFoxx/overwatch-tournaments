"""Value dataclasses the sync passes between its stages, and the per-source lookup key."""

from dataclasses import dataclass

from shared import models
from shared.core import enums
from src import schemas
from src.services.challonge.stage_refs import StageRefs


@dataclass(frozen=True)
class _ImportSource:
    challonge_id: int
    source_id: int | None = None
    source_type: str = "tournament"
    stage: models.Stage | None = None
    stage_item_id: int | None = None
    slug: str | None = None


@dataclass(frozen=True)
class _SourceFetch:
    matches: list[schemas.ChallongeMatch]
    participants: list[schemas.ChallongeParticipant]


@dataclass
class _TeamLookup:
    by_source_key: dict[tuple[int, int], int]
    by_key: dict[tuple[int | None, int], int]
    teams_by_id: dict[int, models.Team]

    def resolve(
        self,
        source: _ImportSource,
        group_id: int | None,
        challonge_id: int | None,
    ) -> int | None:
        if challonge_id is None:
            return None
        if (tid := self.by_source_key.get((_source_lookup_key(source), challonge_id))) is not None:
            return tid
        if (tid := self.by_key.get((group_id, challonge_id))) is not None:
            return tid
        if (tid := self.by_key.get((None, challonge_id))) is not None:
            return tid
        candidates = {tid for (gid, cid), tid in self.by_key.items() if cid == challonge_id}
        return next(iter(candidates)) if len(candidates) == 1 else None


@dataclass
class _MatchLookup:
    by_source_key: dict[tuple[int, int], models.Encounter]
    by_challonge_id: dict[int, models.Encounter]
    mapped_keys: set[tuple[int, int]]
    # Encounters that already occupy a bracket slot (same stage + round + team
    # pair) but carry no ``challonge_match_mapping`` yet -- a bracket generated
    # locally (``StageService.generate_encounters``) before this source was
    # imported. Popped the first time a Challonge match resolves to that slot, so
    # import adopts and links the existing row instead of creating a duplicate.
    unlinked_by_slot: dict[tuple[int | None, int, frozenset[int]], models.Encounter]

    def get(self, source: _ImportSource, challonge_match_id: int) -> models.Encounter | None:
        if (encounter := self.by_source_key.get((_source_lookup_key(source), challonge_match_id))) is not None:
            return encounter
        return self.by_challonge_id.get(challonge_match_id)

    def claim_unlinked(
        self, stage_id: int | None, round_number: int, team_ids: frozenset[int]
    ) -> models.Encounter | None:
        return self.unlinked_by_slot.pop((stage_id, round_number, team_ids), None)

    def set(
        self,
        source: _ImportSource,
        challonge_match_id: int,
        encounter: models.Encounter,
    ) -> None:
        self.by_source_key[(_source_lookup_key(source), challonge_match_id)] = encounter
        self.by_challonge_id[challonge_match_id] = encounter


@dataclass(frozen=True)
class _UpsertResult:
    action: str
    encounter: models.Encounter | None = None
    conflict_type: str | None = None
    # True when THIS upsert moved the encounter into COMPLETED, so import_tournament
    # emits EncounterCompletedEvent (achievement/MVP recalculation) for it.
    newly_completed: bool = False
    before: dict | None = None
    after: dict | None = None
    error: str | None = None
    # The Challonge participant ids that have no local team mapped, when
    # ``action == "error"`` for that reason. Recorded structurally alongside the
    # human message so the admin UI can group "these N participants need mapping"
    # out of one failed row per match, instead of parsing the message back apart.
    missing_participant_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class _UpsertPlan:
    """What ``_plan_upsert`` derived from Challonge for a match that will write. ``encounter`` None means the match
    creates one; ``after`` is the existing encounter's target state. The local state the write is judged on (seats,
    position, result) is re-read by ``_apply_upsert`` under the encounter's row lock, never taken from the plan."""

    encounter: models.Encounter | None
    team_ids: tuple[int | None, int | None]
    scores: tuple[int, int]
    status: enums.EncounterStatus
    refs: StageRefs
    names: dict[int, str]
    teams_mapped: bool
    after: dict | None = None


@dataclass(frozen=True)
class _ChallongeLinkSpec:
    """One Challonge prereq edge, in the encounter layer's terms.

    Challonge's "player1/player2 comes from the winner/loser of match X" is a
    PLACE in that match feeding a SEAT of this one: ``source_position`` 1 is the
    winner and 2 the loser, ``target_slot`` 1 is player1 and 2 player2.
    """

    source_key: int
    source_challonge_id: int
    target_challonge_id: int
    source_position: int
    target_slot: int


def _source_lookup_key(source: _ImportSource) -> int:
    return source.source_id if source.source_id is not None else -source.challonge_id
