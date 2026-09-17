"""Human-readable docs (summary + description) for analytics-service RPC
subjects, merged into the gateway's OpenAPI by the export script. Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    "rpc.analytics.list_algorithms": {
        "summary": "List algorithms",
        "description": "Permission: public; no authentication required. Returns a paginated list of analytics algorithms, optionally filtered by tournament_id.",
    },
    "rpc.analytics.get_algorithm": {
        "summary": "Get algorithm",
        "description": "Permission: public; no authentication required. Returns a single analytics algorithm by id.",
    },
    "rpc.analytics.get_analytics": {
        "summary": "Tournament analytics",
        "description": "Permission: public; no authentication required. Returns per-team analytics (players, wins/losses, shifts) for a tournament and required algorithm; 404 if the algorithm is missing.",
    },
    "rpc.analytics.get_streaks": {
        "summary": "Player streaks",
        "description": "Permission: public; no authentication required. Returns players' placement streaks across recent tournaments for the given tournament_id.",
    },
    "rpc.analytics.performance": {
        "summary": "Performance rows",
        "description": "Permission: global `analytics.read`. Returns ML performance rows for a tournament, optionally filtered by algorithm_id.",
    },
    "rpc.analytics.standings": {
        "summary": "Standings distribution",
        "description": "Permission: global `analytics.read`. Returns standings-distribution rows for a tournament, optionally filtered by algorithm_id.",
    },
    "rpc.analytics.match_quality": {
        "summary": "Match quality",
        "description": "Permission: global `analytics.read`. Returns per-encounter match-quality rows for a tournament, optionally filtered by algorithm_id.",
    },
    "rpc.analytics.player_anomalies": {
        "summary": "Player anomalies",
        "description": "Permission: global `analytics.read`. Returns player-anomaly rows for a tournament, optionally filtered by player_id and kind.",
    },
    "rpc.analytics.feedback_list": {
        "summary": "List anomaly feedback",
        "description": "Permission: global `analytics.read`. Returns all anomaly-feedback rows recorded for a tournament.",
    },
    "rpc.analytics.explain": {
        "summary": "Explain player",
        "description": "Permission: global `analytics.read`. Returns the most recent explanation row for a player in a tournament (optionally by algorithm_id); 404 if none found.",
    },
    "rpc.analytics.artifacts": {
        "summary": "ML artifacts",
        "description": "Permission: global `analytics.read`. Returns ML model artifacts ordered by creation, optionally filtered by model_kind and active_only.",
    },
    "rpc.analytics.jobs_active": {
        "summary": "Active job",
        "description": "Permission: global `analytics.read`. Returns the currently active analytics job for the optional workspace_id, or null if none.",
    },
    "rpc.analytics.jobs_list": {
        "summary": "List jobs",
        "description": "Permission: global `analytics.read`. Returns recent analytics jobs (default limit 20), optionally scoped by workspace_id and active_only.",
    },
    "rpc.analytics.jobs_get": {
        "summary": "Get job",
        "description": "Permission: global `analytics.read`. Returns a single analytics job by id; 404 if not found.",
    },
    "rpc.analytics.shift": {
        "summary": "Override player shift",
        "description": "Permission: global `analytics.update`. Applies a manual shift override for a player and returns recomputed player analytics.",
    },
    "rpc.analytics.feedback_submit": {
        "summary": "Submit anomaly feedback",
        "description": "Permission: global `analytics.update`. Upserts a reviewer verdict/note for a player anomaly and returns the saved row.",
    },
    "rpc.analytics.openskill": {
        "summary": "OpenSkill (gone)",
        "description": "Permission: global `analytics.update`. Deprecated OpenSkill v1 endpoint; validates tournament/workspace then always returns 410 gone, directing callers to run the unified analytics job.",
    },
    "rpc.analytics.create_job": {
        "summary": "Create analytics job",
        "description": "Permission: superuser for `kind=train_ml`; for `kind=compute`, workspace `analytics.update` when `workspace_id` is supplied (that workspace must also be verified or trusted) or global `analytics.update` when it is omitted. Creates an analytics job and enqueues it to the worker, returning 202; 409 on an active-job conflict.",
    },
    "rpc.analytics.recalculate": {
        "summary": "Recalculate analytics",
        "description": "Permission: workspace `analytics.update` when `workspace_id` is supplied (that workspace must also be verified or trusted), else global `analytics.update`. Creates a 202 async compute job for a tournament (optionally scoped to given algorithm_ids), replacing the legacy synchronous recompute. Metered as `analytics.recalculate`: the call consumes quota against the caller's workspace/API-key limits and answers 429 `quota_exceeded` with a `Retry-After` header once they are spent.",
    },
    "rpc.analytics.points": {
        "summary": "Recompute points",
        "description": "Permission: workspace `analytics.update` when `workspace_id` is supplied (that workspace must also be verified or trusted), else global `analytics.update`. Creates a 202 async compute job scoped to the Points algorithm for the required tournament_id.",
    },
    "rpc.analytics.train": {
        "summary": "Train model",
        "description": "Permission: global `analytics.update`, and a verified or trusted workspace when the body carries a workspace_id. Dispatches a 202 ML training job to the worker queue; requires configured RabbitMQ (503 otherwise). Metered as `analytics.train` — the most expensive operation on the platform, so its quota cost is the highest: the call answers 429 `quota_exceeded` with a `Retry-After` header once the caller's limits are spent.",
    },
    "rpc.analytics.infer": {
        "summary": "Run inference",
        "description": "Permission: global `analytics.update`, and a verified or trusted workspace when the body carries a workspace_id. Dispatches a 202 ML inference job for a tournament to the worker queue; requires configured RabbitMQ (503 otherwise). Metered as `analytics.infer`: the call consumes quota against the caller's workspace/API-key limits and answers 429 `quota_exceeded` with a `Retry-After` header once they are spent.",
    },
}
