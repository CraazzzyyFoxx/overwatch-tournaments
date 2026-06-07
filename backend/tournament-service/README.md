# tournament-service

Tournament domain API and worker.

Current scope:
- `/health/live`
- `/health/ready`
- public read routes under `/tournaments`, `/encounters`, and `/teams`
- public registration routes under `/workspaces/{workspace_id}/tournaments/{tournament_id}/registration`
- captain result routes under `/encounters/{id}/...`
- admin tournament/stage/team/player/encounter/standing routes under `/admin`
- Challonge read/import/export/push/log routes under `/admin/challonge`
- admin registration, status catalog, Google Sheets sync/preview/suggest, and active registration export routes under `/admin/balancer` and `/admin/ws`
- map veto routes and websocket under `/encounters/{id}/map-pool`
- tournament realtime events published to `realtime.workspace_event` for realtime-service fan-out
- Rabbit `tournament_changed` consumer for cache invalidation
- Redis realtime publish for multi-replica WebSocket broadcast through realtime-service
- transactional outbox publication for captain/admin tournament changes, recalculation, encounter completion, registration approvals/rejections, and tournament state changes
- outbox sweeper in `serve.py`
- durable computation jobs with history/status API under `/admin/tournament-jobs`
- bracket worker consuming `tournament_bracket_jobs`
- standings worker consuming `tournament_standings_jobs`
- worker scheduler for registration Google Sheets sync
