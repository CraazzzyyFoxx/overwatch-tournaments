# Mix match search: start it again: release note

The import window of a recorded mix match (Deadlock today) can now start the search by players again. The automatic
search only enrolls matches recorded within 24 h and gives up after 24 h, several fits or a team without a linked
account; until now the host could only type the ID.

**Route.** `POST /api/v1/custom-games/{custom_game_id}/matches/{match_id}/match-search` →
`rpc.stats.ingest.mix_search`, 204. Same audience as the match import: the mix's host, a co-host, a superuser or
workspace `log.create`.
- The match's `stats.match_search` row goes back to `pending` with `attempts` 0 and a fresh 24 h window
  (`created_at` = `next_attempt_at` = now). A match never enrolled (recorded before the automatic window) gets its row.
- A search still looking is left as it is.
- 409 `match_search_settled` while the match has statistics or a pending/done import.
- 422 `unsupported_match_search` for a game without a searcher.

**Worker.** A failed import no longer stops the search: only statistics or a pending/done import do.

**History wire.** `rpc.balancer.custom.match_history` rows add `match_search_error`: why a `not_found` search gave up
(`no_linked_accounts`, `not_found_in_window`, `ambiguous: <ids>` or the source's refusal), else null.

**Capability.** `capabilities.match_search` on the discipline descriptor: the game has a searcher whose kind it can
fetch, and an identity provider.

**Frontend.** The import window says why the search gave up and offers «Искать снова» («Найти по участникам» for a
match never searched) while there is no statistics, no search looking and no pending/done import.

## Deploy

No migration. Deploy from one SHA: stats-service (+ worker), balancer-service, app-service, the gateway (regenerated
`schemas.json`, new route) and the frontend (regenerated `api.generated.ts`). Roll the backend and gateway before the
frontend: a frontend served first reads no `match_search` capability and shows no button.

## Wire changes

| Change | Kind |
| --- | --- |
| `POST …/matches/{match_id}/match-search` | additive |
| Mix match history `match_search_error` | additive |
| Discipline `capabilities.match_search` | additive |
| A failed match import no longer stops the match's search | changed behavior |
