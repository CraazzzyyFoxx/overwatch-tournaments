from datetime import datetime

from pydantic import BaseModel

__all__ = ("ChallongeTournament", "ChallongeMatch", "ChallongeParticipant")


class ChallongeTournament(BaseModel):
    id: int
    name: str
    url: str
    tournament_type: str
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    state: str
    participants_count: int
    game_name: str
    match_count: int | None = None
    tournament_url: str | None = None
    tournament_full_url: str | None = None
    tournament_live_image_url: str | None = None
    description: str
    open_signup: bool
    hold_third_place_match: bool
    pts_for_match_win: float
    pts_for_match_tie: float
    pts_for_game_win: float
    pts_for_game_tie: float
    pts_for_bye: float
    swiss_rounds: int
    ranked_by: str
    rr_pts_for_match_win: float
    rr_pts_for_match_tie: float
    rr_pts_for_game_win: float
    rr_pts_for_game_tie: float
    accept_attachments: bool
    hide_forum: bool
    show_rounds: bool
    private: bool
    notify_users_when_matches_open: bool
    notify_users_when_the_tournament_ends: bool
    sequential_pairings: bool
    grand_finals_modifier: str | None
    predict_the_losers_bracket: bool
    full_challonge_url: str
    live_image_url: str
    review_before_finalizing: bool
    accepting_predictions: bool
    participants_locked: bool
    game_id: int
    participants_swappable: bool
    team_convertable: bool
    group_stages_enabled: bool
    allow_participant_match_reporting: bool
    group_stages_were_started: bool


class ChallongeMatch(BaseModel):
    id: int
    started_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    player1_id: int | None
    player2_id: int | None
    player1_prereq_match_id: int | None = None
    player2_prereq_match_id: int | None = None
    player1_is_prereq_match_loser: bool = False
    player2_is_prereq_match_loser: bool = False
    prerequisite_match_ids_csv: str | None = None
    round: int

    identifier: str
    state: str
    scores_csv: str

    tournament_id: int
    group_id: int | None


class ChallongeParticipant(BaseModel):
    id: int
    active: bool
    created_at: datetime
    updated_at: datetime | None
    name: str
    tournament_id: int
    group_player_ids: list[int]
