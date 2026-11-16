# Overwatch profile, career and hero rates from OverFast: release note

**What changes.** The Overwatch rank poll reads the whole OverFast profile (`/players/{id}`) instead of the summary.
For Blizzard this is the same page, so the request count does not change. Besides the ranks, every poll now keeps:

- `rank.account_profile`: the account's current name, avatar, namecard, title, endorsement level and Blizzard career
  id. One row per account, rewritten each poll.
- `rank.career_snapshot`: the career statistics per platform, queue and hero, as a series of changes. A row is written
  only when the series moved, and competitive rows carry their season.

Two collection changes ride on the same poll:

- **Hero rates.** A new hourly tick writes Blizzard's hero pick, win and ban rates once a day to
  `rank.character_rate`: PC, Europe, competitive overall, per division and per map, and quick play overall. That is
  about 48 OverFast requests a day.
- **Renamed accounts.** A BattleTag that stops resolving is read by its stored Blizzard id, so the account keeps being
  collected. The id comes from Blizzard's player search: one search per account at most once a week.

Ranks behave as before. The profile and career are written after the poll's ranks commit, in a transaction of their
own; if that write fails, it is logged and the ranks are kept. A profile that answers without a `summary` counts as a
transient OverFast failure: it backs off and never auto-disables the account.

**Migration.** `rankcareer01_career_rates` creates the three tables and nothing else. There is no backfill:
history starts at the first poll after the deploy. On Blizzard's page competitive statistics are those of the last
season played, so any season that ends before the deploy is lost.

**Operator steps.** Run `make prod-migrate` before starting the new images. Everything is switched by the existing
OverFast rank collection setting; with it off, neither the career nor the hero rates are collected.

**Volume (estimate).** The first polls write one row per hero played per platform and queue, about 70–170 MB across
~1.1 k found accounts. After that, a few thousand rows a day, roughly 1–2 GB a year for `career_snapshot` and
~100 MB a year for `character_rate`. Measure after a week: `SELECT pg_size_pretty(pg_total_relation_size('rank.career_snapshot'))`.

**Rollback.** Deploy the previous image. Nothing reads the new tables yet; they can stay.
