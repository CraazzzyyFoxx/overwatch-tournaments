# Stream chronology: match timestamps without a timezone in the log: release note

POV recordings now get match timestamps on tournaments whose match logs carry no time zone — every Overwatch log on
production so far. The time comes from the log's file name or from the pre-game room.

Why: the first release (`2026-10-25-stream-chronology.md`) cut map chapters only from a log's own start time. A
Workshop log carries none in a time zone, so the decoder stores the upload time. The chronology rightly discarded
that time, and organizers do not set a match start by hand. On MoonRise Mix Vol.5 none of the 50 logged maps had a
usable start, and six live POV streams got no chapters.

## Backend
* **A map's start**, the first source that answers (`stream-service/src/domain/chronology.py`):
  1. the log's own start, unless it equals the upload time (the decoder's fallback);
  2. the log's file name, `Log-YYYY-MM-DD-HH-MM-SS.txt`, which is on the host PC's local clock:
     - the UTC offset is a whole hour, because hosts differ: one tournament had +2, +3, +5, +7 and +8;
     - it is the offset that starts the map nearest the moment the pre-game room finished that round's bans;
     - without a room, it is the latest start that still ends the map before the earliest of: its reported result,
       the series confirmation, the upload;
  3. no usable log: the moment the pre-game room finished the round's bans. This is 30 s to 2 min before the map,
     on the safe side. The game's reported result marks the map's end.
* **A series chapter**, when no map of the encounter could be timed, starts at the pre-game room's opening (the
  earliest pick-ban session start), else at the last readiness confirmation, else at the organizer's start. It ends
  at the organizer's end, else at the result confirmation.
* **Reads**: `StreamChronologyRepository` gains `games` (live positions with their decided map and result time),
  `round_ends` (the room journal's last `step_revealed`/`step_auto_resolved` per round) and `pregame_starts`.
  `logged_maps` now returns every log with its upload time and file name; which source wins is the domain's rule.
* Chapters are computed at read time, so logs and rooms already recorded count right away.

### Validation on production data
* A dry run of the file-name rule on all 28 logged encounters of MoonRise Mix Vol.5, anchored on the series
  confirmation and the upload alone (no room data), put most series' last map 1–8 minutes before its confirmation,
  25 minutes at most.
* Each team's host kept one offset across its matches.
* Where the room was visible, the map started within a minute of its round's bans.

## Known limits
* A host in a :30/:45 time zone lands that remainder off.
* Without a pre-game room, when a map's result, the series confirmation and the log upload all came more than an
  hour after the map ended, the map lands an hour off.
