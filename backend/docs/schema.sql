-- Anak Tournaments — PostgreSQL DDL compiled from SQLAlchemy metadata.
-- Open in any SQL editor (DataGrip, DBeaver, VS Code).
-- Tables: 126
-- Source of truth is backend/shared/models. Regenerate: python scripts/export_db_schema.py

CREATE SCHEMA IF NOT EXISTS achievements;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS balancer;
CREATE SCHEMA IF NOT EXISTS casual;
CREATE SCHEMA IF NOT EXISTS log_processing;
CREATE SCHEMA IF NOT EXISTS matches;
CREATE SCHEMA IF NOT EXISTS overwatch;
CREATE SCHEMA IF NOT EXISTS overwatch_rank;
CREATE SCHEMA IF NOT EXISTS players;
CREATE SCHEMA IF NOT EXISTS realtime;
CREATE SCHEMA IF NOT EXISTS subscriptions;
CREATE SCHEMA IF NOT EXISTS tournament;

CREATE TYPE heroclass AS ENUM ('tank', 'damage', 'support', 'flex');
CREATE TYPE log_processing_status AS ENUM ('pending', 'processing', 'done', 'failed');
CREATE TYPE log_processing_source AS ENUM ('upload', 'discord', 'manual');
CREATE TYPE matchevent AS ENUM ('OffensiveAssist', 'DefensiveAssist', 'UltimateCharged', 'UltimateStart', 'UltimateEnd', 'HeroSwap', 'MercyRez', 'EchoDuplicateStart', 'EchoDuplicateEnd');
CREATE TYPE abilityevent AS ENUM ('PrimaryFire', 'SecondaryFire', 'Ability1', 'Ability2', 'Ultimate', 'Melee', 'Crouch');
CREATE TYPE matches.matchsource AS ENUM ('log_parser', 'captain_report');
CREATE TYPE logstatsname AS ENUM ('Eliminations', 'FinalBlows', 'Deaths', 'AllDamageDealt', 'BarrierDamageDealt', 'HeroDamageDealt', 'HealingDealt', 'HealingReceived', 'SelfHealing', 'DamageTaken', 'DamageBlocked', 'DefensiveAssists', 'OffensiveAssists', 'UltimatesEarned', 'UltimatesUsed', 'MultikillBest', 'Multikills', 'SoloKills', 'ObjectiveKills', 'EnvironmentalKills', 'EnvironmentalDeaths', 'CriticalHits', 'CriticalHitAccuracy', 'ScopedAccuracy', 'ScopedCriticalHitAccuracy', 'ScopedCriticalHitKills', 'ShotsFired', 'ShotsHit', 'ShotsMissed', 'ScopedShotsFired', 'ScopedShotsHit', 'WeaponAccuracy', 'HeroTimePlayed', 'FirstPicks', 'FirstDeaths', 'UltimateKills', 'SupportKills', 'Performance', 'PerformancePoints', 'KD', 'KDA', 'DamageDelta', 'FBE', 'DamageFB', 'Assists', 'ImpactPoints', 'ImpactRank', 'OverperformanceScore');
CREATE TYPE catalogentitytype AS ENUM ('hero', 'map', 'gamemode');
CREATE TYPE tournament.encounterstatus AS ENUM ('COMPLETED', 'PENDING', 'OPEN');
CREATE TYPE tournament.encounterresultstatus AS ENUM ('none', 'pending_confirmation', 'confirmed', 'disputed');
CREATE TYPE tournament.encounterlinkrole AS ENUM ('winner', 'loser');
CREATE TYPE tournament.encounterlinkslot AS ENUM ('home', 'away');
CREATE TYPE tournament.pickbankind AS ENUM ('map', 'hero');
CREATE TYPE tournament.pickbanside AS ENUM ('home', 'away', 'decider', 'admin');
CREATE TYPE tournament.encounterresultauditaction AS ENUM ('confirm', 'reopen', 'auto_confirm', 'auto_dispute', 'import', 'cascade_reset');
CREATE TYPE tournament.pickbanmode AS ENUM ('pool', 'slots');
CREATE TYPE tournament.pickbanfirstpickrule AS ENUM ('higher_seed');
CREATE TYPE tournament.pickbanrotation AS ENUM ('fixed', 'alternate', 'result_winner_first', 'result_loser_first', 'result_loser_choice');
CREATE TYPE tournament.pickbannorepeatscope AS ENUM ('none', 'encounter', 'encounter_same_side');
CREATE TYPE tournament.pickbanentrystatus AS ENUM ('available', 'picked', 'banned', 'played', 'protected');
CREATE TYPE tournament.pickbanseedsource AS ENUM ('bracket_slot', 'standings', 'fallback_home', 'admin');
CREATE TYPE tournament.pickbansessionstatus AS ENUM ('active', 'completed', 'cancelled');
CREATE TYPE tournament.stagetype AS ENUM ('round_robin', 'single_elimination', 'double_elimination', 'swiss');
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
	match_id BIGINT, 
	qualified_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	evidence_json JSON, 
	rule_version INTEGER NOT NULL, 
	run_id UUID, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_eval_result_rule_user_tournament_match UNIQUE (achievement_rule_id, workspace_member_id, tournament_id, match_id), 
	FOREIGN KEY(achievement_rule_id) REFERENCES achievements.rule (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE, 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE, 
	FOREIGN KEY(match_id) REFERENCES matches.match (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES achievements.evaluation_run (id) ON DELETE SET NULL
);

CREATE INDEX ix_achievements_evaluation_result_workspace_member_id ON achievements.evaluation_result (workspace_member_id);

CREATE INDEX ix_achievements_evaluation_result_achievement_rule_id ON achievements.evaluation_result (achievement_rule_id);

CREATE INDEX ix_achievements_evaluation_result_tournament_id ON achievements.evaluation_result (tournament_id);

CREATE INDEX ix_achievements_evaluation_result_run_id ON achievements.evaluation_result (run_id);

CREATE INDEX ix_achievements_evaluation_result_match_id ON achievements.evaluation_result (match_id) WHERE match_id IS NOT NULL;

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

CREATE INDEX ix_achievements_evaluation_run_workspace_id ON achievements.evaluation_run (workspace_id);

CREATE INDEX ix_achievements_evaluation_run_id ON achievements.evaluation_run (id);

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
	FOREIGN KEY(match_id) REFERENCES matches.match (id) ON DELETE CASCADE, 
	FOREIGN KEY(granted_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_achievements_override_workspace_member_id ON achievements.override (workspace_member_id);

CREATE INDEX ix_achievements_override_tournament_id ON achievements.override (tournament_id);

CREATE INDEX ix_achievements_override_achievement_rule_id ON achievements.override (achievement_rule_id);

CREATE INDEX ix_achievements_override_match_id ON achievements.override (match_id);

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
	hero_id BIGINT, 
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
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE, 
	FOREIGN KEY(hero_id) REFERENCES overwatch.hero (id) ON DELETE SET NULL
);

CREATE INDEX ix_achievements_rule_workspace_id ON achievements.rule (workspace_id);

CREATE INDEX ix_achievements_rule_slug ON achievements.rule (slug);

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

CREATE INDEX ix_analytics_anomaly_feedback_reviewer_user_id ON analytics.anomaly_feedback (reviewer_user_id);

CREATE INDEX ix_analytics_anomaly_feedback_player_id ON analytics.anomaly_feedback (player_id);

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

CREATE INDEX ix_analytics_job_tournament_id ON analytics.job (tournament_id);

CREATE INDEX ix_analytics_job_status ON analytics.job (status);

CREATE INDEX ix_analytics_job_workspace_id ON analytics.job (workspace_id);

CREATE UNIQUE INDEX uq_analytics_job_one_running_per_workspace ON analytics.job (workspace_id) WHERE status IN ('pending', 'running');

CREATE INDEX ix_analytics_job_requested_by_user_id ON analytics.job (requested_by_user_id);

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
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
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
	role VARCHAR(16), 
	version VARCHAR(32) NOT NULL, 
	storage_uri TEXT NOT NULL, 
	feature_version VARCHAR(32) NOT NULL, 
	training_cutoff_tournament_id BIGINT, 
	metrics JSON, 
	feature_importance JSON, 
	is_active BOOLEAN DEFAULT 'false' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_analytics_ml_model_artifact UNIQUE (algorithm_id, model_kind, role, version), 
	FOREIGN KEY(algorithm_id) REFERENCES analytics.algorithms (id) ON DELETE CASCADE, 
	FOREIGN KEY(training_cutoff_tournament_id) REFERENCES tournament.tournament (id) ON DELETE SET NULL
);

CREATE INDEX ix_analytics_ml_model_artifact_training_cutoff_tournament_id ON analytics.ml_model_artifact (training_cutoff_tournament_id);

CREATE INDEX ix_analytics_ml_model_artifact_is_active ON analytics.ml_model_artifact (is_active);

CREATE INDEX ix_analytics_ml_model_artifact_model_kind ON analytics.ml_model_artifact (model_kind);

CREATE INDEX ix_analytics_ml_model_artifact_algorithm_id ON analytics.ml_model_artifact (algorithm_id);

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

CREATE INDEX ix_analytics_performance_player_id ON analytics.performance (player_id);

CREATE INDEX ix_analytics_performance_tournament_id ON analytics.performance (tournament_id);

CREATE INDEX ix_analytics_performance_algorithm_id ON analytics.performance (algorithm_id);

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
	FOREIGN KEY(source_encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_analytics_player_anomaly_source_encounter_id ON analytics.player_anomaly (source_encounter_id);

CREATE INDEX ix_analytics_player_anomaly_player_id ON analytics.player_anomaly (player_id);

CREATE INDEX ix_analytics_player_anomaly_tournament_id ON analytics.player_anomaly (tournament_id);

CREATE INDEX ix_analytics_player_anomaly_kind ON analytics.player_anomaly (kind);

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
	confidence FLOAT DEFAULT '0' NOT NULL, 
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

CREATE INDEX ix_analytics_shifts_tournament_id ON analytics.shifts (tournament_id);

CREATE INDEX ix_analytics_shifts_player_id ON analytics.shifts (player_id);

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
	limits_json JSON DEFAULT '{}' NOT NULL, 
	config_policy_json JSON DEFAULT '{}' NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	last_used_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_api_key_public_id_active ON auth.api_key (public_id, revoked_at);

CREATE INDEX ix_auth_api_key_auth_user_id ON auth.api_key (auth_user_id);

CREATE INDEX ix_api_key_owner_workspace ON auth.api_key (auth_user_id, workspace_id);

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

CREATE INDEX ix_auth_permissions_resource ON auth.permissions (resource);

CREATE INDEX ix_auth_permissions_action ON auth.permissions (action);

CREATE UNIQUE INDEX ix_auth_permissions_name ON auth.permissions (name);

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

CREATE TABLE auth.role_permissions (
	id SERIAL NOT NULL, 
	role_id INTEGER NOT NULL, 
	permission_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(role_id) REFERENCES auth.roles (id) ON DELETE CASCADE, 
	FOREIGN KEY(permission_id) REFERENCES auth.permissions (id) ON DELETE CASCADE
);

CREATE INDEX ix_role_permissions_role_id ON auth.role_permissions (role_id);

CREATE INDEX ix_role_permissions_permission_id ON auth.role_permissions (permission_id);

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

CREATE UNIQUE INDEX uq_roles_name_global ON auth.roles (name) WHERE workspace_id IS NULL;

CREATE UNIQUE INDEX uq_roles_name_workspace ON auth.roles (name, workspace_id) WHERE workspace_id IS NOT NULL;

CREATE INDEX ix_auth_roles_workspace_id ON auth.roles (workspace_id);

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

CREATE UNIQUE INDEX ix_auth_user_username ON auth."user" (username);

CREATE UNIQUE INDEX ix_auth_user_email ON auth."user" (email);

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

CREATE UNIQUE INDEX uq_user_permission_deny_user_perm_workspace ON auth.user_permission_deny (user_id, permission_id, COALESCE(workspace_id, 0));

CREATE INDEX ix_user_permission_deny_user_id ON auth.user_permission_deny (user_id);

CREATE TABLE auth.user_roles (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	role_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES auth."user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(role_id) REFERENCES auth.roles (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_roles_user_id ON auth.user_roles (user_id);

CREATE INDEX ix_user_roles_role_id ON auth.user_roles (role_id);

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

CREATE INDEX ix_balancer_balance_workspace_id ON balancer.balance (workspace_id);

CREATE INDEX ix_balancer_balance_tournament_id ON balancer.balance (tournament_id);

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

CREATE TABLE balancer.custom_game (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	workspace_id BIGINT NOT NULL, 
	host_user_id BIGINT, 
	name VARCHAR(255) NOT NULL, 
	status VARCHAR(16) DEFAULT 'draft' NOT NULL, 
	points_per_win INTEGER, 
	balancer_config_json JSONB, 
	balancer_config_version INTEGER DEFAULT '1' NOT NULL, 
	balance_result_json JSONB, 
	balance_result_version INTEGER DEFAULT '1' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_custom_game_status CHECK (status IN ('draft', 'balanced', 'completed', 'cancelled')), 
	CONSTRAINT ck_custom_game_points_per_win CHECK (points_per_win IS NULL OR points_per_win BETWEEN 1 AND 1000), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE, 
	FOREIGN KEY(host_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_custom_game_host_user_id ON balancer.custom_game (host_user_id);

CREATE INDEX ix_balancer_custom_game_workspace_id ON balancer.custom_game (workspace_id);

CREATE TABLE balancer.custom_game_co_host (
	custom_game_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	PRIMARY KEY (custom_game_id, user_id), 
	FOREIGN KEY(custom_game_id) REFERENCES balancer.custom_game (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE TABLE balancer.custom_game_player (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	custom_game_id BIGINT NOT NULL, 
	workspace_member_id BIGINT NOT NULL, 
	sort_order INTEGER DEFAULT '0' NOT NULL, 
	participation VARCHAR(16) DEFAULT 'pool' NOT NULL, 
	role_selection_mode VARCHAR(16) DEFAULT 'all_ranked' NOT NULL, 
	is_flex BOOLEAN DEFAULT 'false' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_custom_game_player_member UNIQUE (custom_game_id, workspace_member_id), 
	CONSTRAINT ck_custom_game_player_participation CHECK (participation IN ('must_play', 'pool', 'benched')), 
	CONSTRAINT ck_custom_game_player_role_selection_mode CHECK (role_selection_mode IN ('all_ranked', 'explicit')), 
	FOREIGN KEY(custom_game_id) REFERENCES balancer.custom_game (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_custom_game_player_custom_game_id ON balancer.custom_game_player (custom_game_id);

CREATE INDEX ix_balancer_custom_game_player_workspace_member_id ON balancer.custom_game_player (workspace_member_id);

CREATE TABLE balancer.custom_game_player_role (
	custom_game_player_id BIGINT NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	priority INTEGER NOT NULL, 
	PRIMARY KEY (custom_game_player_id, role), 
	CONSTRAINT uq_custom_game_player_role_priority UNIQUE (custom_game_player_id, priority), 
	CONSTRAINT ck_custom_game_player_role_priority CHECK (priority > 0), 
	FOREIGN KEY(custom_game_player_id) REFERENCES balancer.custom_game_player (id) ON DELETE CASCADE
);

CREATE TABLE balancer.custom_game_role_slot (
	custom_game_id BIGINT NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	slot_count INTEGER NOT NULL, 
	PRIMARY KEY (custom_game_id, role), 
	CONSTRAINT ck_custom_game_role_slot_count CHECK (slot_count > 0), 
	FOREIGN KEY(custom_game_id) REFERENCES balancer.custom_game (id) ON DELETE CASCADE
);

CREATE TABLE balancer.custom_game_team_name (
	custom_game_id BIGINT NOT NULL, 
	team_index INTEGER NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	PRIMARY KEY (custom_game_id, team_index), 
	CONSTRAINT ck_custom_game_team_name_index CHECK (team_index BETWEEN 0 AND 7), 
	FOREIGN KEY(custom_game_id) REFERENCES balancer.custom_game (id) ON DELETE CASCADE
);

CREATE TABLE balancer.draft_audit_event (
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
	FOREIGN KEY(session_id) REFERENCES balancer.draft_session (id) ON DELETE CASCADE, 
	FOREIGN KEY(actor_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_draft_audit_session_created ON balancer.draft_audit_event (session_id, created_at);

CREATE INDEX ix_balancer_draft_audit_event_actor_auth_user_id ON balancer.draft_audit_event (actor_auth_user_id);

CREATE TABLE balancer.draft_pick (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	session_id BIGINT NOT NULL, 
	overall_no INTEGER NOT NULL, 
	round_no INTEGER NOT NULL, 
	pick_in_round INTEGER NOT NULL, 
	draft_team_id BIGINT NOT NULL, 
	target_role VARCHAR(16), 
	target_rank_value INTEGER, 
	status VARCHAR(16) DEFAULT 'upcoming' NOT NULL, 
	picked_player_id BIGINT, 
	picked_by_workspace_member_id BIGINT, 
	is_autopick BOOLEAN DEFAULT 'false' NOT NULL, 
	is_admin_override BOOLEAN DEFAULT 'false' NOT NULL, 
	clock_started_at TIMESTAMP WITH TIME ZONE, 
	clock_expires_at TIMESTAMP WITH TIME ZONE, 
	clock_remaining_ms INTEGER, 
	version INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_draft_pick_session_overall UNIQUE (session_id, overall_no), 
	FOREIGN KEY(session_id) REFERENCES balancer.draft_session (id) ON DELETE CASCADE, 
	FOREIGN KEY(draft_team_id) REFERENCES balancer.draft_team (id) ON DELETE CASCADE, 
	FOREIGN KEY(picked_player_id) REFERENCES balancer.draft_player (id) ON DELETE SET NULL, 
	FOREIGN KEY(picked_by_workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_draft_pick_picked_player_id ON balancer.draft_pick (picked_player_id);

CREATE INDEX ix_balancer_draft_pick_draft_team_id ON balancer.draft_pick (draft_team_id);

CREATE INDEX ix_draft_pick_session_status ON balancer.draft_pick (session_id, status);

CREATE TABLE balancer.draft_player (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	session_id BIGINT NOT NULL, 
	registration_id BIGINT NOT NULL, 
	workspace_member_id BIGINT, 
	status VARCHAR(16) DEFAULT 'available' NOT NULL, 
	is_captain BOOLEAN DEFAULT 'false' NOT NULL, 
	drafted_by_team_id BIGINT, 
	version INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_draft_player_session_registration UNIQUE (session_id, registration_id), 
	FOREIGN KEY(session_id) REFERENCES balancer.draft_session (id) ON DELETE CASCADE, 
	FOREIGN KEY(registration_id) REFERENCES balancer.registration (id) ON DELETE RESTRICT, 
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL, 
	FOREIGN KEY(drafted_by_team_id) REFERENCES balancer.draft_team (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_draft_player_registration_id ON balancer.draft_player (registration_id);

CREATE INDEX ix_balancer_draft_player_workspace_member_id ON balancer.draft_player (workspace_member_id);

CREATE INDEX ix_draft_player_session_status ON balancer.draft_player (session_id, status);

CREATE INDEX ix_balancer_draft_player_drafted_by_team_id ON balancer.draft_player (drafted_by_team_id);

CREATE TABLE balancer.draft_session (
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

CREATE INDEX ix_draft_session_tournament_status ON balancer.draft_session (tournament_id, status);

CREATE INDEX ix_balancer_draft_session_workspace_id ON balancer.draft_session (workspace_id);

CREATE INDEX ix_balancer_draft_session_source_balance_id ON balancer.draft_session (source_balance_id);

CREATE INDEX ix_draft_session_status_created ON balancer.draft_session (status, created_at);

CREATE UNIQUE INDEX uq_draft_session_active_tournament ON balancer.draft_session (tournament_id) WHERE status IN ('setup','ready','live','paused');

CREATE TABLE balancer.draft_team (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	session_id BIGINT NOT NULL, 
	captain_workspace_member_id BIGINT, 
	captain_auth_user_id BIGINT, 
	name VARCHAR(255) NOT NULL, 
	draft_position INTEGER NOT NULL, 
	exported_team_id BIGINT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_draft_team_session_position UNIQUE (session_id, draft_position), 
	FOREIGN KEY(session_id) REFERENCES balancer.draft_session (id) ON DELETE CASCADE, 
	FOREIGN KEY(captain_workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL, 
	FOREIGN KEY(captain_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(exported_team_id) REFERENCES tournament.team (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_draft_team_exported_team_id ON balancer.draft_team (exported_team_id);

CREATE INDEX ix_balancer_draft_team_captain_workspace_member_id ON balancer.draft_team (captain_workspace_member_id);

CREATE INDEX ix_balancer_draft_team_session_id ON balancer.draft_team (session_id);

CREATE INDEX ix_balancer_draft_team_captain_auth_user_id ON balancer.draft_team (captain_auth_user_id);

CREATE TABLE balancer.member_rank (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	workspace_id BIGINT NOT NULL, 
	workspace_member_id BIGINT NOT NULL, 
	author_user_id BIGINT, 
	role VARCHAR(16) NOT NULL, 
	rank_value INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE CASCADE, 
	FOREIGN KEY(author_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_member_rank_workspace_id ON balancer.member_rank (workspace_id);

CREATE UNIQUE INDEX uq_member_rank_author ON balancer.member_rank (workspace_id, author_user_id, workspace_member_id, role) WHERE author_user_id IS NOT NULL;

CREATE INDEX ix_balancer_member_rank_author_user_id ON balancer.member_rank (author_user_id);

CREATE INDEX ix_balancer_member_rank_workspace_member_id ON balancer.member_rank (workspace_member_id);

CREATE UNIQUE INDEX uq_member_rank_canon ON balancer.member_rank (workspace_id, workspace_member_id, role) WHERE author_user_id IS NULL;

CREATE TABLE balancer.registration (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	tournament_id BIGINT NOT NULL, 
	workspace_member_id BIGINT, 
	display_name VARCHAR(255), 
	battle_tag VARCHAR(255), 
	battle_tag_normalized VARCHAR(255), 
	smurf_tags_json JSON, 
	discord_nick VARCHAR(255), 
	twitch_nick VARCHAR(255), 
	boosty_nick VARCHAR(255), 
	stream_pov BOOLEAN DEFAULT 'false' NOT NULL, 
	notes TEXT, 
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
	PRIMARY KEY (id), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL, 
	FOREIGN KEY(checked_in_by) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(reviewed_by) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(deleted_by) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(registration_team_id) REFERENCES balancer.registration_team (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX uq_balancer_registration_user ON balancer.registration (tournament_id, workspace_member_id) WHERE deleted_at IS NULL;

CREATE INDEX ix_balancer_registration_tournament_balancer_status ON balancer.registration (tournament_id, status, balancer_status) WHERE deleted_at IS NULL;

CREATE INDEX ix_balancer_registration_tournament_id ON balancer.registration (tournament_id);

CREATE UNIQUE INDEX uq_balancer_registration_tournament_tag_active ON balancer.registration (tournament_id, battle_tag_normalized) WHERE battle_tag_normalized IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX ix_balancer_registration_workspace_member_id ON balancer.registration (workspace_member_id);

CREATE INDEX ix_balancer_registration_registration_team_id ON balancer.registration (registration_team_id);

CREATE TABLE balancer.registration_form (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	tournament_id BIGINT NOT NULL, 
	workspace_id BIGINT NOT NULL, 
	is_open BOOLEAN DEFAULT 'false' NOT NULL, 
	auto_approve BOOLEAN DEFAULT 'false' NOT NULL, 
	built_in_fields_json JSON DEFAULT '{}' NOT NULL, 
	custom_fields_json JSON DEFAULT '[]' NOT NULL, 
	require_open_profile BOOLEAN DEFAULT 'false' NOT NULL, 
	open_profile_scope VARCHAR(8) DEFAULT 'main' NOT NULL, 
	show_ranks BOOLEAN DEFAULT 'false' NOT NULL, 
	max_substitutes INTEGER DEFAULT '0' NOT NULL, 
	require_subscription BOOLEAN DEFAULT 'false' NOT NULL, 
	subscription_stage VARCHAR(16) DEFAULT 'check_in' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_balancer_registration_form_tournament UNIQUE (tournament_id), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_registration_form_workspace_id ON balancer.registration_form (workspace_id);

CREATE INDEX ix_balancer_registration_form_tournament_id ON balancer.registration_form (tournament_id);

CREATE TABLE balancer.registration_google_sheet_binding (
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
	CONSTRAINT uq_balancer_registration_google_sheet_binding_key UNIQUE (feed_id, source_record_key), 
	CONSTRAINT uq_balancer_registration_google_sheet_binding_registration UNIQUE (registration_id), 
	FOREIGN KEY(feed_id) REFERENCES balancer.registration_google_sheet_feed (id) ON DELETE CASCADE, 
	FOREIGN KEY(registration_id) REFERENCES balancer.registration (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_registration_google_sheet_binding_feed_id ON balancer.registration_google_sheet_binding (feed_id);

CREATE INDEX ix_balancer_registration_google_sheet_binding_registration_id ON balancer.registration_google_sheet_binding (registration_id);

CREATE TABLE balancer.registration_google_sheet_feed (
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
	CONSTRAINT uq_balancer_registration_google_sheet_feed_tournament UNIQUE (tournament_id), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_registration_google_sheet_feed_tournament_id ON balancer.registration_google_sheet_feed (tournament_id);

CREATE TABLE balancer.registration_role (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	registration_id BIGINT NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	subrole VARCHAR(128), 
	is_primary BOOLEAN DEFAULT 'false' NOT NULL, 
	priority INTEGER DEFAULT '0' NOT NULL, 
	rank_value INTEGER, 
	is_active BOOLEAN DEFAULT 'true' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_balancer_registration_role UNIQUE (registration_id, role), 
	FOREIGN KEY(registration_id) REFERENCES balancer.registration (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_registration_role_registration_id ON balancer.registration_role (registration_id);

CREATE TABLE balancer.registration_role_hero (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	role_id BIGINT NOT NULL, 
	hero_id BIGINT NOT NULL, 
	priority INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_reg_role_hero_role_priority UNIQUE (role_id, priority), 
	CONSTRAINT uq_reg_role_hero_role_hero UNIQUE (role_id, hero_id), 
	FOREIGN KEY(role_id) REFERENCES balancer.registration_role (id) ON DELETE CASCADE, 
	FOREIGN KEY(hero_id) REFERENCES overwatch.hero (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_registration_role_hero_role_id ON balancer.registration_role_hero (role_id);

CREATE TABLE balancer.registration_status (
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
	CONSTRAINT uq_balancer_registration_status_workspace_scope_slug UNIQUE (workspace_id, scope, slug, kind), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_registration_status_workspace_scope ON balancer.registration_status (workspace_id, scope);

CREATE INDEX ix_balancer_registration_status_workspace_id ON balancer.registration_status (workspace_id);

CREATE TABLE balancer.registration_team (
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
	PRIMARY KEY (id), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE, 
	FOREIGN KEY(exported_team_id) REFERENCES tournament.team (id) ON DELETE SET NULL, 
	FOREIGN KEY(deleted_by) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(invite_cap_reset_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_registration_team_tournament_status ON balancer.registration_team (tournament_id, status) WHERE deleted_at IS NULL;

CREATE INDEX ix_balancer_registration_team_captain_registration_id ON balancer.registration_team (captain_registration_id);

CREATE INDEX ix_balancer_registration_team_exported_team_id ON balancer.registration_team (exported_team_id);

CREATE INDEX ix_balancer_registration_team_workspace_id ON balancer.registration_team (workspace_id);

CREATE UNIQUE INDEX uq_balancer_registration_team_name_active ON balancer.registration_team (tournament_id, name_normalized) WHERE deleted_at IS NULL;

CREATE INDEX ix_balancer_registration_team_tournament_id ON balancer.registration_team (tournament_id);

CREATE TABLE balancer.registration_team_invite (
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
	FOREIGN KEY(team_id) REFERENCES balancer.registration_team (id) ON DELETE CASCADE, 
	FOREIGN KEY(target_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(invited_by) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(revoked_by) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(accepted_registration_id) REFERENCES balancer.registration (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX uq_balancer_registration_team_invite_token ON balancer.registration_team_invite (token_sha256) WHERE token_sha256 IS NOT NULL;

CREATE INDEX ix_balancer_registration_team_invite_target_auth_user_id ON balancer.registration_team_invite (target_auth_user_id);

CREATE INDEX ix_balancer_registration_team_invite_team_id ON balancer.registration_team_invite (team_id);

CREATE INDEX ix_balancer_registration_team_invite_team_state ON balancer.registration_team_invite (team_id, state);

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

CREATE INDEX ix_balancer_team_variant_id ON balancer.team (variant_id);

CREATE INDEX ix_balancer_team_exported_team_id ON balancer.team (exported_team_id);

CREATE TABLE balancer.team_slot (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	team_id BIGINT NOT NULL, 
	battle_tag_normalized VARCHAR(255), 
	role VARCHAR(16) NOT NULL, 
	assigned_rank INTEGER NOT NULL, 
	discomfort INTEGER DEFAULT '0' NOT NULL, 
	is_captain BOOLEAN DEFAULT 'false' NOT NULL, 
	sort_order INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(team_id) REFERENCES balancer.team (id) ON DELETE CASCADE
);

CREATE INDEX ix_balancer_team_slot_battle_tag_normalized ON balancer.team_slot (battle_tag_normalized);

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

CREATE TABLE balancer.workspace_config (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	workspace_id BIGINT NOT NULL, 
	config_json JSON DEFAULT '{}' NOT NULL, 
	updated_by BIGINT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_balancer_workspace_config_workspace UNIQUE (workspace_id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE, 
	FOREIGN KEY(updated_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_balancer_workspace_config_workspace_id ON balancer.workspace_config (workspace_id);

CREATE TABLE casual.match (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	custom_game_id BIGINT NOT NULL, 
	map_id BIGINT, 
	recorded_by BIGINT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(custom_game_id) REFERENCES balancer.custom_game (id) ON DELETE CASCADE, 
	FOREIGN KEY(map_id) REFERENCES overwatch.map (id) ON DELETE SET NULL, 
	FOREIGN KEY(recorded_by) REFERENCES auth."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_casual_match_custom_game_id ON casual.match (custom_game_id);

CREATE INDEX ix_casual_match_map_id ON casual.match (map_id);

CREATE TABLE casual.player (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	team_id BIGINT NOT NULL, 
	workspace_member_id BIGINT, 
	display_name_snapshot VARCHAR(255) NOT NULL, 
	role heroclass, 
	rank INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(team_id) REFERENCES casual.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_member_id) REFERENCES workspace_member (id) ON DELETE SET NULL
);

CREATE INDEX ix_casual_player_team_id ON casual.player (team_id);

CREATE INDEX ix_casual_player_workspace_member_id ON casual.player (workspace_member_id);

CREATE TABLE casual.team (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	match_id BIGINT NOT NULL, 
	side VARCHAR(8) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	score INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_casual_team_match_side UNIQUE (match_id, side), 
	CONSTRAINT ck_casual_team_side CHECK (side IN ('home', 'away')), 
	CONSTRAINT ck_casual_team_score CHECK (score >= 0), 
	FOREIGN KEY(match_id) REFERENCES casual.match (id) ON DELETE CASCADE
);

CREATE INDEX ix_casual_team_match_id ON casual.team (match_id);

CREATE TABLE log_processing.discord_channel (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	tournament_id BIGINT NOT NULL, 
	channel_id BIGINT NOT NULL, 
	channel_name VARCHAR(100), 
	is_active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tournament_id), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_log_processing_discord_channel_channel_id ON log_processing.discord_channel (channel_id);

CREATE TABLE log_processing.record (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	tournament_id BIGINT NOT NULL, 
	filename VARCHAR(500) NOT NULL, 
	status log_processing_status NOT NULL, 
	source log_processing_source NOT NULL, 
	uploader_id BIGINT, 
	attached_encounter_id BIGINT, 
	error_message TEXT, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	content_hash VARCHAR(64), 
	attempts INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE, 
	FOREIGN KEY(uploader_id) REFERENCES players."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(attached_encounter_id) REFERENCES tournament.encounter (id) ON DELETE SET NULL
);

CREATE INDEX ix_log_processing_record_tournament_id ON log_processing.record (tournament_id);

CREATE INDEX ix_log_processing_record_uploader_id ON log_processing.record (uploader_id);

CREATE INDEX ix_log_processing_record_content_hash ON log_processing.record (content_hash);

CREATE INDEX ix_log_processing_record_status_created ON log_processing.record (status, created_at);

CREATE INDEX ix_log_processing_record_attached_encounter_id ON log_processing.record (attached_encounter_id);

CREATE TABLE matches.event (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	match_id BIGINT NOT NULL, 
	time FLOAT NOT NULL, 
	round INTEGER NOT NULL, 
	team_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	hero_id BIGINT, 
	related_team_id BIGINT, 
	related_user_id BIGINT, 
	related_hero_id BIGINT, 
	name matchevent NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(match_id) REFERENCES matches.match (id) ON DELETE CASCADE, 
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES players."user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(hero_id) REFERENCES overwatch.hero (id) ON DELETE CASCADE, 
	FOREIGN KEY(related_team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(related_user_id) REFERENCES players."user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(related_hero_id) REFERENCES overwatch.hero (id) ON DELETE CASCADE
);

CREATE INDEX ix_matches_event_match_id ON matches.event (match_id);

CREATE INDEX ix_matches_assists_related_team_id ON matches.event (related_team_id);

CREATE INDEX ix_matches_event_user_id ON matches.event (user_id);

CREATE INDEX ix_matches_assists_related_hero_id ON matches.event (related_hero_id);

CREATE INDEX ix_matches_event_team_id ON matches.event (team_id);

CREATE INDEX ix_matches_assists_hero_id ON matches.event (hero_id);

CREATE INDEX ix_matches_assists_related_user_id ON matches.event (related_user_id);

CREATE TABLE matches.kill_feed (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	match_id BIGINT NOT NULL, 
	time FLOAT NOT NULL, 
	round INTEGER NOT NULL, 
	fight INTEGER NOT NULL, 
	ability abilityevent, 
	killer_id BIGINT NOT NULL, 
	killer_hero_id BIGINT NOT NULL, 
	killer_team_id BIGINT NOT NULL, 
	victim_id BIGINT NOT NULL, 
	victim_team_id BIGINT NOT NULL, 
	victim_hero_id BIGINT NOT NULL, 
	damage FLOAT NOT NULL, 
	is_critical_hit BOOLEAN NOT NULL, 
	is_environmental BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(match_id) REFERENCES matches.match (id) ON DELETE CASCADE, 
	FOREIGN KEY(killer_id) REFERENCES players."user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(killer_hero_id) REFERENCES overwatch.hero (id) ON DELETE CASCADE, 
	FOREIGN KEY(killer_team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(victim_id) REFERENCES players."user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(victim_team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(victim_hero_id) REFERENCES overwatch.hero (id) ON DELETE CASCADE
);

CREATE INDEX ix_matches_kill_feed_victim_hero_id ON matches.kill_feed (victim_hero_id);

CREATE INDEX ix_matches_kill_feed_match_id ON matches.kill_feed (match_id);

CREATE INDEX ix_matches_kill_feed_killer_hero_id ON matches.kill_feed (killer_hero_id);

CREATE INDEX ix_matches_kill_feed_victim_team_id ON matches.kill_feed (victim_team_id);

CREATE INDEX ix_matches_kill_feed_victim_id ON matches.kill_feed (victim_id);

CREATE INDEX ix_matches_kill_feed_killer_team_id ON matches.kill_feed (killer_team_id);

CREATE INDEX ix_matches_kill_feed_killer_id ON matches.kill_feed (killer_id);

CREATE TABLE matches.match (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	home_team_id BIGINT NOT NULL, 
	away_team_id BIGINT NOT NULL, 
	home_score INTEGER NOT NULL, 
	away_score INTEGER NOT NULL, 
	time FLOAT, 
	log_name VARCHAR, 
	code VARCHAR, 
	log_record_id BIGINT, 
	source matches.matchsource DEFAULT 'log_parser' NOT NULL, 
	encounter_id BIGINT NOT NULL, 
	map_id BIGINT NOT NULL, 
	map_index INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(home_team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(away_team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(log_record_id) REFERENCES log_processing.record (id) ON DELETE SET NULL, 
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
	FOREIGN KEY(map_id) REFERENCES overwatch.map (id) ON DELETE CASCADE
);

CREATE INDEX ix_matches_match_log_record_id ON matches.match (log_record_id);

CREATE INDEX ix_matches_match_encounter_id ON matches.match (encounter_id);

CREATE INDEX ix_matches_match_away_team_id ON matches.match (away_team_id);

CREATE INDEX ix_matches_match_home_team_id ON matches.match (home_team_id);

CREATE INDEX ix_matches_match_map_id ON matches.match (map_id);

CREATE TABLE matches.stat_baselines (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	formula_version VARCHAR(64) NOT NULL, 
	role heroclass NOT NULL, 
	rank_bucket SMALLINT DEFAULT '-1' NOT NULL, 
	stat logstatsname NOT NULL, 
	mean FLOAT NOT NULL, 
	std FLOAT NOT NULL, 
	meta JSONB, 
	computed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_stat_baselines_key UNIQUE (formula_version, role, rank_bucket, stat)
);

CREATE INDEX ix_stat_baselines_version ON matches.stat_baselines (formula_version);

CREATE TABLE matches.statistics (
	id BIGSERIAL NOT NULL, 
	match_id BIGINT NOT NULL, 
	round INTEGER NOT NULL, 
	team_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	hero_id BIGINT, 
	name logstatsname NOT NULL, 
	value FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(match_id) REFERENCES matches.match (id) ON DELETE CASCADE, 
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES players."user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(hero_id) REFERENCES overwatch.hero (id) ON DELETE CASCADE
);

CREATE INDEX ix_matches_statistics_team_id ON matches.statistics (team_id);

CREATE INDEX ix_match_statistics_user_round_name ON matches.statistics (user_id, round, name);

CREATE INDEX ix_match_statistics_user_name_r0 ON matches.statistics (user_id, name) WHERE round = 0 AND hero_id IS NULL;

CREATE INDEX ix_match_statistics_playtime_r0 ON matches.statistics (match_id, user_id, hero_id) WHERE round = 0 AND name = 'HeroTimePlayed';

CREATE INDEX ix_match_statistics_match_name_round ON matches.statistics (match_id, name, round);

CREATE INDEX ix_match_statistics_match_user_round ON matches.statistics (match_id, user_id, round);

CREATE INDEX ix_match_statistics_user_hero_r0 ON matches.statistics (user_id, hero_id, name) WHERE round = 0 AND hero_id IS NOT NULL;

CREATE TABLE overwatch.catalog_alias_miss (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	entity_type catalogentitytype NOT NULL, 
	raw_name VARCHAR(128) NOT NULL, 
	occurrences INTEGER DEFAULT '1' NOT NULL, 
	first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	last_log_record_id BIGINT, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_catalog_alias_miss_entity_raw UNIQUE (entity_type, raw_name), 
	FOREIGN KEY(last_log_record_id) REFERENCES log_processing.record (id) ON DELETE SET NULL
);

CREATE TABLE overwatch.gamemode (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	slug VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	image_path VARCHAR NOT NULL, 
	description VARCHAR, 
	aliases JSONB DEFAULT '[]'::jsonb NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slug), 
	UNIQUE (name)
);

CREATE TABLE overwatch.hero (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	slug VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	image_path VARCHAR NOT NULL, 
	type heroclass NOT NULL, 
	color VARCHAR DEFAULT '#ffffff' NOT NULL, 
	aliases JSONB DEFAULT '[]'::jsonb NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slug), 
	UNIQUE (name)
);

CREATE TABLE overwatch.map (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	gamemode_id BIGINT NOT NULL, 
	name VARCHAR NOT NULL, 
	image_path VARCHAR NOT NULL, 
	in_competitive BOOLEAN DEFAULT true NOT NULL, 
	aliases JSONB DEFAULT '[]'::jsonb NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(gamemode_id) REFERENCES overwatch.gamemode (id), 
	UNIQUE (name)
);

CREATE TABLE overwatch_rank.battle_tag_state (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	social_account_id BIGINT NOT NULL, 
	battle_tag VARCHAR(255) NOT NULL, 
	player_id_slug VARCHAR(255) NOT NULL, 
	last_checked_at TIMESTAMP WITH TIME ZONE, 
	last_success_at TIMESTAMP WITH TIME ZONE, 
	last_snapshot_id BIGINT, 
	status VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	consecutive_failures INTEGER DEFAULT '0' NOT NULL, 
	next_eligible_at TIMESTAMP WITH TIME ZONE, 
	last_error TEXT, 
	priority_tier SMALLINT DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (social_account_id), 
	FOREIGN KEY(social_account_id) REFERENCES players.social_account (id) ON DELETE CASCADE, 
	FOREIGN KEY(last_snapshot_id) REFERENCES overwatch_rank.rank_snapshot (id) ON DELETE SET NULL
);

CREATE INDEX ix_battle_tag_state_due ON overwatch_rank.battle_tag_state (status, next_eligible_at, last_checked_at);

CREATE INDEX ix_battle_tag_state_priority ON overwatch_rank.battle_tag_state (priority_tier, last_checked_at);

CREATE TABLE overwatch_rank.fetch_log (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	social_account_id BIGINT, 
	battle_tag VARCHAR(255) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	error TEXT, 
	snapshots_written INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(social_account_id) REFERENCES players.social_account (id) ON DELETE SET NULL
);

CREATE INDEX ix_fetch_log_created_at ON overwatch_rank.fetch_log (created_at);

CREATE INDEX ix_fetch_log_status_created ON overwatch_rank.fetch_log (status, created_at);

CREATE TABLE overwatch_rank.rank_snapshot (
	id BIGSERIAL NOT NULL, 
	user_id BIGINT NOT NULL, 
	social_account_id BIGINT NOT NULL, 
	battle_tag VARCHAR(255) NOT NULL, 
	platform VARCHAR(16) NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	division VARCHAR(32), 
	tier SMALLINT, 
	season INTEGER, 
	rank_value INTEGER, 
	mapping_version VARCHAR(64), 
	is_ranked BOOLEAN DEFAULT 'true' NOT NULL, 
	captured_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	source VARCHAR(32) DEFAULT 'scheduled' NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES players."user" (id) ON DELETE CASCADE, 
	FOREIGN KEY(social_account_id) REFERENCES players.social_account (id) ON DELETE CASCADE
);

CREATE INDEX ix_rank_snapshot_latest_ranked ON overwatch_rank.rank_snapshot (social_account_id, role, captured_at DESC) WHERE rank_value IS NOT NULL AND is_ranked IS TRUE;

CREATE INDEX ix_overwatch_rank_rank_snapshot_captured_at ON overwatch_rank.rank_snapshot (captured_at);

CREATE INDEX ix_rank_snapshot_user_captured ON overwatch_rank.rank_snapshot (user_id, captured_at);

CREATE INDEX ix_rank_snapshot_series_captured ON overwatch_rank.rank_snapshot (social_account_id, role, platform, captured_at);

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

CREATE INDEX ix_players_favorite_player_auth_user_id ON players.favorite_player (auth_user_id);

CREATE INDEX ix_favorite_player_auth_user ON players.favorite_player (auth_user_id);

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
	provider_user_id VARCHAR(255), 
	is_verified BOOLEAN DEFAULT 'false' NOT NULL, 
	is_primary BOOLEAN DEFAULT 'false' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_social_account_user_provider_handle UNIQUE (user_id, provider, username_normalized), 
	FOREIGN KEY(user_id) REFERENCES players."user" (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_social_account_provider_subject ON players.social_account (provider, provider_user_id) WHERE provider_user_id IS NOT NULL;

CREATE INDEX ix_social_account_provider_user_id ON players.social_account (provider_user_id);

CREATE UNIQUE INDEX uq_social_account_user_provider_handle_nullnorm ON players.social_account (user_id, provider, lower(btrim(username))) WHERE username_normalized IS NULL;

CREATE INDEX ix_social_account_provider ON players.social_account (provider);

CREATE INDEX ix_social_account_username_normalized ON players.social_account (username_normalized);

CREATE INDEX ix_social_account_user_id ON players.social_account (user_id);

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

CREATE INDEX ix_social_account_visibility_workspace_id ON players.social_account_visibility (workspace_id);

CREATE UNIQUE INDEX uq_social_visibility_workspace ON players.social_account_visibility (account_id, workspace_id) WHERE workspace_id IS NOT NULL;

CREATE INDEX ix_social_account_visibility_account_id ON players.social_account_visibility (account_id);

CREATE UNIQUE INDEX uq_social_visibility_global ON players.social_account_visibility (account_id) WHERE workspace_id IS NULL;

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

CREATE INDEX ix_audit_log_workspace_created ON audit_log (workspace_id, created_at);

CREATE INDEX ix_audit_log_entity_created ON audit_log (entity_type, entity_id, created_at);

CREATE INDEX ix_audit_log_actor_created ON audit_log (actor_auth_user_id, created_at);

CREATE TABLE division_grid (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	workspace_id BIGINT, 
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
	FOREIGN KEY(source_workspace_id) REFERENCES workspace (id) ON DELETE SET NULL, 
	FOREIGN KEY(source_grid_id) REFERENCES division_grid (id) ON DELETE SET NULL
);

CREATE INDEX ix_division_grid_source_grid_id ON division_grid (source_grid_id);

CREATE INDEX ix_division_grid_source_key ON division_grid (source_key);

CREATE INDEX ix_division_grid_source_fingerprint ON division_grid (source_fingerprint);

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

CREATE INDEX ix_division_grid_mapping_rule_source_tier_id ON division_grid_mapping_rule (source_tier_id);

CREATE INDEX ix_division_grid_mapping_rule_target_tier_id ON division_grid_mapping_rule (target_tier_id);

CREATE INDEX ix_division_grid_mapping_rule_mapping_id ON division_grid_mapping_rule (mapping_id);

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
	ow_rank_min BIGINT, 
	ow_rank_max BIGINT, 
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

CREATE INDEX ix_notification_recipient_published ON notification (recipient_auth_user_id, published_at DESC);

CREATE INDEX ix_notification_audience_published ON notification (audience, published_at DESC) WHERE audience <> 'user';

CREATE INDEX ix_notification_source_workspace_published ON notification (source_workspace_id, published_at DESC) WHERE source_workspace_id IS NOT NULL;

CREATE TABLE notification_read (
	auth_user_id BIGINT NOT NULL, 
	notification_id BIGINT NOT NULL, 
	read_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (auth_user_id, notification_id)
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
	default_division_grid_version_id BIGINT, 
	default_roster_slots_json JSONB, 
	newcomer_scope VARCHAR(16) DEFAULT 'global' NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (discord_guild_id), 
	FOREIGN KEY(discord_guild_verified_by_auth_user_id) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(owner_id) REFERENCES auth."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(default_division_grid_version_id) REFERENCES division_grid_version (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_workspace_custom_domain ON workspace (custom_domain);

CREATE INDEX ix_workspace_owner_id ON workspace (owner_id);

CREATE UNIQUE INDEX ix_workspace_subdomain ON workspace (subdomain);

CREATE UNIQUE INDEX ix_workspace_slug ON workspace (slug);

CREATE INDEX ix_workspace_default_division_grid_version_id ON workspace (default_division_grid_version_id);

CREATE TABLE workspace_member (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	workspace_id BIGINT NOT NULL, 
	player_id BIGINT NOT NULL, 
	display_name VARCHAR(255), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workspace_member_workspace_player UNIQUE (workspace_id, player_id), 
	CONSTRAINT uq_workspace_member_id_workspace UNIQUE (id, workspace_id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE, 
	FOREIGN KEY(player_id) REFERENCES players."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_workspace_member_workspace_id ON workspace_member (workspace_id);

CREATE INDEX ix_workspace_member_player_id ON workspace_member (player_id);

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

CREATE INDEX ix_realtime_workspace_event_topic_id ON realtime.workspace_event (topic, id);

CREATE INDEX ix_realtime_workspace_event_workspace_id ON realtime.workspace_event (workspace_id);

CREATE INDEX ix_realtime_workspace_event_occurred_at ON realtime.workspace_event (occurred_at);

CREATE INDEX ix_realtime_workspace_event_tournament_id ON realtime.workspace_event (tournament_id);

CREATE INDEX ix_realtime_workspace_event_actor_user_id ON realtime.workspace_event (actor_user_id);

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

CREATE INDEX ix_subscription_check_log_user_created ON subscriptions.check_log (auth_user_id, created_at);

CREATE INDEX ix_subscription_check_log_created_at ON subscriptions.check_log (created_at);

CREATE INDEX ix_subscriptions_check_log_workspace_id ON subscriptions.check_log (workspace_id);

CREATE INDEX ix_subscription_check_log_state_created ON subscriptions.check_log (state, created_at);

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

CREATE INDEX ix_subscriptions_entitlement_workspace_id ON subscriptions.entitlement (workspace_id);

CREATE INDEX ix_subscription_entitlement_workspace_provider ON subscriptions.entitlement (workspace_id, provider);

CREATE INDEX ix_subscriptions_entitlement_auth_user_id ON subscriptions.entitlement (auth_user_id);

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
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE
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

CREATE INDEX ix_challonge_source_tournament ON tournament.challonge_source (tournament_id);

CREATE INDEX ix_challonge_source_stage_item ON tournament.challonge_source (stage_item_id);

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

CREATE INDEX ix_tournament_challonge_sync_log_source_id ON tournament.challonge_sync_log (source_id);

CREATE INDEX ix_tournament_challonge_sync_log_tournament_id ON tournament.challonge_sync_log (tournament_id);

CREATE INDEX ix_challonge_sync_log_tournament_created ON tournament.challonge_sync_log (tournament_id, created_at DESC);

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

CREATE UNIQUE INDEX uq_tournament_computation_job_active_key ON tournament.computation_job (idempotency_key) WHERE status IN ('pending', 'running');

CREATE INDEX ix_tournament_computation_job_status ON tournament.computation_job (status);

CREATE INDEX ix_tournament_computation_job_tournament_id ON tournament.computation_job (tournament_id);

CREATE INDEX ix_tournament_computation_job_tournament_kind ON tournament.computation_job (tournament_id, kind);

CREATE INDEX ix_tournament_computation_job_stage_item_id ON tournament.computation_job (stage_item_id);

CREATE INDEX ix_tournament_computation_job_requested_by_user_id ON tournament.computation_job (requested_by_user_id);

CREATE INDEX ix_tournament_computation_job_stage_id ON tournament.computation_job (stage_id);

CREATE TABLE tournament.encounter (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	name VARCHAR NOT NULL, 
	home_team_id BIGINT, 
	away_team_id BIGINT, 
	home_score INTEGER NOT NULL, 
	away_score INTEGER NOT NULL, 
	round INTEGER NOT NULL, 
	closeness FLOAT, 
	best_of INTEGER DEFAULT '3' NOT NULL, 
	scheduled_at TIMESTAMP WITH TIME ZONE, 
	started_at TIMESTAMP WITH TIME ZONE, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	current_map_index INTEGER, 
	tournament_id BIGINT NOT NULL, 
	stage_id BIGINT, 
	stage_item_id BIGINT, 
	status tournament.encounterstatus NOT NULL, 
	result_status tournament.encounterresultstatus DEFAULT 'none' NOT NULL, 
	confirmed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(home_team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(away_team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE, 
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE SET NULL, 
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_encounter_home_team_id ON tournament.encounter (home_team_id);

CREATE INDEX ix_encounter_tournament_status ON tournament.encounter (tournament_id, status);

CREATE INDEX ix_tournament_encounter_stage_id ON tournament.encounter (stage_id);

CREATE INDEX ix_tournament_encounter_away_team_id ON tournament.encounter (away_team_id);

CREATE INDEX ix_tournament_encounter_round ON tournament.encounter (round);

CREATE INDEX ix_encounter_status_live_upcoming ON tournament.encounter (tournament_id, status) WHERE status IN ('PENDING'::tournament.encounterstatus, 'OPEN'::tournament.encounterstatus);

CREATE INDEX ix_tournament_encounter_tournament_id ON tournament.encounter (tournament_id);

CREATE INDEX ix_tournament_encounter_stage_item_id ON tournament.encounter (stage_item_id);

CREATE TABLE tournament.encounter_captain_report (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	encounter_id BIGINT NOT NULL, 
	team_id BIGINT NOT NULL, 
	reporter_user_id BIGINT, 
	home_score INTEGER NOT NULL, 
	away_score INTEGER NOT NULL, 
	closeness INTEGER, 
	comment TEXT, 
	custom_fields_json JSON DEFAULT '{}' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_encounter_captain_report_encounter_team UNIQUE (encounter_id, team_id), 
	CONSTRAINT ck_encounter_captain_report_closeness CHECK (closeness BETWEEN 1 AND 10), 
	CONSTRAINT ck_encounter_captain_report_scores CHECK (home_score >= 0 AND away_score >= 0), 
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(reporter_user_id) REFERENCES players."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_encounter_captain_report_team_id ON tournament.encounter_captain_report (team_id);

CREATE INDEX ix_tournament_encounter_captain_report_encounter_id ON tournament.encounter_captain_report (encounter_id);

CREATE TABLE tournament.encounter_link (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	source_encounter_id INTEGER NOT NULL, 
	target_encounter_id INTEGER NOT NULL, 
	role tournament.encounterlinkrole NOT NULL, 
	target_slot tournament.encounterlinkslot NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_encounter_link_source_role UNIQUE (source_encounter_id, role), 
	FOREIGN KEY(source_encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
	FOREIGN KEY(target_encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_encounter_link_target_encounter_id ON tournament.encounter_link (target_encounter_id);

CREATE INDEX ix_tournament_encounter_link_source_encounter_id ON tournament.encounter_link (source_encounter_id);

CREATE TABLE tournament.encounter_map_code (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	report_id BIGINT NOT NULL, 
	map_index INTEGER NOT NULL, 
	map_id BIGINT, 
	code VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_encounter_map_code_report_index UNIQUE (report_id, map_index), 
	CONSTRAINT ck_encounter_map_code_index CHECK (map_index >= 1), 
	FOREIGN KEY(report_id) REFERENCES tournament.encounter_captain_report (id) ON DELETE CASCADE, 
	FOREIGN KEY(map_id) REFERENCES overwatch.map (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_encounter_map_code_report_id ON tournament.encounter_map_code (report_id);

CREATE INDEX ix_tournament_encounter_map_code_map_id ON tournament.encounter_map_code (map_id);

CREATE TABLE tournament.encounter_map_report (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	encounter_id BIGINT NOT NULL, 
	map_id BIGINT NOT NULL, 
	map_index INTEGER DEFAULT '0' NOT NULL, 
	team_id BIGINT NOT NULL, 
	reporter_user_id BIGINT, 
	home_score INTEGER NOT NULL, 
	away_score INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_encounter_map_report_encounter_map_index_team UNIQUE (encounter_id, map_id, map_index, team_id), 
	CONSTRAINT ck_encounter_map_report_scores CHECK (home_score >= 0 AND away_score >= 0), 
	CONSTRAINT ck_encounter_map_report_index CHECK (map_index >= 0), 
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
	FOREIGN KEY(map_id) REFERENCES overwatch.map (id) ON DELETE CASCADE, 
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(reporter_user_id) REFERENCES players."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_encounter_map_report_team_id ON tournament.encounter_map_report (team_id);

CREATE INDEX ix_tournament_encounter_map_report_map_id ON tournament.encounter_map_report (map_id);

CREATE INDEX ix_tournament_encounter_map_report_encounter_id ON tournament.encounter_map_report (encounter_id);

CREATE TABLE tournament.encounter_pick_ban_ledger (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	encounter_id BIGINT NOT NULL, 
	kind tournament.pickbankind NOT NULL, 
	item_id INTEGER NOT NULL, 
	banned_by_side tournament.pickbanside NOT NULL, 
	round INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_encounter_pick_ban_ledger_entry UNIQUE (encounter_id, kind, item_id, banned_by_side), 
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_encounter_pick_ban_ledger_encounter_id ON tournament.encounter_pick_ban_ledger (encounter_id);

CREATE INDEX ix_tournament_encounter_pick_ban_ledger_item_id ON tournament.encounter_pick_ban_ledger (item_id);

CREATE TABLE tournament.encounter_readiness (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	encounter_id BIGINT NOT NULL, 
	side VARCHAR(16) NOT NULL, 
	ready_user_id BIGINT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_encounter_readiness_encounter_side UNIQUE (encounter_id, side), 
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
	FOREIGN KEY(ready_user_id) REFERENCES players."user" (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_encounter_readiness_encounter_id ON tournament.encounter_readiness (encounter_id);

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

CREATE TABLE tournament.encounter_result_audit (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	encounter_id BIGINT NOT NULL, 
	actor_user_id BIGINT, 
	action tournament.encounterresultauditaction NOT NULL, 
	from_result_status tournament.encounterresultstatus, 
	to_result_status tournament.encounterresultstatus NOT NULL, 
	home_score_before INTEGER, 
	away_score_before INTEGER, 
	home_score_after INTEGER NOT NULL, 
	away_score_after INTEGER NOT NULL, 
	adopted_team_id BIGINT, 
	source VARCHAR(16) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
	FOREIGN KEY(actor_user_id) REFERENCES players."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(adopted_team_id) REFERENCES tournament.team (id) ON DELETE SET NULL
);

CREATE INDEX ix_encounter_result_audit_encounter_created ON tournament.encounter_result_audit (encounter_id, created_at);

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

CREATE INDEX ix_tournament_encounter_saved_view_auth_user_id ON tournament.encounter_saved_view (auth_user_id);

CREATE INDEX ix_tournament_encounter_saved_view_workspace_id ON tournament.encounter_saved_view (workspace_id);

CREATE INDEX ix_encounter_saved_view_workspace_user ON tournament.encounter_saved_view (workspace_id, auth_user_id);

CREATE TABLE tournament.pick_ban_config (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	tournament_id BIGINT NOT NULL, 
	kind tournament.pickbankind NOT NULL, 
	stage_id BIGINT, 
	round INTEGER, 
	mode tournament.pickbanmode DEFAULT 'pool' NOT NULL, 
	first_pick_rule tournament.pickbanfirstpickrule DEFAULT 'higher_seed' NOT NULL, 
	first_ban_rotation tournament.pickbanrotation DEFAULT 'fixed' NOT NULL, 
	turn_timer_seconds INTEGER, 
	preset VARCHAR(32), 
	sequence_json JSON NOT NULL, 
	no_repeat_scope tournament.pickbannorepeatscope DEFAULT 'none' NOT NULL, 
	unique_attribute_per_side_per_round VARCHAR(32), 
	allow_protect BOOLEAN DEFAULT 'false' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_pick_ban_config_round_requires_stage CHECK (round IS NULL OR stage_id IS NOT NULL), 
	CONSTRAINT ck_pick_ban_config_slots_not_custom CHECK (NOT (mode = 'slots' AND preset = 'custom')), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE, 
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_pick_ban_config_level ON tournament.pick_ban_config (tournament_id, kind, stage_id, round) NULLS NOT DISTINCT;

CREATE INDEX ix_tournament_pick_ban_config_tournament_id ON tournament.pick_ban_config (tournament_id);

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

CREATE TABLE tournament.pick_ban_entry (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	session_id BIGINT NOT NULL, 
	item_id INTEGER NOT NULL, 
	"order" INTEGER NOT NULL, 
	action_index INTEGER, 
	round INTEGER, 
	picked_by tournament.pickbanside, 
	status tournament.pickbanentrystatus DEFAULT 'available' NOT NULL, 
	team_id BIGINT, 
	protected_by tournament.pickbanside, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES tournament.pick_ban_session (id) ON DELETE CASCADE, 
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_pick_ban_entry_team_id ON tournament.pick_ban_entry (team_id);

CREATE UNIQUE INDEX uq_pick_ban_entry_session_action_index ON tournament.pick_ban_entry (session_id, action_index) WHERE action_index IS NOT NULL;

CREATE INDEX ix_tournament_pick_ban_entry_item_id ON tournament.pick_ban_entry (item_id);

CREATE INDEX ix_tournament_pick_ban_entry_session_id ON tournament.pick_ban_entry (session_id);

CREATE TABLE tournament.pick_ban_session (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	encounter_id BIGINT NOT NULL, 
	kind tournament.pickbankind NOT NULL, 
	config_id BIGINT, 
	first_side tournament.pickbanside, 
	seed_source tournament.pickbanseedsource NOT NULL, 
	home_seed INTEGER, 
	away_seed INTEGER, 
	resolved_sequence_json JSON NOT NULL, 
	slot_reserves_json JSON, 
	turn_timer_seconds INTEGER, 
	status tournament.pickbansessionstatus DEFAULT 'active' NOT NULL, 
	awaiting_choice BOOLEAN DEFAULT 'false' NOT NULL, 
	pending_loser_side tournament.pickbanside, 
	undo_requested_by tournament.pickbanside, 
	undo_target_index INTEGER, 
	started_at TIMESTAMP WITH TIME ZONE, 
	current_step_started_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_pick_ban_session_encounter_kind UNIQUE (encounter_id, kind), 
	CONSTRAINT ck_pick_ban_session_first_side CHECK (first_side IS NULL OR first_side IN ('home', 'away')), 
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
	FOREIGN KEY(config_id) REFERENCES tournament.pick_ban_config (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_pick_ban_session_encounter_id ON tournament.pick_ban_session (encounter_id);

CREATE TABLE tournament.player (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	name VARCHAR NOT NULL, 
	sub_role VARCHAR(128), 
	rank INTEGER NOT NULL, 
	role heroclass, 
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

CREATE INDEX ix_player_tournament_role_sub_role ON tournament.player (tournament_id, role, sub_role);

CREATE INDEX ix_player_related_player_id ON tournament.player (related_player_id);

CREATE INDEX ix_tournament_player_tournament_id ON tournament.player (tournament_id);

CREATE INDEX ix_player_member_not_sub ON tournament.player (workspace_member_id, tournament_id) WHERE is_substitution = false;

CREATE INDEX ix_player_team_workspace_member ON tournament.player (team_id, workspace_member_id);

CREATE INDEX ix_player_workspace_member_tournament ON tournament.player (workspace_member_id, tournament_id);

CREATE TABLE tournament.player_sub_role (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	workspace_id BIGINT NOT NULL, 
	role VARCHAR(64) NOT NULL, 
	slug VARCHAR(128) NOT NULL, 
	label VARCHAR(128) NOT NULL, 
	description TEXT, 
	sort_order INTEGER DEFAULT '0' NOT NULL, 
	is_active BOOLEAN DEFAULT 'true' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_player_sub_role_workspace_role_slug UNIQUE (workspace_id, role, slug), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE INDEX ix_player_sub_role_workspace_id ON tournament.player_sub_role (workspace_id);

CREATE INDEX ix_player_sub_role_workspace_role_active ON tournament.player_sub_role (workspace_id, role, is_active);

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
	FOREIGN KEY(encounter_id) REFERENCES tournament.encounter (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by_auth_user_id) REFERENCES auth."user" (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_scrim_room_tournament_id ON tournament.scrim_room (tournament_id);

CREATE INDEX ix_tournament_scrim_room_stage_id ON tournament.scrim_room (stage_id);

CREATE INDEX ix_tournament_scrim_room_workspace_id ON tournament.scrim_room (workspace_id);

CREATE INDEX ix_scrim_room_open_by_creator ON tournament.scrim_room (created_by_auth_user_id) WHERE closed_at IS NULL;

CREATE INDEX ix_tournament_scrim_room_encounter_id ON tournament.scrim_room (encounter_id);

CREATE INDEX ix_tournament_scrim_room_created_by_auth_user_id ON tournament.scrim_room (created_by_auth_user_id);

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
	name VARCHAR NOT NULL, 
	description VARCHAR, 
	stage_type tournament.stagetype NOT NULL, 
	max_rounds INTEGER DEFAULT '5' NOT NULL, 
	advance_count INTEGER, 
	split_lower_bracket BOOLEAN DEFAULT 'false' NOT NULL, 
	"order" INTEGER NOT NULL, 
	is_active BOOLEAN DEFAULT 'false' NOT NULL, 
	is_published BOOLEAN DEFAULT 'false' NOT NULL, 
	is_completed BOOLEAN DEFAULT 'false' NOT NULL, 
	settings_json JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
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
	PRIMARY KEY (id), 
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
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE CASCADE, 
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE SET NULL, 
	FOREIGN KEY(source_stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_stage_item_input_stage_item_id ON tournament.stage_item_input (stage_item_id);

CREATE INDEX ix_tournament_stage_item_input_team_id ON tournament.stage_item_input (team_id);

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
	PRIMARY KEY (id), 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE, 
	FOREIGN KEY(team_id) REFERENCES tournament.team (id) ON DELETE CASCADE, 
	FOREIGN KEY(stage_id) REFERENCES tournament.stage (id) ON DELETE SET NULL, 
	FOREIGN KEY(stage_item_id) REFERENCES tournament.stage_item (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_standing_stage_id ON tournament.standing (stage_id);

CREATE INDEX ix_tournament_standing_stage_item_id ON tournament.standing (stage_item_id);

CREATE INDEX ix_standing_tournament_position ON tournament.standing (tournament_id, overall_position);

CREATE INDEX ix_tournament_standing_team_id ON tournament.standing (team_id);

CREATE INDEX ix_standing_stage_stage_item_team ON tournament.standing (stage_id, stage_item_id, team_id);

CREATE INDEX ix_tournament_standing_tournament_id ON tournament.standing (tournament_id);

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
	FOREIGN KEY(captain_id) REFERENCES players."user" (id) ON DELETE SET NULL, 
	FOREIGN KEY(tournament_id) REFERENCES tournament.tournament (id) ON DELETE CASCADE
);

CREATE INDEX ix_tournament_team_tournament_id ON tournament.team (tournament_id);

CREATE INDEX ix_tournament_team_captain_id ON tournament.team (captain_id);

CREATE TABLE tournament.tournament (
	id BIGSERIAL NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	workspace_id BIGINT NOT NULL, 
	name VARCHAR NOT NULL, 
	slug VARCHAR NOT NULL, 
	description VARCHAR, 
	is_league BOOLEAN DEFAULT 'false' NOT NULL, 
	is_finished BOOLEAN DEFAULT 'false' NOT NULL, 
	is_hidden BOOLEAN DEFAULT 'false' NOT NULL, 
	team_formation VARCHAR DEFAULT 'balancer' NOT NULL, 
	status tournament.tournamentstatus NOT NULL, 
	start_date TIMESTAMP WITH TIME ZONE, 
	end_date TIMESTAMP WITH TIME ZONE, 
	auto_transitions_enabled BOOLEAN DEFAULT 'true' NOT NULL, 
	allow_late_registration BOOLEAN DEFAULT 'false' NOT NULL, 
	win_points FLOAT DEFAULT '1.0' NOT NULL, 
	draw_points FLOAT DEFAULT '0.5' NOT NULL, 
	loss_points FLOAT DEFAULT '0.0' NOT NULL, 
	division_grid_version_id BIGINT, 
	roster_slots_json JSONB, 
	cover_image_url VARCHAR, 
	logo_url VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE, 
	FOREIGN KEY(division_grid_version_id) REFERENCES division_grid_version (id) ON DELETE SET NULL
);

CREATE INDEX ix_tournament_tournament_is_hidden ON tournament.tournament (is_hidden);

CREATE INDEX ix_tournament_tournament_division_grid_version_id ON tournament.tournament (division_grid_version_id);

CREATE INDEX ix_tournament_tournament_workspace_id ON tournament.tournament (workspace_id);

CREATE UNIQUE INDEX ix_tournament_tournament_slug ON tournament.tournament (slug);

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

CREATE INDEX ix_tournament_tournament_phase_schedule_tournament_id ON tournament.tournament_phase_schedule (tournament_id);

CREATE INDEX ix_tournament_tournament_phase_schedule_starts_at ON tournament.tournament_phase_schedule (starts_at);

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
