-- Anak Tournaments — PostgreSQL DDL compiled from SQLAlchemy metadata.
-- Open in any SQL editor (DataGrip, DBeaver, VS Code).
-- Runtime mappings only, not a complete physical-database dump.
-- Tables: 164
-- Source of truth is backend/shared/models. Regenerate: python scripts/export_db_schema.py

CREATE SCHEMA IF NOT EXISTS achievements;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS balancer;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS draft;
CREATE SCHEMA IF NOT EXISTS encounter;
CREATE SCHEMA IF NOT EXISTS mix;
CREATE SCHEMA IF NOT EXISTS players;
CREATE SCHEMA IF NOT EXISTS quota;
CREATE SCHEMA IF NOT EXISTS rank;
CREATE SCHEMA IF NOT EXISTS realtime;
CREATE SCHEMA IF NOT EXISTS registration;
CREATE SCHEMA IF NOT EXISTS roster;
CREATE SCHEMA IF NOT EXISTS stats;
CREATE SCHEMA IF NOT EXISTS subscriptions;
CREATE SCHEMA IF NOT EXISTS tournament;

CREATE TYPE encounter.encounterstatus AS ENUM ('COMPLETED', 'PENDING', 'OPEN');
CREATE TYPE encounter.encounterresultstatus AS ENUM ('none', 'pending_confirmation', 'confirmed', 'disputed');
CREATE TYPE encounter.encountergamestate AS ENUM ('planned', 'awaiting_result', 'disputed', 'confirmed', 'cancelled');
CREATE TYPE encounter.encountergameresultsource AS ENUM ('captain_agreement', 'admin', 'admin_log', 'host');
CREATE TYPE encounter.pickbanactor AS ENUM ('team', 'decider', 'admin', 'system');
CREATE TYPE encounter.pickbanentrystatus AS ENUM ('available', 'picked', 'banned', 'protected');
CREATE TYPE encounter.pickbankind AS ENUM ('map', 'hero');
CREATE TYPE encounter.pickbanseedsource AS ENUM ('bracket_slot', 'standings', 'fallback_first_slot', 'admin');
CREATE TYPE encounter.pickbansessionstatus AS ENUM ('active', 'completed', 'cancelled');
CREATE TYPE encounter.encounterresultauditaction AS ENUM ('confirm', 'reopen', 'auto_confirm', 'auto_dispute', 'auto_pending', 'import', 'cascade_reset', 'game_confirm', 'game_correct', 'game_cancel');
CREATE TYPE ck_ingest_job_raw_status AS ENUM ('available', 'missing', 'conflict', 'unverified');
CREATE TYPE ck_ingest_job_status AS ENUM ('pending', 'processing', 'awaiting_link', 'done', 'failed');
CREATE TYPE ck_match_fetch_status AS ENUM ('pending', 'done', 'failed');
CREATE TYPE tournament.pickbanmode AS ENUM ('pool', 'slots');
CREATE TYPE tournament.pickbanfirstpickrule AS ENUM ('higher_seed');
CREATE TYPE tournament.pickbanrotation AS ENUM ('fixed', 'alternate', 'result_winner_first', 'result_loser_first', 'result_loser_choice');
CREATE TYPE tournament.stagetype AS ENUM ('round_robin', 'single_elimination', 'double_elimination', 'swiss', 'ffa_league');
CREATE TYPE tournament.stageitemtype AS ENUM ('group', 'bracket_upper', 'bracket_lower', 'single_bracket');
CREATE TYPE tournament.stageiteminputtype AS ENUM ('final', 'tentative', 'empty');
CREATE TYPE tournament.tournamentstatus AS ENUM ('announcement', 'registration', 'draft', 'check_in', 'live', 'playoffs', 'completed', 'archived');

CREATE TABLE achievements.evaluation_result (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	achievement_rule_id BIGINT NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	tournament_id BIGINT,
	encounter_id BIGINT,
	match_id BIGINT,
	qualified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	evidence_json JSON,
	rule_version INTEGER NOT NULL,
	run_id UUID,
	PRIMARY KEY (id),
	CONSTRAINT uq_eval_result_rule_user_tournament_match UNIQUE (achievement_rule_id, workspace_member_id, tournament_id, encounter_id, match_id),
	FOREIGN KEY(achievement_rule_id) REFERENCES achievements.rule (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE,
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	FOREIGN KEY(match_id) REFERENCES stats.match (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(run_id) REFERENCES achievements.evaluation_run (id) ON DELETE SET NULL
);

CREATE INDEX ix_achievements_evaluation_result_achievement_rule_id ON achievements.evaluation_result (achievement_rule_id);

CREATE INDEX ix_achievements_evaluation_result_encounter_id ON achievements.evaluation_result (encounter_id) WHERE encounter_id IS NOT NULL;

CREATE INDEX ix_achievements_evaluation_result_match_id ON achievements.evaluation_result (match_id) WHERE match_id IS NOT NULL;

CREATE INDEX ix_achievements_evaluation_result_run_id ON achievements.evaluation_result (run_id);

CREATE INDEX ix_achievements_evaluation_result_tournament_id ON achievements.evaluation_result (tournament_id);

CREATE INDEX ix_achievements_evaluation_result_workspace_member_id ON achievements.evaluation_result (workspace_member_id);

CREATE TABLE achievements.evaluation_run (
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	trigger VARCHAR NOT NULL,
	tournament_id BIGINT,
	rules_evaluated INTEGER DEFAULT '0' NOT NULL,
	results_created INTEGER DEFAULT '0' NOT NULL,
	results_removed INTEGER DEFAULT '0' NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	status VARCHAR DEFAULT 'running' NOT NULL,
	error_message VARCHAR,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE SET NULL
);

CREATE INDEX ix_achievements_evaluation_run_id ON achievements.evaluation_run (id);

CREATE INDEX ix_achievements_evaluation_run_workspace_id ON achievements.evaluation_run (workspace_id);

CREATE TABLE achievements.override (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	achievement_rule_id BIGINT NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	tournament_id BIGINT,
	match_id BIGINT,
	action VARCHAR NOT NULL,
	reason VARCHAR NOT NULL,
	granted_by BIGINT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(achievement_rule_id) REFERENCES achievements.rule (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE,
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(match_id) REFERENCES stats.match (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(granted_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_achievements_override_achievement_rule_id ON achievements.override (achievement_rule_id);

CREATE INDEX ix_achievements_override_match_id ON achievements.override (match_id);

CREATE INDEX ix_achievements_override_tournament_id ON achievements.override (tournament_id);

CREATE INDEX ix_achievements_override_workspace_member_id ON achievements.override (workspace_member_id);

CREATE TABLE achievements.rule (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	slug VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	description_ru VARCHAR NOT NULL,
	description_en VARCHAR NOT NULL,
	image_url VARCHAR,
	discipline VARCHAR(32) NOT NULL,
	entity_id BIGINT,
	entity_kind VARCHAR(16) DEFAULT 'character' NOT NULL,
	category VARCHAR NOT NULL,
	scope VARCHAR NOT NULL,
	grain VARCHAR NOT NULL,
	condition_tree JSON DEFAULT '{}' NOT NULL,
	depends_on JSON DEFAULT '[]' NOT NULL,
	enabled BOOLEAN DEFAULT 'true' NOT NULL,
	rule_version INTEGER DEFAULT '1' NOT NULL,
	min_tournament_id INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT uq_achievement_rule_workspace_slug UNIQUE (workspace_id, slug),
	CONSTRAINT ck_rule_entity_kind CHECK (entity_kind = 'character'),
	CONSTRAINT fk_rule_entity FOREIGN KEY(entity_id, entity_kind, discipline) REFERENCES catalog.entity (id, kind, discipline) ON DELETE SET NULL (entity_id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_rule_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code)
);

CREATE INDEX ix_achievements_rule_slug ON achievements.rule (slug);

CREATE INDEX ix_achievements_rule_workspace_id ON achievements.rule (workspace_id);

CREATE TABLE analytics.algorithms (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	name VARCHAR NOT NULL,
	produces_shifts BOOLEAN DEFAULT 'true' NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (name)
);

CREATE TABLE analytics.anomaly_feedback (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	player_id BIGINT NOT NULL,
	kind VARCHAR(32) NOT NULL,
	verdict VARCHAR(16) NOT NULL,
	reviewer_user_id BIGINT,
	note TEXT,
	PRIMARY KEY (id),
	CONSTRAINT uq_analytics_anomaly_feedback UNIQUE (tournament_id, player_id, kind),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(player_id) REFERENCES tournament.player (id) ON DELETE CASCADE,
	FOREIGN KEY(reviewer_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_analytics_anomaly_feedback_kind ON analytics.anomaly_feedback (kind);

CREATE INDEX ix_analytics_anomaly_feedback_player_id ON analytics.anomaly_feedback (player_id);

CREATE INDEX ix_analytics_anomaly_feedback_reviewer_user_id ON analytics.anomaly_feedback (reviewer_user_id);

CREATE INDEX ix_analytics_anomaly_feedback_tournament_id ON analytics.anomaly_feedback (tournament_id);

CREATE TABLE analytics.job (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT,
	tournament_id BIGINT NOT NULL,
	requested_by_user_id BIGINT,
	kind VARCHAR(16) NOT NULL,
	status VARCHAR(16) DEFAULT 'pending' NOT NULL,
	algorithms JSON,
	training_workspace_ids JSON,
	progress JSON DEFAULT '{}' NOT NULL,
	error TEXT,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(requested_by_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_analytics_job_requested_by_user_id ON analytics.job (requested_by_user_id);

CREATE INDEX ix_analytics_job_status ON analytics.job (status);

CREATE INDEX ix_analytics_job_tournament_id ON analytics.job (tournament_id);

CREATE INDEX ix_analytics_job_workspace_id ON analytics.job (workspace_id);

CREATE UNIQUE INDEX uq_analytics_job_one_running_per_workspace ON analytics.job (workspace_id) WHERE status IN ('pending', 'running');

CREATE TABLE analytics.match_quality (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	algorithm_id BIGINT NOT NULL,
	competitiveness FLOAT NOT NULL,
	predictability FLOAT NOT NULL,
	skill_balance FLOAT NOT NULL,
	quality_score FLOAT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_analytics_match_quality UNIQUE (encounter_id, algorithm_id),
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	FOREIGN KEY(algorithm_id) REFERENCES analytics.algorithms (id) ON DELETE CASCADE
);

CREATE INDEX ix_analytics_match_quality_algorithm_id ON analytics.match_quality (algorithm_id);

CREATE INDEX ix_analytics_match_quality_encounter_id ON analytics.match_quality (encounter_id);

CREATE TABLE analytics.ml_model_artifact (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	algorithm_id BIGINT NOT NULL,
	model_kind VARCHAR(32) NOT NULL,
	dimension_id BIGINT,
	role_id BIGINT,
	version VARCHAR(32) NOT NULL,
	storage_uri TEXT NOT NULL,
	feature_version VARCHAR(32) NOT NULL,
	training_cutoff_tournament_id BIGINT,
	metrics JSON,
	feature_importance JSON,
	is_active BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_analytics_ml_model_artifact_role UNIQUE (algorithm_id, model_kind, role_id, version),
	CONSTRAINT fk_ml_model_artifact_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(algorithm_id) REFERENCES analytics.algorithms (id) ON DELETE CASCADE,
	FOREIGN KEY(training_cutoff_tournament_id) REFERENCES tournament.tournament (id) ON DELETE SET NULL
);

CREATE INDEX ix_analytics_ml_model_artifact_algorithm_id ON analytics.ml_model_artifact (algorithm_id);

CREATE INDEX ix_analytics_ml_model_artifact_is_active ON analytics.ml_model_artifact (is_active);

CREATE INDEX ix_analytics_ml_model_artifact_model_kind ON analytics.ml_model_artifact (model_kind);

CREATE INDEX ix_analytics_ml_model_artifact_training_cutoff_tournament_id ON analytics.ml_model_artifact (training_cutoff_tournament_id);

CREATE TABLE analytics.performance (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	player_id BIGINT NOT NULL,
	algorithm_id BIGINT NOT NULL,
	impact_score FLOAT NOT NULL,
	raw_value FLOAT NOT NULL,
	confidence FLOAT DEFAULT '0' NOT NULL,
	log_coverage FLOAT DEFAULT '0' NOT NULL,
	local_mean FLOAT DEFAULT '0' NOT NULL,
	local_std FLOAT DEFAULT '1' NOT NULL,
	local_residual FLOAT DEFAULT '0' NOT NULL,
	local_zscore FLOAT DEFAULT '0' NOT NULL,
	local_percentile FLOAT DEFAULT '50' NOT NULL,
	local_reference_n INTEGER DEFAULT '0' NOT NULL,
	local_band_min_div INTEGER,
	local_band_max_div INTEGER,
	contributions JSON,
	base_value FLOAT,
	PRIMARY KEY (id),
	CONSTRAINT uq_analytics_performance UNIQUE (tournament_id, player_id, algorithm_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(player_id) REFERENCES tournament.player (id) ON DELETE CASCADE,
	FOREIGN KEY(algorithm_id) REFERENCES analytics.algorithms (id) ON DELETE CASCADE
);

CREATE INDEX ix_analytics_performance_algorithm_id ON analytics.performance (algorithm_id);

CREATE INDEX ix_analytics_performance_player_id ON analytics.performance (player_id);

CREATE INDEX ix_analytics_performance_tournament_id ON analytics.performance (tournament_id);

CREATE TABLE analytics.player_anomaly (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	player_id BIGINT NOT NULL,
	kind VARCHAR(32) NOT NULL,
	score FLOAT NOT NULL,
	confidence FLOAT DEFAULT '0' NOT NULL,
	reasons JSON NOT NULL,
	evidence JSON,
	source_encounter_id BIGINT,
	PRIMARY KEY (id),
	CONSTRAINT uq_analytics_player_anomaly UNIQUE (tournament_id, player_id, kind, source_encounter_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(player_id) REFERENCES tournament.player (id) ON DELETE CASCADE,
	FOREIGN KEY(source_encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_analytics_player_anomaly_kind ON analytics.player_anomaly (kind);

CREATE INDEX ix_analytics_player_anomaly_player_id ON analytics.player_anomaly (player_id);

CREATE INDEX ix_analytics_player_anomaly_source_encounter_id ON analytics.player_anomaly (source_encounter_id);

CREATE INDEX ix_analytics_player_anomaly_tournament_id ON analytics.player_anomaly (tournament_id);

CREATE TABLE analytics.player_shift (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	player_id BIGINT NOT NULL,
	wins INTEGER NOT NULL,
	losses INTEGER NOT NULL,
	shift_one INTEGER,
	shift_two INTEGER,
	shift INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT uq_analytics_player_shift UNIQUE (tournament_id, player_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(player_id) REFERENCES tournament.player (id) ON DELETE CASCADE
);

CREATE INDEX ix_analytics_player_shift_player_id ON analytics.player_shift (player_id);

CREATE INDEX ix_analytics_player_shift_tournament_id ON analytics.player_shift (tournament_id);

CREATE TABLE analytics.shifts (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	algorithm_id BIGINT NOT NULL,
	player_id BIGINT NOT NULL,
	shift FLOAT NOT NULL,
	shift_sd FLOAT,
	effective_evidence FLOAT DEFAULT '0' NOT NULL,
	sample_tournaments INTEGER DEFAULT '0' NOT NULL,
	sample_matches INTEGER DEFAULT '0' NOT NULL,
	log_coverage FLOAT DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_analytics_shifts UNIQUE (tournament_id, player_id, algorithm_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(algorithm_id) REFERENCES analytics.algorithms (id) ON DELETE CASCADE,
	FOREIGN KEY(player_id) REFERENCES tournament.player (id) ON DELETE CASCADE
);

CREATE INDEX ix_analytics_shifts_algorithm_id ON analytics.shifts (algorithm_id);

CREATE INDEX ix_analytics_shifts_player_id ON analytics.shifts (player_id);

CREATE INDEX ix_analytics_shifts_tournament_id ON analytics.shifts (tournament_id);

CREATE TABLE analytics.standings_distribution (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	team_id BIGINT NOT NULL,
	algorithm_id BIGINT NOT NULL,
	mean_position FLOAT NOT NULL,
	median_position FLOAT NOT NULL,
	p10_position FLOAT NOT NULL,
	p90_position FLOAT NOT NULL,
	prob_top1 FLOAT DEFAULT '0' NOT NULL,
	prob_top3 FLOAT DEFAULT '0' NOT NULL,
	prob_top8 FLOAT DEFAULT '0' NOT NULL,
	position_histogram JSON NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_analytics_standings_distribution UNIQUE (tournament_id, team_id, algorithm_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE,
	FOREIGN KEY(algorithm_id) REFERENCES analytics.algorithms (id) ON DELETE CASCADE
);

CREATE INDEX ix_analytics_standings_distribution_algorithm_id ON analytics.standings_distribution (algorithm_id);

CREATE INDEX ix_analytics_standings_distribution_team_id ON analytics.standings_distribution (team_id);

CREATE INDEX ix_analytics_standings_distribution_tournament_id ON analytics.standings_distribution (tournament_id);

CREATE TABLE auth.api_key (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	auth_user_id BIGINT NOT NULL,
	workspace_id BIGINT NOT NULL,
	public_id VARCHAR(32) NOT NULL,
	secret_hash VARCHAR(128) NOT NULL,
	name VARCHAR(100) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE,
	revoked_at TIMESTAMP WITH TIME ZONE,
	last_used_at TIMESTAMP WITH TIME ZONE,
	is_superuser BOOLEAN DEFAULT false NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_api_key_owner_workspace ON auth.api_key (auth_user_id, workspace_id);

CREATE INDEX ix_api_key_public_id_active ON auth.api_key (public_id, revoked_at);

CREATE INDEX ix_auth_api_key_auth_user_id ON auth.api_key (auth_user_id);

CREATE UNIQUE INDEX ix_auth_api_key_public_id ON auth.api_key (public_id);

CREATE INDEX ix_auth_api_key_workspace_id ON auth.api_key (workspace_id);

CREATE TABLE auth.api_key_scope (
	api_key_id BIGINT NOT NULL,
	scope VARCHAR(64) NOT NULL,
	PRIMARY KEY (api_key_id, scope),
	FOREIGN KEY(api_key_id) REFERENCES auth.api_key (id) ON DELETE CASCADE
);

CREATE TABLE auth.oauth_connections (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	auth_user_id BIGINT NOT NULL,
	provider VARCHAR(50) NOT NULL,
	provider_user_id VARCHAR(255) NOT NULL,
	email VARCHAR(255),
	username VARCHAR(100) NOT NULL,
	display_name VARCHAR(100),
	avatar_url VARCHAR(500),
	access_token TEXT,
	refresh_token TEXT,
	token_expires_at TIMESTAMP WITH TIME ZONE,
	provider_data JSON,
	PRIMARY KEY (id),
	CONSTRAINT uq_provider_user UNIQUE (provider, provider_user_id),
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_oauth_connections_provider ON auth.oauth_connections (provider);

CREATE INDEX ix_auth_oauth_connections_provider_user_id ON auth.oauth_connections (provider_user_id);

CREATE TABLE auth.permissions (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	name VARCHAR(100) NOT NULL,
	resource VARCHAR(100) NOT NULL,
	action VARCHAR(50) NOT NULL,
	description TEXT,
	PRIMARY KEY (id)
);

CREATE INDEX ix_auth_permissions_action ON auth.permissions (action);

CREATE UNIQUE INDEX ix_auth_permissions_name ON auth.permissions (name);

CREATE INDEX ix_auth_permissions_resource ON auth.permissions (resource);

CREATE TABLE auth.refresh_token (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	token TEXT NOT NULL,
	user_id BIGINT NOT NULL,
	session_id UUID NOT NULL,
	session_started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	is_revoked BOOLEAN NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	user_agent VARCHAR(500),
	ip_address VARCHAR(45),
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_refresh_token_session_id ON auth.refresh_token (session_id);

CREATE UNIQUE INDEX ix_auth_refresh_token_token ON auth.refresh_token (token);

CREATE INDEX ix_auth_refresh_token_user_id ON auth.refresh_token (user_id);

CREATE TABLE auth.role_permissions (
	id SERIAL NOT NULL,
	role_id INTEGER NOT NULL,
	permission_id INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(role_id) REFERENCES auth.roles (id) ON DELETE CASCADE,
	FOREIGN KEY(permission_id) REFERENCES auth.permissions (id) ON DELETE CASCADE
);

CREATE INDEX ix_role_permissions_permission_id ON auth.role_permissions (permission_id);

CREATE INDEX ix_role_permissions_role_id ON auth.role_permissions (role_id);

CREATE TABLE auth.roles (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	name VARCHAR(100) NOT NULL,
	description TEXT,
	is_system BOOLEAN NOT NULL,
	workspace_id BIGINT,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_roles_name ON auth.roles (name);

CREATE INDEX ix_auth_roles_workspace_id ON auth.roles (workspace_id);

CREATE UNIQUE INDEX uq_roles_name_global ON auth.roles (name) WHERE workspace_id IS NULL;

CREATE UNIQUE INDEX uq_roles_name_workspace ON auth.roles (name, workspace_id) WHERE workspace_id IS NOT NULL;

CREATE TABLE auth."user" (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	email VARCHAR(255) NOT NULL,
	username VARCHAR(100) NOT NULL,
	hashed_password VARCHAR(255),
	is_active BOOLEAN NOT NULL,
	is_superuser BOOLEAN NOT NULL,
	is_verified BOOLEAN NOT NULL,
	first_name VARCHAR(100),
	last_name VARCHAR(100),
	avatar_url VARCHAR(500),
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_auth_user_email ON auth."user" (email);

CREATE UNIQUE INDEX ix_auth_user_username ON auth."user" (username);

CREATE TABLE auth.user_permission_deny (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	user_id BIGINT NOT NULL,
	permission_id BIGINT NOT NULL,
	workspace_id BIGINT,
	created_by BIGINT,
	reason TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES auth."user" (id) ON DELETE CASCADE,
	FOREIGN KEY(permission_id) REFERENCES auth.permissions (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_auth_user_permission_deny_workspace_id ON auth.user_permission_deny (workspace_id);

CREATE INDEX ix_user_permission_deny_user_id ON auth.user_permission_deny (user_id);

CREATE UNIQUE INDEX uq_user_permission_deny_user_perm_workspace ON auth.user_permission_deny (user_id, permission_id, COALESCE(workspace_id, 0));

CREATE TABLE auth.user_roles (
	id SERIAL NOT NULL,
	user_id INTEGER NOT NULL,
	role_id INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES auth."user" (id) ON DELETE CASCADE,
	FOREIGN KEY(role_id) REFERENCES auth.roles (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_roles_role_id ON auth.user_roles (role_id);

CREATE INDEX ix_user_roles_user_id ON auth.user_roles (user_id);

CREATE TABLE balancer.balance (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	workspace_id BIGINT,
	algorithm VARCHAR(32),
	division_grid_json JSON,
	division_scope VARCHAR(32),
	config_json JSON,
	result_json JSON NOT NULL,
	saved_by BIGINT,
	saved_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	exported_at TIMESTAMP WITH TIME ZONE,
	export_status VARCHAR(32),
	export_error TEXT,
	PRIMARY KEY (id),
	CONSTRAINT uq_balancer_balance_tournament UNIQUE (tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE SET NULL,
	FOREIGN KEY(saved_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_balance_tournament_id ON balancer.balance (tournament_id);

CREATE INDEX ix_balancer_balance_workspace_id ON balancer.balance (workspace_id);

CREATE TABLE balancer.balance_variant (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	balance_id BIGINT NOT NULL,
	variant_number INTEGER NOT NULL,
	algorithm VARCHAR(32) NOT NULL,
	objective_score FLOAT,
	statistics_json JSON,
	is_selected BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_balancer_balance_variant UNIQUE (balance_id, variant_number),
	FOREIGN KEY(balance_id) REFERENCES balancer.balance (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_balance_variant_balance_id ON balancer.balance_variant (balance_id);

CREATE TABLE balancer.member_hidden_rating (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	dimension_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	mu FLOAT NOT NULL,
	sigma FLOAT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_member_hidden_rating_member_role_id UNIQUE (workspace_member_id, role_id),
	CONSTRAINT fk_member_hidden_rating_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_member_hidden_rating_role_id ON balancer.member_hidden_rating (role_id);

CREATE INDEX ix_balancer_member_hidden_rating_workspace_id ON balancer.member_hidden_rating (workspace_id);

CREATE TABLE balancer.member_rank (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	author_user_id BIGINT,
	dimension_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	rank_value INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_member_rank_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE,
	FOREIGN KEY(author_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_member_rank_author_user_id ON balancer.member_rank (author_user_id);

CREATE INDEX ix_balancer_member_rank_role_id ON balancer.member_rank (role_id);

CREATE INDEX ix_balancer_member_rank_workspace_id ON balancer.member_rank (workspace_id);

CREATE INDEX ix_balancer_member_rank_workspace_member_id ON balancer.member_rank (workspace_member_id);

CREATE UNIQUE INDEX uq_member_rank_author_role ON balancer.member_rank (workspace_id, author_user_id, workspace_member_id, role_id) WHERE author_user_id IS NOT NULL;

CREATE UNIQUE INDEX uq_member_rank_canon_role ON balancer.member_rank (workspace_id, workspace_member_id, role_id) WHERE author_user_id IS NULL;

CREATE TABLE balancer.team (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	balance_id BIGINT NOT NULL,
	variant_id BIGINT,
	exported_team_id BIGINT,
	name VARCHAR(255) NOT NULL,
	balancer_name VARCHAR(255) NOT NULL,
	captain_battle_tag VARCHAR(255),
	avg_sr FLOAT NOT NULL,
	total_sr INTEGER NOT NULL,
	sort_order INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(balance_id) REFERENCES balancer.balance (id) ON DELETE CASCADE,
	FOREIGN KEY(variant_id) REFERENCES balancer.balance_variant (id) ON DELETE CASCADE,
	FOREIGN KEY(exported_team_id) REFERENCES tournament.team (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_team_balance_id ON balancer.team (balance_id);

CREATE INDEX ix_balancer_team_exported_team_id ON balancer.team (exported_team_id);

CREATE INDEX ix_balancer_team_variant_id ON balancer.team (variant_id);

CREATE TABLE balancer.team_slot (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	team_id BIGINT NOT NULL,
	battle_tag_normalized VARCHAR(255),
	dimension_id BIGINT,
	role_id BIGINT,
	assigned_rank INTEGER NOT NULL,
	discomfort INTEGER DEFAULT '0' NOT NULL,
	is_captain BOOLEAN DEFAULT 'false' NOT NULL,
	sort_order INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_team_slot_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(team_id) REFERENCES balancer.team (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_team_slot_battle_tag_normalized ON balancer.team_slot (battle_tag_normalized);

CREATE INDEX ix_balancer_team_slot_role_id ON balancer.team_slot (role_id);

CREATE INDEX ix_balancer_team_slot_team_id ON balancer.team_slot (team_id);

CREATE TABLE balancer.tournament_config (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	workspace_id BIGINT NOT NULL,
	config_json JSON DEFAULT '{}' NOT NULL,
	updated_by BIGINT,
	PRIMARY KEY (id),
	CONSTRAINT uq_balancer_tournament_config_tournament UNIQUE (tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(updated_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_tournament_config_tournament_id ON balancer.tournament_config (tournament_id);

CREATE INDEX ix_balancer_tournament_config_workspace_id ON balancer.tournament_config (workspace_id);

CREATE TABLE balancer.user_config (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	user_id BIGINT NOT NULL,
	config_json JSONB DEFAULT '{}' NOT NULL,
	points_per_win INTEGER,
	rating_mode VARCHAR(16) DEFAULT 'points' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_balancer_user_config_user UNIQUE (user_id),
	CONSTRAINT ck_balancer_user_config_rating_mode CHECK (rating_mode IN ('points', 'ranker')),
	FOREIGN KEY(user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_user_config_user_id ON balancer.user_config (user_id);

CREATE TABLE balancer.workspace_config (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	config_json JSON DEFAULT '{}' NOT NULL,
	updated_by BIGINT,
	ranker_json JSONB,
	PRIMARY KEY (id),
	CONSTRAINT uq_balancer_workspace_config_workspace UNIQUE (workspace_id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(updated_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_workspace_config_workspace_id ON balancer.workspace_config (workspace_id);

CREATE TABLE catalog.alias_miss (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	discipline VARCHAR(32) NOT NULL,
	kind VARCHAR(16) NOT NULL,
	raw_name VARCHAR(128) NOT NULL,
	occurrences INTEGER DEFAULT '1' NOT NULL,
	first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_ingest_job_id BIGINT,
	resolved_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_alias_miss_kind CHECK (kind IN ('character', 'map', 'mode', 'stat', 'event', 'role')),
	CONSTRAINT uq_alias_miss UNIQUE (discipline, kind, raw_name),
	CONSTRAINT fk_alias_miss_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code),
	CONSTRAINT fk_alias_miss_ingest_job FOREIGN KEY(last_ingest_job_id) REFERENCES stats.ingest_job (id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_alias_miss_ingest_job ON catalog.alias_miss (last_ingest_job_id);

CREATE TABLE catalog.discipline (
	code VARCHAR(32) NOT NULL,
	name VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (code)
);

CREATE TABLE catalog.entity (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	discipline VARCHAR(32) NOT NULL,
	kind VARCHAR(16) NOT NULL,
	slug VARCHAR(64) NOT NULL,
	name VARCHAR(128) NOT NULL,
	image_path VARCHAR,
	parent_id BIGINT,
	attrs JSONB DEFAULT '{}'::jsonb NOT NULL,
	aliases JSONB DEFAULT '[]'::jsonb NOT NULL,
	active BOOLEAN DEFAULT true NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_entity_kind CHECK (kind IN ('character', 'map', 'mode')),
	CONSTRAINT ck_entity_attrs CHECK (jsonb_typeof(attrs) = 'object'),
	CONSTRAINT ck_entity_aliases CHECK (jsonb_typeof(aliases) = 'array'),
	CONSTRAINT uq_entity_slug UNIQUE (discipline, kind, slug),
	CONSTRAINT uq_entity_name UNIQUE (discipline, kind, name),
	CONSTRAINT uq_entity_id_kind UNIQUE (id, kind),
	CONSTRAINT uq_entity_id_discipline UNIQUE (id, discipline),
	CONSTRAINT uq_entity_key UNIQUE (id, discipline, kind),
	CONSTRAINT fk_entity_parent FOREIGN KEY(parent_id, discipline) REFERENCES catalog.entity (id, discipline),
	CONSTRAINT fk_entity_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code)
);

CREATE TABLE catalog.role (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	dimension_id BIGINT NOT NULL,
	workspace_id BIGINT,
	parent_role_id BIGINT,
	code VARCHAR(64) NOT NULL,
	name VARCHAR(128) NOT NULL,
	description TEXT,
	selectable BOOLEAN DEFAULT true NOT NULL,
	active BOOLEAN DEFAULT true NOT NULL,
	sort_order INTEGER DEFAULT 0 NOT NULL,
	attrs JSONB DEFAULT '{}'::jsonb NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_role_key UNIQUE (id, dimension_id),
	CONSTRAINT fk_role_parent FOREIGN KEY(parent_role_id, dimension_id) REFERENCES catalog.role (id, dimension_id),
	CONSTRAINT ck_role_workspace_is_child CHECK (workspace_id IS NULL OR parent_role_id IS NOT NULL),
	CONSTRAINT ck_role_attrs CHECK (jsonb_typeof(attrs) = 'object'),
	CONSTRAINT fk_role_dimension FOREIGN KEY(dimension_id) REFERENCES catalog.role_dimension (id),
	CONSTRAINT fk_role_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_role_module_code ON catalog.role (dimension_id, code) WHERE workspace_id IS NULL;

CREATE UNIQUE INDEX uq_role_workspace_code ON catalog.role (dimension_id, workspace_id, code) WHERE workspace_id IS NOT NULL;

CREATE TABLE catalog.role_dimension (
	id BIGSERIAL NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	code VARCHAR(32) NOT NULL,
	name VARCHAR(64) NOT NULL,
	selection_mode VARCHAR(8) NOT NULL,
	rated BOOLEAN DEFAULT false NOT NULL,
	active BOOLEAN DEFAULT true NOT NULL,
	sort_order INTEGER DEFAULT 0 NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_role_dimension_selection_mode CHECK (selection_mode IN ('single', 'multi')),
	CONSTRAINT uq_role_dimension_code UNIQUE (discipline, code),
	CONSTRAINT uq_role_dimension_key UNIQUE (id, discipline),
	CONSTRAINT fk_role_dimension_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code)
);

CREATE UNIQUE INDEX uq_role_dimension_rated ON catalog.role_dimension (discipline) WHERE rated;

CREATE TABLE draft.audit_event (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	session_id BIGINT NOT NULL,
	actor_auth_user_id BIGINT,
	action VARCHAR(64) NOT NULL,
	entity_type VARCHAR(64) NOT NULL,
	entity_id BIGINT NOT NULL,
	reason TEXT NOT NULL,
	before_json JSON NOT NULL,
	after_json JSON NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(session_id) REFERENCES draft.session (id) ON DELETE CASCADE,
	FOREIGN KEY(actor_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_draft_audit_event_actor_auth_user_id ON draft.audit_event (actor_auth_user_id);

CREATE INDEX ix_draft_audit_session_created ON draft.audit_event (session_id, created_at);

CREATE TABLE draft.pick (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	session_id BIGINT NOT NULL,
	overall_no INTEGER NOT NULL,
	round_no INTEGER NOT NULL,
	pick_in_round INTEGER NOT NULL,
	draft_team_id BIGINT NOT NULL,
	dimension_id BIGINT,
	target_role_id BIGINT,
	target_rank_value INTEGER,
	status VARCHAR(16) DEFAULT 'upcoming' NOT NULL,
	picked_player_id BIGINT,
	picked_by_workspace_member_id BIGINT,
	is_autopick BOOLEAN DEFAULT 'false' NOT NULL,
	is_admin_override BOOLEAN DEFAULT 'false' NOT NULL,
	clock_started_at TIMESTAMP WITH TIME ZONE,
	clock_expires_at TIMESTAMP WITH TIME ZONE,
	clock_remaining_ms INTEGER,
	overtime_started_at TIMESTAMP WITH TIME ZONE,
	version INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_draft_pick_session_overall UNIQUE (session_id, overall_no),
	CONSTRAINT fk_draft_pick_target_role FOREIGN KEY(target_role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(session_id) REFERENCES draft.session (id) ON DELETE CASCADE,
	FOREIGN KEY(draft_team_id) REFERENCES draft.team (id) ON DELETE CASCADE,
	FOREIGN KEY(picked_player_id) REFERENCES draft.player (id) ON DELETE SET NULL,
	FOREIGN KEY(picked_by_workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL
);

CREATE INDEX ix_draft_pick_draft_team_id ON draft.pick (draft_team_id);

CREATE INDEX ix_draft_pick_picked_player_id ON draft.pick (picked_player_id);

CREATE INDEX ix_draft_pick_session_status ON draft.pick (session_id, status);

CREATE INDEX ix_draft_pick_target_role_id ON draft.pick (target_role_id);

CREATE TABLE draft.player (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	session_id BIGINT NOT NULL,
	registration_id BIGINT NOT NULL,
	workspace_member_id BIGINT,
	status VARCHAR(16) DEFAULT 'available' NOT NULL,
	is_captain BOOLEAN DEFAULT 'false' NOT NULL,
	drafted_by_team_id BIGINT,
	dimension_id BIGINT,
	captain_role_id BIGINT,
	version INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_draft_player_session_registration UNIQUE (session_id, registration_id),
	CONSTRAINT fk_draft_player_captain_role FOREIGN KEY(captain_role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(session_id) REFERENCES draft.session (id) ON DELETE CASCADE,
	FOREIGN KEY(registration_id) REFERENCES registration.registration (id) ON DELETE RESTRICT,
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL,
	FOREIGN KEY(drafted_by_team_id) REFERENCES draft.team (id) ON DELETE SET NULL
);

CREATE INDEX ix_draft_player_captain_role_id ON draft.player (captain_role_id);

CREATE INDEX ix_draft_player_drafted_by_team_id ON draft.player (drafted_by_team_id);

CREATE INDEX ix_draft_player_registration_id ON draft.player (registration_id);

CREATE INDEX ix_draft_player_session_status ON draft.player (session_id, status);

CREATE INDEX ix_draft_player_workspace_member_id ON draft.player (workspace_member_id);

CREATE TABLE draft.session (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	workspace_id BIGINT NOT NULL,
	status VARCHAR(16) DEFAULT 'setup' NOT NULL,
	blocked_reason VARCHAR(64),
	format VARCHAR(16) DEFAULT 'snake' NOT NULL,
	rounds INTEGER DEFAULT '4' NOT NULL,
	pick_time_seconds INTEGER DEFAULT '45' NOT NULL,
	overtime_seconds INTEGER DEFAULT '0' NOT NULL,
	current_pick_id BIGINT,
	pool_source VARCHAR(32) DEFAULT 'balancer_balance' NOT NULL,
	source_balance_id BIGINT,
	autopick_strategy VARCHAR(16) DEFAULT 'best_fit' NOT NULL,
	allow_admin_override BOOLEAN DEFAULT 'true' NOT NULL,
	exported_at TIMESTAMP WITH TIME ZONE,
	export_status VARCHAR(32),
	settings_json JSON DEFAULT '{}' NOT NULL,
	version INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(source_balance_id) REFERENCES balancer.balance (id) ON DELETE SET NULL
);

CREATE INDEX ix_draft_session_source_balance_id ON draft.session (source_balance_id);

CREATE INDEX ix_draft_session_status_created ON draft.session (status, created_at);

CREATE INDEX ix_draft_session_tournament_status ON draft.session (tournament_id, status);

CREATE INDEX ix_draft_session_workspace_id ON draft.session (workspace_id);

CREATE UNIQUE INDEX uq_draft_session_active_tournament ON draft.session (tournament_id) WHERE status IN ('setup','ready','live','paused');

CREATE TABLE draft.team (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	session_id BIGINT NOT NULL,
	captain_workspace_member_id BIGINT,
	captain_auth_user_id BIGINT,
	name VARCHAR(255) NOT NULL,
	draft_position INTEGER NOT NULL,
	exported_team_id BIGINT,
	pick_queue JSONB DEFAULT '[]' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_draft_team_session_position UNIQUE (session_id, draft_position),
	FOREIGN KEY(session_id) REFERENCES draft.session (id) ON DELETE CASCADE,
	FOREIGN KEY(captain_workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL,
	FOREIGN KEY(captain_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(exported_team_id) REFERENCES tournament.team (id) ON DELETE SET NULL
);

CREATE INDEX ix_draft_team_captain_auth_user_id ON draft.team (captain_auth_user_id);

CREATE INDEX ix_draft_team_captain_workspace_member_id ON draft.team (captain_workspace_member_id);

CREATE INDEX ix_draft_team_exported_team_id ON draft.team (exported_team_id);

CREATE INDEX ix_draft_team_session_id ON draft.team (session_id);

CREATE TABLE encounter.encounter (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	tournament_id BIGINT,
	custom_game_id BIGINT,
	scoring_rule_id BIGINT NOT NULL,
	name VARCHAR NOT NULL,
	slot_count INTEGER NOT NULL,
	best_of INTEGER DEFAULT '3' NOT NULL,
	status encounter.encounterstatus NOT NULL,
	result_status encounter.encounterresultstatus DEFAULT 'none' NOT NULL,
	result_source VARCHAR(16),
	result_version BIGINT DEFAULT '0' NOT NULL,
	current_game_position INTEGER,
	closeness FLOAT,
	scheduled_at TIMESTAMP WITH TIME ZONE,
	started_at TIMESTAMP WITH TIME ZONE,
	ended_at TIMESTAMP WITH TIME ZONE,
	confirmed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_encounter_id_tournament UNIQUE (id, tournament_id),
	CONSTRAINT fk_encounter_owner FOREIGN KEY(tournament_id, workspace_id, discipline) REFERENCES tournament.tournament (id, workspace_id, discipline) ON DELETE CASCADE,
	CONSTRAINT fk_encounter_custom_game FOREIGN KEY(custom_game_id, workspace_id, discipline) REFERENCES mix.custom_game (id, workspace_id, discipline) ON DELETE CASCADE,
	CONSTRAINT ck_encounter_owner CHECK (num_nonnulls(tournament_id, custom_game_id) = 1),
	CONSTRAINT fk_encounter_scoring_rule FOREIGN KEY(scoring_rule_id, workspace_id) REFERENCES encounter.scoring_rule (id, workspace_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_encounter_best_of CHECK (best_of >= 1),
	CONSTRAINT ck_encounter_slot_count CHECK (slot_count >= 2),
	CONSTRAINT ck_encounter_result_version CHECK (result_version >= 0),
	CONSTRAINT ck_encounter_result_source CHECK (result_source IN ('games', 'series_claim', 'admin', 'import', 'host')),
	CONSTRAINT ck_encounter_confirmed_completed CHECK ((result_status = 'confirmed') = (status = 'COMPLETED')),
	CONSTRAINT ck_encounter_confirmed_source CHECK (result_status <> 'confirmed' OR result_source IS NOT NULL)
);

CREATE INDEX ix_encounter_custom_game_id ON encounter.encounter (custom_game_id);

CREATE INDEX ix_encounter_ended_at ON encounter.encounter (ended_at);

CREATE INDEX ix_encounter_scheduled_at ON encounter.encounter (scheduled_at);

CREATE INDEX ix_encounter_started_at ON encounter.encounter (started_at);

CREATE INDEX ix_encounter_status_live_upcoming ON encounter.encounter (tournament_id, status) WHERE status IN ('PENDING'::encounter.encounterstatus, 'OPEN'::encounter.encounterstatus);

CREATE INDEX ix_encounter_tournament_status ON encounter.encounter (tournament_id, status);

CREATE INDEX ix_encounter_workspace_id ON encounter.encounter (workspace_id);

CREATE TABLE encounter.game (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	position INTEGER NOT NULL,
	map_id BIGINT,
	map_kind VARCHAR(16) DEFAULT 'map' NOT NULL,
	mode_id BIGINT,
	mode_kind VARCHAR(16) DEFAULT 'mode' NOT NULL,
	state encounter.encountergamestate DEFAULT 'planned' NOT NULL,
	result_source encounter.encountergameresultsource,
	result_version INTEGER DEFAULT '0' NOT NULL,
	confirmed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_game_id_encounter UNIQUE (id, encounter_id),
	CONSTRAINT ck_game_position CHECK (position >= 1),
	CONSTRAINT ck_game_map_kind CHECK (map_kind = 'map'),
	CONSTRAINT fk_game_map FOREIGN KEY(map_id, map_kind) REFERENCES catalog.entity (id, kind) ON DELETE RESTRICT,
	CONSTRAINT ck_game_mode_kind CHECK (mode_kind = 'mode'),
	CONSTRAINT fk_game_mode FOREIGN KEY(mode_id, mode_kind) REFERENCES catalog.entity (id, kind) ON DELETE RESTRICT,
	CONSTRAINT ck_game_confirmed_shape CHECK (state != 'confirmed' OR (result_source IS NOT NULL AND confirmed_at IS NOT NULL)),
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_game_encounter_id ON encounter.game (encounter_id);

CREATE INDEX ix_game_map_id ON encounter.game (map_id);

CREATE INDEX ix_game_mode_id ON encounter.game (mode_id);

CREATE UNIQUE INDEX uq_game_encounter_position ON encounter.game (encounter_id, position) WHERE state != 'cancelled';

CREATE TABLE encounter.game_claim (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	game_id BIGINT NOT NULL,
	claimant_team_id BIGINT NOT NULL,
	reporter_user_id BIGINT,
	basis_version INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_game_claim_claimant UNIQUE (game_id, claimant_team_id),
	CONSTRAINT uq_game_claim_id_game UNIQUE (id, game_id),
	CONSTRAINT fk_game_claim_game FOREIGN KEY(game_id, encounter_id) REFERENCES encounter.game (id, encounter_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_game_claim_claimant FOREIGN KEY(game_id, claimant_team_id) REFERENCES encounter.game_team (game_id, encounter_team_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	FOREIGN KEY(reporter_user_id) REFERENCES players."user" (id) ON DELETE SET NULL
);

CREATE TABLE encounter.game_claim_result (
	claim_id BIGINT NOT NULL,
	game_id BIGINT NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	score INTEGER,
	placement INTEGER,
	column_values JSONB DEFAULT '{}'::jsonb NOT NULL,
	PRIMARY KEY (claim_id, encounter_team_id),
	CONSTRAINT fk_claim_result_claim FOREIGN KEY(claim_id, game_id) REFERENCES encounter.game_claim (id, game_id) ON DELETE CASCADE,
	CONSTRAINT fk_claim_result_participant FOREIGN KEY(game_id, encounter_team_id) REFERENCES encounter.game_team (game_id, encounter_team_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_claim_result_score CHECK (score IS NULL OR score >= 0),
	CONSTRAINT ck_claim_result_placement CHECK (placement IS NULL OR placement >= 1),
	CONSTRAINT ck_claim_result_values CHECK (jsonb_typeof(column_values) = 'object')
);

CREATE TABLE encounter.game_team (
	game_id BIGINT NOT NULL,
	encounter_id BIGINT NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	score INTEGER,
	placement INTEGER,
	column_values JSONB DEFAULT '{}'::jsonb NOT NULL,
	starting_side VARCHAR(16),
	replay_code VARCHAR(32),
	PRIMARY KEY (game_id, encounter_team_id),
	CONSTRAINT fk_game_team_game FOREIGN KEY(game_id, encounter_id) REFERENCES encounter.game (id, encounter_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_game_team_team FOREIGN KEY(encounter_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_game_team_score CHECK (score IS NULL OR score >= 0),
	CONSTRAINT ck_game_team_placement CHECK (placement IS NULL OR placement >= 1),
	CONSTRAINT ck_game_team_values CHECK (jsonb_typeof(column_values) = 'object'),
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_game_team_team ON encounter.game_team (encounter_team_id);

CREATE UNIQUE INDEX uq_game_team_side ON encounter.game_team (game_id, starting_side) WHERE starting_side IS NOT NULL;

CREATE TABLE encounter.pick_ban_entry (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	session_id BIGINT NOT NULL,
	encounter_id BIGINT NOT NULL,
	item_id INTEGER NOT NULL,
	"order" INTEGER NOT NULL,
	action_index INTEGER,
	round INTEGER,
	picked_by_kind encounter.pickbanactor,
	picked_by_team_id BIGINT,
	status encounter.pickbanentrystatus DEFAULT 'available' NOT NULL,
	protected_by_kind encounter.pickbanactor,
	protected_by_team_id BIGINT,
	carried_from_round INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT fk_pick_ban_entry_session FOREIGN KEY(session_id, encounter_id) REFERENCES encounter.pick_ban_session (id, encounter_id) ON DELETE CASCADE,
	CONSTRAINT fk_pick_ban_entry_picked_by FOREIGN KEY(picked_by_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) ON DELETE SET NULL (picked_by_team_id),
	CONSTRAINT fk_pick_ban_entry_protected_by FOREIGN KEY(protected_by_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) ON DELETE SET NULL (protected_by_team_id),
	CONSTRAINT ck_pick_ban_entry_picked_by CHECK ((picked_by_kind = 'team') = (picked_by_team_id IS NOT NULL)),
	CONSTRAINT ck_pick_ban_entry_protected_by CHECK ((protected_by_kind = 'team') = (protected_by_team_id IS NOT NULL))
);

CREATE INDEX ix_pick_ban_entry_item_id ON encounter.pick_ban_entry (item_id);

CREATE INDEX ix_pick_ban_entry_session_id ON encounter.pick_ban_entry (session_id);

CREATE TABLE encounter.pick_ban_session (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	kind encounter.pickbankind NOT NULL,
	pool_json JSON NOT NULL,
	first_team_id BIGINT,
	seed_source encounter.pickbanseedsource NOT NULL,
	resolved_sequence_json JSON NOT NULL,
	slot_reserves_json JSON,
	ruleset_json JSON NOT NULL,
	status encounter.pickbansessionstatus DEFAULT 'active' NOT NULL,
	awaiting_choice BOOLEAN DEFAULT 'false' NOT NULL,
	pending_chooser_team_id BIGINT,
	undo_requested_by_team_id BIGINT,
	undo_target_index INTEGER,
	started_at TIMESTAMP WITH TIME ZONE,
	current_step_started_at TIMESTAMP WITH TIME ZONE,
	paused_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_pick_ban_session_encounter_kind UNIQUE (encounter_id, kind),
	CONSTRAINT uq_pick_ban_session_id_encounter UNIQUE (id, encounter_id),
	CONSTRAINT fk_pick_ban_session_first_team FOREIGN KEY(first_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) ON DELETE SET NULL (first_team_id),
	CONSTRAINT fk_pick_ban_session_pending_chooser FOREIGN KEY(pending_chooser_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) ON DELETE SET NULL (pending_chooser_team_id),
	CONSTRAINT fk_pick_ban_session_undo_requested_by FOREIGN KEY(undo_requested_by_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) ON DELETE SET NULL (undo_requested_by_team_id),
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_pick_ban_session_encounter_id ON encounter.pick_ban_session (encounter_id);

CREATE TABLE encounter.pick_ban_submission (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	session_id BIGINT NOT NULL,
	encounter_id BIGINT NOT NULL,
	step_index INTEGER NOT NULL,
	encounter_team_id BIGINT,
	attempt INTEGER DEFAULT '1' NOT NULL,
	state VARCHAR(16) NOT NULL,
	items_json JSON DEFAULT '[]' NOT NULL,
	locked_at TIMESTAMP WITH TIME ZONE,
	revealed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_pick_ban_submission_state CHECK (state IN ('draft', 'locked', 'revealed', 'voided')),
	CONSTRAINT fk_pick_ban_submission_session FOREIGN KEY(session_id, encounter_id) REFERENCES encounter.pick_ban_session (id, encounter_id) ON DELETE CASCADE,
	CONSTRAINT fk_pick_ban_submission_team FOREIGN KEY(encounter_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_pick_ban_submission_session_id ON encounter.pick_ban_submission (session_id);

CREATE UNIQUE INDEX uq_pick_ban_submission_step_team_attempt ON encounter.pick_ban_submission (session_id, step_index, encounter_team_id, attempt) NULLS NOT DISTINCT;

CREATE TABLE encounter.readiness (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	ready_user_id BIGINT,
	PRIMARY KEY (id),
	CONSTRAINT uq_readiness_team UNIQUE (encounter_id, encounter_team_id),
	CONSTRAINT fk_readiness_team FOREIGN KEY(encounter_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	FOREIGN KEY(ready_user_id) REFERENCES players."user" (id) ON DELETE SET NULL
);

CREATE TABLE encounter.result_audit (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	result_version BIGINT NOT NULL,
	snapshot_scope VARCHAR(16) NOT NULL,
	game_id BIGINT,
	game_result_version INTEGER,
	actor_user_id BIGINT,
	action encounter.encounterresultauditaction NOT NULL,
	from_result_status encounter.encounterresultstatus,
	to_result_status encounter.encounterresultstatus NOT NULL,
	before JSONB,
	after JSONB NOT NULL,
	adopted_team_id BIGINT,
	reason TEXT,
	source VARCHAR(32) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_result_audit_version UNIQUE (encounter_id, result_version),
	CONSTRAINT fk_result_audit_game FOREIGN KEY(game_id, encounter_id) REFERENCES encounter.game (id, encounter_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_result_audit_adopted FOREIGN KEY(adopted_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) ON DELETE SET NULL (adopted_team_id),
	CONSTRAINT ck_result_audit_scope CHECK (snapshot_scope IN ('encounter', 'game')),
	CONSTRAINT ck_result_audit_game_scope CHECK (snapshot_scope = 'encounter' OR game_id IS NOT NULL),
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	FOREIGN KEY(actor_user_id) REFERENCES players."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_encounter_result_audit_encounter_created ON encounter.result_audit (encounter_id, created_at);

CREATE INDEX ix_result_audit_game_id ON encounter.result_audit (game_id);

CREATE TABLE encounter.room_event (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	kind VARCHAR(8),
	action VARCHAR(64) NOT NULL,
	source VARCHAR(16) NOT NULL,
	encounter_team_id BIGINT,
	actor_auth_user_id BIGINT,
	reason TEXT,
	data JSON DEFAULT '{}' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_room_event_team FOREIGN KEY(encounter_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) ON DELETE SET NULL (encounter_team_id),
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	FOREIGN KEY(actor_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_encounter_room_event_encounter_created ON encounter.room_event (encounter_id, created_at);

CREATE TABLE encounter.scoring_rule (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	preset VARCHAR(16) NOT NULL,
	columns JSONB DEFAULT '[]'::jsonb NOT NULL,
	placement_points FLOAT[] DEFAULT '{}' NOT NULL,
	game_formula VARCHAR(500) NOT NULL,
	end_formula VARCHAR(500) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_scoring_rule_id_workspace UNIQUE (id, workspace_id),
	CONSTRAINT ck_scoring_rule_preset CHECK (preset IN ('wins', 'points')),
	CONSTRAINT ck_scoring_rule_columns CHECK (jsonb_typeof(columns) = 'array'),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE TABLE encounter.team (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	tournament_id BIGINT,
	slot INTEGER NOT NULL,
	team_id BIGINT,
	name VARCHAR(255) NOT NULL,
	seed INTEGER,
	active BOOLEAN DEFAULT 'true' NOT NULL,
	score FLOAT DEFAULT '0' NOT NULL,
	placement INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT uq_team_id_encounter UNIQUE (id, encounter_id),
	CONSTRAINT uq_team_id_encounter_active UNIQUE (id, encounter_id, active),
	CONSTRAINT fk_team_encounter_tournament FOREIGN KEY(encounter_id, tournament_id) REFERENCES encounter.encounter (id, tournament_id) ON DELETE CASCADE,
	CONSTRAINT fk_team_source FOREIGN KEY(team_id, tournament_id) REFERENCES tournament.team (id, tournament_id) ON DELETE SET NULL (team_id),
	CONSTRAINT ck_team_slot CHECK (slot >= 1),
	CONSTRAINT ck_team_placement CHECK (placement IS NULL OR placement >= 1),
	CONSTRAINT ck_team_score_finite CHECK (score NOT IN ('NaN', 'Infinity', '-Infinity')),
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_team_team_id ON encounter.team (team_id);

CREATE UNIQUE INDEX uq_team_active_slot ON encounter.team (encounter_id, slot) WHERE active;

CREATE UNIQUE INDEX uq_team_active_source ON encounter.team (encounter_id, team_id) WHERE active AND team_id IS NOT NULL;

CREATE TABLE encounter.team_member (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	active BOOLEAN NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	display_name_snapshot VARCHAR(255) NOT NULL,
	rank INTEGER,
	is_substitute BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_team_member_member UNIQUE (encounter_team_id, workspace_member_id),
	CONSTRAINT fk_team_member_team FOREIGN KEY(encounter_team_id, encounter_id, active) REFERENCES encounter.team (id, encounter_id, active) ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	CONSTRAINT fk_team_member_workspace_member FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_team_member_workspace_member_id ON encounter.team_member (workspace_member_id);

CREATE UNIQUE INDEX uq_team_member_active_member ON encounter.team_member (encounter_id, workspace_member_id) WHERE active;

CREATE TABLE encounter.team_member_role (
	team_member_id BIGINT NOT NULL,
	dimension_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	PRIMARY KEY (team_member_id, role_id),
	CONSTRAINT fk_team_member_role_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_team_member_role_member FOREIGN KEY(team_member_id) REFERENCES encounter.team_member (id) ON DELETE CASCADE
);

CREATE INDEX ix_encounter_team_member_role_role_id ON encounter.team_member_role (role_id);

CREATE TABLE encounter.team_report (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	encounter_id BIGINT NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	reporter_user_id BIGINT,
	games_played INTEGER,
	basis_version BIGINT NOT NULL,
	closeness INTEGER,
	comment TEXT,
	custom_fields_json JSON DEFAULT '{}' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_team_report_claimant UNIQUE (encounter_id, encounter_team_id),
	CONSTRAINT uq_team_report_id_encounter UNIQUE (id, encounter_id),
	CONSTRAINT fk_team_report_team FOREIGN KEY(encounter_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_team_report_games CHECK (games_played IS NULL OR games_played >= 1),
	CONSTRAINT ck_team_report_closeness CHECK (closeness BETWEEN 1 AND 10),
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	FOREIGN KEY(reporter_user_id) REFERENCES players."user" (id) ON DELETE SET NULL
);

CREATE TABLE encounter.team_report_result (
	report_id BIGINT NOT NULL,
	encounter_id BIGINT NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	score FLOAT NOT NULL,
	placement INTEGER,
	wins INTEGER,
	PRIMARY KEY (report_id, encounter_team_id),
	CONSTRAINT fk_report_result_report FOREIGN KEY(report_id, encounter_id) REFERENCES encounter.team_report (id, encounter_id) ON DELETE CASCADE,
	CONSTRAINT fk_report_result_team FOREIGN KEY(encounter_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_report_result_score_finite CHECK (score NOT IN ('NaN', 'Infinity', '-Infinity')),
	CONSTRAINT ck_report_result_placement CHECK (placement IS NULL OR placement >= 1),
	CONSTRAINT ck_report_result_wins CHECK (wins IS NULL OR wins >= 0)
);

CREATE TABLE mix.co_host (
	custom_game_id BIGINT NOT NULL,
	user_id BIGINT NOT NULL,
	PRIMARY KEY (custom_game_id, user_id),
	FOREIGN KEY(custom_game_id) REFERENCES mix.custom_game (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_mix_co_host_user_id ON mix.co_host (user_id);

CREATE TABLE mix.custom_game (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	host_user_id BIGINT,
	name VARCHAR(255) NOT NULL,
	status VARCHAR(16) DEFAULT 'draft' NOT NULL,
	lobby_count INTEGER DEFAULT '1' NOT NULL,
	self_signup VARCHAR(16) DEFAULT 'closed' NOT NULL,
	self_role_edit BOOLEAN DEFAULT 'false' NOT NULL,
	general_voice_channel_id BIGINT,
	discipline VARCHAR(32) DEFAULT 'overwatch' NOT NULL,
	scoring_rule_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_custom_game_status CHECK (status IN ('draft', 'balanced', 'completed', 'cancelled')),
	CONSTRAINT ck_custom_game_self_signup CHECK (self_signup IN ('closed', 'pool', 'benched')),
	CONSTRAINT ck_custom_game_lobby_count CHECK (lobby_count BETWEEN 1 AND 6),
	CONSTRAINT uq_custom_game_owner_key UNIQUE (id, workspace_id, discipline),
	CONSTRAINT fk_custom_game_scoring_rule FOREIGN KEY(scoring_rule_id, workspace_id) REFERENCES encounter.scoring_rule (id, workspace_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(host_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL,
	CONSTRAINT fk_custom_game_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code)
);

CREATE INDEX ix_mix_custom_game_host_user_id ON mix.custom_game (host_user_id);

CREATE INDEX ix_mix_custom_game_workspace_id ON mix.custom_game (workspace_id);

CREATE TABLE mix.lobby (
	custom_game_id BIGINT NOT NULL,
	lobby_index INTEGER NOT NULL,
	selected_variant_index INTEGER DEFAULT '0' NOT NULL,
	balance_result_json JSONB,
	balance_result_version INTEGER DEFAULT '1' NOT NULL,
	next_map_id BIGINT,
	next_map_kind VARCHAR(16) DEFAULT 'map' NOT NULL,
	balanced_at TIMESTAMP WITH TIME ZONE,
	team1_voice_channel_id BIGINT,
	team2_voice_channel_id BIGINT,
	PRIMARY KEY (custom_game_id, lobby_index),
	CONSTRAINT ck_custom_game_lobby_index CHECK (lobby_index BETWEEN 0 AND 5),
	CONSTRAINT ck_custom_game_lobby_next_map_kind CHECK (next_map_kind = 'map'),
	CONSTRAINT fk_custom_game_lobby_next_map FOREIGN KEY(next_map_id, next_map_kind) REFERENCES catalog.entity (id, kind) ON DELETE SET NULL (next_map_id),
	FOREIGN KEY(custom_game_id) REFERENCES mix.custom_game (id) ON DELETE CASCADE
);

CREATE TABLE mix.player (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	custom_game_id BIGINT NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	sort_order INTEGER DEFAULT '0' NOT NULL,
	participation VARCHAR(16) DEFAULT 'pool' NOT NULL,
	role_selection_mode VARCHAR(16) DEFAULT 'all_ranked' NOT NULL,
	is_flex BOOLEAN DEFAULT 'false' NOT NULL,
	lobby_pin INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT uq_custom_game_player_member UNIQUE (custom_game_id, workspace_member_id),
	CONSTRAINT ck_custom_game_player_participation CHECK (participation IN ('must_play', 'pool', 'benched')),
	CONSTRAINT ck_custom_game_player_role_selection_mode CHECK (role_selection_mode IN ('all_ranked', 'explicit')),
	CONSTRAINT ck_custom_game_player_lobby_pin CHECK (lobby_pin BETWEEN 0 AND 5),
	FOREIGN KEY(custom_game_id) REFERENCES mix.custom_game (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE
);

CREATE INDEX ix_mix_player_custom_game_id ON mix.player (custom_game_id);

CREATE INDEX ix_mix_player_workspace_member_id ON mix.player (workspace_member_id);

CREATE TABLE mix.player_role (
	custom_game_player_id BIGINT NOT NULL,
	dimension_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	priority INTEGER NOT NULL,
	PRIMARY KEY (custom_game_player_id, role_id),
	CONSTRAINT uq_custom_game_player_role_priority UNIQUE (custom_game_player_id, priority),
	CONSTRAINT ck_custom_game_player_role_priority CHECK (priority > 0),
	CONSTRAINT fk_custom_game_player_role_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(custom_game_player_id) REFERENCES mix.player (id) ON DELETE CASCADE
);

CREATE INDEX ix_mix_player_role_role_id ON mix.player_role (role_id);

CREATE TABLE mix.round (
	encounter_id BIGINT NOT NULL,
	lobby_index INTEGER NOT NULL,
	points_per_win_applied INTEGER,
	PRIMARY KEY (encounter_id),
	CONSTRAINT ck_custom_game_round_lobby_index CHECK (lobby_index BETWEEN 0 AND 5),
	CONSTRAINT fk_custom_game_round_encounter FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE
);

CREATE TABLE mix.round_member (
	encounter_id BIGINT NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	busy BOOLEAN NOT NULL,
	rank_delta_applied INTEGER,
	PRIMARY KEY (encounter_id, workspace_member_id),
	CONSTRAINT ck_custom_game_round_member_busy CHECK (NOT busy OR rank_delta_applied IS NULL),
	CONSTRAINT fk_custom_game_round_member_round FOREIGN KEY(encounter_id) REFERENCES mix.round (encounter_id) ON DELETE CASCADE,
	CONSTRAINT fk_custom_game_round_member_workspace_member FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_custom_game_round_member_workspace_member_id ON mix.round_member (workspace_member_id);

CREATE TABLE mix.team_name (
	custom_game_id BIGINT NOT NULL,
	team_index INTEGER NOT NULL,
	name VARCHAR(60) NOT NULL,
	PRIMARY KEY (custom_game_id, team_index),
	CONSTRAINT ck_custom_game_team_name_index CHECK (team_index BETWEEN 0 AND 11),
	FOREIGN KEY(custom_game_id) REFERENCES mix.custom_game (id) ON DELETE CASCADE
);

CREATE TABLE players.favorite_player (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	auth_user_id BIGINT NOT NULL,
	player_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_favorite_player_auth_user_player UNIQUE (auth_user_id, player_id),
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE,
	FOREIGN KEY(player_id) REFERENCES players."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_favorite_player_auth_user ON players.favorite_player (auth_user_id);

CREATE INDEX ix_players_favorite_player_auth_user_id ON players.favorite_player (auth_user_id);

CREATE INDEX ix_players_favorite_player_player_id ON players.favorite_player (player_id);

CREATE TABLE players.social_account (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	user_id BIGINT NOT NULL,
	provider VARCHAR(64) NOT NULL,
	username VARCHAR(255) NOT NULL,
	username_normalized VARCHAR(255),
	url VARCHAR(500),
	display_name VARCHAR(255),
	provider_user_id VARCHAR(255),
	is_verified BOOLEAN DEFAULT 'false' NOT NULL,
	is_primary BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_social_account_user_provider_handle UNIQUE (user_id, provider, username_normalized),
	FOREIGN KEY(user_id) REFERENCES players."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_social_account_provider ON players.social_account (provider);

CREATE INDEX ix_social_account_provider_user_id ON players.social_account (provider_user_id);

CREATE INDEX ix_social_account_user_id ON players.social_account (user_id);

CREATE INDEX ix_social_account_username_normalized ON players.social_account (username_normalized);

CREATE UNIQUE INDEX uq_social_account_provider_subject ON players.social_account (provider, provider_user_id) WHERE provider_user_id IS NOT NULL;

CREATE UNIQUE INDEX uq_social_account_user_provider_handle_nullnorm ON players.social_account (user_id, provider, lower(btrim(username))) WHERE username_normalized IS NULL;

CREATE TABLE players.social_account_visibility (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	account_id BIGINT NOT NULL,
	workspace_id BIGINT,
	PRIMARY KEY (id),
	FOREIGN KEY(account_id) REFERENCES players.social_account (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_social_account_visibility_account_id ON players.social_account_visibility (account_id);

CREATE INDEX ix_social_account_visibility_workspace_id ON players.social_account_visibility (workspace_id);

CREATE UNIQUE INDEX uq_social_visibility_global ON players.social_account_visibility (account_id) WHERE workspace_id IS NULL;

CREATE UNIQUE INDEX uq_social_visibility_workspace ON players.social_account_visibility (account_id, workspace_id) WHERE workspace_id IS NOT NULL;

CREATE TABLE players."user" (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	name VARCHAR NOT NULL,
	avatar_url VARCHAR(500),
	stream_visible BOOLEAN DEFAULT 'true' NOT NULL,
	auth_user_id BIGINT,
	PRIMARY KEY (id),
	UNIQUE (name),
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_players_user_auth_user_id ON players."user" (auth_user_id);

CREATE INDEX ix_user_name_trgm ON players."user" USING gin (name gin_trgm_ops);

CREATE TABLE players.user_merge_audit (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	source_user_id BIGINT,
	target_user_id BIGINT,
	operator_auth_user_id BIGINT,
	field_policy_json JSON NOT NULL,
	moved_identity_ids_json JSON NOT NULL,
	deduped_identity_ids_json JSON NOT NULL,
	affected_counts_json JSON NOT NULL,
	preview_snapshot_json JSON NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(source_user_id) REFERENCES players."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(target_user_id) REFERENCES players."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(operator_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_players_user_merge_audit_operator_auth_user_id ON players.user_merge_audit (operator_auth_user_id);

CREATE INDEX ix_players_user_merge_audit_source_user_id ON players.user_merge_audit (source_user_id);

CREATE INDEX ix_players_user_merge_audit_target_user_id ON players.user_merge_audit (target_user_id);

CREATE TABLE audit_log (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id BIGINT,
	actor_auth_user_id BIGINT,
	actor_label VARCHAR(255),
	source VARCHAR(16) NOT NULL,
	action VARCHAR(64) NOT NULL,
	entity_type VARCHAR(64),
	entity_id BIGINT,
	entity_label VARCHAR(255),
	before_json JSONB,
	after_json JSONB,
	reason TEXT,
	ip_address VARCHAR(45),
	user_agent VARCHAR(255),
	correlation_id VARCHAR(64),
	PRIMARY KEY (id)
);

CREATE INDEX ix_audit_log_actor_created ON audit_log (actor_auth_user_id, created_at);

CREATE INDEX ix_audit_log_entity_created ON audit_log (entity_type, entity_id, created_at);

CREATE INDEX ix_audit_log_workspace_created ON audit_log (workspace_id, created_at);

CREATE TABLE chat_message (
	id BIGSERIAL NOT NULL,
	room_kind VARCHAR(16) NOT NULL,
	room_ref_id BIGINT NOT NULL,
	auth_user_id BIGINT NOT NULL,
	author_name TEXT NOT NULL,
	author_role VARCHAR(16) NOT NULL,
	body TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	deleted_by_auth_user_id BIGINT,
	PRIMARY KEY (id)
);

CREATE INDEX ix_chat_message_author ON chat_message (room_kind, room_ref_id, auth_user_id, id);

CREATE INDEX ix_chat_message_room ON chat_message (room_kind, room_ref_id, id);

CREATE TABLE chat_mute (
	room_kind VARCHAR(16) NOT NULL,
	room_ref_id BIGINT NOT NULL,
	auth_user_id BIGINT NOT NULL,
	muted_until TIMESTAMP WITH TIME ZONE,
	reason TEXT,
	created_by_auth_user_id BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (room_kind, room_ref_id, auth_user_id)
);

CREATE TABLE chat_room_settings (
	room_kind VARCHAR(16) NOT NULL,
	room_ref_id BIGINT NOT NULL,
	spectators_can_read BOOLEAN NOT NULL,
	updated_by_auth_user_id BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (room_kind, room_ref_id)
);

CREATE TABLE discord_message (
	id BIGSERIAL NOT NULL,
	channel VARCHAR(32) NOT NULL,
	target VARCHAR(64) NOT NULL,
	dedupe_key VARCHAR(128),
	subject VARCHAR(160) NOT NULL,
	slot VARCHAR(64) NOT NULL,
	kind VARCHAR(64) NOT NULL,
	notification_id BIGINT,
	workspace_id BIGINT,
	status VARCHAR(16) DEFAULT 'pending' NOT NULL,
	discord_channel_id BIGINT,
	message_id BIGINT,
	error TEXT,
	payload_json JSON,
	card_json JSON,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_discord_message_target UNIQUE (channel, target, dedupe_key),
	CONSTRAINT ck_discord_message_status CHECK (status IN ('pending', 'posted', 'failed', 'deleting', 'deleted'))
);

CREATE INDEX ix_discord_message_subject ON discord_message (subject);

CREATE TABLE division_grid (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT,
	discipline VARCHAR(32) DEFAULT 'overwatch' NOT NULL,
	slug VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	description VARCHAR,
	source_workspace_id BIGINT,
	source_grid_id BIGINT,
	source_key VARCHAR(255),
	source_fingerprint VARCHAR(64),
	imported_at TIMESTAMP WITH TIME ZONE,
	archived_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (workspace_id, slug),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_division_grid_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code),
	FOREIGN KEY(source_workspace_id) REFERENCES workspace (id) ON DELETE SET NULL,
	FOREIGN KEY(source_grid_id) REFERENCES division_grid (id) ON DELETE SET NULL
);

CREATE INDEX ix_division_grid_source_fingerprint ON division_grid (source_fingerprint);

CREATE INDEX ix_division_grid_source_grid_id ON division_grid (source_grid_id);

CREATE INDEX ix_division_grid_source_key ON division_grid (source_key);

CREATE INDEX ix_division_grid_source_workspace_id ON division_grid (source_workspace_id);

CREATE INDEX ix_division_grid_workspace_id ON division_grid (workspace_id);

CREATE TABLE division_grid_import_job (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	source_workspace_id BIGINT,
	requested_by_user_id BIGINT,
	status VARCHAR(16) DEFAULT 'pending' NOT NULL,
	progress INTEGER DEFAULT '0' NOT NULL,
	request_json JSON NOT NULL,
	result_json JSON,
	error TEXT,
	idempotency_key VARCHAR(255) NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (workspace_id, idempotency_key),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(source_workspace_id) REFERENCES workspace (id) ON DELETE SET NULL,
	FOREIGN KEY(requested_by_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_division_grid_import_job_requested_by_user_id ON division_grid_import_job (requested_by_user_id);

CREATE INDEX ix_division_grid_import_job_source_workspace_id ON division_grid_import_job (source_workspace_id);

CREATE INDEX ix_division_grid_import_job_status ON division_grid_import_job (status);

CREATE INDEX ix_division_grid_import_job_workspace_id ON division_grid_import_job (workspace_id);

CREATE TABLE division_grid_mapping (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	source_version_id BIGINT NOT NULL,
	target_version_id BIGINT NOT NULL,
	name VARCHAR NOT NULL,
	is_complete BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (source_version_id, target_version_id),
	FOREIGN KEY(source_version_id) REFERENCES division_grid_version (id) ON DELETE CASCADE,
	FOREIGN KEY(target_version_id) REFERENCES division_grid_version (id) ON DELETE CASCADE
);

CREATE INDEX ix_division_grid_mapping_source_version_id ON division_grid_mapping (source_version_id);

CREATE INDEX ix_division_grid_mapping_target_version_id ON division_grid_mapping (target_version_id);

CREATE TABLE division_grid_mapping_rule (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	mapping_id BIGINT NOT NULL,
	source_tier_id BIGINT NOT NULL,
	target_tier_id BIGINT NOT NULL,
	weight FLOAT DEFAULT '1.0' NOT NULL,
	is_primary BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(mapping_id) REFERENCES division_grid_mapping (id) ON DELETE CASCADE,
	FOREIGN KEY(source_tier_id) REFERENCES division_grid_tier (id) ON DELETE CASCADE,
	FOREIGN KEY(target_tier_id) REFERENCES division_grid_tier (id) ON DELETE CASCADE
);

CREATE INDEX ix_division_grid_mapping_rule_mapping_id ON division_grid_mapping_rule (mapping_id);

CREATE INDEX ix_division_grid_mapping_rule_source_tier_id ON division_grid_mapping_rule (source_tier_id);

CREATE INDEX ix_division_grid_mapping_rule_target_tier_id ON division_grid_mapping_rule (target_tier_id);

CREATE TABLE division_grid_tier (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	version_id BIGINT NOT NULL,
	slug VARCHAR NOT NULL,
	number BIGINT NOT NULL,
	name VARCHAR NOT NULL,
	sort_order BIGINT NOT NULL,
	rank_min BIGINT NOT NULL,
	rank_max BIGINT,
	icon_url VARCHAR NOT NULL,
	native_rank_min BIGINT,
	native_rank_max BIGINT,
	canonical_number BIGINT,
	PRIMARY KEY (id),
	UNIQUE (version_id, slug),
	UNIQUE (version_id, sort_order),
	FOREIGN KEY(version_id) REFERENCES division_grid_version (id) ON DELETE CASCADE
);

CREATE INDEX ix_division_grid_tier_version_id ON division_grid_tier (version_id);

CREATE TABLE division_grid_version (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	grid_id BIGINT NOT NULL,
	version BIGINT NOT NULL,
	label VARCHAR NOT NULL,
	status VARCHAR DEFAULT 'draft' NOT NULL,
	created_from_version_id BIGINT,
	published_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (grid_id, version),
	FOREIGN KEY(grid_id) REFERENCES division_grid (id) ON DELETE CASCADE,
	FOREIGN KEY(created_from_version_id) REFERENCES division_grid_version (id) ON DELETE SET NULL
);

CREATE INDEX ix_division_grid_version_created_from_version_id ON division_grid_version (created_from_version_id);

CREATE INDEX ix_division_grid_version_grid_id ON division_grid_version (grid_id);

CREATE TABLE event_outbox (
	id BIGSERIAL NOT NULL,
	event_id VARCHAR(64) NOT NULL,
	event_type VARCHAR(128) NOT NULL,
	exchange VARCHAR(255),
	routing_key VARCHAR(255) NOT NULL,
	payload_json JSON NOT NULL,
	status VARCHAR(16) NOT NULL,
	attempts INTEGER NOT NULL,
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	last_error TEXT,
	PRIMARY KEY (id),
	UNIQUE (event_id)
);

CREATE INDEX ix_event_outbox_status_next_attempt ON event_outbox (status, next_attempt_at);

CREATE TABLE notification (
	id BIGSERIAL NOT NULL,
	audience VARCHAR(16) NOT NULL,
	recipient_auth_user_id BIGINT,
	workspace_id BIGINT,
	source_workspace_id BIGINT,
	kind VARCHAR(64) NOT NULL,
	dedupe_key VARCHAR(128),
	payload_json JSONB DEFAULT '{}' NOT NULL,
	actor_auth_user_id BIGINT,
	published_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_notification_user_has_recipient CHECK (audience <> 'user' OR recipient_auth_user_id IS NOT NULL),
	CONSTRAINT ck_notification_non_user_has_no_recipient CHECK (audience = 'user' OR recipient_auth_user_id IS NULL),
	CONSTRAINT ck_notification_workspace_has_workspace CHECK (audience <> 'workspace' OR workspace_id IS NOT NULL),
	CONSTRAINT ck_notification_non_workspace_has_no_workspace CHECK (audience = 'workspace' OR workspace_id IS NULL)
);

CREATE INDEX ix_notification_audience_published ON notification (audience, published_at DESC) WHERE audience <> 'user';

CREATE INDEX ix_notification_dedupe ON notification (kind, dedupe_key) WHERE dedupe_key IS NOT NULL;

CREATE INDEX ix_notification_recipient_published ON notification (recipient_auth_user_id, published_at DESC);

CREATE INDEX ix_notification_source_workspace_published ON notification (source_workspace_id, published_at DESC) WHERE source_workspace_id IS NOT NULL;

CREATE TABLE notification_preference (
	auth_user_id BIGINT NOT NULL,
	discord_dm JSONB DEFAULT '{}' NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (auth_user_id),
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE TABLE notification_read (
	auth_user_id BIGINT NOT NULL,
	notification_id BIGINT NOT NULL,
	read_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (auth_user_id, notification_id)
);

CREATE TABLE notification_workspace_config (
	workspace_id BIGINT NOT NULL,
	discord_channel_id BIGINT,
	locale VARCHAR(2) DEFAULT 'ru' NOT NULL,
	broadcast_kinds JSONB DEFAULT '["registration.opened", "check_in.opened"]' NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (workspace_id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE TABLE settings (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	key VARCHAR NOT NULL,
	value JSON DEFAULT '{}' NOT NULL,
	description VARCHAR,
	updated_by BIGINT,
	PRIMARY KEY (id),
	FOREIGN KEY(updated_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_settings_key ON settings (key);

CREATE TABLE workspace (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	slug VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	description VARCHAR,
	icon_url VARCHAR,
	tagline VARCHAR(120),
	about TEXT,
	discord_url VARCHAR(512),
	twitch_url VARCHAR(512),
	boosty_url VARCHAR(512),
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	is_hidden BOOLEAN DEFAULT 'false' NOT NULL,
	timezone VARCHAR(64) DEFAULT 'Europe/Moscow' NOT NULL,
	branding_enabled BOOLEAN DEFAULT 'false' NOT NULL,
	brand_primary VARCHAR,
	brand_secondary VARCHAR,
	brand_background VARCHAR,
	brand_surface VARCHAR,
	brand_accent VARCHAR,
	brand_foreground VARCHAR,
	brand_muted VARCHAR,
	brand_border VARCHAR,
	brand_ring VARCHAR,
	brand_destructive VARCHAR,
	subdomain VARCHAR(63),
	seo_title VARCHAR,
	seo_description VARCHAR,
	custom_domain VARCHAR(255),
	custom_domain_verified_at TIMESTAMP WITH TIME ZONE,
	custom_domain_verification_token VARCHAR(64),
	discord_guild_id VARCHAR(32),
	discord_guild_verified_at TIMESTAMP WITH TIME ZONE,
	discord_guild_verified_by_auth_user_id BIGINT,
	owner_id BIGINT,
	verification_status VARCHAR(16) DEFAULT 'unverified' NOT NULL,
	quota_plan_id BIGINT,
	disciplines_enabled VARCHAR(32)[] DEFAULT '{overwatch}' NOT NULL,
	newcomer_scope VARCHAR(16) DEFAULT 'global' NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (discord_guild_id),
	FOREIGN KEY(discord_guild_verified_by_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(owner_id) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(quota_plan_id) REFERENCES quota.plan (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_workspace_custom_domain ON workspace (custom_domain);

CREATE INDEX ix_workspace_owner_id ON workspace (owner_id);

CREATE INDEX ix_workspace_quota_plan_id ON workspace (quota_plan_id);

CREATE UNIQUE INDEX ix_workspace_slug ON workspace (slug);

CREATE UNIQUE INDEX ix_workspace_subdomain ON workspace (subdomain);

CREATE TABLE workspace_division_grid_default (
	workspace_id BIGINT NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	version_id BIGINT NOT NULL,
	PRIMARY KEY (workspace_id, discipline),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(discipline) REFERENCES catalog.discipline (code),
	FOREIGN KEY(version_id) REFERENCES division_grid_version (id) ON DELETE CASCADE
);

CREATE INDEX ix_workspace_division_grid_default_version_id ON workspace_division_grid_default (version_id);

CREATE TABLE workspace_member (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	player_id BIGINT NOT NULL,
	display_name VARCHAR(255),
	removed_at TIMESTAMP WITH TIME ZONE,
	observed_only BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_workspace_member_workspace_player UNIQUE (workspace_id, player_id),
	CONSTRAINT uq_workspace_member_id_workspace UNIQUE (id, workspace_id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(player_id) REFERENCES players."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_workspace_member_player_id ON workspace_member (player_id);

CREATE INDEX ix_workspace_member_workspace_id ON workspace_member (workspace_id);

CREATE TABLE quota.api_key_limit (
	api_key_id BIGINT NOT NULL,
	requests_per_minute INTEGER,
	heavy_per_day INTEGER,
	concurrent_heavy INTEGER,
	max_upload_bytes BIGINT,
	max_items_per_request INTEGER,
	updated_by BIGINT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (api_key_id),
	FOREIGN KEY(api_key_id) REFERENCES auth.api_key (id) ON DELETE CASCADE,
	FOREIGN KEY(updated_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE TABLE quota.operation (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	slug VARCHAR(64) NOT NULL,
	cost INTEGER DEFAULT '1' NOT NULL,
	enabled BOOLEAN DEFAULT 'true' NOT NULL,
	description TEXT,
	PRIMARY KEY (id),
	CONSTRAINT ck_quota_operation_cost CHECK (cost >= 0)
);

CREATE UNIQUE INDEX ix_quota_operation_slug ON quota.operation (slug);

CREATE TABLE quota.plan (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	slug VARCHAR(32) NOT NULL,
	title VARCHAR(64) NOT NULL,
	description TEXT,
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_quota_plan_slug ON quota.plan (slug);

CREATE TABLE quota.plan_limit (
	plan_id BIGINT NOT NULL,
	scope VARCHAR(16) NOT NULL,
	requests_per_minute INTEGER,
	heavy_per_day INTEGER,
	concurrent_heavy INTEGER,
	max_upload_bytes BIGINT,
	max_items_per_request INTEGER,
	PRIMARY KEY (plan_id, scope),
	CONSTRAINT ck_quota_plan_limit_nonneg CHECK (COALESCE(requests_per_minute, 0) >= 0 AND COALESCE(heavy_per_day, 0) >= 0 AND COALESCE(concurrent_heavy, 0) >= 0 AND COALESCE(max_upload_bytes, 0) >= 0 AND COALESCE(max_items_per_request, 0) >= 0),
	FOREIGN KEY(plan_id) REFERENCES quota.plan (id) ON DELETE CASCADE
);

CREATE TABLE quota.workspace_limit (
	workspace_id BIGINT NOT NULL,
	scope VARCHAR(16) NOT NULL,
	requests_per_minute INTEGER,
	heavy_per_day INTEGER,
	concurrent_heavy INTEGER,
	max_upload_bytes BIGINT,
	max_items_per_request INTEGER,
	updated_by BIGINT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (workspace_id, scope),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(updated_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE TABLE rank.account_state (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	discipline VARCHAR(32) NOT NULL,
	social_account_id BIGINT NOT NULL,
	handle VARCHAR(255) NOT NULL,
	external_id VARCHAR(255),
	region VARCHAR(16),
	last_checked_at TIMESTAMP WITH TIME ZONE,
	last_success_at TIMESTAMP WITH TIME ZONE,
	status VARCHAR(32) DEFAULT 'pending' NOT NULL,
	consecutive_failures INTEGER DEFAULT '0' NOT NULL,
	next_eligible_at TIMESTAMP WITH TIME ZONE,
	last_error TEXT,
	priority_tier SMALLINT DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (social_account_id),
	FOREIGN KEY(social_account_id) REFERENCES players.social_account (id) ON DELETE CASCADE
);

CREATE INDEX ix_account_state_due ON rank.account_state (discipline, status, next_eligible_at, last_checked_at);

CREATE INDEX ix_account_state_priority ON rank.account_state (priority_tier, last_checked_at);

CREATE TABLE rank.fetch_log (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	discipline VARCHAR(32) NOT NULL,
	social_account_id BIGINT,
	handle VARCHAR(255) NOT NULL,
	status VARCHAR(32) NOT NULL,
	source VARCHAR(32) NOT NULL,
	error TEXT,
	snapshots_written INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(social_account_id) REFERENCES players.social_account (id) ON DELETE SET NULL
);

CREATE INDEX ix_fetch_log_created_at ON rank.fetch_log (created_at);

CREATE INDEX ix_fetch_log_status_created ON rank.fetch_log (status, created_at);

CREATE TABLE rank.rank_snapshot (
	id BIGSERIAL NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	user_id BIGINT NOT NULL,
	social_account_id BIGINT NOT NULL,
	handle VARCHAR(255) NOT NULL,
	platform VARCHAR(16),
	role VARCHAR(16),
	queue VARCHAR(16),
	division VARCHAR(32),
	tier SMALLINT,
	season INTEGER,
	lp INTEGER,
	wins INTEGER,
	losses INTEGER,
	rank_value INTEGER,
	mapping_version VARCHAR(64),
	is_ranked BOOLEAN DEFAULT 'true' NOT NULL,
	captured_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	source VARCHAR(32) DEFAULT 'scheduled' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES players."user" (id) ON DELETE CASCADE,
	FOREIGN KEY(social_account_id) REFERENCES players.social_account (id) ON DELETE CASCADE
);

CREATE INDEX ix_rank_rank_snapshot_captured_at ON rank.rank_snapshot (captured_at);

CREATE INDEX ix_rank_snapshot_latest_ranked ON rank.rank_snapshot (social_account_id, role, queue, captured_at DESC) WHERE rank_value IS NOT NULL AND is_ranked IS TRUE;

CREATE INDEX ix_rank_snapshot_series_captured ON rank.rank_snapshot (social_account_id, role, platform, queue, captured_at);

CREATE INDEX ix_rank_snapshot_user_captured ON rank.rank_snapshot (user_id, captured_at);

CREATE TABLE realtime.workspace_event (
	id BIGSERIAL NOT NULL,
	topic TEXT NOT NULL,
	event_type VARCHAR(128) NOT NULL,
	workspace_id BIGINT,
	tournament_id BIGINT,
	actor_user_id BIGINT,
	schema_version SMALLINT DEFAULT '1' NOT NULL,
	payload JSONB NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_realtime_workspace_event_actor_user_id ON realtime.workspace_event (actor_user_id);

CREATE INDEX ix_realtime_workspace_event_occurred_at ON realtime.workspace_event (occurred_at);

CREATE INDEX ix_realtime_workspace_event_topic_id ON realtime.workspace_event (topic, id);

CREATE INDEX ix_realtime_workspace_event_tournament_id ON realtime.workspace_event (tournament_id);

CREATE INDEX ix_realtime_workspace_event_workspace_id ON realtime.workspace_event (workspace_id);

CREATE TABLE registration.form (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	workspace_id BIGINT NOT NULL,
	is_open BOOLEAN DEFAULT 'false' NOT NULL,
	auto_approve BOOLEAN DEFAULT 'false' NOT NULL,
	current_version_id BIGINT,
	require_open_profile BOOLEAN DEFAULT 'false' NOT NULL,
	open_profile_scope VARCHAR(8) DEFAULT 'main' NOT NULL,
	show_ranks BOOLEAN DEFAULT 'false' NOT NULL,
	hide_registrations BOOLEAN DEFAULT 'false' NOT NULL,
	max_participants INTEGER,
	max_substitutes INTEGER DEFAULT '0' NOT NULL,
	require_subscription BOOLEAN DEFAULT 'false' NOT NULL,
	subscription_stage VARCHAR(16) DEFAULT 'check_in' NOT NULL,
	subscription_scope VARCHAR(16) DEFAULT 'player' NOT NULL,
	team_rank_min INTEGER,
	team_rank_max INTEGER,
	team_max_rank_spread INTEGER,
	team_unique_identity BOOLEAN DEFAULT 'false' NOT NULL,
	team_require_discord_guild BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_registration_form_tournament UNIQUE (tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(current_version_id) REFERENCES registration.form_version (id) ON DELETE SET NULL
);

CREATE INDEX ix_registration_form_tournament_id ON registration.form (tournament_id);

CREATE INDEX ix_registration_form_workspace_id ON registration.form (workspace_id);

CREATE TABLE registration.form_template (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	name VARCHAR(64) NOT NULL,
	schema_json JSON NOT NULL,
	created_by BIGINT,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_registration_form_template_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code),
	FOREIGN KEY(created_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_registration_form_template_workspace_id ON registration.form_template (workspace_id);

CREATE UNIQUE INDEX uq_registration_form_template_name ON registration.form_template (workspace_id, lower(name));

CREATE TABLE registration.form_version (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	form_id BIGINT NOT NULL,
	number INTEGER NOT NULL,
	schema_json JSON NOT NULL,
	created_by BIGINT,
	PRIMARY KEY (id),
	CONSTRAINT uq_registration_form_version_number UNIQUE (form_id, number),
	FOREIGN KEY(form_id) REFERENCES registration.form (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_registration_form_version_form_id ON registration.form_version (form_id);

CREATE TABLE registration.google_sheet_binding (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	feed_id BIGINT NOT NULL,
	registration_id BIGINT NOT NULL,
	source_record_key VARCHAR(255) NOT NULL,
	raw_row_json JSON,
	parsed_fields_json JSON,
	row_hash VARCHAR(128),
	last_seen_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_registration_google_sheet_binding_key UNIQUE (feed_id, source_record_key),
	CONSTRAINT uq_registration_google_sheet_binding_registration UNIQUE (registration_id),
	FOREIGN KEY(feed_id) REFERENCES registration.google_sheet_feed (id) ON DELETE CASCADE,
	FOREIGN KEY(registration_id) REFERENCES registration.registration (id) ON DELETE CASCADE
);

CREATE INDEX ix_registration_google_sheet_binding_feed_id ON registration.google_sheet_binding (feed_id);

CREATE INDEX ix_registration_google_sheet_binding_registration_id ON registration.google_sheet_binding (registration_id);

CREATE TABLE registration.google_sheet_feed (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	source_url TEXT NOT NULL,
	sheet_id VARCHAR(255) NOT NULL,
	gid VARCHAR(64),
	title VARCHAR(255),
	auto_sync_enabled BOOLEAN DEFAULT 'false' NOT NULL,
	auto_sync_interval_seconds INTEGER DEFAULT '300' NOT NULL,
	header_row_json JSON,
	mapping_config_json JSON,
	value_mapping_json JSON,
	last_synced_at TIMESTAMP WITH TIME ZONE,
	last_sync_status VARCHAR(32),
	last_error TEXT,
	PRIMARY KEY (id),
	CONSTRAINT uq_registration_google_sheet_feed_tournament UNIQUE (tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE INDEX ix_registration_google_sheet_feed_tournament_id ON registration.google_sheet_feed (tournament_id);

CREATE TABLE registration.identity (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	registration_id BIGINT NOT NULL,
	provider VARCHAR(32) NOT NULL,
	position INTEGER DEFAULT '0' NOT NULL,
	handle VARCHAR(255) NOT NULL,
	handle_normalized VARCHAR(255) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_registration_identity_position UNIQUE (registration_id, provider, position) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT uq_registration_identity_handle UNIQUE (registration_id, provider, handle_normalized) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(registration_id) REFERENCES registration.registration (id) ON DELETE CASCADE
);

CREATE INDEX ix_registration_identity_handle ON registration.identity (provider, handle_normalized);

CREATE INDEX ix_registration_identity_registration_id ON registration.identity (registration_id);

CREATE TABLE registration.registration (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	workspace_member_id BIGINT,
	display_name VARCHAR(255),
	stream_pov BOOLEAN DEFAULT 'false' NOT NULL,
	is_reserve BOOLEAN DEFAULT 'false' NOT NULL,
	form_version_id BIGINT,
	public_notes TEXT,
	organizer_notes TEXT,
	exclude_reason VARCHAR(64),
	admin_notes TEXT,
	custom_fields_json JSON,
	status VARCHAR(32) DEFAULT 'pending' NOT NULL,
	balancer_status VARCHAR(32) DEFAULT 'not_in_balancer' NOT NULL,
	checked_in BOOLEAN DEFAULT 'false' NOT NULL,
	checked_in_at TIMESTAMP WITH TIME ZONE,
	checked_in_by BIGINT,
	submitted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	reviewed_at TIMESTAMP WITH TIME ZONE,
	reviewed_by BIGINT,
	deleted_at TIMESTAMP WITH TIME ZONE,
	deleted_by BIGINT,
	balancer_profile_overridden_at TIMESTAMP WITH TIME ZONE,
	registration_team_id BIGINT,
	team_slot_code VARCHAR(16),
	is_substitute BOOLEAN DEFAULT 'false' NOT NULL,
	is_team_manager BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL,
	FOREIGN KEY(form_version_id) REFERENCES registration.form_version (id) ON DELETE SET NULL,
	FOREIGN KEY(checked_in_by) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(reviewed_by) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(deleted_by) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(registration_team_id) REFERENCES registration.team (id) ON DELETE SET NULL
);

CREATE INDEX ix_registration_registration_form_version_id ON registration.registration (form_version_id);

CREATE INDEX ix_registration_registration_registration_team_id ON registration.registration (registration_team_id);

CREATE INDEX ix_registration_registration_tournament_id ON registration.registration (tournament_id);

CREATE INDEX ix_registration_registration_workspace_member_id ON registration.registration (workspace_member_id);

CREATE INDEX ix_registration_tournament_balancer_status ON registration.registration (tournament_id, status, balancer_status) WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX uq_registration_user ON registration.registration (tournament_id, workspace_member_id) WHERE deleted_at IS NULL;

CREATE TABLE registration.role (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	registration_id BIGINT NOT NULL,
	dimension_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	is_primary BOOLEAN DEFAULT 'false' NOT NULL,
	priority INTEGER DEFAULT '0' NOT NULL,
	rank_value INTEGER,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_registration_role_role UNIQUE (registration_id, role_id),
	CONSTRAINT fk_registration_role_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	FOREIGN KEY(registration_id) REFERENCES registration.registration (id) ON DELETE CASCADE
);

CREATE INDEX ix_registration_role_registration_id ON registration.role (registration_id);

CREATE INDEX ix_registration_role_role_id ON registration.role (role_id);

CREATE TABLE registration.role_entity (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	role_id BIGINT NOT NULL,
	entity_id BIGINT NOT NULL,
	entity_kind VARCHAR(16) DEFAULT 'character' NOT NULL,
	priority INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_reg_role_entity_role_priority UNIQUE (role_id, priority) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT uq_reg_role_entity_role_entity UNIQUE (role_id, entity_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_registration_role_entity_kind CHECK (entity_kind = 'character'),
	CONSTRAINT fk_registration_role_entity_entity FOREIGN KEY(entity_id, entity_kind) REFERENCES catalog.entity (id, kind) ON DELETE CASCADE,
	FOREIGN KEY(role_id) REFERENCES registration.role (id) ON DELETE CASCADE
);

CREATE INDEX ix_registration_role_entity_role_id ON registration.role_entity (role_id);

CREATE TABLE registration.status (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT,
	scope VARCHAR(32) NOT NULL,
	slug VARCHAR(32) NOT NULL,
	kind VARCHAR(16) DEFAULT 'custom' NOT NULL,
	icon_slug VARCHAR(128),
	icon_color VARCHAR(32),
	name VARCHAR(64) NOT NULL,
	description TEXT,
	excludes_from_balancer BOOLEAN DEFAULT 'false' NOT NULL,
	excludes_from_ready BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_registration_status_workspace_scope_slug UNIQUE (workspace_id, scope, slug, kind),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_registration_status_workspace_id ON registration.status (workspace_id);

CREATE INDEX ix_registration_status_workspace_scope ON registration.status (workspace_id, scope);

CREATE TABLE registration.team (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	workspace_id BIGINT NOT NULL,
	name VARCHAR(255) NOT NULL,
	name_normalized VARCHAR(255) NOT NULL,
	image_url VARCHAR(255),
	captain_registration_id BIGINT,
	status VARCHAR(16) DEFAULT 'forming' NOT NULL,
	exported_team_id BIGINT,
	exported_at TIMESTAMP WITH TIME ZONE,
	export_status VARCHAR(32),
	export_error TEXT,
	deleted_at TIMESTAMP WITH TIME ZONE,
	deleted_by BIGINT,
	invite_cap_reset_at TIMESTAMP WITH TIME ZONE,
	invite_cap_reset_by BIGINT,
	admission VARCHAR(16) DEFAULT 'pending' NOT NULL,
	rejection_reason TEXT,
	organizer_notes TEXT,
	roster_locked_at TIMESTAMP WITH TIME ZONE,
	roster_locked_by BIGINT,
	subscription_covered_at TIMESTAMP WITH TIME ZONE,
	subscription_covered_by BIGINT,
	subscription_provider VARCHAR(32),
	subscription_tier_rank INTEGER,
	subscription_expires_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(exported_team_id) REFERENCES tournament.team (id) ON DELETE SET NULL,
	FOREIGN KEY(deleted_by) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(invite_cap_reset_by) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(roster_locked_by) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(subscription_covered_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_registration_team_captain_registration_id ON registration.team (captain_registration_id);

CREATE INDEX ix_registration_team_exported_team_id ON registration.team (exported_team_id);

CREATE INDEX ix_registration_team_tournament_id ON registration.team (tournament_id);

CREATE INDEX ix_registration_team_tournament_status ON registration.team (tournament_id, status) WHERE deleted_at IS NULL;

CREATE INDEX ix_registration_team_workspace_id ON registration.team (workspace_id);

CREATE UNIQUE INDEX uq_registration_team_name_active ON registration.team (tournament_id, name_normalized) WHERE deleted_at IS NULL;

CREATE TABLE registration.team_invite (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	team_id BIGINT NOT NULL,
	slot_code VARCHAR(16) NOT NULL,
	is_substitute BOOLEAN DEFAULT 'false' NOT NULL,
	target_auth_user_id BIGINT,
	token_sha256 VARCHAR(64),
	expires_at TIMESTAMP WITH TIME ZONE,
	state VARCHAR(16) DEFAULT 'pending' NOT NULL,
	invited_by BIGINT,
	invited_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	revoked_by BIGINT,
	revoked_at TIMESTAMP WITH TIME ZONE,
	revoked_by_organizer BOOLEAN DEFAULT 'false' NOT NULL,
	accepted_at TIMESTAMP WITH TIME ZONE,
	accepted_registration_id BIGINT,
	PRIMARY KEY (id),
	FOREIGN KEY(team_id) REFERENCES registration.team (id) ON DELETE CASCADE,
	FOREIGN KEY(target_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(invited_by) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(revoked_by) REFERENCES auth."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(accepted_registration_id) REFERENCES registration.registration (id) ON DELETE SET NULL
);

CREATE INDEX ix_registration_team_invite_target_auth_user_id ON registration.team_invite (target_auth_user_id);

CREATE INDEX ix_registration_team_invite_team_id ON registration.team_invite (team_id);

CREATE INDEX ix_registration_team_invite_team_state ON registration.team_invite (team_id, state);

CREATE UNIQUE INDEX uq_registration_team_invite_token ON registration.team_invite (token_sha256) WHERE token_sha256 IS NOT NULL;

CREATE TABLE roster.format_role_rule (
	team_format_id BIGINT NOT NULL,
	dimension_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	hard_min INTEGER,
	hard_max INTEGER,
	recommended_min INTEGER,
	recommended_max INTEGER,
	include_descendants BOOLEAN DEFAULT true NOT NULL,
	PRIMARY KEY (team_format_id, role_id),
	CONSTRAINT fk_frr_dimension FOREIGN KEY(team_format_id, dimension_id) REFERENCES roster.team_format_dimension (team_format_id, dimension_id) ON DELETE CASCADE,
	CONSTRAINT fk_frr_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT ck_frr_nonnegative CHECK (hard_min >= 0 AND hard_max >= 0 AND recommended_min >= 0 AND recommended_max >= 0),
	CONSTRAINT ck_frr_hard CHECK (hard_min IS NULL OR hard_max IS NULL OR hard_min <= hard_max),
	CONSTRAINT ck_frr_recommended CHECK (recommended_min IS NULL OR recommended_max IS NULL OR recommended_min <= recommended_max)
);

CREATE INDEX ix_roster_format_role_rule_role_id ON roster.format_role_rule (role_id);

CREATE TABLE roster.team_format (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	tournament_id BIGINT,
	custom_game_id BIGINT,
	preset_code VARCHAR(64),
	name VARCHAR(128) NOT NULL,
	starter_min INTEGER NOT NULL,
	starter_max INTEGER NOT NULL,
	substitute_min INTEGER DEFAULT 0 NOT NULL,
	substitute_max INTEGER DEFAULT 0 NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_team_format_owner CHECK (num_nonnulls(tournament_id, custom_game_id) <= 1),
	CONSTRAINT ck_team_format_sizes CHECK (1 <= starter_min AND starter_min <= starter_max AND 0 <= substitute_min AND substitute_min <= substitute_max),
	CONSTRAINT uq_team_format_key UNIQUE (id, discipline),
	CONSTRAINT uq_team_format_tournament UNIQUE (tournament_id),
	CONSTRAINT uq_team_format_custom_game UNIQUE (custom_game_id),
	CONSTRAINT fk_team_format_tournament FOREIGN KEY(tournament_id, workspace_id, discipline) REFERENCES tournament.tournament (id, workspace_id, discipline) ON DELETE CASCADE,
	CONSTRAINT fk_team_format_custom_game FOREIGN KEY(custom_game_id, workspace_id, discipline) REFERENCES mix.custom_game (id, workspace_id, discipline) ON DELETE CASCADE,
	CONSTRAINT fk_team_format_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_team_format_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code)
);

CREATE UNIQUE INDEX uq_team_format_workspace_default ON roster.team_format (workspace_id, discipline) WHERE tournament_id IS NULL AND custom_game_id IS NULL;

CREATE TABLE roster.team_format_dimension (
	team_format_id BIGINT NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	dimension_id BIGINT NOT NULL,
	mode VARCHAR(16) NOT NULL,
	player_min_assignments INTEGER,
	player_max_assignments INTEGER,
	PRIMARY KEY (team_format_id, dimension_id),
	CONSTRAINT ck_tfd_mode CHECK (mode IN ('off', 'informational', 'preference', 'enforced')),
	CONSTRAINT ck_tfd_assignments CHECK (player_min_assignments IS NULL OR player_max_assignments IS NULL OR player_min_assignments <= player_max_assignments),
	CONSTRAINT fk_tfd_format FOREIGN KEY(team_format_id, discipline) REFERENCES roster.team_format (id, discipline) ON DELETE CASCADE,
	CONSTRAINT fk_tfd_dimension FOREIGN KEY(dimension_id, discipline) REFERENCES catalog.role_dimension (id, discipline)
);

CREATE TABLE stats.discord_channel (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	channel_id BIGINT NOT NULL,
	channel_name VARCHAR(100),
	is_active BOOLEAN NOT NULL,
	last_scanned_message_id BIGINT,
	PRIMARY KEY (id),
	UNIQUE (tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_stats_discord_channel_channel_id ON stats.discord_channel (channel_id);

CREATE TABLE stats.event (
	id BIGSERIAL NOT NULL,
	match_id BIGINT NOT NULL,
	segment SMALLINT DEFAULT '0' NOT NULL,
	t DOUBLE PRECISION NOT NULL,
	type_id SMALLINT NOT NULL,
	actor_member_id BIGINT,
	actor_team_id BIGINT,
	target_member_id BIGINT,
	target_team_id BIGINT,
	entity_id BIGINT,
	related_entity_id BIGINT,
	entity_kind VARCHAR(16) DEFAULT 'character' NOT NULL,
	data JSONB,
	PRIMARY KEY (id),
	CONSTRAINT ck_event_entity_kind CHECK (entity_kind = 'character'),
	CONSTRAINT fk_event_actor FOREIGN KEY(match_id, actor_member_id) REFERENCES stats.match_player (match_id, workspace_member_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_event_target FOREIGN KEY(match_id, target_member_id) REFERENCES stats.match_player (match_id, workspace_member_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_event_actor_team FOREIGN KEY(match_id, actor_team_id) REFERENCES stats.match_team (match_id, encounter_team_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_event_target_team FOREIGN KEY(match_id, target_team_id) REFERENCES stats.match_team (match_id, encounter_team_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_event_entity FOREIGN KEY(entity_id, entity_kind) REFERENCES catalog.entity (id, kind) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_event_related_entity FOREIGN KEY(related_entity_id, entity_kind) REFERENCES catalog.entity (id, kind) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_event_match FOREIGN KEY(match_id) REFERENCES stats.match (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_event_type FOREIGN KEY(type_id) REFERENCES stats.event_type (id)
);

CREATE INDEX ix_event_match ON stats.event (match_id, t);

CREATE TABLE stats.event_type (
	id SMALLINT GENERATED ALWAYS AS IDENTITY,
	discipline VARCHAR(32) NOT NULL,
	code VARCHAR(64) NOT NULL,
	name VARCHAR(128) NOT NULL,
	active BOOLEAN DEFAULT true NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_event_type_code UNIQUE (discipline, code),
	CONSTRAINT fk_event_type_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code)
);

CREATE TABLE stats.fact (
	match_id BIGINT NOT NULL,
	segment SMALLINT DEFAULT '0' NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	workspace_member_id BIGINT,
	entity_id BIGINT,
	entity_kind VARCHAR(16) DEFAULT 'character' NOT NULL,
	stat_id SMALLINT NOT NULL,
	value DOUBLE PRECISION NOT NULL,
	CONSTRAINT ck_fact_entity_kind CHECK (entity_kind = 'character'),
	CONSTRAINT fk_fact_team FOREIGN KEY(match_id, encounter_team_id) REFERENCES stats.match_team (match_id, encounter_team_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_fact_player FOREIGN KEY(match_id, workspace_member_id) REFERENCES stats.match_player (match_id, workspace_member_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_fact_entity FOREIGN KEY(entity_id, entity_kind) REFERENCES catalog.entity (id, kind) ON DELETE RESTRICT,
	CONSTRAINT uq_fact UNIQUE NULLS NOT DISTINCT (match_id, segment, encounter_team_id, workspace_member_id, entity_id, stat_id),
	CONSTRAINT fk_fact_stat FOREIGN KEY(stat_id) REFERENCES stats.stat_def (id)
);

CREATE INDEX ix_fact_match_member ON stats.fact (match_id, workspace_member_id, segment);

CREATE INDEX ix_fact_member_entity_total ON stats.fact (workspace_member_id, entity_id, stat_id) WHERE segment = 0 AND entity_id IS NOT NULL;

CREATE INDEX ix_fact_member_stat_total ON stats.fact (workspace_member_id, stat_id) WHERE segment = 0 AND entity_id IS NULL;

CREATE INDEX ix_fact_stat_value_total ON stats.fact (stat_id, value) WHERE segment = 0 AND entity_id IS NULL AND workspace_member_id IS NOT NULL;

CREATE TABLE stats.ingest_job (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	source_kind VARCHAR(32) NOT NULL,
	external_id VARCHAR(128),
	content_hash CHAR(64),
	raw_status VARCHAR(16) DEFAULT 'available' NOT NULL,
	filename VARCHAR(500),
	raw_ref VARCHAR(512) NOT NULL,
	document_ref VARCHAR(512),
	status VARCHAR(16) NOT NULL,
	attempts INTEGER DEFAULT '0' NOT NULL,
	error_message TEXT,
	uploader_user_id BIGINT,
	api_key_id BIGINT,
	hint_tournament_id BIGINT,
	hint_encounter_id BIGINT,
	hint_encounter_game_id BIGINT,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_ingest_job_available_hash CHECK (raw_status <> 'available' OR content_hash IS NOT NULL),
	CONSTRAINT fk_ingest_job_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_ingest_job_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code),
	CONSTRAINT ck_ingest_job_raw_status CHECK (raw_status IN ('available', 'missing', 'conflict', 'unverified')),
	CONSTRAINT ck_ingest_job_status CHECK (status IN ('pending', 'processing', 'awaiting_link', 'done', 'failed')),
	CONSTRAINT fk_ingest_job_uploader FOREIGN KEY(uploader_user_id) REFERENCES players."user" (id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_ingest_job_api_key FOREIGN KEY(api_key_id) REFERENCES auth.api_key (id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_ingest_job_tournament FOREIGN KEY(hint_tournament_id) REFERENCES tournament.tournament (id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_ingest_job_encounter FOREIGN KEY(hint_encounter_id) REFERENCES encounter.encounter (id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_ingest_job_game FOREIGN KEY(hint_encounter_game_id) REFERENCES encounter.game (id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_ingest_job_api_key ON stats.ingest_job (api_key_id);

CREATE INDEX ix_ingest_job_encounter ON stats.ingest_job (hint_encounter_id);

CREATE INDEX ix_ingest_job_game ON stats.ingest_job (hint_encounter_game_id);

CREATE INDEX ix_ingest_job_status ON stats.ingest_job (status, created_at);

CREATE INDEX ix_ingest_job_tournament ON stats.ingest_job (hint_tournament_id);

CREATE INDEX ix_ingest_job_uploader ON stats.ingest_job (uploader_user_id);

CREATE UNIQUE INDEX uq_ingest_job_external ON stats.ingest_job (workspace_id, source_kind, external_id) WHERE external_id IS NOT NULL;

CREATE UNIQUE INDEX uq_ingest_job_hash ON stats.ingest_job (workspace_id, content_hash) WHERE external_id IS NULL;

CREATE TABLE stats.match (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	encounter_id BIGINT NOT NULL,
	encounter_game_id BIGINT,
	source_map_index INTEGER,
	ingest_job_id BIGINT,
	revision INTEGER DEFAULT '1' NOT NULL,
	played_at TIMESTAMP WITH TIME ZONE,
	duration_s DOUBLE PRECISION,
	map_entity_id BIGINT NOT NULL,
	map_kind VARCHAR(16) DEFAULT 'map' NOT NULL,
	mode_entity_id BIGINT,
	mode_kind VARCHAR(16) DEFAULT 'mode' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_stats_match_game UNIQUE (encounter_game_id),
	CONSTRAINT uq_stats_match_owner UNIQUE (id, encounter_id),
	CONSTRAINT ck_stats_match_map_kind CHECK (map_kind = 'map'),
	CONSTRAINT fk_match_map FOREIGN KEY(map_entity_id, discipline, map_kind) REFERENCES catalog.entity (id, discipline, kind) ON DELETE RESTRICT,
	CONSTRAINT ck_stats_match_mode_kind CHECK (mode_kind = 'mode'),
	CONSTRAINT fk_match_mode FOREIGN KEY(mode_entity_id, discipline, mode_kind) REFERENCES catalog.entity (id, discipline, kind) ON DELETE RESTRICT,
	CONSTRAINT fk_stats_match_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_stats_match_encounter FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_stats_match_game FOREIGN KEY(encounter_game_id) REFERENCES encounter.game (id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_stats_match_ingest_job FOREIGN KEY(ingest_job_id) REFERENCES stats.ingest_job (id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_stats_match_encounter ON stats.match (encounter_id);

CREATE INDEX ix_stats_match_ingest_job ON stats.match (ingest_job_id);

CREATE INDEX ix_stats_match_workspace ON stats.match (workspace_id);

CREATE TABLE stats.match_fetch (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	discipline VARCHAR(32) NOT NULL,
	source_kind VARCHAR(32) NOT NULL,
	external_id VARCHAR(128) NOT NULL,
	hint_tournament_id BIGINT NOT NULL,
	hint_encounter_id BIGINT NOT NULL,
	hint_encounter_game_id BIGINT NOT NULL,
	requested_by_user_id BIGINT,
	status VARCHAR(16) DEFAULT 'pending' NOT NULL,
	attempts INTEGER DEFAULT '0' NOT NULL,
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_error TEXT,
	ingest_job_id BIGINT,
	PRIMARY KEY (id),
	CONSTRAINT uq_match_fetch_game UNIQUE (source_kind, external_id, hint_encounter_game_id),
	CONSTRAINT fk_match_fetch_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_match_fetch_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code),
	CONSTRAINT fk_match_fetch_tournament FOREIGN KEY(hint_tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	CONSTRAINT fk_match_fetch_encounter FOREIGN KEY(hint_encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	CONSTRAINT fk_match_fetch_game FOREIGN KEY(hint_encounter_game_id) REFERENCES encounter.game (id) ON DELETE CASCADE,
	CONSTRAINT fk_match_fetch_requested_by FOREIGN KEY(requested_by_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL,
	CONSTRAINT ck_match_fetch_status CHECK (status IN ('pending', 'done', 'failed')),
	CONSTRAINT fk_match_fetch_ingest_job FOREIGN KEY(ingest_job_id) REFERENCES stats.ingest_job (id) ON DELETE SET NULL
);

CREATE INDEX ix_match_fetch_due ON stats.match_fetch (status, next_attempt_at);

CREATE INDEX ix_match_fetch_workspace_external ON stats.match_fetch (workspace_id, source_kind, external_id);

CREATE TABLE stats.match_player (
	match_id BIGINT NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	handle_snapshot VARCHAR(255) NOT NULL,
	observed_role_id BIGINT,
	CONSTRAINT pk_stats_match_player PRIMARY KEY (match_id, workspace_member_id),
	CONSTRAINT fk_match_player_team FOREIGN KEY(match_id, encounter_team_id) REFERENCES stats.match_team (match_id, encounter_team_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_match_player_member FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_match_player_role FOREIGN KEY(observed_role_id) REFERENCES catalog.role (id) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_match_player_member ON stats.match_player (workspace_member_id);

CREATE INDEX ix_match_player_observed_role ON stats.match_player (observed_role_id);

CREATE TABLE stats.match_team (
	match_id BIGINT NOT NULL,
	encounter_id BIGINT NOT NULL,
	encounter_team_id BIGINT NOT NULL,
	source_position INTEGER NOT NULL,
	CONSTRAINT pk_stats_match_team PRIMARY KEY (match_id, encounter_team_id),
	CONSTRAINT ck_match_team_source_position CHECK (source_position >= 1),
	CONSTRAINT uq_match_team_source_position UNIQUE (match_id, source_position),
	CONSTRAINT fk_match_team_match FOREIGN KEY(match_id, encounter_id) REFERENCES stats.match (id, encounter_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_match_team_encounter_team FOREIGN KEY(encounter_team_id, encounter_id) REFERENCES encounter.team (id, encounter_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_match_team_encounter_team ON stats.match_team (encounter_team_id, encounter_id);

CREATE TABLE stats.segment (
	match_id BIGINT NOT NULL,
	segment SMALLINT NOT NULL,
	kind VARCHAR(16) NOT NULL,
	attrs JSONB DEFAULT '{}'::jsonb NOT NULL,
	CONSTRAINT pk_stats_segment PRIMARY KEY (match_id, segment),
	CONSTRAINT ck_stats_segment_positive CHECK (segment >= 1),
	CONSTRAINT fk_segment_match FOREIGN KEY(match_id) REFERENCES stats.match (id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE stats.stat_baseline (
	id BIGSERIAL NOT NULL,
	formula_version VARCHAR(64) NOT NULL,
	role_id BIGINT NOT NULL,
	rank_bucket SMALLINT DEFAULT '-1' NOT NULL,
	stat_id SMALLINT NOT NULL,
	mean DOUBLE PRECISION NOT NULL,
	std DOUBLE PRECISION NOT NULL,
	meta JSONB,
	computed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_stat_baseline UNIQUE (formula_version, role_id, rank_bucket, stat_id),
	CONSTRAINT fk_stat_baseline_role FOREIGN KEY(role_id) REFERENCES catalog.role (id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_stat_baseline_stat FOREIGN KEY(stat_id) REFERENCES stats.stat_def (id)
);

CREATE INDEX ix_stat_baseline_role ON stats.stat_baseline (role_id);

CREATE TABLE stats.stat_def (
	id SMALLINT GENERATED ALWAYS AS IDENTITY,
	discipline VARCHAR(32) NOT NULL,
	code VARCHAR(64) NOT NULL,
	name VARCHAR(128) NOT NULL,
	value_format VARCHAR(16) NOT NULL,
	aggregation VARCHAR(8) NOT NULL,
	stat_group VARCHAR(32),
	active BOOLEAN DEFAULT true NOT NULL,
	sort_order INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_stat_def_code UNIQUE (discipline, code),
	CONSTRAINT ck_stat_def_aggregation CHECK (aggregation IN ('sum', 'max', 'min', 'avg', 'last')),
	CONSTRAINT fk_stat_def_discipline FOREIGN KEY(discipline) REFERENCES catalog.discipline (code)
);

CREATE TABLE subscriptions.check_log (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT,
	auth_user_id BIGINT,
	provider VARCHAR(32) NOT NULL,
	state VARCHAR(16) NOT NULL,
	tier_rank INTEGER,
	tier_label VARCHAR(64),
	source VARCHAR(32) DEFAULT 'scheduled' NOT NULL,
	mechanism VARCHAR(32),
	reason VARCHAR(64),
	error TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE SET NULL,
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_subscription_check_log_created_at ON subscriptions.check_log (created_at);

CREATE INDEX ix_subscription_check_log_state_created ON subscriptions.check_log (state, created_at);

CREATE INDEX ix_subscription_check_log_user_created ON subscriptions.check_log (auth_user_id, created_at);

CREATE INDEX ix_subscriptions_check_log_workspace_id ON subscriptions.check_log (workspace_id);

CREATE TABLE subscriptions.entitlement (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	auth_user_id BIGINT NOT NULL,
	provider VARCHAR(32) NOT NULL,
	state VARCHAR(16) DEFAULT 'unknown' NOT NULL,
	tier_rank INTEGER,
	tier_label VARCHAR(64),
	source VARCHAR(32),
	checked_at TIMESTAMP WITH TIME ZONE,
	expires_at TIMESTAMP WITH TIME ZONE,
	evidence_json JSON,
	PRIMARY KEY (id),
	CONSTRAINT uq_subscription_entitlement_scope UNIQUE (workspace_id, auth_user_id, provider),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_subscription_entitlement_workspace_provider ON subscriptions.entitlement (workspace_id, provider);

CREATE INDEX ix_subscriptions_entitlement_auth_user_id ON subscriptions.entitlement (auth_user_id);

CREATE INDEX ix_subscriptions_entitlement_workspace_id ON subscriptions.entitlement (workspace_id);

CREATE TABLE subscriptions.provider_config (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	provider VARCHAR(32) NOT NULL,
	enabled BOOLEAN DEFAULT 'false' NOT NULL,
	config_json JSON DEFAULT '{}' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_subscription_config_workspace_provider UNIQUE (workspace_id, provider),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_subscriptions_provider_config_workspace_id ON subscriptions.provider_config (workspace_id);

CREATE TABLE subscriptions.requirement (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	name VARCHAR(64) DEFAULT 'default' NOT NULL,
	requirement_json JSON DEFAULT '{}' NOT NULL,
	is_default BOOLEAN DEFAULT 'false' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_subscription_requirement_workspace_name UNIQUE (workspace_id, name),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_subscriptions_requirement_workspace_id ON subscriptions.requirement (workspace_id);

CREATE TABLE tournament.bracket_encounter (
	encounter_id BIGINT NOT NULL,
	tournament_id BIGINT NOT NULL,
	stage_id BIGINT,
	stage_item_id BIGINT,
	round INTEGER NOT NULL,
	PRIMARY KEY (encounter_id),
	CONSTRAINT fk_bracket_encounter FOREIGN KEY(encounter_id, tournament_id) REFERENCES encounter.encounter (id, tournament_id) ON DELETE CASCADE,
	CONSTRAINT fk_bracket_stage FOREIGN KEY(stage_id, tournament_id) REFERENCES tournament.stage (id, tournament_id) ON DELETE SET NULL (stage_id),
	CONSTRAINT fk_bracket_stage_item FOREIGN KEY(stage_item_id, stage_id) REFERENCES tournament.stage_item (id, stage_id) ON DELETE SET NULL (stage_item_id)
);

CREATE INDEX ix_bracket_encounter_stage_id ON tournament.bracket_encounter (stage_id);

CREATE INDEX ix_bracket_encounter_stage_item_id ON tournament.bracket_encounter (stage_item_id);

CREATE TABLE tournament.challonge_match_mapping (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	source_id BIGINT NOT NULL,
	challonge_match_id INTEGER NOT NULL,
	encounter_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_challonge_match_mapping_source_match UNIQUE (source_id, challonge_match_id),
	CONSTRAINT uq_challonge_match_mapping_source_encounter UNIQUE (source_id, encounter_id),
	FOREIGN KEY(source_id) REFERENCES tournament.challonge_source (id) ON DELETE CASCADE,
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_challonge_match_mapping_encounter ON tournament.challonge_match_mapping (encounter_id);

CREATE INDEX ix_challonge_match_mapping_source ON tournament.challonge_match_mapping (source_id);

CREATE TABLE tournament.challonge_participant_mapping (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	source_id BIGINT NOT NULL,
	challonge_participant_id INTEGER NOT NULL,
	team_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_challonge_participant_mapping_source_participant UNIQUE (source_id, challonge_participant_id),
	FOREIGN KEY(source_id) REFERENCES tournament.challonge_source (id) ON DELETE CASCADE,
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE
);

CREATE INDEX ix_challonge_participant_mapping_source ON tournament.challonge_participant_mapping (source_id);

CREATE INDEX ix_challonge_participant_mapping_team ON tournament.challonge_participant_mapping (team_id);

CREATE TABLE tournament.challonge_source (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	stage_id BIGINT,
	stage_item_id BIGINT,
	challonge_tournament_id INTEGER NOT NULL,
	slug VARCHAR,
	source_type VARCHAR(32) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_challonge_source_tournament_challonge UNIQUE (tournament_id, challonge_tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE SET NULL,
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE SET NULL
);

CREATE INDEX ix_challonge_source_stage ON tournament.challonge_source (stage_id);

CREATE INDEX ix_challonge_source_stage_item ON tournament.challonge_source (stage_item_id);

CREATE INDEX ix_challonge_source_tournament ON tournament.challonge_source (tournament_id);

CREATE TABLE tournament.challonge_sync_log (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	source_id BIGINT,
	direction VARCHAR(10) NOT NULL,
	operation VARCHAR(32),
	entity_type VARCHAR(32) NOT NULL,
	entity_id INTEGER,
	challonge_id INTEGER,
	status VARCHAR(16) NOT NULL,
	conflict_type VARCHAR(32),
	payload_json JSON,
	before_json JSON,
	after_json JSON,
	error_message TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(source_id) REFERENCES tournament.challonge_source (id) ON DELETE SET NULL
);

CREATE INDEX ix_challonge_sync_log_tournament_created ON tournament.challonge_sync_log (tournament_id, created_at DESC);

CREATE INDEX ix_tournament_challonge_sync_log_source_id ON tournament.challonge_sync_log (source_id);

CREATE INDEX ix_tournament_challonge_sync_log_tournament_id ON tournament.challonge_sync_log (tournament_id);

CREATE TABLE tournament.computation_job (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	kind VARCHAR(16) NOT NULL,
	operation VARCHAR(48) NOT NULL,
	tournament_id BIGINT NOT NULL,
	stage_id BIGINT,
	stage_item_id BIGINT,
	status VARCHAR(16) DEFAULT 'pending' NOT NULL,
	payload_json JSON DEFAULT '{}'::json NOT NULL,
	result_json JSON,
	error TEXT,
	requested_by_user_id BIGINT,
	idempotency_key VARCHAR(255) NOT NULL,
	attempts INTEGER DEFAULT '0' NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE CASCADE,
	FOREIGN KEY(requested_by_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_computation_job_requested_by_user_id ON tournament.computation_job (requested_by_user_id);

CREATE INDEX ix_tournament_computation_job_stage_id ON tournament.computation_job (stage_id);

CREATE INDEX ix_tournament_computation_job_stage_item_id ON tournament.computation_job (stage_item_id);

CREATE INDEX ix_tournament_computation_job_status ON tournament.computation_job (status);

CREATE INDEX ix_tournament_computation_job_tournament_id ON tournament.computation_job (tournament_id);

CREATE INDEX ix_tournament_computation_job_tournament_kind ON tournament.computation_job (tournament_id, kind);

CREATE UNIQUE INDEX uq_tournament_computation_job_active_key ON tournament.computation_job (idempotency_key) WHERE status IN ('pending', 'running');

CREATE TABLE tournament.encounter_link (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	source_encounter_id BIGINT NOT NULL,
	source_position INTEGER NOT NULL,
	target_encounter_id BIGINT NOT NULL,
	target_slot INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_link_source_position UNIQUE (source_encounter_id, source_position),
	CONSTRAINT uq_link_target_slot UNIQUE (target_encounter_id, target_slot),
	CONSTRAINT fk_link_source FOREIGN KEY(source_encounter_id, tournament_id) REFERENCES encounter.encounter (id, tournament_id) ON DELETE CASCADE,
	CONSTRAINT fk_link_target FOREIGN KEY(target_encounter_id, tournament_id) REFERENCES encounter.encounter (id, tournament_id) ON DELETE CASCADE,
	CONSTRAINT ck_link_not_self CHECK (source_encounter_id <> target_encounter_id),
	CONSTRAINT ck_link_positions CHECK (source_position >= 1 AND target_slot >= 1)
);

CREATE TABLE tournament.encounter_report_form (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	built_in_fields_json JSON DEFAULT '{}' NOT NULL,
	custom_fields_json JSON DEFAULT '[]' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_encounter_report_form_tournament UNIQUE (tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_encounter_report_form_tournament_id ON tournament.encounter_report_form (tournament_id);

CREATE TABLE tournament.encounter_saved_view (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	auth_user_id BIGINT NOT NULL,
	name VARCHAR(80) NOT NULL,
	filters_json JSON NOT NULL,
	sort_order INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_encounter_saved_view_workspace_user_name UNIQUE (workspace_id, auth_user_id, name),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_encounter_saved_view_workspace_user ON tournament.encounter_saved_view (workspace_id, auth_user_id);

CREATE INDEX ix_tournament_encounter_saved_view_auth_user_id ON tournament.encounter_saved_view (auth_user_id);

CREATE INDEX ix_tournament_encounter_saved_view_workspace_id ON tournament.encounter_saved_view (workspace_id);

CREATE TABLE tournament.pick_ban_config (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	kind encounter.pickbankind NOT NULL,
	stage_id BIGINT,
	round INTEGER,
	mode tournament.pickbanmode DEFAULT 'pool' NOT NULL,
	first_pick_rule tournament.pickbanfirstpickrule DEFAULT 'higher_seed' NOT NULL,
	first_ban_rotation tournament.pickbanrotation DEFAULT 'fixed' NOT NULL,
	ruleset_json JSON NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_pick_ban_config_round_requires_stage CHECK (round IS NULL OR stage_id IS NOT NULL),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_pick_ban_config_tournament_id ON tournament.pick_ban_config (tournament_id);

CREATE UNIQUE INDEX uq_pick_ban_config_level ON tournament.pick_ban_config (tournament_id, kind, stage_id, round) NULLS NOT DISTINCT;

CREATE TABLE tournament.pick_ban_config_item (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	pick_ban_config_id BIGINT NOT NULL,
	item_id INTEGER NOT NULL,
	sort_order INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_pick_ban_config_item UNIQUE (pick_ban_config_id, item_id),
	FOREIGN KEY(pick_ban_config_id) REFERENCES tournament.pick_ban_config (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_pick_ban_config_item_item_id ON tournament.pick_ban_config_item (item_id);

CREATE INDEX ix_tournament_pick_ban_config_item_pick_ban_config_id ON tournament.pick_ban_config_item (pick_ban_config_id);

CREATE TABLE tournament.pick_ban_config_slot (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	pick_ban_config_id BIGINT NOT NULL,
	position INTEGER NOT NULL,
	reserve_item_id INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT uq_pick_ban_config_slot_position UNIQUE (pick_ban_config_id, position),
	CONSTRAINT ck_pick_ban_config_slot_position_positive CHECK (position >= 1),
	FOREIGN KEY(pick_ban_config_id) REFERENCES tournament.pick_ban_config (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_pick_ban_config_slot_pick_ban_config_id ON tournament.pick_ban_config_slot (pick_ban_config_id);

CREATE TABLE tournament.pick_ban_config_slot_item (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	pick_ban_config_slot_id BIGINT NOT NULL,
	item_id INTEGER NOT NULL,
	sort_order INTEGER DEFAULT '0' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_pick_ban_config_slot_item UNIQUE (pick_ban_config_slot_id, item_id),
	FOREIGN KEY(pick_ban_config_slot_id) REFERENCES tournament.pick_ban_config_slot (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_pick_ban_config_slot_item_item_id ON tournament.pick_ban_config_slot_item (item_id);

CREATE INDEX ix_tournament_pick_ban_config_slot_item_pick_ban_config_slot_id ON tournament.pick_ban_config_slot_item (pick_ban_config_slot_id);

CREATE TABLE tournament.player (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	name VARCHAR NOT NULL,
	rank INTEGER NOT NULL,
	is_substitution BOOLEAN DEFAULT 'false' NOT NULL,
	related_player_id BIGINT,
	tournament_id BIGINT NOT NULL,
	is_newcomer BOOLEAN DEFAULT 'false' NOT NULL,
	is_newcomer_role BOOLEAN DEFAULT 'false' NOT NULL,
	workspace_member_id BIGINT NOT NULL,
	team_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(related_player_id) REFERENCES tournament.player (id) ON DELETE SET NULL,
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE,
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE
);

CREATE INDEX ix_player_member_not_sub ON tournament.player (workspace_member_id, tournament_id) WHERE is_substitution = false;

CREATE INDEX ix_player_related_player_id ON tournament.player (related_player_id);

CREATE INDEX ix_player_team_workspace_member ON tournament.player (team_id, workspace_member_id);

CREATE INDEX ix_player_workspace_member_tournament ON tournament.player (workspace_member_id, tournament_id);

CREATE INDEX ix_tournament_player_tournament_id ON tournament.player (tournament_id);

CREATE TABLE tournament.player_role (
	player_id BIGINT NOT NULL,
	dimension_id BIGINT NOT NULL,
	role_id BIGINT NOT NULL,
	PRIMARY KEY (player_id, role_id),
	CONSTRAINT fk_player_role_role FOREIGN KEY(role_id, dimension_id) REFERENCES catalog.role (id, dimension_id) DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_player_role_player FOREIGN KEY(player_id) REFERENCES tournament.player (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_player_role_role_id ON tournament.player_role (role_id);

CREATE TABLE tournament.recalculation_state (
	tournament_id BIGINT NOT NULL,
	requested_generation BIGINT DEFAULT '0' NOT NULL,
	completed_generation BIGINT DEFAULT '0' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE TABLE tournament.scrim_room (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	token VARCHAR(32) NOT NULL,
	label VARCHAR(255) NOT NULL,
	workspace_id BIGINT NOT NULL,
	tournament_id BIGINT NOT NULL,
	stage_id BIGINT NOT NULL,
	encounter_id BIGINT NOT NULL,
	created_by_auth_user_id BIGINT NOT NULL,
	closed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_scrim_room_token UNIQUE (token),
	CONSTRAINT uq_scrim_room_encounter UNIQUE (encounter_id),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE,
	FOREIGN KEY(encounter_id) REFERENCES encounter.encounter (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_scrim_room_open_by_creator ON tournament.scrim_room (created_by_auth_user_id) WHERE closed_at IS NULL;

CREATE INDEX ix_tournament_scrim_room_created_by_auth_user_id ON tournament.scrim_room (created_by_auth_user_id);

CREATE INDEX ix_tournament_scrim_room_encounter_id ON tournament.scrim_room (encounter_id);

CREATE INDEX ix_tournament_scrim_room_stage_id ON tournament.scrim_room (stage_id);

CREATE INDEX ix_tournament_scrim_room_tournament_id ON tournament.scrim_room (tournament_id);

CREATE INDEX ix_tournament_scrim_room_workspace_id ON tournament.scrim_room (workspace_id);

CREATE TABLE tournament.slug_redirect (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	old_slug VARCHAR NOT NULL,
	tournament_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_tournament_slug_redirect_old_slug ON tournament.slug_redirect (old_slug);

CREATE INDEX ix_tournament_slug_redirect_tournament_id ON tournament.slug_redirect (tournament_id);

CREATE TABLE tournament.stage (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	scoring_rule_id BIGINT NOT NULL,
	name VARCHAR NOT NULL,
	description VARCHAR,
	stage_type tournament.stagetype NOT NULL,
	max_rounds INTEGER DEFAULT '5' NOT NULL,
	advance_count INTEGER,
	advance_upper_count INTEGER,
	"order" INTEGER NOT NULL,
	is_active BOOLEAN DEFAULT 'false' NOT NULL,
	is_published BOOLEAN DEFAULT 'false' NOT NULL,
	is_completed BOOLEAN DEFAULT 'false' NOT NULL,
	ranking_preset VARCHAR,
	tiebreak_order VARCHAR[],
	win_points FLOAT,
	draw_points FLOAT,
	loss_points FLOAT,
	swiss_bye_points FLOAT,
	swiss_qualify_wins INTEGER,
	swiss_eliminate_losses INTEGER,
	de_grand_final_type VARCHAR(16) DEFAULT 'no_reset' NOT NULL,
	seed_ranking VARCHAR(16) DEFAULT 'slot' NOT NULL,
	best_of_default INTEGER DEFAULT '3' NOT NULL,
	best_of_final INTEGER,
	best_of_swiss_qualify INTEGER,
	best_of_swiss_eliminate INTEGER,
	challonge_group_id BIGINT,
	bracket_template JSONB,
	PRIMARY KEY (id),
	CONSTRAINT ck_stage_de_grand_final_type CHECK (de_grand_final_type IN ('no_reset', 'with_reset')),
	CONSTRAINT ck_stage_seed_ranking CHECK (seed_ranking IN ('slot', 'avg_sr', 'total_sr', 'random')),
	CONSTRAINT ck_stage_best_of_default CHECK (best_of_default >= 1),
	CONSTRAINT ck_stage_best_of_final CHECK (best_of_final IS NULL OR best_of_final >= 1),
	CONSTRAINT ck_stage_swiss_qualify_wins CHECK (swiss_qualify_wins IS NULL OR swiss_qualify_wins >= 1),
	CONSTRAINT ck_stage_swiss_eliminate_losses CHECK (swiss_eliminate_losses IS NULL OR swiss_eliminate_losses >= 1),
	CONSTRAINT ck_stage_best_of_swiss_qualify CHECK (best_of_swiss_qualify IS NULL OR best_of_swiss_qualify >= 1),
	CONSTRAINT ck_stage_best_of_swiss_eliminate CHECK (best_of_swiss_eliminate IS NULL OR best_of_swiss_eliminate >= 1),
	CONSTRAINT uq_stage_id_tournament UNIQUE (id, tournament_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(scoring_rule_id) REFERENCES encounter.scoring_rule (id) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_tournament_stage_tournament_id ON tournament.stage (tournament_id);

CREATE TABLE tournament.stage_item (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	stage_id BIGINT NOT NULL,
	name VARCHAR NOT NULL,
	type tournament.stageitemtype NOT NULL,
	"order" INTEGER NOT NULL,
	advance_count INTEGER,
	advance_upper_count INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT uq_stage_item_id_stage UNIQUE (id, stage_id),
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_stage_item_stage_id ON tournament.stage_item (stage_id);

CREATE TABLE tournament.stage_item_input (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	stage_item_id BIGINT NOT NULL,
	slot INTEGER NOT NULL,
	input_type tournament.stageiteminputtype NOT NULL,
	team_id BIGINT,
	source_stage_item_id BIGINT,
	source_position INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT uq_stage_item_input_item_slot UNIQUE (stage_item_id, slot),
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE CASCADE,
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE SET NULL,
	FOREIGN KEY(source_stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_stage_item_input_stage_item_id ON tournament.stage_item_input (stage_item_id);

CREATE INDEX ix_tournament_stage_item_input_team_id ON tournament.stage_item_input (team_id);

CREATE TABLE tournament.stage_round_best_of (
	stage_id BIGINT NOT NULL,
	round INTEGER NOT NULL,
	best_of INTEGER NOT NULL,
	PRIMARY KEY (stage_id, round),
	CONSTRAINT ck_stage_round_best_of_best_of CHECK (best_of >= 1),
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE
);

CREATE TABLE tournament.standing (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id INTEGER NOT NULL,
	team_id INTEGER NOT NULL,
	stage_id INTEGER,
	stage_item_id INTEGER,
	position INTEGER NOT NULL,
	overall_position INTEGER DEFAULT '0' NOT NULL,
	matches INTEGER NOT NULL,
	win INTEGER NOT NULL,
	draw INTEGER NOT NULL,
	lose INTEGER NOT NULL,
	points FLOAT NOT NULL,
	buchholz FLOAT,
	full_buchholz FLOAT,
	tie_group INTEGER,
	tb INTEGER,
	score_differential INTEGER,
	is_pinned BOOLEAN DEFAULT 'false' NOT NULL,
	swiss_status VARCHAR(16),
	PRIMARY KEY (id),
	CONSTRAINT ck_standing_swiss_status CHECK (swiss_status IN ('qualified', 'eliminated')),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE SET NULL,
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE SET NULL
);

CREATE INDEX ix_standing_stage_stage_item_team ON tournament.standing (stage_id, stage_item_id, team_id);

CREATE INDEX ix_standing_tournament_position ON tournament.standing (tournament_id, overall_position);

CREATE INDEX ix_tournament_standing_stage_id ON tournament.standing (stage_id);

CREATE INDEX ix_tournament_standing_stage_item_id ON tournament.standing (stage_item_id);

CREATE INDEX ix_tournament_standing_team_id ON tournament.standing (team_id);

CREATE INDEX ix_tournament_standing_tournament_id ON tournament.standing (tournament_id);

CREATE TABLE tournament.standing_pin (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	stage_id BIGINT NOT NULL,
	stage_item_id BIGINT,
	team_id BIGINT NOT NULL,
	position INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_standing_pin_position CHECK (position >= 1),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE CASCADE,
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_standing_pin_team_id ON tournament.standing_pin (team_id);

CREATE INDEX ix_tournament_standing_pin_tournament_id ON tournament.standing_pin (tournament_id);

CREATE UNIQUE INDEX uq_standing_pin_position ON tournament.standing_pin (stage_id, stage_item_id, position) NULLS NOT DISTINCT;

CREATE UNIQUE INDEX uq_standing_pin_team ON tournament.standing_pin (stage_id, stage_item_id, team_id) NULLS NOT DISTINCT;

CREATE TABLE tournament.swiss_bye (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	stage_id BIGINT NOT NULL,
	stage_item_id BIGINT,
	team_id BIGINT NOT NULL,
	round INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE CASCADE,
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_swiss_bye_stage_id ON tournament.swiss_bye (stage_id);

CREATE INDEX ix_tournament_swiss_bye_team_id ON tournament.swiss_bye (team_id);

CREATE TABLE tournament.swiss_stopped_scope (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	stage_id BIGINT NOT NULL,
	stage_item_id BIGINT,
	PRIMARY KEY (id),
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE,
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_swiss_stopped_scope ON tournament.swiss_stopped_scope (stage_id, stage_item_id) NULLS NOT DISTINCT;

CREATE TABLE tournament.team (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	balancer_name VARCHAR NOT NULL,
	name VARCHAR NOT NULL,
	image_url VARCHAR,
	captain_id BIGINT,
	tournament_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_team_id_tournament UNIQUE (id, tournament_id),
	FOREIGN KEY(captain_id) REFERENCES players."user" (id) ON DELETE SET NULL,
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_team_captain_id ON tournament.team (captain_id);

CREATE INDEX ix_tournament_team_tournament_id ON tournament.team (tournament_id);

CREATE TABLE tournament.tournament (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	workspace_id BIGINT NOT NULL,
	discipline VARCHAR(32) DEFAULT 'overwatch' NOT NULL,
	name VARCHAR NOT NULL,
	slug VARCHAR NOT NULL,
	description VARCHAR,
	rules TEXT,
	is_league BOOLEAN DEFAULT 'false' NOT NULL,
	is_finished BOOLEAN DEFAULT 'false' NOT NULL,
	is_hidden BOOLEAN DEFAULT 'false' NOT NULL,
	team_formation VARCHAR DEFAULT 'balancer' NOT NULL,
	status tournament.tournamentstatus NOT NULL,
	start_date TIMESTAMP WITH TIME ZONE,
	end_date TIMESTAMP WITH TIME ZONE,
	auto_transitions_enabled BOOLEAN DEFAULT 'true' NOT NULL,
	allow_late_registration BOOLEAN DEFAULT 'false' NOT NULL,
	discord_broadcasts_enabled BOOLEAN DEFAULT 'true' NOT NULL,
	discord_dms_enabled BOOLEAN DEFAULT 'true' NOT NULL,
	logs_official BOOLEAN DEFAULT 'false' NOT NULL,
	win_points FLOAT DEFAULT '1.0' NOT NULL,
	draw_points FLOAT DEFAULT '0.5' NOT NULL,
	loss_points FLOAT DEFAULT '0.0' NOT NULL,
	division_grid_version_id BIGINT,
	draft_format_json JSONB,
	cover_image_url VARCHAR,
	logo_url VARCHAR,
	PRIMARY KEY (id),
	CONSTRAINT uq_tournament_owner_key UNIQUE (id, workspace_id, discipline),
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	FOREIGN KEY(discipline) REFERENCES catalog.discipline (code),
	FOREIGN KEY(division_grid_version_id) REFERENCES division_grid_version (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_tournament_division_grid_version_id ON tournament.tournament (division_grid_version_id);

CREATE INDEX ix_tournament_tournament_is_hidden ON tournament.tournament (is_hidden);

CREATE UNIQUE INDEX ix_tournament_tournament_slug ON tournament.tournament (slug);

CREATE INDEX ix_tournament_tournament_status ON tournament.tournament (status);

CREATE INDEX ix_tournament_tournament_workspace_id ON tournament.tournament (workspace_id);

CREATE TABLE tournament.tournament_link (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	kind VARCHAR(32) NOT NULL,
	label VARCHAR(128),
	url VARCHAR(500) NOT NULL,
	sort_order INTEGER DEFAULT '0' NOT NULL,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_tournament_link_tournament_kind_url UNIQUE (tournament_id, kind, url),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_link_tournament_active ON tournament.tournament_link (tournament_id, is_active);

CREATE INDEX ix_tournament_tournament_link_tournament_id ON tournament.tournament_link (tournament_id);

CREATE TABLE tournament.tournament_phase_schedule (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	status tournament.tournamentstatus NOT NULL,
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ends_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_tournament_phase_schedule_phase UNIQUE (tournament_id, status),
	CONSTRAINT ck_tournament_phase_schedule_window CHECK (ends_at IS NULL OR ends_at > starts_at),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_tournament_phase_schedule_starts_at ON tournament.tournament_phase_schedule (starts_at);

CREATE INDEX ix_tournament_tournament_phase_schedule_tournament_id ON tournament.tournament_phase_schedule (tournament_id);

CREATE TABLE tournament.tournament_preview_access (
	id BIGSERIAL NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE,
	tournament_id BIGINT NOT NULL,
	auth_user_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_tournament_preview_access_tournament_user UNIQUE (tournament_id, auth_user_id),
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE,
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_tournament_preview_access_auth_user_id ON tournament.tournament_preview_access (auth_user_id);

CREATE INDEX ix_tournament_tournament_preview_access_tournament_id ON tournament.tournament_preview_access (tournament_id);
