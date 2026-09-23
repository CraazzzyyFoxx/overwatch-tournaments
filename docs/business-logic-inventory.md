# Business-logic inventory

Canonical map of **domain rules**, not HTTP plumbing. Architecture and request flow live in [`architecture.md`](./architecture.md); vocabulary in [`glossary.md`](./glossary.md); identity in [`users-identity.md`](./users-identity.md); tables in [`database_erd.md`](./database_erd.md).

Authority is the server. The frontend duplicates a few gates for UX and cites the Python symbol it mirrors.

Decoupling the statistical engine from the tournament engine is a separate intention: [`plans/2026-09-13-decouple-stats-from-tournament.md`](./plans/2026-09-13-decouple-stats-from-tournament.md).

---

## 0. Where logic lives

One PostgreSQL database, one SQLAlchemy metadata (`backend/shared`). Domain boundaries are Postgres schemas: `auth`, `players`, `public`, `tournament`, `matches`, `overwatch`, `overwatch_rank`, `balancer`, `achievements`, `analytics`, `log_processing`, `realtime`, `subscriptions`.

| Owner | Decides |
| --- | --- |
| `tournament-svc` | Tournament lifecycle, registration, brackets, results, pick-ban, scrims, outbox sweeper |
| `balancer-svc` | NSGA-II / mix balance, live draft, custom games |
| `identity-svc` | JWT, OAuth, RBAC, hostnames, API keys, player linking |
| `parser-svc` | Match logs, impact/MVP, achievements, OverFast ranks |
| `analytics-svc` | OpenSkill / linear / ML shifts |
| `app-svc` | Public reads: players, stats, catalogs, assets |
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
- Self-service link requires Discord/Battle.net OAuth **and** a handle intersection with `social_account`; otherwise 403; another owner → 409.
- Unlink is blocked while the account holds any workspace role other than `player` (otherwise an orphan `workspace_member` that admin lists cannot see, because those lists require `auth_user_id IS NOT NULL`).

---

## 2. RBAC

Grant-only catalog + workspace system roles + a **deny overlay** that beats every grant, including superuser. Catalog: `backend/shared/rbac/catalog.py`. Evaluation: `AuthUser.has_workspace_permission`.

| Role | Grants |
| --- | --- |
| `owner` | `admin.*` |
| `admin` | Everything except governance (`role` / `permission`) and `workspace.delete` / `workspace_member.delete` |
| `host` | Member reads + full `custom_game` CRUD (this **is** the right to run a mix) |
| `member` | `*.read` on `_MEMBER_READ_RESOURCES` |
| `player` | Empty |

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

Rank resolution (`pick_rank`, first non-null layer wins):

- Tournament: `registration → workspace → ow`
- Mix: `author → workspace → ow`

Absence of a row is inheritance. A stored `0` would break fall-through, so writes delete rather than zero.

### Admission

Two requirements, fixed order (`backend/shared/services/admission/registry.py`):

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
- Overflow: `must_play` always kept (error if they exceed slots); optional players trimmed by `rotation_priority`.
- Captains pinned; roles assigned by backtracking that never evicts a captain.

**Tournament balancer** (Rust NSGA-II, N teams): MMR gap (tax-bracket rates 1/3/8/18/40), tank gap (1/3/8/20), intra-std, discomfort, sub-role collisions (weight 24/pair), low-rank pairs (250/pair), role-line, pain. Hard `time_limit_ms` (default 600s). Discomfort: 0 flex, `pref×100`, 1000 playable-unpreferred, 5000 unplayable.

**Mix balancer** (C++ brute force, exactly 2 teams, Linux): comfort/fairness tilt; retry without `balance_limit` if empty; dedupe mirrored seatings.

Captains: top N by `(-max_rating, uuid)`.

### Live draft

Session: `setup → ready → live ⇄ paused → completed | cancelled`.

Formats: `snake | linear | custom`. Custom round rules: linear / reverse / weakest / strongest / `team_avg_asc` / `team_avg_desc`. Captain order: manual / weakest / strongest / random (Mulberry32, seed in settings).

Clock is **server-authoritative** (Redis lock, 10s TTL). Manual pick vs autopick is one conditional `UPDATE (on_clock AND version)`; the loser gets 409.

Autopick only from feasibility-safe `(player, role)`:

- Bipartite matching of remaining slots.
- A hypothetical pick is tested **before** apply so it cannot starve another team's slot.
- No safe choice → pause `role_shortage`, never force-pick.
- `team_avg_*` re-seats on round start and pauses with `order_recalculated`.

Strategies: `best_fit` (default), `best_available`, `role_need`. Fit is deliberately simpler than the balancer.

### Mix / custom game

`MixStatus`: draft / balanced / completed / cancelled. Participation: `must_play` / `pool` / `benched`.

Rotation (`mix_rotation.py`): longest sit-out streak → shortest played streak → fewest games → input order. `must_play` always seated. No history, or the whole pool fits → all `NEUTRAL` (do not invent fairness).

Caps: 8 teams, 16 co-hosts. Host role required (`custom_game.*`).

---

## 7. Stages, brackets, standings

`StageType`: `round_robin` | `single_elimination` | `double_elimination` | `swiss`.

Stage lifecycle: `DRAFT` (no encounters) → `PREVIEW` (encounters exist, not published) → `LIVE` (published/active) → `DONE`.

Generation (`backend/shared/services/bracket/engine.py`):

- Round-robin: circle method, BYE skipped, **no** advancement edges.
- SE/DE: skeleton + `EncounterLink` (winner/loser → home/away). The bracket **is** those edges, not an implied tree.
- DE: optional lower-bracket seeds (group runners-up). Grand Final Reset is **lazy**: only if the LB champion wins the GF.
- Swiss: Monrad, sort `(points, buchholz)`. Rematch-free first; rematch only if the alternative is idle teams. Bye not to a team that already had one. Unpairable field → error.

**Advancement** (`advance_winner`): only `COMPLETED` and not a draw. Idempotent if the target slot already holds the same team. A changed winner cascade-resets downstream results.

A draw cannot complete an elimination encounter.

**Standings** count only **closed** rounds (no playable encounter in that scope still open — otherwise FORM runs ahead of W·D·L):

Scoring: `win_points` / `draw_points` / `loss_points` from the tournament, stage override allowed. Swiss bye uses `swiss_bye_points` (default = win).

Computed: W/D/L, points, score differential, Buchholz + median Buchholz, head-to-head inside a points bucket, `tie_group`, manual positions.

Jobs: `tournament_bracket_jobs` / `tournament_standings_jobs`, prefetch 4, isolated from the RPC channel.

---

## 8. Encounters, reports, pick-ban

Encounter status: `OPEN | PENDING | COMPLETED`. Result status includes `none | confirmed | disputed`. Match provenance: `log_parser | captain_report | …`.

Two report layers:

1. **Per-map** (`EncounterMapReport`) — drives the series and the next ban opener. Both sides agreeing writes a `Match` with `source=captain_report`. Disagreement → dispute + organizer notification. Key is `(encounter, map_id, map_index, team)` because the same map can be played twice.
2. **Series** (`EncounterCaptainReport`) — after the series. Once `confirmed`, only an admin can change it. Disabled form fields are dropped, not 422.

A preview bracket rejects writes (409).

A **scrim** uses per-map reports to run the series engine but **does not write** `matches.match`; standings are not recalculated.

### Pick-ban

Kinds: `map` | `hero`. Config cascade: tournament → stage → round. An empty pool is a rules **template** and does not open a session.

Modes: `pool` | `slots` (each slot ≥ 2 candidates; `preset=custom` is forbidden in slots).

Steps: `ban|pick|protect` × `first|second` plus `decider`. Hero sequences are always custom. Map + bracket preset → `buildSequenceForBestOf(bestOf, poolSize)`.

A session opens only when both sides are ready, the encounter is live, and (for hero round N) map N is settled. Progressive rounds: round 2 cannot ban before map 1 is played.

`no_repeat_scope`: `none` / `encounter` / `encounter_same_side`. Protects are never written to the ledger.

`unique_attribute_per_side_per_round`: currently `"role"` for heroes.

First pick: `higher_seed`. First-ban rotation includes `result_loser_choice` (previous map winner).

Undo requires both captains. Admins can override.

---

## 9. Scrims

A hidden per-workspace container tournament. A room = one stage + two rosterless teams + one encounter, published immediately.

Creator takes home. Away is claimed by token (the URL, not an invite). Cap of open rooms per user. Closing frees the slot; the room stays readable to participants.

Viewer side is server-authoritative (`Team.captain_id`).

---

## 10. Ranks and division grid

`member_rank` layers:

- `author_user_id IS NULL` = workspace canon (everyone sees it).
- Non-null = that account's private book, used only for **their** mixes. The two dictionaries are never merged.

Overwatch snapshots (OverFast) are normalised onto the workspace grid.

Grids are versioned. Cosmetic tier edits apply in place; structural edits spawn a version and auto-map from every used source. Activation requires complete mappings. A tournament may pin `division_grid_version_id`.

---

## 11. Logs, impact, achievements

Ingest (upload / gateway base64 / Discord): strict UTF-8, no path traversal, S3 **before** the DB row.

Dedup: `(tournament_id, filename, content_hash)` — identical bytes skipped. Same filename pending/failed → reuse, `attempts=0`.

Impact (pure, `parser-service/src/domain/match_logs/impact.py`):

- A fight starts on round change or a gap > 15s.
- FirstPick / FirstDeath from fight boundaries.
- Dominant role = max hero-seconds.
- Z-score vs role / role+rank baselines, winsorized, × time share.
- Flex and sub-`MIN_SECONDS` rows are not scored.
- `ImpactPoints` = role-only baseline; `OverperformanceScore` = role+rank.

Achievements: JSON condition tree (AND ∩, OR ∪, NOT complements at **user** grain even if the leaf is `user_tournament`). ~22 leaf types: stats, standings, bracket path (UB/LB, min LB wins, lost-in-round), MVP, newcomer, captain, revenge, streaks, OTP, teammate recurrence, …

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

Feature extraction joins `matches.statistics` (round 0, `hero_id IS NULL`) to `tournament.player` on `(team_id, tournament_id)` — a tournament-scoped roster, not `workspace_member`.

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
| `frontend/src/middleware.ts` | Tenant host; client-supplied workspace headers are always stripped |

---

## 16. Rule → file

| Rule | Home |
| --- | --- |
| Tournament phases | `backend/shared/core/tournament_state.py` |
| Registration window | `backend/shared/services/registration_window.py` |
| Admission | `backend/shared/services/admission/` |
| Roster shape / occupancy | `backend/shared/domain/roster_shape.py`, `team_roster.py` |
| Playable role | `backend/shared/domain/roster.py` |
| Rank layers | `backend/shared/domain/member_rank.py` |
| Team eligibility | `backend/shared/domain/team_eligibility.py` |
| Bracket gen / advance | `backend/shared/services/bracket/` |
| Finalize + no-draw | `backend/shared/services/encounter/finalize.py` |
| Pick-ban engine | `backend/shared/services/pick_ban_engine.py`, `tournament-service/src/services/encounter/pick_ban_*` |
| Draft rules / clock | `balancer-service/src/domain/draft/`, `…/services/draft/clock.py` |
| Balancer objectives | `balancer-service/native/tournament_balancer/src/objectives.rs` |
| Mix rotation | `balancer-service/src/domain/mix_rotation.py` |
| RBAC | `backend/shared/rbac/catalog.py`, `backend/shared/models/identity/auth_user.py` |
| Visibility | `backend/shared/services/tournament/visibility.py` |
| Impact | `parser-service/src/domain/match_logs/impact.py` |
| Achievements | `parser-service/src/services/achievement/engine/`, `backend/shared/services/achievement_effective.py` |
| Standings | `tournament-service/src/services/standings/service.py` |
| Match row | `backend/shared/models/matches/match.py` |

---

## 17. End-to-end tournament

Announcement → registration window (solo or captain + invites + eligibility + subscription) → check-in (profile + sub) → balancer **or** draft → materialize `tournament.team` → generate bracket → LIVE encounters → pick-ban → map reports → finalize → advance → standings job → parse logs → impact → achievements → analytics shift.

Scrim and mix cut that pipeline: no standings materialize, same pre-game engine.
