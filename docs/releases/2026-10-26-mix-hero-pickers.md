# Mix hero rooms: a free pick order and captains-only picks: release note

**Free pick order.** The mix header's Rules popover has «Порядок пиков: По составу / Свободный» for a preset whose
players pick one at a time (`member: "next"`: `lol_draft`, `deadlock_bans_pick_turns`, `deadlock_two_phase_draft`).
Free turns each such step into `member: "any"` as the next room opens:
- the team's turn is for whichever of its players still without a hero this round the picker names: the captain or a
  host taps the player's row, then the hero; a player may take the turn for themselves;
- the team order (the snake, the two halves) is unchanged;
- until the act names a player, the step is bound to the first of them in lineup order, and every act re-binds the
  team's later free turns of the round to the rest in lineup order (`pick_ban_rules.rebind_free_pick`), so a turn
  whose clock runs out goes to the first player in lineup order still without a hero;
- the room state lists every such player in `acting_member_ids` (and `member_eligible`), and the room waits for a tap
  when the viewer may pick for more than one of them: the heroes stay greyed and the bar says «Нажмите на игрока,
  затем выберите ему героя»;
- a step's player is named in the step list once the pick is made.

**Captains only.** «Кто пикает героев: Игроки и капитан / Только капитаны», for any preset with player picks (turn by
turn, all at once, or free). Captains only marks every member step `captains_only`:
- only the team's captain (the lineup's crown) or a host picks, for any player of the team; a player's own pick
  through the captain route is a 403, and their state reads `viewer_can_act: false` with the bar saying «Героев
  выбирают капитаны»;
- a team whose lineup crowns nobody picks as without the rule, each player for themselves;
- an assignment (`lol_captains`) is a captain's already and is unchanged.

Both choices apply from the next Start: the room reads them as it opens, like the clocks and Fearless, and a running
room keeps its ruleset. A clone copies them; there is no host default. The rules line names each while it is on.

`bind_members` now binds a `next`/`any` step to the first of the team's players no earlier `next`/`any` step of the
round names, rather than by counting those steps; for lineup-order picks the result is the same.

## Migration and deploy

One migration after `mixcode01`: **`mixpickers01`**. It adds `mix.custom_game.hero_free_order` and
`hero_captains_only`, `BOOLEAN NOT NULL DEFAULT false`: a constant default, so the ADD COLUMN is metadata-only and
every mix keeps picking as before. Deploy from one SHA: run the migration first, then roll balancer-service,
tournament-service, the gateway (regenerated `schemas.json`) and the frontend.

### Downgrade cost

Rolling back drops both columns and deletes every pick-ban session whose ruleset has a free-order (`member: "any"`)
or `captains_only` step, as `mixpick01`'s downgrade does for member steps: older code cannot read them.

## Wire changes

| Change | Kind |
| --- | --- |
| Mix read `hero_free_order`, `hero_captains_only` | additive |
| `PUT …/custom-games/{id}/ban-preset` accepts optional `hero_free_order` / `hero_captains_only` (omitted = unchanged) | additive |
| Pick-ban ruleset step and resolved step: `member` may be `"any"`; `captains_only: true` (sent only when set) | additive |
| Captain act on a `captains_only` step by a player who is not the captain: 403 | new refusal |
