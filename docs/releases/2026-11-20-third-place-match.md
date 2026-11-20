# Optional third-place match in elimination brackets: release note

**Setting.** `tournament.stage.third_place_match` (default `false`) adds a third-place match to a single- or
double-elimination bracket. It can be changed only while the stage has no generated matches and no custom bracket. A
custom bracket adds the match itself in **Edit structure**.

**Pairings.** Single elimination: the two semifinal losers. Double elimination: the loser of the lower-bracket final
and the loser of the lower-bracket match whose winner reached it. No match is created when a feeder is a bye.

**Results.** The winner is third and the loser fourth, overriding the lower bracket's provisional places. The match is
never `is_final`, does not take `best_of.final`, and keeps automatic stage completion waiting for its result. Reads
carry `is_third_place`. A third-place match swaps seats only within itself.

**Migration.** `bronzematch01_stage_option` adds the column with `false`. Existing stages and brackets are unchanged.
The encounter, tournament and standings cache namespaces move to new versions.
