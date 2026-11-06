from pydantic import BaseModel

__all__ = ("TournamentReadiness",)


class TournamentReadiness(BaseModel):
    """Living-checklist aggregate for one tournament.

    Field groups are masked by the caller's workspace permissions:
    ``tournament.read`` gates the setup/bracket/logs/recalc fields, ``team.read``
    the registration/pool/balance/draft fields, ``match.read`` the result backlog
    and ``achievement.read`` the evaluation status — a missing group yields
    ``None`` so the checklist renders "no-access" instead of zeros.
    """

    tournament_id: int
    status: str
    #: Distinct ``mode`` of the tournament's formation nodes (balancer | draft | registered | manual), sorted;
    #: empty without a formation node. The flow decides which formation checks apply. Unmasked.
    formation_modes: list[str]
    # visible with tournament.read:
    schedule_configured: bool | None
    grid_selected: bool | None
    stages_total: int | None
    stage_slots_filled: bool | None
    bracket_generated: bool | None
    # Duels only (slot_count == 2): a lobby never produces a match log.
    duel_encounters_total: int | None
    duel_encounters_with_logs: int | None
    logs_used: bool | None
    standings_recalc_pending: bool | None
    # visible with team.read (None -> checklist renders no-access):
    registration_form_configured: bool | None
    registrations_pending: int | None
    registrations_approved: int | None
    registrations_checked_in: int | None
    registrations_ranked: int | None
    pool_ready: int | None
    pool_need_fix: int | None
    balance_saved: bool | None
    balance_exported_at: str | None
    draft_session_status: str | None
    # visible with match.read (overdue: result_status none, scheduled_at < now, status != completed):
    results_overdue: int | None
    results_pending_confirmation: int | None
    results_disputed: int | None
    # visible with achievement.read: latest evaluation run status; "none" = never ran;
    # "not_configured" = no enabled rules for the tournament's discipline
    achievements_status: str | None
