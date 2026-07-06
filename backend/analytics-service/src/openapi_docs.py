"""Human-readable docs (summary + description) for analytics-service RPC
subjects, merged into the gateway's OpenAPI by the export script. Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    "rpc.analytics.list_algorithms": {
        "summary": "List algorithms",
        "description": "Returns a paginated list of analytics algorithms, optionally filtered by tournament_id.",
    },
    "rpc.analytics.get_algorithm": {
        "summary": "Get algorithm",
        "description": "Returns a single analytics algorithm by id.",
    },
    "rpc.analytics.get_analytics": {
        "summary": "Tournament analytics",
        "description": "Returns per-team analytics (players, wins/losses, shifts) for a tournament and required algorithm; 404 if the algorithm is missing.",
    },
    "rpc.analytics.get_streaks": {
        "summary": "Player streaks",
        "description": "Returns players' placement streaks across recent tournaments for the given tournament_id.",
    },
    "rpc.analytics.balance_quality": {
        "summary": "Balance quality",
        "description": "Returns the stored balance-quality snapshot (objective score, SR spread, discomfort, per-player rows) for a tournament, or null if none exists.",
    },
    "rpc.analytics.v2_performance": {
        "summary": "Performance rows",
        "description": "Returns ML performance rows for a tournament, optionally filtered by algorithm_id; requires analytics.read.",
    },
    "rpc.analytics.v2_standings": {
        "summary": "Standings distribution",
        "description": "Returns standings-distribution rows for a tournament, optionally filtered by algorithm_id; requires analytics.read.",
    },
    "rpc.analytics.v2_match_quality": {
        "summary": "Match quality",
        "description": "Returns per-encounter match-quality rows for a tournament, optionally filtered by algorithm_id; requires analytics.read.",
    },
    "rpc.analytics.v2_player_anomalies": {
        "summary": "Player anomalies",
        "description": "Returns player-anomaly rows for a tournament, optionally filtered by player_id and kind; requires analytics.read.",
    },
    "rpc.analytics.v2_feedback_list": {
        "summary": "List anomaly feedback",
        "description": "Returns all anomaly-feedback rows recorded for a tournament; requires analytics.read.",
    },
    "rpc.analytics.v2_explain": {
        "summary": "Explain player",
        "description": "Returns the most recent explanation row for a player in a tournament (optionally by algorithm_id); 404 if none found; requires analytics.read.",
    },
    "rpc.analytics.v2_artifacts": {
        "summary": "ML artifacts",
        "description": "Returns ML model artifacts ordered by creation, optionally filtered by model_kind and active_only; requires analytics.read.",
    },
    "rpc.analytics.jobs_active": {
        "summary": "Active job",
        "description": "Returns the currently active analytics job for the optional workspace_id, or null if none; requires analytics.read.",
    },
    "rpc.analytics.jobs_list": {
        "summary": "List jobs",
        "description": "Returns recent analytics jobs (default limit 20), optionally scoped by workspace_id and active_only; requires analytics.read.",
    },
    "rpc.analytics.jobs_get": {
        "summary": "Get job",
        "description": "Returns a single analytics job by id; 404 if not found; requires analytics.read.",
    },
    "rpc.analytics.shift": {
        "summary": "Override player shift",
        "description": "Applies a manual shift override for a player and returns recomputed player analytics; requires analytics.update.",
    },
    "rpc.analytics.feedback_submit": {
        "summary": "Submit anomaly feedback",
        "description": "Upserts a reviewer verdict/note for a player anomaly and returns the saved row; requires analytics.update.",
    },
    "rpc.analytics.openskill": {
        "summary": "OpenSkill (gone)",
        "description": "Deprecated OpenSkill v1 endpoint; validates tournament/workspace then always returns 410 gone, directing callers to run the unified analytics job.",
    },
    "rpc.analytics.create_job": {
        "summary": "Create analytics job",
        "description": "Creates an analytics job and enqueues it to the worker, returning 202; gates by kind (compute=workspace analytics.update, train_ml=superuser), 409 on an active-job conflict.",
    },
    "rpc.analytics.recalculate": {
        "summary": "Recalculate analytics",
        "description": "Creates a 202 async compute job for a tournament (optionally scoped to given algorithm_ids), replacing the legacy synchronous recompute.",
    },
    "rpc.analytics.points": {
        "summary": "Recompute points",
        "description": "Creates a 202 async compute job scoped to the Points algorithm for the required tournament_id.",
    },
    "rpc.analytics.train": {
        "summary": "Train model",
        "description": "Dispatches a 202 ML training job to the worker queue; requires analytics.update and configured RabbitMQ (503 otherwise).",
    },
    "rpc.analytics.infer": {
        "summary": "Run inference",
        "description": "Dispatches a 202 ML inference job for a tournament to the worker queue; requires analytics.update and configured RabbitMQ (503 otherwise).",
    },
}
