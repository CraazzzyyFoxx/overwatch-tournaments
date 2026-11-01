# Mix match search by players: release note

A recorded mix match of a game whose module declares a match searcher (Deadlock today) is now looked up by its
players. The stats worker finds the private lobby match the round's teams played and files its ID as the round's
match import. The host no longer has to type it. The lobby the players sit in does not matter: it can be the same
custom lobby all evening, created by hand or by anyone.

**Module hook.** `DisciplineSpec.match_searchers`, keyed by source kind (one of `match_fetchers`):
`search(MatchQuery) -> [MatchCandidate]`.
- `MatchQuery` carries the round's linked identities and the start window.
- `MatchCandidate` carries the external ID and each side's identities.
- The searcher raises `MatchFetchNotReady` / `MatchFetchFailed` like a fetcher.

Deadlock's searcher (`shared/disciplines/deadlock/search.py`) calls `GET /v1/matches/metadata` with
`match_mode=private_lobby`, the account IDs and `min/max_unix_timestamp`. Private profiles (account 0) are left out of
their side. A 404 means no matches yet.

**Worker** (`stats-service/src/services/ingest/search.py`, a 60 s tick under `stats:match_search:leader:<code>`):
- **Enrolment.** Every mix match recorded within 24 h in a searchable game gets one `stats.match_search` row. A missed
  tick or a restart loses nothing. Matches recorded up to 24 h before the deploy are searched too.
- **Query.** The worker asks for the matches the round's linked accounts (`identity_provider`, Steam) played between
  Start − 5 min and Record.
- **Fit rule.** A match fits when every team has at least half of its linked members on one distinct side and none
  on another. A one-player swap is another round. A match another game of the workspace already holds is skipped.
- **One fit.** Filed through `submit_fetch` with no requester (`found`), so the existing import pipeline takes over.
- **Several fits.** The search stops as `not_found` with `last_error` `ambiguous: …`, and the host files the ID by hand.
- **No fit.** Retried with the import backoff for 24 h, then `not_found`.
- **No linked account on a team.** `not_found` with `no_linked_accounts`.
- **Stopped.** Statistics or any filed ID stop the search (`stopped`). A host's filed ID stops a pending search at once.
- **Undo.** Deleting the match's encounter deletes its search too.

**History wire.** `rpc.balancer.custom.match_history` rows add `match_search`: `searching`, `not_found` or null.
A search still looking makes `log_state` read `processing`.

**Frontend.** The import window shows «Ищем этот матч…» while the search looks and «По участникам матч не нашёлся»
once it gave up.

## Migration and deploy

One migration after `mixfetch01`: **`mixsearch01`**. It creates `stats.match_search`, unique per encounter, with
`ix_match_search_due`. Deploy from one SHA:
1. Run the migration.
2. Roll stats-service (+ worker; the tick starts only where a selected discipline has a searcher).
3. Roll balancer-service (history wire).
4. Roll the gateway (regenerated `schemas.json`) and the frontend.

The search shares deadlock-api's anonymous limit (30 metadata requests a minute per IP) with nothing else.
`DEADLOCK_API_KEY` raises it.

### Downgrade cost

Downgrade drops `stats.match_search`. The imports it filed stay.

## Wire changes

| Change | Kind |
| --- | --- |
| Mix match history `match_search` | additive |
| Mix match history `log_state` also reads `processing` while the match is being looked up | changed meaning |
