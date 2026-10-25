# Deleting a match with a pick-ban board no longer fails: release note

**The bug.** Cancelling or undoing a mix match whose hero room had a team pick or protect failed with
`ck_pick_ban_entry_picked_by` (Sentry OWT-TOURNAMENTS-2CW); any other encounter delete (admin delete, stage or
tournament delete) could hit the same, and a team protect could fail on `ck_pick_ban_entry_protected_by`. The board's
`fk_pick_ban_entry_picked_by` / `fk_pick_ban_entry_protected_by` were `ON DELETE SET NULL (…_team_id)`, which the
CHECKs refuse for a `team` actor. An encounter's delete removes its participations and its rooms through separate
cascades, and where Postgres ran the participations' first (trigger-name order, per database), the SET NULL hit a row
the room's cascade had not removed yet.

**The fix.** Both foreign keys are now `DEFERRABLE INITIALLY DEFERRED` with no action, like
`fk_pick_ban_submission_team`: they are checked at commit, when both cascades have run. A participation still cannot be
deleted on its own while the board names it.

## Migration and deploy

One migration after `mixpickers01`: **`pbentry01`**. It drops and re-adds the two foreign keys on
`encounter.pick_ban_entry`; the re-add validates the board against `encounter.team` (a short lock on a small table;
every row already passes, `enclayer01` validated both). No service change: run the migration, nothing to roll.

### Downgrade cost

None: it restores the `SET NULL` foreign keys, and with them the bug.
