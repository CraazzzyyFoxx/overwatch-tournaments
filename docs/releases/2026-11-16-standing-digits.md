# Standings tiebreaks at thousandths; the qualification lock takes any draft format: release note

**Tiebreak precision.** `shared.domain.encounter_scoring.STANDING_DIGITS = 3` is the one precision standings
tiebreaks are kept at (half-up):

- Individual Swiss stores Buchholz rounded to it. Before, the raw float sum was stored and compared, so a true tie
  could split on float noise (`0.2 + 0.4 = 0.6000000000000001` ranked above `0.6`).
- Team standings compare `buchholz` and `median_buchholz` at thousandths instead of tenths. Two teams at 2.25 and 2.3
  no longer tie on Buchholz; the next tiebreaker decides only an exact tie. Running stages can reorder on their next
  recalculation.
- Game and FFA points keep `GAME_POINTS_DIGITS = 4`.

The site shows Buchholz to hundredths, keeping one decimal (`formatBuchholz` in `src/lib/tournament/tiebreakers.ts`).

**Qualification lock.** `POST …/stages/{stage_id}/lock-qualification` no longer answers 409
`draft_format_not_snake`. The captain draft after individual Swiss runs in the formation node's `draft_format` —
snake, linear or custom — like every other draft.

**Migration.** None. Stored individual-Swiss Buchholz is rounded on the stage's next recalculation.
