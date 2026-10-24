"""Pre-encounter OpenSkill snapshot helpers.

The ML win-probability classifier and the per-match Performance target
both need an estimate of *each team's strength as it was before the
encounter was played* — using the post-encounter rating would leak the
outcome.

The helpers in this module replay the window from the players' seed ratings
and freeze the rating snapshot *before* applying each encounter, yielding a
``(encounter_id, team_id) → mu`` map that can be merged into feature frames.
"""

from __future__ import annotations

import typing

import pandas as pd
from openskill.models import PlackettLuce, PlackettLuceRating
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.analytics_exports import analytics_exports
from src.domain.ratings import get_id_role, get_plackett_luce, get_player_rating, prepare_openskill_data
from src.services.analytics.service import analytics_service

from .cache import get_or_build_dataframe, scope_cache_params

__all__ = ("snapshot_pre_encounter_team_mu", "snapshot_pre_tournament_team_mu")


async def snapshot_pre_encounter_team_mu(
    session: AsyncSession,
    tournament_id: int,
    *,
    discipline: str,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
    look_back: int = 10,
) -> pd.DataFrame:
    params = {
        "tournament_id": int(tournament_id),
        "look_back": int(look_back),
        **scope_cache_params(workspace_id=workspace_id, workspace_ids=workspace_ids),
    }

    async def _build() -> pd.DataFrame:
        return await _snapshot_pre_encounter_team_mu_uncached(
            session,
            tournament_id,
            discipline=discipline,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            look_back=look_back,
        )

    return await get_or_build_dataframe("opponent_strength_snapshot", params, _build, discipline=discipline)


async def _snapshot_pre_encounter_team_mu_uncached(
    session: AsyncSession,
    tournament_id: int,
    *,
    discipline: str,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
    look_back: int = 10,
) -> pd.DataFrame:
    """Return a DataFrame with one row per ``(encounter_id, team_id)`` holding
    the team-average OpenSkill ``mu`` evaluated *just before* the encounter was
    played.

    Algorithm:

    1. Load the encounters of the ``look_back`` most recent tournaments up to and
       including ``tournament_id`` (chronological window, same range as the v1
       OpenSkill flow).
    2. Replay them in chronological order from the seed ratings: a player is seeded
       from their roster rank on first appearance (:func:`get_player_rating`, the
       seeding :func:`prepare_openskill_data` uses). **Before** each encounter,
       snapshot the team-average mu of its rosters, then rate it once.

    Output columns: ``encounter_id``, ``team_id``, ``avg_mu``, ``max_mu``,
    ``min_mu``, ``std_mu`` (NaN-safe).
    """
    window_ids = await analytics_service.lookback_tournament_ids(
        session,
        tournament_id,
        look_back,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
        discipline=discipline,
    )
    matches = await analytics_service.get_matches_for_tournaments(
        session,
        window_ids,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
        discipline=discipline,
    )
    pl: PlackettLuce = get_plackett_luce()
    rosters = await analytics_service.get_rosters(session, matches)

    # Players keyed by (user_id, role). Starts empty: seeding from post-replay ratings
    # would leak every window outcome into its own "pre-encounter" snapshot.
    rating_map: dict[str, PlackettLuceRating] = {}

    # Group matches by encounter so we snapshot pre-encounter (not pre-match).
    snapshots: list[dict[str, typing.Any]] = []
    seen_encounters: set[int] = set()

    # ``get_matches_for_tournaments`` returns ``Sequence[models.Encounter]``
    # despite its name: each row's own id is ``Encounter.id``; there is no
    # ``encounter_id`` attribute on the ORM object itself.
    for encounter in matches:
        if encounter.id in seen_encounters:
            # Already snapshotted before the first match of this encounter.
            continue
        seen_encounters.add(encounter.id)

        # One snapshot per live seat that has a roster; a seat is one team of the
        # encounter, whether it is a duel or a lobby.
        seats = sorted((seat for seat in encounter.teams if seat.active), key=lambda seat: seat.slot)
        replay: list[tuple[typing.Any, list[typing.Any]]] = []
        for seat in seats:
            team = rosters.get(seat.team_id) if seat.team_id is not None else None
            if team is None or not getattr(team, "players", None):
                continue
            mus: list[float] = []
            for player in team.players:
                key = get_id_role(player)
                if key not in rating_map:
                    rating_map[key] = get_player_rating(pl, player)
                mus.append(float(rating_map[key].mu))
            snapshots.append(
                {
                    "encounter_id": int(encounter.id),
                    "team_id": int(seat.team_id),
                    "avg_mu": float(sum(mus) / len(mus)),
                    "max_mu": float(max(mus)),
                    "min_mu": float(min(mus)),
                    "std_mu": float(pd.Series(mus).std(ddof=0)) if len(mus) > 1 else 0.0,
                }
            )
            replay.append((seat, team.players))

        # Update ratings *after* snapshotting, replicating the v1 replay order: every
        # live seat is one team, ranked by its placement. An encounter without a
        # result, or with a seat that has no roster, rates nobody.
        if len(replay) < 2 or len(replay) != len(seats) or any(seat.placement is None for seat, _ in replay):
            continue
        rated = pl.rate(
            [[rating_map[get_id_role(p)] for p in players] for _, players in replay],
            ranks=[seat.placement for seat, _ in replay],
        )
        for (_, players), new_ratings in zip(replay, rated, strict=True):
            for player, new_rating in zip(players, new_ratings, strict=True):
                rating_map[get_id_role(player)] = new_rating

    if not snapshots:
        return pd.DataFrame(columns=["encounter_id", "team_id", "avg_mu", "max_mu", "min_mu", "std_mu"])
    # Enforce the documented one-row-per-(encounter_id, team_id) contract as a
    # defensive backstop against any future fan-out source.
    return (
        pd.DataFrame(snapshots).drop_duplicates(subset=["encounter_id", "team_id"], keep="first").reset_index(drop=True)
    )


async def snapshot_pre_tournament_team_mu(
    session: AsyncSession,
    tournament_id: int,
    *,
    discipline: str,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
    look_back: int = 10,
) -> pd.DataFrame:
    """Return one row per team of ``tournament_id`` with the team-average
    OpenSkill ``mu`` as it stands *before the tournament starts*.

    Sibling of :func:`snapshot_pre_encounter_team_mu` for the pre-tournament
    case, where there is no encounter to anchor a snapshot to. The replay covers
    the ``look_back`` window up to but **excluding** ``tournament_id`` itself, so
    nothing that happens inside the tournament being forecast leaks into its own
    strength estimate. Rosters with no rated history still get a rating:
    :func:`prepare_openskill_data` seeds every team player from their
    registration rank (the model's default mu when unranked).

    Output columns: ``team_id``, ``avg_mu``, ``max_mu``, ``min_mu``, ``std_mu``
    plus per-role means ``tank_mu`` / ``damage_mu`` / ``support_mu`` (NaN when
    the roster has no rated player on that role) — the roster average hides a
    weak tank behind strong supports, and role gaps are how a balanced-looking
    team actually loses.

    Deliberately uncached, unlike its per-encounter sibling: this frame exists
    for tournaments whose rosters are still being assembled, where a TTL'd
    snapshot would forecast a field that has since changed.
    """
    exports = analytics_exports(discipline)
    teams = await analytics_service.get_teams_with_players(session, tournament_id)
    if not teams:
        return exports.summarize_team_strength([], {}, rating_key=get_id_role)

    window_ids = await analytics_service.lookback_tournament_ids(
        session,
        tournament_id,
        look_back,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
        discipline=discipline,
    )
    history = [
        encounter
        for encounter in await analytics_service.get_matches_for_tournaments(
            session,
            window_ids,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
            discipline=discipline,
        )
        if encounter.tournament_id != tournament_id
    ]

    pl: PlackettLuce = get_plackett_luce()
    # ``prepare_openskill_data`` ignores its ``df`` argument entirely; it needs
    # only the replay encounters plus the rosters to seed unrated players.
    rosters = await analytics_service.get_rosters(session, history)
    _, players_rating, _ = prepare_openskill_data(pd.DataFrame(), pl, teams, history, rosters)
    return exports.summarize_team_strength(teams, players_rating, rating_key=get_id_role)
