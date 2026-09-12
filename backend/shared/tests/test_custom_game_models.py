from __future__ import annotations

import sqlalchemy as sa

from shared import models
from shared.core import enums


class TestMixEnums:
    def test_participation_has_exactly_three_valid_states(self):
        assert {state.value for state in enums.MixParticipation} == {"must_play", "pool", "benched"}

    def test_role_selection_distinguishes_inherited_and_explicit_roles(self):
        assert {mode.value for mode in enums.MixRoleSelectionMode} == {"all_ranked", "explicit"}


class TestCustomGameModel:
    def test_known_settings_are_not_stored_in_one_config_bag(self):
        columns = models.CustomGame.__table__.columns
        assert "points_per_win" in columns
        assert "balance_result_json" in columns
        assert "config_json" not in columns
        assert "result_json" not in columns
        assert "outcome_json" not in columns
        assert "co_host_user_ids" not in columns

    def test_lineup_state_is_one_enum_like_column(self):
        columns = models.CustomGamePlayer.__table__.columns
        assert "participation" in columns
        assert "role_selection_mode" in columns
        assert "is_flex" in columns
        assert "is_active" not in columns
        assert "must_play" not in columns
        assert "roles_json" not in columns
        assert "team_index" not in columns

    def test_repeating_groups_have_relational_models(self):
        assert models.CustomGameCoHost.__table__.schema == "balancer"
        assert models.CustomGamePlayerRole.__table__.schema == "balancer"
        assert models.CustomGameTeamName.__table__.schema == "balancer"
        assert models.CustomGameRoleSlot.__table__.schema == "balancer"

    def test_co_host_grant_addresses_a_login_not_a_roster_row(self):
        # Membership is RBAC, so a co-host can hold write access here without a
        # `workspace_member` row -- the same identity `host_user_id` uses.
        columns = models.CustomGameCoHost.__table__.columns
        assert "workspace_member_id" not in columns
        assert next(iter(columns["user_id"].foreign_keys)).target_fullname == "auth.user.id"

    def test_player_role_priority_is_unique_per_player(self):
        constraints = models.CustomGamePlayerRole.__table__.constraints
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }
        assert ("custom_game_player_id", "priority") in unique_columns


class TestCasualHistoryModel:
    def test_match_is_the_history_aggregate_root(self):
        match_columns = models.CasualMatch.__table__.columns
        team_columns = models.CasualTeam.__table__.columns
        assert "workspace_id" not in match_columns
        assert "home_team_id" not in match_columns
        assert "away_team_id" not in match_columns
        assert "home_score" not in match_columns
        assert "away_score" not in match_columns
        assert {"match_id", "side", "score"} <= set(team_columns.keys())
        assert "workspace_id" not in team_columns

    def test_historical_player_survives_workspace_member_deletion(self):
        column = models.CasualPlayer.__table__.columns["workspace_member_id"]
        assert column.nullable is True
        assert next(iter(column.foreign_keys)).ondelete == "SET NULL"
        assert "display_name_snapshot" in models.CasualPlayer.__table__.columns
