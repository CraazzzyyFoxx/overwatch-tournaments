# Overwatch career reads and admission signals: release note

**What changes.** Two reads over the career the OverFast poll collects (see
[`2026-11-16-overfast-career.md`](./2026-11-16-overfast-career.md)):

- `GET /api/v1/users/{id}/career` (public). Covers every Overwatch account shown on the player's public profile; a
  hidden account is left out. For each account it returns:
  - its game profile: name, avatar, namecard, title, endorsement level, and whether the profile is open now;
  - per platform and queue, the career as the game shows it now: time, games, winrate, per-10-minute rates, roles
    with their pool size and mains, and heroes.

  Competitive covers the current season only. A closed profile shows no career, even if one was collected while it
  was open.
- `GET /api/v1/admin/rank/career-signals?user_id=…` (`rank.read`, scoped by `workspace_id`, up to 200 players).
  For each player it returns:
  - current-season competitive role shares, hours, and the last time the profile changed;
  - signals:
    - `profile_not_found`;
    - `previously_found`: the tag resolved before, so the account was likely renamed;
    - `profile_private`;
    - `never_collected`;
    - `renamed`: read by the Blizzard id under another name;
    - `low_hours_high_rank`: under 60 hours at Diamond 5 or above;
    - `inactive`: the profile has not changed for 30 days.

**Migration.** `rankcareer02_profile_public` adds `rank.account_profile.is_public`. The collection status `private`
only means "no competitive rank", which an open, unranked profile also gets. The backfill marks a profile open when
some career was collected for it, and the next poll sets the real value.

**Admission: open profile.** The "All Profiles Open" requirement read `private` as a closed profile and refused a
player whose open profile simply had no competitive rank yet. A `private` tag whose profile is open
(`is_public`) now counts as open. A closed or unfound profile still blocks; a tag never collected since the column
appeared reads as before until its next poll.

**Data fix shipped before this.** v2.10.14 fixed career parsing. Blizzard repeats some keys inside one category
(a hero's `games_won`, then its hero wins under the same key), and the parser kept the last value. Career rows
written by v2.10.13 were deleted after v2.10.14 started; the next poll rewrites them.

**Rollback.** Deploy the previous image. The admission rule returns to reading `private` as closed; nothing else reads
the new column.
