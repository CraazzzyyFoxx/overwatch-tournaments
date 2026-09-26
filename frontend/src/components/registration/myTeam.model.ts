import { ROSTER_SLOT_CODES, type RosterSlotCode } from "@/lib/roster/shape";
import type { SlotLabelTranslator } from "@/lib/registration/team-shortfall";
import type { RegistrationTeam } from "@/types/registration-team.types";

/** Translated slot vocabulary, falling back to the raw code for anything the
 *  server sends that this build does not know a name for. */
export function slotLabelFor(code: string, tSlot: SlotLabelTranslator): string {
  const known = ROSTER_SLOT_CODES.find((candidate) => candidate === code);
  return known ? tSlot(known) : code;
}

/** Everything the roster card derives from one team, in one pass. */
export interface MyTeamRoster {
  /** Live offers, expired ones included — see the note below. */
  pendingInvites: RegistrationTeam["invites"];
  /** One entry per unfilled, unoffered starter place, in roster order. */
  freeSlots: RosterSlotCode[];
  /** The distinct codes of `freeSlots`. */
  offerableSlots: RosterSlotCode[];
  starters: RegistrationTeam["members"];
  starterCapacity: number;
  /** Every slot code this roster actually uses. */
  benchSlots: RosterSlotCode[];
  freeBenchCount: number;
  benchOpen: boolean;
}

export function buildMyTeamRoster(team: RegistrationTeam): MyTeamRoster {
  // Pending is pending: the server reserves a slot for an offer whose clock has
  // run out too (it stays `pending` until someone consumes or revokes it), so
  // discounting expired rows here would advertise a slot the invite call then
  // refuses with `slot_already_offered`.
  const pendingInvites = team.invites.filter((invite) => invite.state === "pending");
  // Open slots count accepted members only; live offers reserve, but do not fill, them.
  const freeSlots = ROSTER_SLOT_CODES.flatMap((code) =>
    Array.from({
      length: Math.max(0, (team.open_slots[code] ?? 0) -
        pendingInvites.filter((invite) => !invite.is_substitute && invite.slot_code === code).length),
    }, () => code),
  );
  const offerableSlots = ROSTER_SLOT_CODES.filter((code) => freeSlots.includes(code));
  const starters = team.members.filter((member) => !member.is_substitute);
  const starterCapacity =
    starters.length + Object.values(team.open_slots).reduce((sum, count) => sum + count, 0);
  /** Every slot code this roster actually uses, reconstructed from the rows that
   *  hold one. A substitute covers a slot that is by definition FULL, so
   *  `open_slots` — the starter shortfall — can never name it: on a complete
   *  roster it is empty, which left the bench with nothing to select. */
  const shapeSlots = new Set<string>([
    ...Object.keys(team.open_slots),
    ...team.members.map((member) => member.slot_code ?? ""),
    ...team.invites.map((invite) => invite.slot_code),
  ]);
  const benchSlots = ROSTER_SLOT_CODES.filter((code) => shapeSlots.has(code));
  /** Pending substitute offers reserve a bench place — the same arithmetic
   *  `can_offer` does server-side, so the checkbox never promises a seat the
   *  server answers `bench_full` for. */
  const freeBenchCount = Math.max(0, team.max_substitutes - team.substitutes_used -
    pendingInvites.filter((invite) => invite.is_substitute).length);

  return {
    pendingInvites,
    freeSlots,
    offerableSlots,
    starters,
    starterCapacity,
    benchSlots,
    freeBenchCount,
    benchOpen: freeBenchCount > 0,
  };
}
