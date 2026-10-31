import fs from "node:fs";
import path from "node:path";

/**
 * §10.2 users rows: the pre-move functions' CAPTURED outputs (`disciplines/overwatch/__fixtures__/pre-move`, real
 * old-wire responses of the §10.1 parity seed at aff7943fc, never edited) against the REAL native responses of the
 * SAME seed at the post-8b HEAD (`__fixtures__/post-move/users-*.json`, plus the `mvp-rank.<player>.json`
 * user-encounter shards, byte-identical at this HEAD). Same request variants and labels as the pre-move capture; the
 * native requests carry `discipline=overwatch` and the renamed routes/params (§4.3, C12). Nothing on the input side
 * is derived from an output. Everything is exact `toEqual`.
 *
 * The assertions live with their subjects: the Overwatch module's (`disciplines/overwatch/character/
 * users.pre-move.parity.test.ts`) and the users route's (`app/(site)/users/users.pre-move.parity.test.ts`); these
 * are their shared fixture readers.
 *
 * Renames, compared through an explicit mapping (never dropped): `hero` → `character` (§4.1), `left_/right_hero_id`
 * → `left_/right_entity_id` (§4.3), a user match's `impact_*`/`overperformance_score` → `viewer.facts`
 * and `heroes` → `viewer.characters` (§6.5 8b row),
 * `home/away` team ids and `score` → `participants` by encounter slot (§6.1), `time` → `duration_s`, a map's
 * `gamemode_id/gamemode` → `parent_id/parent` (§4.1). The request's added `discipline` param is not a compare query
 * int (it did not exist in the pre-move request). The legacy MVP outputs (`performance`, a group's `avg_mvp`, the
 * match `overperformance_badge`) are not the contract after impact_v2 and are dropped from the captured side.
 *
 * Output fields that cannot be produced, dropped from the captured side only (each by its reference):
 *  - `Hero.color` (every captured hero; seed default `#ffffff`, asserted): §4.1 `HeroRead` → `CatalogEntityRead`.
 *  - a map's `in_competitive` and its mode's `description`: §4.1 `MapRead`/`GamemodeRead` → `CatalogEntityRead`.
 *  - `compare/utils` `parseRole` and `roleLabelKey` (the fixed Tank/Damage/Support vocabulary) and
 *    `tournaments-history` `roleColorVar` (`role_color`, `player_role_colors`): removed with the fixed role
 *    vocabulary (§9 5a deletion obligation "fixed role arrays/accents", Ruling 5a: family owners remove the retained
 *    fixed role-selector exports; 8b removed them in 190c8e8a1). Roles now come from the browsed game's ontology
 *    (`compareRoleFilter`, §1.5/§1.6), which has no equivalent of these fixed-token outputs.
 *
 * MISMATCH U1 (reported, awaiting a ruling — not hidden): `heroes-compare` column `per10_damage_taken` changed its
 * `barColor`/`accentColor` from the tank role token (`color-mix(... var(--aqt-tank) ...)` / `var(--aqt-tank)`) to
 * `bg-slate-400/65` / `bg-slate-400` (190c8e8a1). Pinned exactly by the "U1" test; every other column and value is
 * compared in full.
 */
const FIXTURES = path.join(__dirname, "..", "disciplines", "overwatch", "__fixtures__");
export const PRE = path.join(FIXTURES, "pre-move");
export const POST = path.join(FIXTURES, "post-move");
export const read = (dir: string, name: string) => JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));

const toJson = (value: unknown): string =>
  JSON.stringify(value, (_key, item) => {
    if (typeof item === "number" && !Number.isFinite(item)) return `__${String(item)}__`;
    if (item === undefined) return "__undefined__";
    return item;
  });
export const norm = (value: unknown): unknown => JSON.parse(toJson(value));

export interface Capture<T> {
  request: { method: string; path: string; query: [string, string][] };
  status: number;
  body: T;
}
export type Captures<T> = Record<string, Capture<T>>;
export const native = <T>(name: string): Captures<T> => read(POST, name).input_native_wire;
export const ok = <T>(records: Captures<T>, test: (label: string) => boolean): [string, Capture<T>][] =>
  Object.entries(records).filter(([label, rec]) => rec.status === 200 && test(label));

export const PLAYERS = ["player", "player_away", "player_event_only", "player_other", "player_removed", "player_no_member"];
