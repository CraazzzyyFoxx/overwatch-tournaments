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

**Meta comparison.** The career read compares each hero with Blizzard's newest daily hero rates (PC, Europe, from
`rank.character_rate`). In competitive the slice is the account's current division in the hero's role: Champion
reads the Grandmaster slice, the top one Blizzard publishes, and a role the account is unranked in reads every
division. Quick play reads its only slice. Each hero carries `meta` (pick, win and ban rate as fractions, the
division and the day). Each queue carries `meta_fit`, the time-weighted pick rate of the player's heroes, and
`ban_exposure`, their time-weighted ban rate. Console careers get no meta, because only PC rates are collected.

**Collection health.** `GET /api/v1/admin/rank/career-health` (`rank.read`, scoped by `workspace_id`) returns:
- how many players and accounts are linked, found by the game now, open, not found, and never collected;
- up to 200 tags to fix: `lost` (stopped resolving after they had) and `renamed` (the game shows another name).

**Site.** The public player profile gets a «Ладдер» / "Ladder" tab with:
- the game profile, ranks, the queue's figures, roles and heroes, with each hero's meta;
- tournament against ladder per hero.

The Overview tab gets a short ladder card. The registrations list gets a ladder-signals column and an inspector
section. The rank collector's health tab shows Blizzard-profile coverage and the tags to fix.

**Data fix shipped before this.** v2.10.14 fixed career parsing. Blizzard repeats some keys inside one category
(a hero's `games_won`, then its hero wins under the same key), and the parser kept the last value. Career rows
written by v2.10.13 were deleted after v2.10.14 started; the next poll rewrites them.

**Rollback.** Deploy the previous image. The admission rule returns to reading `private` as closed; nothing else reads
the new column.
