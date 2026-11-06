"""ORM → narrow DTO conversion helpers for user/ flows.

Each function produces a DTO defined in `src.schemas.user` that contains
only the fields the frontend actually renders on user-scoped pages.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa

from shared import models
from shared.division_grid import DivisionGrid
from shared.repository.stats_reads import MatchReadContext
from shared.schemas.catalog import CatalogEntityRef
from shared.schemas.identity import PersonDisplayRead
from shared.schemas.match import NativeFact
from shared.schemas.role import RoleRef
from shared.services.division_grid.resolution import resolve_tournament_division
from shared.services.match_reads import match_header_fields
from src import schemas
from src.schemas.division_grid import DivisionGridVersionRead

_IDENTITY_ENTITIES = ("social_accounts",)

#: What a user encounter read can expand (``?entities=``).
ENCOUNTER_ENTITIES = frozenset({"tournament", "stage", "stage_item", "teams", "teams.players", "matches"})


def encounter_entities(requested: Collection[str]) -> frozenset[str]:
    """The expansions ``requested`` names: ``matches.map`` is ``matches`` (a match's map is always expanded) and
    ``teams.players`` implies ``teams``. An entity left out is null/empty on the row and never queried."""
    names = set(requested)
    if "matches.map" in names:
        names.add("matches")
    if "teams.players" in names:
        names.add("teams")
    return frozenset(names & ENCOUNTER_ENTITIES)


def _is_globally_visible(account: models.SocialAccount) -> bool:
    """True when the account is shown on the public profile (has a global,
    workspace-less visibility row). Fail-open when ``visibilities`` isn't
    eager-loaded so a read path that forgot to load it never silently hides
    everything — mirrors the ``visible_global=True`` default in the read model."""
    if "visibilities" in sa.inspect(account).unloaded:
        return True
    return any(v.workspace_id is None for v in account.visibilities)


def _social_account_read(account: models.SocialAccount) -> schemas.SocialAccountRead:
    """Serialize a social account, including display-visibility scopes when the
    ``visibilities`` relationship is eager-loaded (admin profile dialog). When it
    isn't loaded we leave the defaults (``visible_global=True``) and never touch
    the relationship — avoiding a lazy load outside the async greenlet."""
    read = schemas.SocialAccountRead.model_validate(account, from_attributes=True)
    if "visibilities" not in sa.inspect(account).unloaded:
        scopes = list(account.visibilities)
        read.visible_global = any(v.workspace_id is None for v in scopes)
        read.visible_workspace_ids = sorted({v.workspace_id for v in scopes if v.workspace_id is not None})
    return read


def resolve_team_placement(team: models.Team) -> int | None:
    """Pick the best (lowest, positive) overall_position across standings."""
    standings = getattr(team, "standings", None) or []
    positive_positions = [
        standing.overall_position for standing in standings if getattr(standing, "overall_position", 0) > 0
    ]
    if positive_positions:
        return min(positive_positions)
    return None


def _division_grid_version(tournament: models.Tournament) -> DivisionGridVersionRead | None:
    if getattr(tournament, "division_grid_version", None) is None:
        return None
    return DivisionGridVersionRead.model_validate(tournament.division_grid_version, from_attributes=True)


def to_user_tournament_summary(tournament: models.Tournament) -> schemas.UserTournamentSummary:
    """Narrow tournament card for UserProfile.tournaments + filter lists."""
    return schemas.UserTournamentSummary(
        id=tournament.id,
        name=tournament.name,
        discipline=tournament.discipline,
        is_finished=tournament.is_finished,
        status=tournament.status,
    )


def to_user_tournament_player(
    player: models.Player,
    *,
    grid: DivisionGrid | None,
    avg_mvp: float | None = None,
    characters: list[models.CatalogEntity] | None = None,
) -> schemas.UserTournamentPlayer:
    """Player card inside UserTournament.players.

    ``avg_mvp`` and ``characters`` are supplied by the caller from bulk lookups
    keyed by (tournament_id, user_id) — see ``queries.encounters`` — so this stays a
    pure ORM→DTO conversion with no per-player queries.
    """
    return schemas.UserTournamentPlayer(
        id=player.id,
        name=player.name,
        role=player.role_ref,
        rank=player.rank,
        division=resolve_tournament_division(player.rank, tournament_grid=grid),
        # workspace_member_id is NOT NULL: the identity anchor is always
        # workspace_member.player_id.
        user_id=player.workspace_member.player_id,
        is_substitution=player.is_substitution,
        is_newcomer=player.is_newcomer,
        is_newcomer_role=player.is_newcomer_role,
        related_player_id=player.related_player_id,
        relative_player=getattr(player, "relative_player", None),
        avg_mvp=avg_mvp,
        characters=[CatalogEntityRef.from_entity(entity) for entity in (characters or [])],
    )


@dataclass(frozen=True, slots=True)
class UserMatchStats:
    """What the user pages add to a match header: the viewer's seat and totals, and every observed member's totals."""

    viewer: schemas.UserMatchViewer | None
    member_totals: list[NativeFact]


def to_match_with_user_stats(
    context: MatchReadContext, stats: UserMatchStats | None = None
) -> schemas.MatchReadWithUserStats:
    """One match in a user-scoped encounter: the native header, the map with its mode, and the viewer's totals.

    Participants follow their historical encounter slots, never the live seats or the log's source order. Nothing
    derived rides on the wire -- a discipline's renderer ranks ``viewer.facts`` against ``member_totals``.
    """
    return schemas.MatchReadWithUserStats(
        **match_header_fields(context, with_map=True, with_parent=True),
        viewer=stats.viewer if stats is not None else None,
        member_totals=stats.member_totals if stats is not None else [],
    )


def to_encounter_tournament_summary(
    tournament: models.Tournament | None,
) -> schemas.UserEncounterTournament | None:
    if tournament is None:
        return None
    return schemas.UserEncounterTournament(
        id=tournament.id,
        name=tournament.name,
        is_finished=tournament.is_finished,
        status=tournament.status,
    )


def to_encounter_stage_summary(
    stage: models.Stage | None,
) -> schemas.UserEncounterStageSummary | None:
    if stage is None:
        return None
    return schemas.UserEncounterStageSummary(id=stage.id, name=stage.name)


def to_encounter_stage_item_summary(
    stage_item: models.StageItem | None,
) -> schemas.UserEncounterStageItemSummary | None:
    if stage_item is None:
        return None
    return schemas.UserEncounterStageItemSummary(id=stage_item.id, name=stage_item.name)


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One roster snapshot row of a participation, with the account it belongs to."""

    member: models.EncounterTeamMember
    user_id: int
    role: RoleRef | None
    display: PersonDisplayRead


@dataclass(frozen=True, slots=True)
class EncounterContext:
    """What the user pages need around an encounter row: its live seats with their
    rosters, and where it sits in the bracket (nothing, outside a bracket)."""

    seats: list[tuple[models.EncounterTeam, list[RosterEntry]]]
    position: models.BracketEncounter | None = None
    stage: models.Stage | None = None
    stage_item: models.StageItem | None = None

    @property
    def participations(self) -> list[models.EncounterTeam]:
        return [seat for seat, _ in self.seats]


def _to_encounter_team_player_ref(entry: RosterEntry) -> schemas.UserEncounterTeamPlayerRef:
    return schemas.UserEncounterTeamPlayerRef(
        id=entry.member.id,
        user_id=entry.user_id,
        role=entry.role,
        name=entry.member.display_name_snapshot,
        display=entry.display,
    )


def to_encounter_team_summary(
    seat: models.EncounterTeam, roster: list[RosterEntry]
) -> schemas.UserEncounterTeamSummary:
    return schemas.UserEncounterTeamSummary(
        id=seat.id,
        slot=seat.slot,
        team_id=seat.team_id,
        name=seat.name,
        score=seat.score,
        placement=seat.placement,
        players=[_to_encounter_team_player_ref(entry) for entry in roster],
    )


def _resolve_user_team_id(context: EncounterContext, user_id: int) -> int | None:
    """The source team of the seat whose roster snapshot holds the viewer."""
    for seat, roster in context.seats:
        if any(entry.user_id == user_id for entry in roster):
            return seat.team_id
    return None


def to_encounter_with_user_stats(
    encounter: models.Encounter,
    context: EncounterContext,
    matches: list[schemas.MatchReadWithUserStats],
    *,
    viewer_user_id: int | None = None,
    entities: frozenset[str] = ENCOUNTER_ENTITIES,
) -> schemas.EncounterReadWithUserStats:
    """User-scoped encounter view.

    The tournament summary only when ``entities`` names it (the repository then loads it); ``context`` carries the
    seats and the bracket position it was read with. `viewer_user_id` fills the convenience `user_team_id` shortcut
    from the seats' rosters (``None`` without them) so the frontend doesn't have to scan rosters itself.
    """
    return schemas.EncounterReadWithUserStats(
        id=encounter.id,
        name=encounter.name,
        slot_count=encounter.slot_count,
        round=context.position.round if context.position is not None else 0,
        best_of=encounter.best_of,
        tournament_id=encounter.tournament_id,
        discipline=encounter.discipline,
        status=encounter.status,
        closeness=encounter.closeness,
        has_logs=encounter.has_logs,
        result_status=getattr(encounter, "result_status", "none"),
        user_team_id=_resolve_user_team_id(context, viewer_user_id) if viewer_user_id is not None else None,
        tournament=(
            to_encounter_tournament_summary(getattr(encounter, "tournament", None))
            if "tournament" in entities
            else None
        ),
        stage=to_encounter_stage_summary(context.stage),
        stage_item=to_encounter_stage_item_summary(context.stage_item),
        teams=[to_encounter_team_summary(seat, roster) for seat, roster in context.seats],
        matches=matches,
    )


_MISSING_PLAYED_AT = datetime.min.replace(tzinfo=UTC)


def encounter_play_key(encounter: models.Encounter) -> tuple[datetime, int]:
    """Sort key for a series: when it was played, then id.

    Bracket rows are inserted playoffs-first, so ``id``/``created_at`` are not
    play order. ``confirmed_at`` is when the result landed; ``scheduled_at`` is
    ignored — it is a plan, not a play.
    """
    played = encounter.ended_at or encounter.confirmed_at or encounter.started_at or encounter.created_at
    return (played or _MISSING_PLAYED_AT, encounter.id)


def sort_user_matches(
    matches: list[schemas.MatchReadWithUserStats],
) -> list[schemas.MatchReadWithUserStats]:
    """Proven positions first; unknown positions stay unset, with stable display order."""
    return sorted(matches, key=lambda match: (match.map_index is None, match.map_index, match.id))
