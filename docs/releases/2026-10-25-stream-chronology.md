# Stream chronology: match timestamps in participants' POV recordings: release note

When a participant streams their POV on Twitch, the platform now remembers the broadcast and shows, for its Twitch
recording, where each of their team's matches starts: "0:45:10 — Alpha vs Bravo · Map 2 · King's Row". The timestamps
are on the tournament's **Stream** tab, under **Past broadcasts**, and on the match page, under **Watch the match**.

Why: a POV stream is the only footage of most matches, and finding a match in a four-hour recording meant scrubbing.

## Scope
* Participants' POV streams only: the channels stream-svc already polls with consent (`stream_pov` + the Twitch
  identity, or a verified public Twitch account; the `stream_visible` veto outranks both). Official casts, mixes and
  YouTube are out of scope.
* Only broadcasts seen live after this release. Twitch does not expose a past stream's exact start, so there is no
  backfill.

## Backend
* **`stream.session`** (migration `strchron01`, the first table stream-svc owns): one row per participant POV broadcast
  per tournament, unique on `(tournament_id, stream_id)`. The poll tick upserts it for every live POV channel with the
  Helix stream id, broadcaster id and `started_at`, moving `last_seen_at` on each tick.
* **VOD sync**, at the end of every poll tick, active tournaments or not:
  - a broadcast seen in the last 24 h without a VOD is matched through `GET /videos?user_id=…&type=archive` on
    `video.stream_id` (one call per broadcaster, ≤ 20 a tick, each retried at most every 10 minutes). The archive
    exists while the stream is live, so timestamps appear during the broadcast;
  - resolved VODs are re-checked daily with `GET /videos?id=…` (100 ids a call, ≤ 5 calls a tick); a VOD Twitch no
    longer returns gets `vod_gone_at` and disappears from every read;
  - Helix failures are logged and never change the recorded tick status; every call respects the shared
    `Ratelimit-Remaining` floor.
* **Chapters** (`stream-service/src/domain/chronology.py`), per encounter of the streamer's team(s):
  - one chapter per logged map with a trustworthy start (`stats.match.played_at`; a `played_at` equal to its ingest
    job's `created_at` is the decoder's no-timestamp fallback and is skipped);
  - otherwise one series chapter from the organizer's `encounter.started_at`; `scheduled_at` and `confirmed_at` are
    never used;
  - the broadcast covers `[started_at − delay, last_seen_at − delay]`; a map already running when the stream began
    links to 0:00.
* **`tournament.tournament.pov_stream_delay_s`** (0..900, default 0): the delay the tournament's rules require of POV
  streams, added to every timestamp. In `TournamentRead`/`TournamentUpdate` (`tournament.update`).
* **Reads**, public, gated like the live block (a hidden tournament answers 404), consent re-applied on every read:
  - `rpc.stream.tournament_vods` — `GET /api/v1/streams/tournament/{tournament_id}/vods`: every alive VOD with at least
    one chapter, newest first;
  - `rpc.stream.encounter_vods` — `GET /api/v1/streams/encounter/{encounter_id}/vods`: only that encounter's chapters;
    an unknown encounter is 404, a mix encounter an empty list.

## Gateway
* The two routes above, `AuthOptional`, on the anonymous TTL response cache like the live read.

## Frontend
* **Stream tab:** a **Past broadcasts** section; a chapter plays the VOD from that moment in the page's player
  (`player.twitch.tv/?video=v<id>&time=…`), or opens it on Twitch. The tab now also shows after the tournament ends,
  as long as a recording with timestamps exists.
* **Match page:** **Watch the match** lists both teams' POV recordings with their timestamps, linking to Twitch.
* **Admin → tournament settings → Links:** the **POV stream delay** field.

## Docs
* Player guide (tournaments, Streams), organizer guides (first tournament → Links, Collectors → Streams and its
  troubleshooting), `stream-service` README, architecture and ERD.
