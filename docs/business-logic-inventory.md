# Business-logic inventory

Canonical map of **domain rules**, not HTTP plumbing. Architecture and request flow live in [`architecture.md`](./architecture.md); vocabulary in [`glossary.md`](./glossary.md); identity in [`users-identity.md`](./users-identity.md); tables in [`database_erd.md`](./database_erd.md).

Authority is the server. The frontend duplicates a few gates for UX and cites the Python symbol it mirrors.

---

## 0. Where logic lives

One PostgreSQL database, one SQLAlchemy metadata (`backend/shared`). Domain boundaries are Postgres schemas: `auth`, `players`, `public`, `tournament`, `matches`, `overwatch`, `rank`, `balancer`, `achievements`, `analytics`, `log_processing`, `realtime`, `subscriptions`.

| Owner | Decides |
| --- | --- |
| `tournament-svc` | Tournament lifecycle, registration, brackets, results, pick-ban, scrims, outbox sweeper, organizer dashboard and readiness |
| `balancer-svc` | NSGA-II / mix balance, live draft, custom games |
| `identity-svc` | JWT, OAuth, RBAC, hostnames, API keys, player linking |
| `stats-svc` | Match logs, match import by external id, impact/MVP, achievements, native ranks (OverFast, Riot API, deadlock-api); public statistics, `/users/*` player statistics and achievement reads |
| `analytics-svc` | OpenSkill / linear / ML shifts |
| `app-svc` | Catalogs, player identity (directory, search, merge), workspaces, notifications, assets |
| `stream-svc` | Twitch live status (Redis only, no Postgres schema) |
| `discord-svc` | Log ingest, subscription resync |
| Gateway | JWT, topic ACL — not domain |

---

## 1. Tenancy and identity

**Workspace** is the tenant root. Nearly every business row carries `workspace_id` directly or through `tournament` / `workspace_member`.

**Host → tenant** (`backend/shared/tenancy/hostnames.py`):

- Subdomain of `PLATFORM_ZONE`. Label 1–63 chars, `[a-z0-9-]`, no leading/trailing hyphen. Reserved: `www`, `api`, `auth`, `admin`, `app`, `assets`, `static`, `cdn`, `mail`, `ws`.
- Custom domain is a **separate** path: multi-label FQDN **not** under the platform zone, UNIQUE, proven by DNS TXT (`custom_domain_verified_at`). The two resolution paths are mutually exclusive.

**Four layers, joined at `workspace_member`:**

1. `auth.user` — login, sessions, RBAC.
2. `players.user` — the game person (BattleTag, history). `auth_user_id` UNIQUE nullable. `NULL` = virtual/shadow player (from a log or CSV; cannot sign in).
3. `public.workspace_member` UNIQUE `(workspace_id, player_id)` — anchor for rosters, registrations, drafts, achievements, ranks. **No** `auth_user_id` and **no** role column: role lives only in `user_roles`.
4. `balancer.member_rank` — rank layers on the member.

**Linking is anti-takeover:**

- `OAuthConnection` UNIQUE `(provider, provider_user_id)` — one external subject binds to one account. One account may hold several subjects of the same provider.
- OAuth callback: (1) proven `provider_user_id` → (2) exactly one unowned player matching the handle → (3) new account. Never overwrites an already-owned player.
- Self-service link requires a Discord, Battle.net, Riot or Steam OAuth connection **and** a handle intersection with `social_account`; otherwise 403; another owner → 409.
- Unlink is blocked while the account holds any workspace role other than `player` (otherwise an orphan `workspace_member` that admin lists cannot see, because those lists require `auth_user_id IS NOT NULL`).

---

## 2. RBAC

Grant-only catalog + workspace system roles + a **deny overlay** that beats every grant, including superuser. Catalog: `backend/shared/rbac/catalog.py`. Evaluation: `AuthUser.has_workspace_permission`.

| Role | Grants |
| --- | --- |
| `owner` | `admin.*` |
| `admin` | Everything except governance (`role` / `permission`) and `workspace.delete` / `workspace_member.delete` |
| `host` | Player reads + full `custom_game` CRUD (this **is** the right to run a mix) |
| `player` | `*.read` on `_PLAYER_READ_RESOURCES` |

Allow-by-default capabilities exist only so a deny row can revoke them: `account.avatar`, `account.social`, `registration.self_register`, `workspace.self_create`.

Evaluation order: deny → superuser / global-admin → global permission → workspace-admin bypass (not on governance, not on destructive delete) → workspace grant.

Other rules:

- `assign_default_member_role_if_roleless` fires only when the account has **zero** roles in that workspace; it never downgrades.
- The last owner cannot be removed.
- API-key scopes **are** permission names; they are intersected with the owner's real RBAC and baked into the JWT. There is no second scope-check path.
- Host ≠ admin panel: `custom_game` is carved out of admin-panel access.

---

## 3. Tournament lifecycle

State machine: `backend/shared/core/tournament_state.py`. Only `tournament-svc` applies it.

```
ANNOUNCEMENT → REGISTRATION → [CHECK_IN] → [DRAFT] → LIVE → [PLAYOFFS] → COMPLETED ⇄ ARCHIVED
```

Phase order is 0…7. `CHECK_IN` is optional. `DRAFT` applies only when `team_formation="draft"`. Forward skips are legal (`REGISTRATION → LIVE` is one hop). Rollback edges exist up to `LIVE` so an organizer can reopen a phase without the superuser `force` bypass. `PLAYOFFS` only leads to `COMPLETED`. `COMPLETED ⇄ ARCHIVED` is reversible.

`is_finished` is **derived**: true exactly for `COMPLETED` and `ARCHIVED`. “In play” = `LIVE | PLAYOFFS` (check-in is a lobby, not a ball in play).

**Schedule** (`tournament_phase_schedule`):

- Schedulable: `REGISTRATION`, `CHECK_IN`, `DRAFT`, `LIVE`. Not `ANNOUNCEMENT`, `PLAYOFFS`, `COMPLETED`.
- `starts_at` moves status. `ends_at` **never** moves status — it only closes that phase's action window.
- One row per phase; strictly increasing `starts_at`; `ends_at > starts_at` when set.

**What moves status — only two things:**

1. An admin via `tournament_status`. Validated against the transition matrix unless `force`. A manual transition **disables** `auto_transitions_enabled` in the same transaction so automation never fights the admin.
2. The 30-second tick. Forward only, only out of `{ANNOUNCEMENT, REGISTRATION, CHECK_IN, DRAFT}`, furthest destination `LIVE`. Several due rows → jump to the **latest** due phase, not step through intermediates. `FOR UPDATE SKIP LOCKED`, one transaction per tournament.

Side effect of reaching `LIVE`: auto-start the first group-stage wave (stages sharing `order` are one parallel phase).

**Visibility.** A hidden tournament 404s as “not found”. Preview allowlist (`tournament_preview_access`) for unpublished hidden events. Exception: a **scrim container** is readable by any workspace member (the opponent must open the link before claiming). Listings still hide the container.

---

## 4. Registration, captain teams, admission

### Windows

Registration inverts the other windows (`backend/shared/services/registration_window.py`):

- No `REGISTRATION` schedule row → closed.
- `COMPLETED` / `ARCHIVED` → always closed.
- `allow_late_registration` lifts `ends_at` without erasing the intended close time.
- The tournament's current **phase does not participate**.

Check-in: status **must** be `CHECK_IN` **and** `now` inside the window (missing row / `ends_at NULL` = the whole phase).

### Form and statuses

One form per tournament: fields, flex mode, team rank rules, Discord-guild requirement, subscription toggle/stage/scope.

Registration statuses are a per-workspace catalog. `ready` / `incomplete` **cannot be written by hand** — they are derived from roles + ranks.

One registration per player per tournament (partial unique). Withdrawal is **final** — an invite cannot revive a withdrawn/rejected row.

### Flex / playable role

`backend/shared/domain/roster.py`:

```
playable  ⇔  is_active  AND  a rank number was found (> 0)
```

Form flex mode: `optional` | `all_roles` | `forced`. Unreadable form → `optional`.

A game with one rated role (Deadlock, VALORANT) is normalized like `forced` on every write path: the role set is always that role,
primary; a write naming no role keeps the stored row (and its rank); a new registration without a `roles` answer gets
it; a public sign-up's absent `roles` answer is that role (`_common.only_role_answer`) — its form shows no role step.

Rank resolution (`pick_rank`, first non-null layer wins):

- Tournament: `registration → workspace → ow`
- Mix: `author → workspace → ow`

Absence of a row is inheritance. A stored `0` would break fall-through, so writes delete rather than zero.

### Admission

Two requirements, fixed order (`backend/tournament-service/src/services/admission/registry.py`):

1. **Open profile** — always `check_in`. There is no stage column (YAGNI until an organizer asks).
2. **Subscription** — stage from the form; garbage/NULL defaults to `check_in` (a typo must not start refusing sign-ups).

`registration` implies `check_in`. After check-in, blockers become `overridden` (the gate is behind); `ready` stays a separate completeness flag.

Subscription:

- The **rule** lives on the workspace, not the tournament.
- A toggle with no rule does not enforce.
- `mode=any` keeps a reason per failed provider.
- At sign-up a refusal is **softened** if a challenge code could still satisfy a provider.
- Scope `team`: a current team stamp covers the player and skips live resolve.
- Missing Discord/Twitch credentials → `unknown` → **fail open**.

### Captain-formed teams (pre-formation)

Distinct from `tournament.team` (the post-balancer/draft materialized roster).

Pending invites **reserve** offerable slots but **do not** block accept (accept looks at open, not unoffered).

Invite:

- Not a placeholder registration (must not inflate the public participant count).
- Two addresses: `target_auth_user_id` and/or a shareable token (only sha256 stored).
- Consume is one `UPDATE … WHERE pending AND not expired RETURNING`. Double-redeem is impossible.
- An existing solo registration is **attached** to the team; the submitted form body is ignored.
- Accept rate-limit fails open (token entropy is the real defence).

Occupancy (`RosterOccupancy`): `is_complete` is starter slots only; substitutes are a separate `max_substitutes` budget.

Eligibility (starters only): min/max rank and max spread (unrated fails min/max, not spread); unique identity keys vs the rest of the tournament; Discord guild membership.

Export into `tournament.team` skips waitlisted / incomplete / empty and records `skipped` with a code — never silent drop.

---

## 5. Roster shape

`backend/shared/domain/roster_shape.py`

Codes: `tank | damage | support | flex`. Built-in 5v5: `{tank: 1, damage: 2, support: 2}`.

A game without open slots (`DisciplineSpec.flex = False`: Deadlock, VALORANT) gives every open starter to its single rated role — Deadlock 6v6 is `{agent: 6}`, VALORANT 5v5 `{agent: 5}`; with several rated roles such a format is refused (`team_format_open_slots_without_flex`).

Team size **2–12**. A one-slot roster is forbidden (nothing to draft or balance). `draft_rounds = team_size - 1`.

Resolve: tournament override → workspace default → built-in 5v5. The client receives the already-resolved shape; it does not recompute `team_size` / `draft_rounds` except as a preview of an unconfirmed editor total.

Locks: cannot change the workspace default while an inheriting tournament uses it and a draft/formation is in flight. Cannot change `team_formation` or shape while a draft session is active.

---

## 6. Team formation

`tournament.team_formation` is a string, default `"balancer"`. Known values: **`balancer`**, **`draft`**. Captain-registered teams are a separate export path into `tournament.team`.

### Balancer

Shared prep (`backend/balancer-service/src/domain/balancer/runtime.py`):

- Drop unplayable players.
- Every mask role needs ≥ 1 capable player.
- `num_teams = floor(pool / team_size)`, then the backend cap.
- Overflow: `must_play` always kept (error if they exceed slots); optional players trimmed by `rotation_priority`, then input (uuid) order — skipping a player the remaining seats' roles cannot take, so a pool that can fill the teams is never refused for whoever sorts last (`mix_lobby_split.seated_set`, shared with the lobby split and the mix draft).
- Captains pinned; roles assigned by backtracking that never evicts a captain.

**Tournament balancer** (Rust NSGA-II, N teams): MMR gap (tax-bracket rates 1/3/8/18/40), per-role line gap (1/3/8/20) and line std weighted by `role_settings` (default: tank only), role `impact` in the effective team total, intra-std, discomfort, sub-role collisions (weight 24/pair), low-rank pairs (250/pair), role-line, pain. Hard `time_limit_ms` (default 600s). Discomfort: 0 flex, `pref×100`, 1000 playable-unpreferred, 5000 unplayable. Per-role weights are declared once in `AlgorithmConfig.role_settings`; the engine receives them per role and knows no role names.

**Mix balancer** (Rust exhaustive search, exactly 2 teams): comfort/fairness tilt, per-role `mix_weight` from the host's preferences; optional `balance_limit` (unset by the service); each unordered seating enumerated once.

Captains: top N by `(-max_rating, uuid)`.

### Live draft

Session: `setup → ready → live ⇄ paused → completed | cancelled`.

A session is created, seeded and started only for a `team_formation="draft"` tournament (409 `tournament_not_draft_formation`; a superuser's start does not bypass it). Its settings (pick time, overtime, autopick strategy, override flag) change only in `setup | ready`; once the draft starts a patch is 409 `draft_settings_locked`.

Formats: `snake | linear | custom`. Custom round rules: linear / reverse / weakest / strongest / `team_avg_asc` / `team_avg_desc`. Captain order: manual / weakest / strongest / random (Mulberry32, seed in settings).

Clock is **server-authoritative** (Redis lock, 10s TTL). Manual pick vs autopick is one conditional `UPDATE (on_clock AND version)`; the loser gets 409.

Autopick only from feasibility-safe `(player, role)`:

- Bipartite matching of remaining slots.
- A hypothetical pick is tested **before** apply so it cannot starve another team's slot.
- No safe choice → pause `role_shortage`, never force-pick.
- `team_avg_*` re-seats on round start and pauses with `order_recalculated`.

Strategies: `best_fit` (default), `best_available`, `role_need`. Fit is deliberately simpler than the balancer. Fit's role impact is per team: each role's weight is scaled by `1 − 0.5 × filled share` of that role's seats (own + flex), so a support-captain team prefers tank/damage over a somewhat higher-ranked support (`rules.team_fit_config`).

### Mix / custom game

`MixStatus`: draft / balanced / completed / cancelled. Participation: `must_play` / `pool` / `benched`.

**Lobbies.** A mix runs `lobby_count` lobbies (1..6, CHECK). Every per-match fact lives on
`mix.lobby` keyed `(custom_game_id, lobby_index)` (0..5): `balance_result_json`,
`balance_result_version`, `selected_variant_index`, `next_map_id`, `balanced_at`. The mix itself
carries none of them. Team names stay in `CustomGameTeamName` at the global index
`lobby_index * 2 + team` (A: 0-1, B: 2-3, …, F: 10-11).

Lobby membership is **not stored**: a player's `current_lobby` is derived from the selected variant
of each lobby, `null` = waiting. Only the host's tie is stored — `custom_game_player.lobby_pin`
(422 unless `lobby_pin < lobby_count`). `set_lobby_count(n)` opens the lobbies missing below `n`
and, going down, drops every lobby row with `lobby_index >= n` together with the pins that named
them; pins to surviving lobbies and recorded matches stay.

`balance` takes `{scope: "lobby", lobby_index} | {scope: "all"}`. Scope `lobby` excludes players
seated in another lobby and players pinned to one, then runs the unchanged `run_mix_balance` path.
Scope `all` needs `lobby_count >= 2` (422 `single_lobby`), splits the pool into `lobby_count`
equally strong parts with `domain/mix_lobby_split.py` (422 `not_enough_players` / `too_many_pinned`
/ `too_many_must_play` — more `must_play` than all lobbies have seats — / `roles_infeasible`) and
solves each lobby. `set_variant_index` refuses a variant that would seat somebody another lobby
already seated: 409 `seat_conflict`.

A lobby's match has a lifecycle (spec §5): **Start match** (`start_match`) opens an encounter of the lobby's shown lineup
(captains in `encounter.team_member.is_captain`, both participations marked ready, one `awaiting_result` game on its
`next_map_id`) and sets `mix.lobby.live_encounter_id` (409 `match_live` when one is already live). With the mix's
`hero_ban_preset` set (spec §8) it seats the ban opener in slot 1 (`domain/mix_opener.ban_opener`: the loser of the
lobby's last round when the same two teams meet again, else the lower average rating; `flip_opener` swaps it), freezes
the preset into `mix.lobby.live_ban_preset` and, through the outbox, asks tournament-service to open the hero room on it
(`PickBanRoomOpenRequestedEvent`). **Record** (`record_outcome`, 409 `no_live_match` without a live match) completes it
with `apply_result(source=host)`, stamps `mix.round.lobby_index`, writes a `mix.round_member` row per seat of the
encounter's roster and a busy one per member seated in another lobby's selected variant or away (a seat wins over busy),
then clears the pointer, the frozen preset and the next map; **Cancel** (`cancel_match`) deletes the encounter and
clears the pointer and the frozen preset. Close and cancelling a mix cancel every live match. Host writes of one mix run
one at a time:
`_writable` locks the mix row (`SELECT … FOR UPDATE`) and the lobbies are re-read after the lock. While live, swap /
variant / next map / captain / balance of that lobby (or `scope="all"` while any lobby is live) and dropping the lobby
answer 409 `match_live`; balance refuses before it reads the pool (never `empty_lineup`), and `set_next_map` checks the
map first (404 for one the game does not have). The lobby state (`idle` / `ready` / `pregame` / `live`) is derived
(`lobby_state`), never stored: `pregame` while `live_ban_preset` is set and the encounter's hero room is missing or
neither completed nor cancelled.

Rounds read in recording order (`encounter.confirmed_at`, then id): the history, undo, rotation, the ranker replay and
the leaderboard form. `encounter.created_at` is the start: the stats' `played_at`, the leaderboard's period window and
the list's `last_match_at`. `undo_match` rolls back the newest match **of that match's lobby** (`newest_id_for_lobby`),
not of the mix; a live match is no round, so undo ignores it.

Captains live in the lineup (`teams[t].captain_member_id`, `domain/mix_lobbies.with_captains`): the strongest seat by
the solver's rating, lower member id on a tie; kept while seated; re-derived for both teams when a swap involves a
captain; a fresh balance starts over. The detail read and Start captain a lineup stored without them, on a copy.
`set_captain` reassigns in the lobby's shown option (404 when it does not seat the player). `mix.player.away` removes a
player from every seated set (balance, split, rotation queue, rotation-hint application) without touching their
must-play mark, and records them busy in every round meanwhile. The player sets it through `self_away` (the role-edit
gate minus `self_role_edit`: `can_set_away` / `away_blocker`), a host through the player patch; it never clears itself.

Rank movement on `record_outcome` follows the **host's** `user_config.rating_mode`: `points` moves
both teams by `points_per_win` (decided matches only, frozen in `points_per_win_applied`); `ranker`
moves each seat by the mix ranker (draws included, never against the result, frozen per seat in
`mix.round_member.rank_delta_applied`) and the host's mixes balance on the effective rating. Either way
the workspace's hidden ratings (`member_hidden_rating`) advance. `undo_match` gives back what was
frozen, then rebuilds the hidden ratings from the remaining history. The hidden book is derived data:
saving a new `rating_min`/`rating_max`/`rating_avg`/`sigma_init` or the admin's rebuild replays it.

Rotation (`mix_rotation.py`): longest sit-out streak → shortest played streak → fewest games → input
order. `must_play` always seated. No history, or the whole pool fits → all `NEUTRAL` (do not invent
fairness). **A round in which the member is `busy` is skipped entirely** — they were playing in another lobby, or away,
which is neither "played" nor "sat out". An empty busy set reproduces the one-lobby behaviour exactly, so no backfill
was needed.

Self-signup (`custom_game.self_signup` = `closed` | `pool` | `benched`, `self_role_edit`): one policy,
`mix_self_service.mix_self_policy`, gates Discord and the board alike. Check order is the reason order —
`mix_closed` → `discord_not_linked` → `<provider>_not_linked` → `player_not_linked` → `self_join_denied` →
`already_joined`/`not_on_roster` → `signup_closed` → `roster_full` → `role_edit_off`. Discord **and** the mix game's
identity provider must be linked (`account_links.required_link_providers`: Battle.net for Overwatch, Riot for LoL and
VALORANT, Steam for Deadlock; `missing_account_links`); capability `custom_game.self_join` is
allow-by-default, an admin cuts one account with a deny. `already_joined` is not an error: `self_join` is
idempotent and a host's bench decision survives a second press. `can_leave` ignores every link. A signup is an
ordinary `custom_game_player` row — no separate application table. A player writes `roles` and `is_flex` only;
ranks stay the host's book, participation the host's decision, and an edit applies from the next balance
(`balance_result_json` is a snapshot).
`is_flex = true` in a game without Full flex (`DisciplineSpec.flex = False`: Deadlock, VALORANT) is a 422 `full_flex_unsupported`
from the host and the player alike; `false` is accepted.

Caps: 6 lobbies (`MAX_LOBBIES`), 8 teams, 16 co-hosts, 100 roster rows for a self-signup (`roster_full`). Host role required (`custom_game.*`).

---

## 7. Stages, brackets, standings

`StageType`: `round_robin` | `single_elimination` | `double_elimination` | `swiss`.

Stage lifecycle: `DRAFT` (no encounters) → `PREVIEW` (encounters exist, not published) → `LIVE` (published/active) → `DONE`.

Generation (`backend/shared/services/bracket/engine.py`):

- Round-robin: circle method, BYE skipped, **no** advancement edges.
- SE/DE: skeleton + `EncounterLink` (the team in position *k* of the source encounter fills a numbered slot of the target). The bracket **is** those edges, not an implied tree.
- DE: optional lower-bracket seeds (group runners-up). Grand Final Reset is **lazy**: only if the LB champion wins the GF.
- Swiss: Monrad, sort `(points, buchholz)`. Rematch-free first; rematch only if the alternative is idle teams. Bye not to a team that already had one. Unpairable field → error.
- Swiss thresholds (`swiss_qualify_wins` / `swiss_eliminate_losses`, `SwissThresholds`): a team with that many wins (byes count) / losses is decided and paired no more; fewer than two undecided → no round, scope complete before `max_rounds`; a threshold disables the full-circle round-robin shortcut. A match that can decide a team takes `best_of_swiss_qualify` / `best_of_swiss_eliminate` (the larger when both) over the round's best-of; the best-of backfill replays each round's records to agree.

**Advancement** (`advance_after_result`): reads the final positions the result writer materialised on the participations and fills only empty seats; a position two teams share (a draw) blocks and nobody advances out of it until an admin breaks the tie. A changed result is reopen → `reset_downstream` (retires the seats it filled and cancels the games they had not played, recursively) → write the new result → advance.

**Standings** count only **closed** rounds (no playable encounter in that scope still open — otherwise FORM runs ahead of W·D·L):

Scoring: `win_points` / `draw_points` / `loss_points` from the tournament, stage override allowed. Swiss bye uses `swiss_bye_points` (default = win).

Computed: W/D/L, points, score differential, Buchholz + median Buchholz, head-to-head inside a points bucket, `tie_group`, manual positions.

Elimination positions are counted from the bottom: the losers of a closed round share the best place below every team still alive (a beaten semi-finalist is 3rd while the final is unplayed, quarter-final losers 5th), and a team still alive has position 0 until it is eliminated or the final settles 1st/2nd. A third-place match -- an upper-round encounter every `encounter_link` into which carries a losing place, e.g. Challonge's "hold third place match" -- is never the final even when it shares the final's round: once completed its winner is 3rd and its loser 4th. Pins apply on top: an unpinned eliminated team keeps that place unless a pin displaces it.

Jobs: `tournament_bracket_jobs` / `tournament_standings_jobs`, prefetch 4, isolated from the RPC channel.

---

## 8. Encounters, reports, pick-ban

Encounter status: `OPEN | PENDING | COMPLETED`. An encounter (`encounter.encounter`) seats `slot_count` participations (`encounter.team`, append-only; a replaced occupant is `active = false`). The official result is `result_status` (`none | pending_confirmation | confirmed | disputed`) with `result_source` `games | series_claim | admin | import`, and every change of it bumps `result_version` and writes one `encounter.result_audit` row. The result of one position is the **encounter game** (`encounter.game`, with one `game_team` row per participation): `state` `planned | awaiting_result | disputed | confirmed | cancelled`, `result_source` `captain_agreement | admin | admin_log`. The series score is wins over confirmed, non-cancelled games (the `wins` scoring preset). A `Match` is the parsed-log record of a played map and carries statistics, not the result.

Two report layers, plus log evidence:

1. **Per-game** (`encounter.game_claim` + `game_claim_result`) — one participation's claim about one game, at most one claim per `(game, participation)`. Two matching claims confirm the game with `result_source=captain_agreement` and drive the next ban opener; conflicting claims → `disputed` + organizer notification. A claim against a confirmed game is rejected (`result_locked`); changing it is the admin correction command, which requires a reason.
2. **Series** (`encounter.team_report` + `team_report_result`) — after the series. A participation may re-file until the result is confirmed; once every live participation has reported and the reports agree the result becomes `series_claim` and advancement runs, reports that differ give `disputed`. After `confirmed` (by the games — a pick-ban series confirms on its last map —, an agreement or an admin) a report is still accepted as evidence: it must state the confirmed score (else 409 `result_locked`), is not checked against the games, never re-derives the result, opens no game position, and only re-averages the encounter's `closeness`. Only an admin changes a confirmed result. Disabled form fields are dropped, not 422.
3. **Ingest evidence** (`match.ingested`, `tournament-service/src/services/encounter/log_evidence.py`) — stats observes, the match layer decides, one durable `match_ingested` room-journal receipt per decision (source `stats-service`; `outcome` ∈ `accepted | logs_disabled | owner_policy_refused | result_locked | stale_basis | result_incomplete | applied_roster_only`). Only a tournament with `logs_official = true` (default false, set by `tournament.update`, never by a Challonge import) may take it, and only for an unaccepted, uncancelled game of an undecided encounter whose `result_version` still equals the evidence basis: the canonical placements become an `admin_log` game result (`GameResultIn(score=None, placement=…)`) through `record_result`, then the same recalculation/pick-ban signals as an admin correction. Admin, captain, import and confirmed results are never overwritten (`result_locked`), and a later or lower revision never replaces the first accepted one (changing it stays the organizer's reopen/correct action). Missing placements or mandatory organizer columns journal `result_incomplete`; stats stays done. Extra participants the roster lacks join their team as encounter substitutes (existing member/team mappings are idempotent, a contradictory team or a removed/foreign member refuses the evidence; no rank or replaced player is guessed). Mix rounds (host/co-host authority) and scrim containers (specified policy: claims of both sides, result optional) never accept log-driven results or additions. Duplicate/out-of-order delivery is decided from the full scoped journal (JSON `game_id`/`evidence_id`), not the UI history window, and writes nothing.
   The game's map and mode, where both sides know one, must also still equal the observation's (checked under the game lock, else `stale_basis` with reason `game_map_changed`); a game with no map or mode yet takes the observation's with the accepted result.

A preview bracket rejects gameplay writes (409), including readiness, map choices and results. Organizers with `match.update` may swap team slots before publication; swaps still require open, unsettled encounters in the same stage.

Parsed-match reads use `stats.match` bound to an encounter game. Overwatch match cards use that game's historical participant slots 1/2 (including retired participations), integer observed `score` facts, and the game's real `position` as `map_index`; official game results are never substituted. Match `source` and `code` no longer exist in public/admin responses or search/sort. Admin match updates accept only observed scores, duration and the already-bound map: removed/unknown fields return 422, and a different map returns 409 `stats_match_map_binding_conflict`. A different game/team binding requires the ingestion binding workflow.

**Match mode.** A match's mode is its own (`stats.match.mode_entity_id`, `encounter.game.mode_id`), never read from the map's catalog parent: one map can host several modes (Deadlock's Midtown). A document without `mode` takes the map's parent; a given mode must equal it when the map has one (422 `mode_map_mismatch`). Opening a game with a map, the pick-ban sync, a map selection and a mix round set the game's mode to the map's parent when that parent is a mode; a parentless map keeps the game's mode only while the map is unchanged. A hinted document may bind to a game with no map yet; an unhinted one needs an equal map. Statistics, map filters, map-coverage achievements and Push/Clash detection read the match's mode.

Admin match duration, display filename and source-team pointers can be null. `log_record: null` / `unlinked_only` mean no raw log is available; an internal object key is not reconstructed from the display filename. Player-stat counts exclude team-score facts, and kill/timeline arrays retain event multiplicity and chronological order. Score/duration edits and tournament/encounter/stage cascades stage narrow native-state evidence before their existing commit and retain the existing cache/outbox behavior.

A **scrim** uses per-map reports to run the series engine; standings are not recalculated.

### Pick-ban

Kinds: `map` | `hero`. Config cascade: tournament → stage → round. An empty pool is a rules **template** and does not open a session.

Modes: `pool` | `slots` (each slot ≥ 2 candidates; `preset=custom` is forbidden in slots).

A map pool of a game that declares the `mode` kind may also name catalog modes, in the shared pool only (never slots or reserves): an ingested match of another mode is refused (`mode_not_in_pool`), maps are checked against the map items alone, and the room vetoes the map items only.

Steps: `ban|pick|protect` × `first|second` plus `decider`. Hero sequences are always custom. Map + bracket preset → `buildSequenceForBestOf(bestOf, poolSize)`.

A session opens only when both sides are ready, the encounter is live, and (for hero round N) map N is settled. Progressive rounds: round 2 cannot ban before map 1 is played.

Cross-round memory is a rules condition, not a ledger table: a phase's `pool_filter` and a step's `eligible` read `banned_by` / `picked_by` leaves over `series`, `round` or `previous_round`. The legacy `no_repeat_scope` (`none` / `encounter` / `encounter_same_side`) compiles to a `banned_by` filter.

Role uniqueness for heroes (the legacy `unique_attribute_per_side_per_round = "role"`) compiles to a `max_per_group` constraint.

First pick: `higher_seed`. First-ban rotation includes `result_loser_choice` (previous map winner).

Undo requires both captains. Admins can override.

The pre-game room's organizer controls and history are hidden on entry. Authorized organizers
can show or hide them on the readiness, pick-ban, map-report and closing screens. While hidden,
the pool does not accept organizer-only selections; captain actions are unchanged. Visibility is
local to the open room, survives phase changes, and resets on reload or when opening another encounter.

---

## 9. Scrims

A hidden per-workspace container tournament. A room = one stage + two rosterless teams + one encounter, published immediately.

Creator takes slot 1. Slot 2 is claimed by token (the URL, not an invite). Cap of open rooms per user. Closing frees the slot; the room stays readable to participants.

The API returns the room as `teams[]` with slot numbers and `team_names`; the viewer's slot (`viewer_slot`) is server-authoritative (`Team.captain_id`).

---

## 10. Ranks and division grid

`member_rank` layers:

- `author_user_id IS NULL` = workspace canon (everyone sees it).
- Non-null = that account's private book, used only for **their** mixes. The two dictionaries are never merged.

Native snapshots (`rank.rank_snapshot`: Overwatch from OverFast, LoL Solo/Duo from the Riot API, Deadlock from deadlock-api) are normalised onto the owner's grid of the same discipline. Every grid belongs to a discipline; existing grids are Overwatch grids.

Grids are versioned. Cosmetic tier edits apply in place; structural edits spawn a version and auto-map from used sources of the same discipline. Activation requires complete mappings and an enabled discipline. A tournament may pin `division_grid_version_id` only from its own discipline and workspace (or a system grid). Otherwise the owner resolves its discipline's workspace default, then its discipline's system default.

Workspace defaults are independently persisted per `(workspace_id, discipline)`: activating Overwatch cannot replace the LoL default. Public workspace reads expose `default_division_grid_versions` (explicit selections only) and `effective_division_grid_versions` (resolved public version/tier payloads, including same-discipline persisted system fallback); the workspace list's rows carry only the former, and the frontend reads the current workspace's grids from its own single-workspace read. Missing persisted versions are omitted; native ladders remain module-owned. These replace the former singular ID/payload wire fields; grid activation, not workspace create/update, changes assignments.

Overwatch (45 tiers), LoL (31 league-v4 tiers), Deadlock (66 tiers: 11 × 6 subranks) and VALORANT (25 tiers: Iron 1 … Immortal 3, Radiant) declare native ladders: a new grid of any of them is seeded with its ladder, and a tournament or mix (including a clone) without a grid of its own falls back to its own game's ladder, never another game's. VALORANT has no native rank reader: its ranks are entered by organizers. A game without a native ladder needs a tiered grid of its own; missing or empty runtime grids return 422 `division_grid_required`.

Legacy public player/hero statistics and workspace-wide achievements still query Overwatch data, so their grid and normalization target remain explicitly Overwatch even in a LoL-first workspace. Generic workspace rank entrypoints continue to use the first enabled discipline. Tournament player sheets, autofill previews, and pick/ban crests carry the owner's resolved grid through nested controls; the player sheet exposes no rank controls until that owner scope is available. Grid administration renders native ladder bars, native-rank columns, and native crest fallbacks only for Overwatch, never for a LoL grid with or without an activated version. Activation and version-mapping explanations apply to the selected game.

The player editor resolves an explicit tournament grid pin before opening, even without a workspace default for that game. It reuses the overview's embedded version, or the existing version read/cache key when only the pin ID is available; pending or failed pins never fall through to another grid. History previews retain their workspace-normalized target and original source-tournament labels/crests. Applying history converts the normalized rank through that workspace scale, then resolves the edited division in the owner's grid. Numeric entry keeps open-ended tiers unbounded on blur; wholly finite grids retain their real maximum.

A missing `rank_max` in an embedded tournament response means the same open-ended bound as explicit `null`. Rank saves retain the registration's rated role dimension instead of reconstructing every preference as an Overwatch `player_role`.

Portable exports use `division-grid/v2` with `discipline`. User-held `division-grid/v1` files still import as Overwatch, translating `ow_rank_min/max` to `native_rank_min/max`; malformed shapes and conflicting old/new bounds are rejected. Marketplace and portable imports require the target workspace to enable the grid's discipline.

---

## 11. Logs, impact, achievements

Ingest (upload / gateway base64 / Discord): strict UTF-8, no path traversal, S3 **before** the DB row.

Dedup: `(tournament_id, filename, content_hash)` — identical bytes skipped. Same filename pending/failed → reuse, `attempts=0`.

Impact (pure, `stats-service/src/domain/match_logs/impact.py`):

- A fight starts on round change or a gap > 15s.
- FirstPick / FirstDeath from fight boundaries.
- Dominant role = max hero-seconds.
- Z-score vs role / role+rank baselines, winsorized, × time share.
- Flex and sub-`MIN_SECONDS` rows are not scored.
- `ImpactPoints` = role-only baseline; `OverperformanceScore` = role+rank.

Achievements: JSON condition tree (AND ∩, OR ∪, NOT complements the eligible universe at the inferred leaf grain). ~22 leaf types: stats, standings, bracket path (UB/LB, min LB wins, lost-in-round), MVP, newcomer, captain, revenge, streaks, OTP, teammate recurrence, …

Overwatch conditions read workspace-scoped native `stats` facts, match/game context and events. Stat and event comparisons use catalog codes; observed map winners come from participant score facts, while comeback order follows game position. Event actor/target members are converted explicitly to global player evaluation keys; identical events retain their multiplicity. Upload counts use actual ingest-job uploader, tournament hint and lifecycle state. Rule edits, imports and seeding derive native `depends_on` arrays from the tree (`stats.fact`, `stats.match`, `stats.event`, `stats.ingest_job`), never client arrays. Rule dependencies and evaluation/override match references are captured with transaction-bound evidence; mutations and cascades use bounded owner batches.

Time-weighted rate rankings reduce the observed rate × playtime products and playtime denominator in immutable `(match_id, workspace_member_id)` order. Workspace-wide and tournament-scoped queries therefore use the same arithmetic order rather than whichever join plan PostgreSQL chooses.

Effective set = evaluation ∪ grants − revokes (global / tournament / match precedence). Anchored on `workspace_member_id`.

Runner: `parse_complete` inline; `manual` / `rule_version_bump` on an unverified workspace is deferred. Each rule in a savepoint; a lost DB connection aborts the whole run. Empty/disabled tree wipes results. Incomplete division-grid mapping → 409.

---

## 12. Analytics

At most one pending/running job per workspace (partial unique → 409).

- **OpenSkill** Plackett-Luce: replay every encounter in time order, seeded from prior rating. Note: `get_matches_for_tournaments` historically returns **encounters**.
- **Points / Linear**: stable vs trend vs hybrid, confidence, log coverage. Persist only the target tournament's rows.
- **ML v2**: GBM residual, time-series split (validation = latest tournament), workspace hyperparameters. `train_ml` is superuser; `compute` is organizer.

Shift (`actual div − predicted`) feeds achievement `div_change` / `div_level`.

Match quality scores an encounter (competitiveness, predictability, skill balance) from series scores + pre-encounter team µ.

Feature extraction reads native `stats.fact` rows (segment 0, `entity_id IS NULL`) joined to `tournament.player` — a tournament-scoped roster, not `workspace_member`.

---

## 13. Streams, Discord, notifications

**Streams.** One Helix batch for all active tournaments. A partially rate-limited tournament is left untouched (TTL = 3× poll interval). Realtime fires only when the **set** of live channels changes, not viewer count. Hidden tournaments store state but emit nothing. Non-durable.

**Discord.** Only `.txt` / `.log` / `.json`. Already `done` → skip. Reactions ✅/⚠️/❌. Subscription resync from OAuth + workspace.

**Notifications.** Append-only, no FKs (must outlive the business rows). Audience `user | workspace | global` with CHECKs. `published_at` is distinct from `created_at` (scheduled announcements). Superuser does **not** bypass `user:{id}:notifications`. Platform-wide banners are superuser-only, not a workspace grant.

---

## 14. Cross-cutting policies

**Realtime scopes** (`backend/shared/services/realtime/scope.py`): tournament / workspace / user / encounter. Encounter carries data only (map-veto, hero pick-ban) — no invalidation topic. Hidden tournaments use spectate ACL. User inbox is self-only.

**Outbox.** The domain event is written in the same transaction as the mutation. The only sweeper is `tournament-svc` (one global table: while that worker is down, every service's events queue, they are not lost). At-least-once; consumers must be idempotent.

**Idempotency points:** invite consume, `advance_winner`, log content-hash, achievement differ, draft version CAS.

**Fail-open vs fail-closed:**

- Open: missing subscription credentials, accept rate-limit, unknown subscription stage → `check_in`.
- Closed: hidden tournament 404, elimination draw, empty roster shape, unpairable Swiss, draft with no safe pick → pause.

**Audit.** Admin writes → `record_admin_audit`. Encounter results: one audit row per transition, including cascade reset. Invite revoke distinguishes captain vs organizer.

---

## 15. Client (not authoritative)

Duplicates only what the UI needs instantly; comments cite the server symbol:

| Module | Rule |
| --- | --- |
| `frontend/src/lib/draft/logic.ts` | Event reducer; confirm only from server `safe` options + `pick_version` |
| `…/pickBanConfig.helpers.ts` | Cascade / template / `SLOT_CANDIDATE_FLOOR=2`; does **not** guess elimination round numbers |
| `…/roster-shape-editor.model.ts` | Only 2–12 to preempt a 422; `inherit` sends `null` |
| `frontend/src/hooks/usePermissions.ts` | RBAC mirror including deny and host ≠ admin panel |
| `…/tournament-checklist.ts` | Challonge slug skips registration-form checklist items; `null` readiness fields mean no-access, not zero |
| `frontend/src/proxy.ts` | Tenant host; client-supplied workspace headers are always stripped |

---

## 16. Rule → file

| Rule | Home |
| --- | --- |
| Tournament phases | `backend/shared/core/tournament_state.py` |
| Registration window | `backend/shared/services/registration_window.py` |
| Admission | `backend/tournament-service/src/services/admission/` |
| Roster shape / occupancy | `backend/shared/domain/roster_shape.py`, `team_roster.py` |
| Playable role | `backend/shared/domain/roster.py` |
| Rank layers | `backend/shared/domain/member_rank.py` |
| Team eligibility | `backend/shared/domain/team_eligibility.py` |
| Bracket gen / advance | `backend/shared/services/bracket/` |
| Result writer, scoring | `backend/shared/services/encounter/result.py`, `backend/shared/domain/encounter_scoring.py` |
| Log evidence acceptance | `tournament-service/src/services/encounter/log_evidence.py`, `…/log_evidence_events.py` |
| Pick-ban engine | `backend/shared/domain/pick_ban_engine.py`, `tournament-service/src/services/encounter/pick_ban_*` |
| Draft rules / clock | `balancer-service/src/domain/draft/`, `…/services/draft/clock.py` |
| Balancer objectives | `balancer-service/native/balancer_native/src/moo/objectives.rs`, mix: `…/src/mix.rs` |
| Mix rotation | `balancer-service/src/domain/mix_rotation.py` |
| RBAC | `backend/shared/rbac/catalog.py`, `backend/shared/models/identity/auth_user.py` |
| Visibility | `backend/shared/services/tournament/visibility.py` |
| Impact | `stats-service/src/domain/match_logs/impact.py` |
| Achievements | `stats-service/src/services/achievement/engine/`, `backend/shared/services/achievement_effective.py` |
| Standings | `tournament-service/src/services/standings/service.py` |
| Match row | `backend/shared/models/matches/match.py` |

---

## 17. End-to-end tournament

Announcement → registration window (solo or captain + invites + eligibility + subscription) → check-in (profile + sub) → balancer **or** draft → materialize `tournament.team` → generate bracket → LIVE encounters → pick-ban → map reports → finalize → advance → standings job → parse logs → impact → achievements → analytics shift.

Scrim and mix cut that pipeline: no standings materialize, same pre-game engine.
