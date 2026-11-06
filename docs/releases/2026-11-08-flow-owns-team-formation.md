# The flow owns team formation: release note

`tournament.team_formation` and `tournament.draft_format_json` are gone. The flow graph is the only authority: a
formation node's `config.mode` (`balancer | draft | registered | manual`) says how its teams form, a registration node's
`config.intake` (`solo | team`) how players enter, and the draft format is the draft formation node's
`config.draft_format`. A mix's own `team_formation` (`balance | draft`) is untouched.

## Wire changes

- `TournamentRead` loses `team_formation` and `draft_format_json`. `TournamentCreate` and `TournamentUpdate` lose both
  too. A new tournament always starts as registration (`intake: solo`) -> formation (`mode: balancer`); the client
  shapes the rest of the flow through the flow write route.
- `DashboardTournamentCard.team_formation` is removed. `TournamentReadiness.team_formation` becomes
  `formation_modes: string[]`: the distinct modes of the tournament's formation nodes, sorted, empty without one. The
  balancer checks of the work queue (`pool_need_fix`, `balance_not_exported`) apply when it contains `balancer`.
- A formation node's `config.draft_format` is validated and stored normalized (a non-custom format keeps no round rules).
- `apply_changes` answers 409 `draft_session_active` when a formation node's `mode` or `draft_format` changes while an
  unfinished draft session belongs to that node. The old 400 on the tournament update is gone with the fields.
- A draft session takes its format from its formation node. The individual-Swiss qualification lock refuses
  (`draft_format_not_snake`) when any draft formation node of the tournament is not snake.
- `gateway/internal/openapi/schemas.json`, `frontend/src/types/api.generated.ts`, the ERD and `backend/docs/schema.*`
  are regenerated.

## Migration and deploy

- `flowP7_01_drop_team_formation` copies `draft_format_json` into the config of each draft-mode formation node of the
  tournament. A tournament with a format but no draft node keeps it on its first formation node (inert until the mode
  becomes `draft`) and the move is logged; with no formation node the format is dropped (logged). Then both columns are
  dropped. Downgrade restores `team_formation` from the first formation node (`registered` or a registration node with
  `intake: team` -> `registration`, `manual` -> `solo`) and `draft_format_json` from its first draft node, and strips
  `draft_format` from node configs.
- Deploy from one SHA in this order: migration, tournament-service, balancer-service, gateway, frontend. Old
  tournament-service/balancer-service replicas cannot run against the migrated schema.
