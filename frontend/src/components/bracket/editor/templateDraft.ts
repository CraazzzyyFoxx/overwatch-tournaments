/**
 * The bracket layout editor's draft, and the two conversions around it.
 *
 * A saved `BracketTemplate` has every slot filled; a draft being edited does
 * not — a freshly added match has two empty slots, and moving a connection out
 * of a slot leaves it empty. `null` is that in-between state: the editor can
 * hold it, the PUT body cannot, which is exactly why `draftToTemplate` returns
 * `null` until the last slot is wired.
 *
 * No React in here, so the whole editing model is assertable as plain data.
 */
import type { BracketMatch } from "@/lib/bracket/view";
import type { DuelSlot } from "@/lib/encounter/seats";
import type { BracketTemplate, TemplateSlot } from "@/types/admin.types";
import type { EncounterSlotSource } from "@/types/encounter.types";

/** The backend model's bounds (`shared/services/bracket/template.py`), mirrored. */
const MAX_MATCH_ID = 10_000;
const MAX_ROUND = 256;
const MAX_SEEDS = 512;

/** `null` = not wired yet; a draft holding one cannot be saved. */
type DraftSlot = TemplateSlot | null;

/** The editor draws duels: a match's two slots, slot 1 first. */
export interface DraftMatch {
  id: number;
  round: number;
  slots: DraftSlot[];
}

export interface Draft {
  upper_seeds: number;
  lower_seeds: number;
  /** Order inside a round is display order, top to bottom (spec §5.1). */
  matches: DraftMatch[];
}

export type DraftAction =
  | { type: "connect"; source: number; role: "winner" | "loser"; target: number; slot: DuelSlot }
  | { type: "seed"; target: number; slot: DuelSlot; seed: string }
  | { type: "clear"; target: number; slot: DuelSlot }
  /** Exchange two slots' contents; refused across rounds (a seed belongs to its round's column). */
  | { type: "swap"; a: { match: number; slot: DuelSlot }; b: { match: number; slot: DuelSlot } }
  /** `beforeFinal` renumbers the final out one round and takes its place. */
  | { type: "addMatch"; round: number; beforeFinal?: boolean }
  | { type: "deleteMatch"; id: number }
  | { type: "move"; id: number; direction: -1 | 1 }
  | { type: "setSeeds"; upper: number; lower: number }
  | { type: "reset"; draft: Draft };

/**
 * Write `value` into one slot and empty every other slot that `held` matches.
 *
 * Both of the editor's writes are this shape: a result (a match plus a role)
 * and a seed each belong to exactly one slot, so placing one has to take it
 * away from wherever it was — the server refuses the alternative with
 * `result_reused` / `seed_duplicate`.
 */
function place(
  draft: Draft,
  target: number,
  slot: DuelSlot,
  value: TemplateSlot,
  held: (current: DraftSlot) => boolean
): Draft {
  return {
    ...draft,
    matches: draft.matches.map((match) => ({
      ...match,
      slots: match.slots.map((current, index): DraftSlot => {
        if (match.id === target && index + 1 === slot) return value;
        return held(current) ? null : current;
      })
    }))
  };
}

export function draftReducer(draft: Draft, action: DraftAction): Draft {
  switch (action.type) {
    case "connect": {
      const { source, role, target, slot } = action;
      // A duel's first place is the winner, its second the loser.
      const position = role === "winner" ? 1 : 2;
      const value: TemplateSlot = { source_match: source, source_position: position };
      return place(
        draft,
        target,
        slot,
        value,
        (current) => current?.source_match === source && current.source_position === position
      );
    }

    case "seed":
      return place(
        draft,
        action.target,
        action.slot,
        { seed: action.seed },
        (current) => current?.seed === action.seed
      );

    case "clear":
      return {
        ...draft,
        matches: draft.matches.map((match) =>
          match.id === action.target
            ? {
                ...match,
                slots: match.slots.map((slot, index) => (index + 1 === action.slot ? null : slot))
              }
            : match
        )
      };

    case "swap": {
      const { a, b } = action;
      const first = draft.matches.find((match) => match.id === a.match);
      const second = draft.matches.find((match) => match.id === b.match);
      if (!first || !second || first.round !== second.round) return draft;
      const valueA = first.slots[a.slot - 1] ?? null;
      const valueB = second.slots[b.slot - 1] ?? null;
      return {
        ...draft,
        matches: draft.matches.map((match) =>
          match.id !== a.match && match.id !== b.match
            ? match
            : {
                ...match,
                slots: match.slots.map((current, index) => {
                  if (match.id === a.match && index + 1 === a.slot) return valueB;
                  if (match.id === b.match && index + 1 === b.slot) return valueA;
                  return current;
                })
              }
        )
      };
    }

    case "addMatch": {
      const id = Math.max(0, ...draft.matches.map((match) => match.id)) + 1;
      if (id > MAX_MATCH_ID || Math.abs(action.round) > MAX_ROUND) return draft;
      const added: DraftMatch = { id, round: action.round, slots: [null, null] };
      // The final is the only match of the last positive round, so an upper
      // round added "at the end" is really added before it.
      const matches = action.beforeFinal
        ? draft.matches.map((match) =>
            match.round === action.round ? { ...match, round: match.round + 1 } : match
          )
        : draft.matches;
      if (matches.some((match) => Math.abs(match.round) > MAX_ROUND)) return draft;
      return { ...draft, matches: [...matches, added] };
    }

    case "deleteMatch": {
      const orphaned = (current: DraftSlot): DraftSlot =>
        current?.source_match === action.id ? null : current;
      return {
        ...draft,
        matches: draft.matches
          .filter((match) => match.id !== action.id)
          .map((match) => ({ ...match, slots: match.slots.map(orphaned) }))
      };
    }

    case "move": {
      const index = draft.matches.findIndex((match) => match.id === action.id);
      if (index < 0) return draft;
      const { round } = draft.matches[index];
      // Only a neighbour in the same round: the rounds are columns, and
      // swapping across them would move nothing on the canvas.
      const neighbour =
        action.direction === -1
          ? draft.matches.findLastIndex((match, at) => at < index && match.round === round)
          : draft.matches.findIndex((match, at) => at > index && match.round === round);
      if (neighbour < 0) return draft;
      const matches = [...draft.matches];
      [matches[index], matches[neighbour]] = [matches[neighbour], matches[index]];
      return { ...draft, matches };
    }

    case "setSeeds":
      return {
        ...draft,
        upper_seeds: Math.min(Math.max(action.upper, 2), MAX_SEEDS),
        lower_seeds: Math.min(Math.max(action.lower, 0), MAX_SEEDS)
      };

    case "reset":
      return action.draft;
  }
}

export function draftFromTemplate(template: BracketTemplate): Draft {
  return {
    upper_seeds: template.upper_seeds,
    lower_seeds: template.lower_seeds,
    matches: template.matches.map((match) => ({
      id: match.id,
      round: match.round,
      slots: match.slots.map(({ slot: _slot, ...rest }) => rest)
    }))
  };
}

/** The PUT body, or `null` while any slot is still unwired. */
export function draftToTemplate(draft: Draft): BracketTemplate | null {
  if (draft.matches.some((match) => match.slots.some((slot) => slot === null))) return null;
  return {
    version: 1,
    upper_seeds: draft.upper_seeds,
    lower_seeds: draft.lower_seeds,
    matches: draft.matches.map((match) => ({
      id: match.id,
      round: match.round,
      // Every slot is wired (checked above); the card is numbered 1..n in order.
      slots: match.slots.map((slot, index) => ({ ...(slot as TemplateSlot), slot: index + 1 }))
    }))
  };
}

/**
 * The draft as the bracket view reads it — the same mapping the preview does
 * for the generator's skeleton (`BracketPreview.toBracketMatches`): the
 * template id is the match id, so `sources` point at other template matches and
 * `computeSlotHints` renders the real "W M3" labels rather than guessing a
 * shape from round numbers.
 */
export function draftToBracketMatches(draft: Draft): BracketMatch[] {
  return draft.matches.map((match) => {
    const sources = match.slots.flatMap<EncounterSlotSource>((slot, index) =>
      slot?.source_match != null
        ? [
            {
              encounter_id: slot.source_match,
              source_position: slot.source_position,
              slot: index + 1
            }
          ]
        : []
    );
    return {
      id: match.id,
      round: match.round,
      status: "open",
      // A seed slot names its placeholder; anything else is TBD, and a wired
      // one gets its "W M3" hint from `sources` above.
      teams: match.slots.flatMap((slot, index) =>
        slot?.seed != null ? [{ slot: index + 1, team_id: null, name: slot.seed, score: 0 }] : []
      ),
      sources
    };
  });
}

/**
 * `U1…Un`, `L1…Lm` that no slot holds — the slot menu's offer.
 *
 * `round` narrows it to the half that round belongs to: the validator refuses
 * a lower seed in an upper-round match and the other way round, so offering
 * both is offering a draft that cannot be saved.
 */
export function unusedSeeds(draft: Draft, round?: number): string[] {
  const placed = new Set(
    draft.matches.flatMap((match) => match.slots.map((slot) => slot?.seed)).filter(Boolean)
  );
  const pool = round == null ? null : round < 0 ? "L" : "U";
  const all = [
    ...Array.from({ length: draft.upper_seeds }, (_, index) => `U${index + 1}`),
    ...Array.from({ length: draft.lower_seeds }, (_, index) => `L${index + 1}`)
  ];
  return all.filter((seed) => !placed.has(seed) && (pool === null || seed.startsWith(pool)));
}
