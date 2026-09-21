# Shared room chat (draft + pre-game)

**Status:** draft

**Goal:** One chat that serves both live rooms — the draft room (`/draft/{tournamentId}`) and the pre-game room
(`/tournaments/{slug}/pregame/{encounterId}`) — backed by its own tables, with spectator read that organizers can switch off,
staff moderation (delete + mute), and the pre-game chat shipped on 2026-09-21 migrated onto it. That chat stores each message as a
durable `realtime.workspace_event` row; that was the right shape for one closed two-captain room and is the wrong shape for a
second room, for moderation, for a visibility toggle, and for retention.

**Architecture:** Three tables — `chat_message`, `chat_room` (per-room settings), `chat_mute` — addressed by a room key
`(room_kind, room_ref_id)`. One shared service `shared/services/chat/` owns them plus sanitizing, the throttle and the realtime
publish. **Who may participate is the only thing that varies**, so it is a protocol: tournament-service supplies the encounter
resolver, balancer-service supplies the draft-session resolver. Both mount the same six endpoints, so the wire shape is identical
and the frontend keeps ONE component, ONE hook and ONE service, parameterized by a room descriptor.

**Tech Stack:** Python 3.14 / FastStream / SQLAlchemy 2 / Alembic (backend), Go (gateway route table, realtime ACL, topic
re-authorization), Next.js 16 / react-query / next-intl / vitest (frontend).

---

## Why not keep riding `realtime.workspace_event`

The current pre-game chat writes durable domain events and reads history back off the `(topic, id)` index. It works, and for one
room it was the smaller diff. It does not survive the second room:

1. **Nothing can be deleted or hidden.** `workspace_event` is an append-only journal shared with invalidations and every other
   domain event. Staff "remove this message" has no write path there, and adding one would mean mutating a journal other
   consumers replay.
2. **Retention is all-or-nothing.** `purge_stale_realtime_events` deliberately refuses to touch pregame/draft topics — those
   sessions have no upper bound on duration, so a 7-day floor would cut a live one. Chat rows therefore accumulate forever inside
   the replay table that every subscribe reads.
3. **Two paginations fight.** The realtime cursor (`after_event_id`) and the chat's own "load older" want the same column for
   different purposes; the first-subscribe rule (`after == nil` → live-only) is correct for invalidations and wrong for a chat.
4. **No room for a column.** `author_role`, `deleted_at`, `deleted_by`, per-room `spectators_can_read` are chat facts. Inside
   `payload` JSONB they get no index and no constraint.

## Design

### Room addressing

```python
class ChatRoomKind(StrEnum):
    ENCOUNTER = "encounter"   # ref_id = tournament.encounter.id
    DRAFT     = "draft"       # ref_id = balancer.draft_session.id


@dataclass(frozen=True, slots=True)
class ChatRoom:
    kind: ChatRoomKind
    ref_id: int

    @property
    def topic(self) -> str:      # Scope(kind).domain_topic("chat")
        ...
```

| kind | ref | realtime topic | spectator read default |
|---|---|---|---|
| `encounter` | encounter id | `encounter:{id}:chat` | **off** — captains trade custom-lobby codes here |
| `draft` | **draft session** id | `draft:{session_id}:chat` | **on** — a draft is a show; viewers and casters follow it |

The draft room is the **session**, not the tournament: a session is the draft, and a re-seed is a different draft. A tournament
that drafts twice gets two conversations, which is what happened.

`ScopeKind.DRAFT` is new in `shared/services/realtime/scope.py`, added exactly like `ENCOUNTER`: a data-only scope with no
invalidation topic (`invalidation_topic` raises — whatever a draft write stales is a tournament-scoped resource).

### Tables

Default schema, model file `shared/models/platform/chat.py`, beside `notification` — ruling R1 of
`2026-09-07-notifications.md` already settled that a Postgres schema for a couple of tables whose sibling journals sit in `public`
would be a second convention.

```
chat_message
  id                       BIGSERIAL PK
  room_kind                VARCHAR(16)  NOT NULL
  room_ref_id              BIGINT       NOT NULL
  auth_user_id             BIGINT       NOT NULL     -- author
  author_name              TEXT         NOT NULL     -- snapshot; a rename keeps history readable
  author_role              VARCHAR(16)  NOT NULL     -- home | away | captain | staff
  body                     TEXT         NOT NULL
  created_at               TIMESTAMPTZ  NOT NULL DEFAULT now()
  deleted_at               TIMESTAMPTZ  NULL
  deleted_by_auth_user_id  BIGINT       NULL
  ix_chat_message_room     (room_kind, room_ref_id, id)                 -- history + "load older"
  ix_chat_message_author   (room_kind, room_ref_id, auth_user_id, id)   -- the throttle probe

chat_room                                  -- settings; the row exists only once something is not the default
  room_kind                VARCHAR(16)  NOT NULL
  room_ref_id              BIGINT       NOT NULL
  spectators_can_read      BOOLEAN      NOT NULL
  updated_by_auth_user_id  BIGINT       NOT NULL
  created_at / updated_at  TIMESTAMPTZ
  PRIMARY KEY (room_kind, room_ref_id)

chat_mute
  room_kind                VARCHAR(16)  NOT NULL
  room_ref_id              BIGINT       NOT NULL
  auth_user_id             BIGINT       NOT NULL     -- the muted account
  muted_until              TIMESTAMPTZ  NULL         -- NULL = until lifted
  reason                   TEXT         NULL
  created_by_auth_user_id  BIGINT       NOT NULL
  created_at               TIMESTAMPTZ  NOT NULL DEFAULT now()
  PRIMARY KEY (room_kind, room_ref_id, auth_user_id)
```

**No foreign keys** — the convention `audit_log`, `event_outbox`, `notification` and `realtime.workspace_event` already follow: an
append-only journal outlives the rows it talks about, and `ON DELETE CASCADE` on a tournament would take the record of what was
said with it. Cleanup is the retention job's, not the referent's.

**`author_role` is stored, not derived.** Who captained which side is a fact about the moment the message was sent; resolving it
at read time would relabel a whole history the instant an organizer swaps a captain.

**`chat_room` is lazily materialized.** No row means "the kind's default", so nothing has to create a room up front and a draft
that nobody reconfigures costs zero rows. The composite PK makes the toggle an idempotent upsert.

**Mutes are per room, not global.** A captain who has to be silenced in one draft has done nothing in the next tournament's
pre-game room. `muted_until NULL` is the indefinite mute; expiry is evaluated at read time (`muted_until IS NULL OR muted_until > now()`),
never by a sweeper — an expired row is simply inert and the retention job collects it.

### Permissions

One resolver per room kind, living where the domain data does. It returns a `ChatMembership`, never a bare boolean:

```python
@dataclass(frozen=True, slots=True)
class ChatMembership:
    role: str          # home | away | captain | staff | spectator
    can_write: bool
    can_moderate: bool
    muted_until: datetime | None
```

| room | writers | moderators | spectators (read-only) |
|---|---|---|---|
| `encounter` | captain of home/away, workspace member, superuser | workspace member, superuser | anyone who may view the encounter, **iff** `spectators_can_read` |
| `draft` | captain of a `draft_team` of the session, workspace member, superuser | workspace member, superuser | anyone who may view the tournament, **iff** `spectators_can_read` |

"May view" is the existing hidden-tournament rule (`allowSpectate`), so a hidden tournament's chat stays invisible regardless of
the toggle. Anonymous visitors count as spectators — the draft room already serves them, and presence already counts them
separately.

A muted author gets 403 `chat_muted` with `muted_until` in the detail; the composer disables itself from the same field carried in
the `GET` envelope, so the muted user is told rather than silently failing.

### Delivery

Realtime stays the transport, with **non-durable** events (`durable=False`, `event_id=0`, no `workspace_event` row): the table is
the history now, and persisting each message twice would put the replay cursor and the chat's own `after_id` pagination in charge
of the same thing.

| event | payload | audience |
|---|---|---|
| `chat.message` | `{id, auth_user_id, author_name, author_role, body, created_at}` | everyone on the topic |
| `chat.message_deleted` | `{id}` | everyone on the topic |
| `chat.muted` / `chat.unmuted` | `{auth_user_id, muted_until, reason}` | everyone on the topic |
| `chat.visibility_changed` | `{spectators_can_read}` | everyone on the topic |

Catch-up after a disconnect is `GET …/chat?after_id=<last id on screen>`, fired from `useRealtimeTopic`'s existing `onSubscribed`
callback — the pattern `useRealtimeCoalescedRefetch` already uses. Strictly better than cursor replay: it also repairs a gap from
a dropped Redis publish, which at-most-once pub/sub can produce with no reconnect at all.

### Revoking a subscription when the organizer hides the chat

The gateway checks the topic ACL **at subscribe time only**. Flipping `spectators_can_read` to false therefore does not, by
itself, stop a spectator who is already subscribed from receiving everything said afterwards — which is precisely the case the
toggle exists for. A cooperative client-side unsubscribe is not a boundary.

So the visibility event drives a real re-authorization in the gateway:

- `ws.NewTopicRevoker(hub, authz, log)` implements `events.Broadcaster` and is registered in the existing
  `events.Fanout(hub, cache, revoker)` — the same subscription that already carries every realtime frame.
- On a frame whose `event.event_type` is `chat.visibility_changed`, it re-runs `authz.Allow` for every connection currently
  subscribed to that topic, unsubscribes the ones now denied and sends them a `forbidden` error frame.
- Bounded work: one ACL call per subscriber of one topic, only when an organizer clicks. The ACL's own TTL cache is bypassed for
  this path (or given a short TTL for `chat_room`, see below) so the re-check reads the new value, not the cached old one.

`Store.RoomSpectatorRead` is cached with a **15 s** TTL — short, because it gates a deliberate, observable action, and the
re-check above must not be answered from a stale entry. The toggle write also invalidates the entry it is about to contradict via
the same `chat.visibility_changed` path.

### Wire shape (identical for both rooms)

```
GET    X/chat?after_id=&limit=            AuthOptional  → ChatEnvelope
POST   X/chat            {"body"}          AuthRequired  → ChatMessage
DELETE X/chat/{message_id}                 AuthRequired  → {"deleted": true}
PATCH  X/chat/settings   {"spectators_can_read"}  AuthRequired → ChatSettings
PUT    X/chat/mutes/{auth_user_id}  {"minutes"|null, "reason"}  AuthRequired → ChatMute
DELETE X/chat/mutes/{auth_user_id}         AuthRequired  → {"deleted": true}
```

```ts
interface ChatEnvelope {
  messages: ChatMessage[];                 // oldest-first, limit ≤ 200, default 50
  settings: { spectators_can_read: boolean };
  viewer: { role: ChatRole; can_write: boolean; can_moderate: boolean; muted_until: string | null };
  mutes: ChatMute[];                       // moderators only; [] for everyone else
}
```

The `GET` returns everything the panel needs in one round trip — messages, whether this viewer may type, whether they are muted,
whether spectators can see it, and (for a moderator) who is currently muted.

| | tournament-service base | balancer-service base |
|---|---|---|
| path | `/api/v1/encounters/{encounter_id}/chat` | `/api/v1/balancer/draft/sessions/{session_id}/chat` |
| queues | `rpc.tournament.encounter_chat_{history,post,delete,settings,mute_set,mute_clear}` | `rpc.balancer.draft.chat_{history,post,delete,settings,mute_set,mute_clear}` |

`backend/tests/test_rpc_route_parity.py` scans the Go `Queue:` literals against the Python subject literals, so a route and its
subscriber ship in the same task or the suite fails.

### Limits (moved verbatim out of the shipped pre-game chat into the shared service)

- body: raw > 2000 → 422; C0/C1 controls except `\n` stripped; 3+ consecutive newlines collapsed to 2; empty after strip or > 500 → 422.
- throttle: 10 messages / 10 s per author per room → 429, as a single indexed probe over `ix_chat_message_author` — "the author's
  10th-newest message in this room, is it younger than `now() - 10s`?".

### Retention

New daily job `chat_message_purge` in tournament-service's scheduler, beside `realtime_workspace_event_purge`: delete
`chat_message` older than 90 days, and `chat_mute` rows whose `muted_until` expired more than 90 days ago. Room chatter has a
short useful life; the record of what was *decided* lives in `encounter_result_audit` / `draft_audit_event`, not here. `chat_room`
rows are tiny and are left alone.

### Cutover of the shipped pre-game chat

The alembic revision copies the existing rows in the same transaction that creates the tables:

```sql
INSERT INTO chat_message (room_kind, room_ref_id, auth_user_id, author_name, author_role, body, created_at)
SELECT 'encounter',
       split_part(topic, ':', 2)::bigint,
       actor_user_id,
       COALESCE(payload->>'author_name', 'unknown'),
       COALESCE(payload->>'author_side', 'staff'),
       payload->>'text',
       occurred_at
FROM realtime.workspace_event
WHERE event_type = 'chat.message' AND actor_user_id IS NOT NULL AND payload ? 'text';
```

`purge_stale_realtime_events` gains `'%:chat'` so the copied originals age out. `services/encounter/chat.py` is deleted outright —
no shim, no dual write.

## Rulings

- **R1 — mutes are in.** Per room, indefinite or timed, moderator-only, evaluated at read time. (Superseded the earlier "defer
  mute" call: with spectators reading, the room is no longer two people who can be asked to stop.)
- **R2 — spectators read by default in the draft room, and organizers can switch it off per room.** Same mechanism in the pre-game
  room with the default inverted, so an organizer can *open* a pre-game chat for a broadcast. Spectators never write, in either
  room, at any setting.
- **R3 — the draft room is the draft session.** A re-seed starts a new conversation with the new draft.
- **R4 — non-durable events.** Reverses the shipped chat's `durable=True`. Two histories of the same thing is the bug being removed.
- **R5 — backfill, not drop.** The pre-game chat shipped today; if it is deployed, its messages are real. The copy is 8 lines of
  SQL in the migration that has to run anyway.
- **R6 — hiding the chat revokes live subscriptions server-side.** A client-side unsubscribe would make the toggle advisory.

## Tasks

Each task is independently committable and names its own check. No project-wide formatters/linters/suites per task.

### 1 — scope, tables, migration
`shared/services/realtime/scope.py` (`ScopeKind.DRAFT` + `Scope.draft()`), `shared/models/platform/chat.py`, the two
`__init__.py` exports, new alembic revision creating `chat_message` (+2 indexes), `chat_room`, `chat_mute`, and running the R5
backfill. Regenerate `backend/docs/schema.sql` / `schema.dbml` with the repo's export script.
**Check:** `alembic upgrade head` → `downgrade -1` → `upgrade head` on a scratch DB; the schema-export diff contains only the three
tables. Plus a unit test that `Scope.draft(7).domain_topic("chat") == "draft:7:chat"` and that its `invalidation_topic` raises.

### 2 — repository
`shared/repository/chat.py`: `ChatMessageRepository` (`history(room, after_id, limit)` oldest-first excluding deleted,
`throttle_probe`, `soft_delete`), `ChatRoomRepository` (`get`, `upsert`), `ChatMuteRepository` (`active_for`, `list_active`,
`set`, `clear`). Export from `shared/repository/__init__.py`.
**Check:** `pytest backend/tests/test_chat_repository.py` — history windowing, deleted exclusion, an expired mute reading as
inactive, upsert idempotence. Fake-session style of `backend/tests/test_stream_repository.py`.

### 3 — shared service
`shared/services/chat/{__init__,room,access,service,schemas}.py`.
- `room.py` — `ChatRoomKind`, `ChatRoom`, `topic`, per-kind `default_spectators_can_read`.
- `access.py` — `ChatMembership`, `ChatAccess` protocol: `resolve(session, auth_user, room) -> ChatMembership` (403 when the
  viewer may not even see the room).
- `service.py` — `ChatService(access)` with `history` / `post` / `delete` / `set_settings` / `set_mute` / `clear_mute`; sanitize,
  throttle, mute check, `emit(..., durable=False)`, commit.
- `schemas.py` — `ChatMessageRead`, `ChatEnvelope`, `ChatSettings`, `ChatMute`, `ChatPostInput`, `ChatMuteInput`.
Lifts the sanitizer and throttle out of `tournament-service/src/services/encounter/chat.py` verbatim.
**Check:** `pytest backend/tests/test_chat_service.py` — spectator read allowed/denied by the setting, spectator write always 403,
muted author 403 with `muted_until`, expired mute writes fine, 11th message 429, delete refused for a non-author without
`can_moderate`, `chat.visibility_changed` emitted on a real change and not on a no-op write.

### 4 — tournament-service cutover
`src/services/encounter/chat_access.py` (resolver lifted from today's `chat.py`, extended with the spectator branch), delete
`src/services/encounter/chat.py`, rewire + add the four new subscribers in `rpc/public_rpc.py`, rewrite
`tests/test_encounter_chat.py` against the new shape.
**Check:** `pytest tournament-service/tests/test_encounter_chat.py`.

### 5 — balancer-service draft chat
`src/services/draft/chat_access.py` — captain via `DraftTeam.captain_auth_user_id` on `session_id`, staff via the existing
`_get_draft_session_workspace_id`, spectator via the tournament's visibility. Six subscribers in `src/rpc/draft.py`.
**Check:** `pytest balancer-service/tests/test_draft_chat.py` — a captain of another session refused as writer but admitted as
spectator while the toggle is on, and refused entirely once it is off; staff get `can_moderate`.

### 6 — gateway ACL + routes
`internal/workspace/workspace.go`: `IsDraftSessionCaptain(authUserID, sessionID)`
(`SELECT EXISTS(SELECT 1 FROM balancer.draft_team WHERE session_id=$1 AND captain_auth_user_id=$2)`),
`DraftSessionTournamentID(sessionID)`, `RoomSpectatorRead(kind, refID)` (15 s TTL, falls back to the kind default when no row).
`internal/acl/acl.go`: rules `draft:*:chat` and the widened `encounter:*:chat` — participant, or spectator when the room allows it
and the tournament is not hidden. Route specs: four new encounter routes in `internal/tournament/public_routes.go`, six draft
routes in `internal/balancer/routes.go` (`GET` is `AuthOptional`, the rest `AuthRequired`).
**Check:** `go test ./internal/acl/... ./internal/workspace/... ./internal/tournament/... ./internal/balancer/...` and
`pytest backend/tests/test_rpc_route_parity.py`.

### 7 — gateway subscription revocation (R6)
`internal/ws/revoke.go`: `TopicRevoker` implementing `events.Broadcaster`; `Hub.SubscribersOf(topic) []*Conn`; wire into the
existing `events.Fanout(...)` in `cmd/gateway/main.go`.
**Check:** `go test ./internal/ws/...` — a table test with two connections (participant + spectator) on one topic: a
`chat.visibility_changed{false}` frame leaves the participant subscribed and drops the spectator with a `forbidden` frame.

### 8 — retention
`tournament-service/serve.py`: `chat_message_purge` daily job (90 days, messages + long-expired mutes), `'%:chat'` added to
`purge_stale_realtime_events`, README scheduler table updated.
**Check:** extend `tests/test_bracket_event_retention.py` with the chat patterns.

### 9 — frontend: generalize the chat
`src/types/chat.types.ts` (`id`, `author_role`, `body`, plus `ChatEnvelope`/`ChatSettings`/`ChatMute`),
`src/lib/chat-rooms.ts` (`encounterChatRoom(id)`, `draftChatRoom(sessionId)` → `{ topic, basePath }`),
`src/services/roomChat.service.ts` (six calls against a room descriptor),
`src/components/chat/useRoomChat.ts` — `after_id` catch-up on `onSubscribed`, handles `chat.message_deleted` / `chat.muted` /
`chat.unmuted` / `chat.visibility_changed`, exposes `canWrite` / `canModerate` / `mutedUntil` / `settings`.
`RoomChat` — read-only mode for spectators (no composer, a "read-only" note), a muted note with the expiry, a delete affordance on
hover for moderators, a mute action on a message's author, and a visibility switch in the header for moderators.
**Check:** `vitest run src/components/chat`.

### 10 — frontend: mount points
Draft: `src/components/draft/DraftBoard.tsx`, keyed by `board.session.id` (the panel simply does not exist before a session does).
Admin: `src/app/admin/tournaments/[id]/components/draft/AdminControlRoom.tsx`, so organizers talk to captains from where they run
the draft. Pre-game: the existing wrapper in `PregameRoom.tsx`, switched to the room descriptor.
**Check:** `vitest run src/components/draft "src/app/(site)/tournaments/[slug]/pregame"`.

### 11 — i18n
Move `pickBan.room.chat.*` to a top-level `chat.*` namespace (both rooms share every string), add role labels, delete/mute/
visibility strings and the read-only + muted notices, register `chat` in `src/i18n/zone-namespaces.json` for **both** the `web`
and `admin` zones (task 10 mounts it in each).
**Check:** `bun test src/i18n/messages.parity.test.ts src/i18n/plural-messages.test.ts` and `node scripts/check-zone-boundaries.mjs`.

### 12 — visual + live pass
Both rooms in a real browser at 1280 and 390: message list, spectator read-only view, an organizer hiding the chat and the
spectator tab losing it live, mute → the muted composer, delete, catch-up after a forced socket drop.
**Check:** screenshots; no throwaway route left behind.

## Non-goals

Message edits · reactions · typing indicators · unread badges · `@mentions` · attachments and images · tombstones for deleted
messages · a report/abuse flow · profanity filtering · direct messages between users · search over history · exporting a
transcript · a global (cross-room) ban list.
