# Deadlock match statistics and the Deadlock match view: release note

A Deadlock match now records far more of deadlock-api's metadata. It also has its own match view, built on the
Overwatch one: a scoreboard with column sets, builds and a player panel, then a breakdown, lanes and a timeline.

**Decoder** (`shared/disciplines/deadlock/ingest.py`, the module docstring is the contract):

- **Facts**, per player on the played hero. These are the top-level counters, plus these from the last `stats[]`
  sample: hero, objective and taken damage, healing, shots hit and missed, hero hits and headshots, self, ally and
  barrier support, absorbed and mitigated damage, healing prevented, lane creeps and neutrals killed. `souls_*` are
  the souls by `gold_sources` (gold plus orbs; items and abilities share `souls_items`), and `souls_lost` is
  `gold_death_loss`.
- **Events**:
  - `purchase` per `items[]` entry. `data` is `item_id`, plus `sold_t` and `imbued_ability_id` when they are set.
    Ability points share this list; the asset's `type` tells them apart, so the reader does. No metadata field
    separates them on older matches: `upgrade_id == 1` marks shop items only in recent ones.
  - `snapshot` per `stats[]` sample, with `data` = the time-series counters (`stats.SNAPSHOT_STATS`).
  - `lane` per player: `data.lane`, a `CMsgLaneColor` (1 yellow, 3 green, 4 blue, 6 purple).
  - `objective` per destroyed objective. The owner is the target team, and `data.objective` is an
    `ECitadelTeamObjective`. A `destroyed_time_s` of 0 means still standing and is skipped.
  - `mid_boss`: the killing team acts and the claiming team is the target.
  - `damage` (to one enemy hero) and `damage_source` (`data.source` is an asset `class_name`), both with
    `data.amount`. They come from `damage_matrix`, using only its `Damage` stat type and only damage to enemy heroes
    (slot 0 is everything else). `damage` sums the `Bullet`/`Ability`/`Melee`/`UnknownAbility` buckets and
    `damage_source` the named sources. The matrix files every hit under both, so the two never add up to each other.
- A sample taken on the last tick (`t` past `duration_s`) is pinned to the end. Corrupted-item data (`upgrade_info`)
  and movement paths are not kept.

**Vocabulary**: 24 more stats. `boss_damage` is now named "Objective damage". There are six more event types
(`snapshot`, `lane`, `objective`, `mid_boss`, `damage`, `damage_source`). All of it is projected on startup.

**Backfill**: `python -m scripts.deadlock_purchases_replay [--dry-run]` (from `backend/`) publishes a revision-fenced
replay to `stats.ingest.deadlock.replay` for every `done` Deadlock job that is still its game's current provenance.
The worker redecodes the stored raw metadata, so deadlock-api is not called again. Run it after deploying the decoder,
with a Deadlock stats worker up.

**Frontend** (`disciplines/deadlock/match.ts` serves `matchStats`):

- **Sides in the game's colours.** Each participation is painted in the side it played, Hidden King amber or
  Archmother sapphire, read from `source_position` (1 is `team0`, 2 is `team1`). The hues live in
  `disciplines/deadlock/theme.css`, next to the shop columns' weapon / vitality / spirit (DESIGN.md §2, "Game themes").
- **Ribbon**, one strip above the tabs, pinned while the view scrolls (under the site header on a page, to the top of
  the match dialog; not pinned on a phone). Each team's name sits by its half of the strip with the match clock between
  them. The strip shows the souls lead over the whole match. Kills tick along the edges and fights shade the strip.
  Destroyed structures (Guardian shield, Walker castle, Base Guardian half-shield, Shrine gem, Patron crown, filled) and
  mid bosses (skull) are icon badges in the colour of the side that did it, on its edge, stacked into rows when close.
  Hovering one opens a card: what fell and in which lane, the time, which team did it to whom, its count for that team
  (mid boss: its count in the match). The legend (only the marks the match has) and the how-to sit behind a "?" button.
  The strip is the timeline control: dragging or clicking it sets the **moment** the whole view shows.
  From the keyboard it is a slider: arrows by 10 s, Shift by a minute, Home / End. There is no "end" button: the
  strip's last 1% (or End) is the end of the match, back to the final figures.
- **Teams** (the first tab): both teams side by side, as the in-game scoreboard. Each team line shows its side and its
  kills, souls and objectives at the moment; each player is two lines (hero with level, name, K/D/A and souls; the build
  below), the match's best kills and souls bold. A player opens the same panel as in the full table, under his card.
- **Full table**, the second tab; its column sets sit in the tab row:
  - At a moment, kills, deaths and items are exact. The other figures come from the game's last sample by then, and
    the caption names its time. Columns with no time data show a dash.
  - Column sets are Overview, Combat, Economy and Support. Each team has a totals line, and each column's best value
    is bold.
  - The hero portrait carries the level reached.
  - The build is grouped by shop column, strongest tier first, then the souls it is worth and their split across the
    columns. Items bought in the minute before the moment are marked.
  - A row opens the player panel: the **build path** (every purchase over the minute it was bought, stacked when close,
    sold items dim, later ones faint behind the cursor), damage to each enemy hero, damage by source, rivals and the
    facts on which he is first in the match.
- **Breakdown**: hero damage, objective damage, healing and damage taken per team. Turning points (biggest lead per
  side, lead changes, first objective, mid bosses), each time clickable onto the ribbon. Every player's souls or hero
  damage over time with the cursor, who carried, and where each player's souls came from.
- **Lanes** (yellow, blue, green, as the game's minimap names them), read at the 9:00 sample (or the last one before
  it), with a link that puts that moment on the ribbon:
  - A lane picker: one card per lane with both pairs' heroes and KDA, the lane winner's souls lead in %, and the lane's
    souls lead at each early sample (3:00, 6:00, 9:00) as up/down bars in the side colours.
  - The chosen lane: its winner and lead; each player with souls, KDA, creeps, denies, hero damage and damage taken;
    between the two sides, a tug bar per stat (each side's share from its own end, the side behind dimmed).
  - The lane over the match: these players' souls lead across the whole match, laning shaded, the lane's structures
    falling as diamonds; and a table of when each side's Guardian, Walker and Base Guardian fell (each time puts it on
    the ribbon).
- **Timeline**: every engagement in order. Kills at most 15 s apart are one engagement; three or more kills make a
  numbered fight, smaller ones are picks. Each lists the structures and mid bosses that fell during it. The engagement
  under the moment is marked and later ones are faint. An engagement's time puts it on the ribbon.
- Items and damage-source art come from `@deadlock-api/ui-react` / `@deadlock-api/ui-core`, from deadlock-api's
  `/v1/assets/items` in the page language. The list is loaded once in the browser and shared with the cards. If it
  fails, builds and sources draw nothing and an alert says why.
- The view is the Deadlock `matchStats` slot, so it shows wherever a match's statistics do: the match statistics dialog
  (tournament maps, mix history rows) and `/matches/{id}`. Builds, snapshots, lanes and objectives appear once the
  backend decoder is deployed; older matches show them after the backfill above.
