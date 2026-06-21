"""OpenAPI request/response model map for tournament-service RPC subjects.

Schemas-only module (no flows/DB) consumed by the export script — see
``shared.rpc.openapi``. Models below mirror the return annotations of the flow
functions each handler calls (src/rpc/reads.py + src/services/*/flows.py).

Coverage: public reads. Admin CRUD + writes are not yet mapped (they fall back to
a generic object in the gateway docs).
"""

from __future__ import annotations

from shared.core.pagination import Paginated
from shared.rpc.openapi import Op

from src import schemas

OPERATIONS: dict[str, Op] = {
    # single-object reads
    "rpc.tournament.get_tournament": Op(response=schemas.TournamentRead),
    "rpc.tournament.get_team": Op(response=schemas.TeamRead),
    "rpc.tournament.get_encounter": Op(response=schemas.EncounterRead),
    "rpc.tournament.get_match": Op(response=schemas.MatchReadWithStats),
    "rpc.tournament.encounters_overview": Op(response=schemas.EncounterOverviewRead),
    "rpc.tournament.statistics_overall": Op(response=schemas.OverallStatistics),
    "rpc.tournament.owal_results": Op(response=schemas.OwalStandings),
    # list reads (raw arrays)
    "rpc.tournament.lookup_tournaments": Op(response=schemas.LookupItem, response_array=True),
    "rpc.tournament.get_stages": Op(response=schemas.StageRead, response_array=True),
    "rpc.tournament.get_standings": Op(response=schemas.StandingRead, response_array=True),
    "rpc.tournament.statistics_history": Op(response=schemas.TournamentStatistics, response_array=True),
    "rpc.tournament.statistics_division": Op(response=schemas.DivisionStatistics, response_array=True),
    "rpc.tournament.owal_stacks": Op(response=schemas.LeaguePlayerStack, response_array=True),
    "rpc.tournament.saved_views": Op(response=schemas.EncounterSavedViewRead, response_array=True),
    # paginated lists
    "rpc.tournament.list_tournaments": Op(response=Paginated[schemas.TournamentRead]),
    "rpc.tournament.list_encounters": Op(response=Paginated[schemas.EncounterRead]),
    "rpc.tournament.list_matches": Op(response=Paginated[schemas.MatchRead]),
    "rpc.tournament.list_teams": Op(response=Paginated[schemas.TeamRead]),
}
