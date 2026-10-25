# Mix hero rooms: Deadlock picks in turn and in two phases, the host's clocks, one frame per hero: release note

**Picks in turn.** New Deadlock preset `deadlock_bans_pick_turns` («По два бана, затем пики по очереди»,
`mix_eligible`). It starts with the same four bans A-B-A-B. Then come twelve picks in snake order, A-BB-AA-BB-AA-B,
where A is the team that banned first. Each pick is a `member: "next"` step: a team's k-th pick belongs to its k-th
seat in lineup order. That player's captain or a host may pick for them. A team with fewer than six players skips its
extra turns. Each turn runs 30 s unless the host sets a pick clock. `deadlock_bans_pick` is now labelled «По два бана,
затем все пикают сразу». Like every member preset, a tournament config refuses the new one (`mix_only`).

**Ban, three picks, ban, three picks.** New Deadlock preset `deadlock_two_phase_draft` («Бан, три пика, бан, три
пика», `mix_eligible`). The same twelve turn-by-turn picks come in two halves:
- a ban each (A, then B);
- picks A-BB-AA-B;
- a ban each (B first, because A had the first pick);
- picks B-AA-BB-A.

The bans total two per team, as in the other Deadlock presets. The second bans wait for the first six picks. If
short teams leave first-half turns with nobody to pick, the room skips them and stops on the second bans. Mixes only,
like every member preset.

**The host's clocks.** The mix header's Rules popover has «Время на бан» and «Время на пик» fields (10..600 s; empty
means the preset's own clock, shown as the field's hint). A field appears only when the chosen preset has that kind
of step.
- The ban clock times every ban and protect step of the next room; the pick clock times every pick step.
- The all-at-once pick is one step, so its clock covers the whole pick.
- A side pick or an assignment keeps the preset's clock.
- The room reads the clocks when it opens, like Fearless. A running room keeps its timers.
- A clone copies the clocks. There is no host default.
- The rules line shows a host clock while one is set.

**One frame per hero.** A hero in the pool (`PickBanGrid`, used by the mix room and the tournament pre-game room)
wore the tile's ring plus the portrait's own ring. Now the portrait has no border of its own and fills the tile. The
tile's ring still carries the state (selected, protected, round locked, hover).

## Migration and deploy

One migration after `strchron01`: **`mixclock01`**. It adds `mix.custom_game.hero_ban_seconds` and
`hero_pick_seconds`, both nullable `INTEGER` with `CHECK … BETWEEN 10 AND 600`. Nothing is backfilled, and the ADD
COLUMN is metadata-only. Deploy from one SHA: run the migration first, then roll balancer-service, tournament-service,
the gateway (regenerated `schemas.json`) and the frontend.

### Downgrade cost

Rolling back drops both columns, so every mix goes back to its preset's clocks. It also unsets
`deadlock_bans_pick_turns` and `deadlock_two_phase_draft` from `mix.custom_game.hero_ban_preset`,
`mix.lobby.live_ban_preset` and the hosts' default presets (`balancer.user_config.hero_ban_presets`). A room already
open on one of them stays readable, because its member steps are `mixpick01`'s.

## Wire changes

| Change | Kind |
| --- | --- |
| Rules catalog presets `deadlock_bans_pick_turns`, `deadlock_two_phase_draft` (`mix_eligible: true`) | additive |
| Mix read `hero_ban_seconds`, `hero_pick_seconds` (null = the preset's own) | additive |
| `PUT …/custom-games/{id}/ban-preset` accepts optional `hero_ban_seconds` / `hero_pick_seconds` (10..600 or null; omitted = unchanged) | additive |

## Not in this release

Host per-game defaults for the clocks, one time budget for the whole pick phase, and a turn that any teammate who has
not picked yet may take.
