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
import type { BracketTemplate, TemplateSlot } from "@/types/admin.types";
import type { EncounterSlotSource } from "@/types/encounter.types";
import type { Team } from "@/types/team.types";

type Side = "home" | "away";

/** `null` = not wired yet; a draft holding one cannot be saved. */
export type DraftSlot = TemplateSlot | null;

export interface DraftMatch {
  id: number;
  round: number;
  home: DraftSlot;
  away: DraftSlot;
}

export interface Draft {
  upper_seeds: number;
  lower_seeds: number;
  /** Order inside a round is display order, top to bottom (spec §5.1). */
  matches: DraftMatch[];
}

export type DraftAction =
  | { type: "connect"; source: number; role: "winner" | "loser"; target: number; slot: Side }
  | { type: "seed"; target: number; slot: Side; seed: string }
  | { type: "clear"; target: number; slot: Side }
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
  slot: Side,
  value: TemplateSlot,
  held: (current: DraftSlot) => boolean
): Draft {
  const next = (match: DraftMatch, side: Side): DraftSlot => {
    if (match.id === target && side === slot) return value;
    return held(match[side]) ? null : match[side];
  };
  return {
    ...draft,
    matches: draft.matches.map((match) => ({
      ...match,
      home: next(match, "home"),
      away: next(match, "away")
    }))
  };
}

export function draftReducer(draft: Draft, action: DraftAction): Draft {
  switch (action.type) {
    case "connect": {
      const { source, role, target, slot } = action;
      const value: TemplateSlot = role === "winner" ? { winner_of: source } : { loser_of: source };
      return place(draft, target, slot, value, (current) =>
        role === "winner" ? current?.winner_of === source : current?.loser_of === source
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
          match.id === action.target ? { ...match, [action.slot]: null } : match
        )
      };

    case "addMatch": {
      const id = Math.max(0, ...draft.matches.map((match) => match.id)) + 1;
      const added: DraftMatch = { id, round: action.round, home: null, away: null };
      // The final is the only match of the last positive round, so an upper
      // round added "at the end" is really added before it.
      const matches = action.beforeFinal
        ? draft.matches.map((match) =>
            match.round === action.round ? { ...match, round: match.round + 1 } : match
          )
        : draft.matches;
      return { ...draft, matches: [...matches, added] };
    }

    case "deleteMatch": {
      const orphaned = (current: DraftSlot): DraftSlot =>
        current?.winner_of === action.id || current?.loser_of === action.id ? null : current;
      return {
        ...draft,
        matches: draft.matches
          .filter((match) => match.id !== action.id)
          .map((match) => ({ ...match, home: orphaned(match.home), away: orphaned(match.away) }))
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
          ? draft.matches.findLastIndex(
              (match, at) => at < index && match.round === round
            )
          : draft.matches.findIndex((match, at) => at > index && match.round === round);
      if (neighbour < 0) return draft;
      const matches = [...draft.matches];
      [matches[index], matches[neighbour]] = [matches[neighbour], matches[index]];
      return { ...draft, matches };
    }

    case "setSeeds":
      return { ...draft, upper_seeds: action.upper, lower_seeds: action.lower };

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
      home: match.home,
      away: match.away
    }))
  };
}

/** The PUT body, or `null` while any slot is still unwired. */
export function draftToTemplate(draft: Draft): BracketTemplate | null {
  const matches = draft.matches.map((match) =>
    match.home && match.away
      ? { id: match.id, round: match.round, home: match.home, away: match.away }
      : null
  );
  if (matches.some((match) => match === null)) return null;
  return {
    version: 1,
    upper_seeds: draft.upper_seeds,
    lower_seeds: draft.lower_seeds,
    matches: matches as BracketTemplate["matches"]
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
    const sources = (["home", "away"] as const).flatMap<EncounterSlotSource>((side) => {
      const slot = match[side];
      if (slot?.winner_of != null) return [{ encounter_id: slot.winner_of, role: "winner", slot: side }];
      if (slot?.loser_of != null) return [{ encounter_id: slot.loser_of, role: "loser", slot: side }];
      return [];
    });
    return {
      id: match.id,
      round: match.round,
      status: "open",
      score: { home: 0, away: 0 },
      home_team_id: 0,
      away_team_id: 0,
      // A seed slot names its placeholder; anything else is TBD, and a wired
      // one gets its "W M3" hint from `sources` above.
      home_team: { name: match.home?.seed ?? "TBD" } as Team,
      away_team: { name: match.away?.seed ?? "TBD" } as Team,
      sources
    };
  });
}

/** `U1…Un`, `L1…Lm` that no slot holds — the slot menu's offer. */
export function unusedSeeds(draft: Draft): string[] {
  const placed = new Set(
    draft.matches.flatMap((match) => [match.home?.seed, match.away?.seed].filter(Boolean))
  );
  const all = [
    ...Array.from({ length: draft.upper_seeds }, (_, index) => `U${index + 1}`),
    ...Array.from({ length: draft.lower_seeds }, (_, index) => `L${index + 1}`)
  ];
  return all.filter((seed) => !placed.has(seed));
}
