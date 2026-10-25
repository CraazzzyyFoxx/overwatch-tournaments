# Discord: every game's rank badge

A Deadlock mix showed bare numbers in Discord: the bot's rank badges were Overwatch's only. Now every game with a native
ladder (Overwatch, LoL, Deadlock, Valorant) wears its own emblem. No wire change, no migration.

## Behaviour

* **Where.** The signup card's rows (`:badge: Name · 2800`), the seat panel («Моё место»: `:badge: Mystic 4 · 2800`)
  and the lineup picture badge a rank with the tier it lands in on its game's own ladder (`ladder_grid`), never a
  workspace grid. Role emoji stay Overwatch's (`art_drawn_for`); another game's roles go by name.
* **Names** (`src/ui.py` `badge_name`): one emoji per picture, the tier's `icon_url` file name. Overwatch keeps its
  `div_<slug>` (`div_gold_3`); another game's carries its code, since ladders share tier names
  (`div_valorant_gold_3`), and one picture may serve several ranks (Deadlock's Mystic 1..6 are all
  `div_deadlock_mystic`). 46 new: 11 Deadlock, 10 LoL, 25 Valorant.
* **Pictures.** `emoji_sync` reads every ladder tier's `icon_url` under the checkout's `frontend/public`, the site's
  own emblems. `static/divisions` (a byte-identical copy of `frontend/public/divisions/<slug>.png` that only this job
  read) is deleted; the `discord-emoji` service mounts `./frontend/public` instead, in both compose files.

## Deploy

`ops/deploy/remote-deploy.sh` runs `discord-emoji` from the tag's compose file, so the release uploads the new badges
by itself; the bot re-reads its emoji within 10 minutes and each live signup card picks them up on its next re-render.
A badge not uploaded yet simply does not show. Uploaded Overwatch badges keep their names and are not touched.

## Verification

`uv run pytest` in `backend/discord-service` (216 passed), `ruff check` and `ruff format --check`; a throwaway render of
the GNC Deadlock #2 roster (every row wears its emblem), its seat panel and its lineup picture (the emblems drawn), and
the upload plan against an application holding the 45 Overwatch badges (46 new, every picture found, none over
256 KiB).
