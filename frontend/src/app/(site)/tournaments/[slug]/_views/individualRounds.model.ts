import { seatsBySlot } from "@/lib/encounter/seats";
import type { IndividualRound } from "@/types/tournament.types";

type RoundEncounter = IndividualRound["encounters"][number];
export type RoundSeat = RoundEncounter["seats"][number];

/** A lobby as the round view draws it: its two teams by slot and whether a score is meaningful yet. */
export type RoundLobby = {
  encounterId: number;
  number: number;
  bestOf: number;
  seats: RoundSeat[];
  /** A pending lobby has not started: its 0–0 is not a result. */
  scored: boolean;
  /** Slot of the team ahead on a finished lobby; `null` while it is open or level. */
  winnerSlot: number | null;
};

export type RoundView = { round: number; lobbies: RoundLobby[] };

/** Rounds in order, lobbies numbered from 1 in the API's order, seats in slot order. */
export function buildRoundViews(rounds: readonly IndividualRound[]): RoundView[] {
  return [...rounds]
    .sort((a, b) => a.round - b.round)
    .map((round) => ({
      round: round.round,
      lobbies: round.encounters.map((encounter, index) => {
        const seats = seatsBySlot(encounter.seats);
        const [first, second] = seats;
        const finished = encounter.status === "completed";
        return {
          encounterId: encounter.encounter_id,
          number: index + 1,
          bestOf: encounter.best_of,
          seats,
          scored: encounter.status !== "pending",
          winnerSlot:
            finished && first && second && first.score !== second.score
              ? first.score > second.score
                ? first.slot
                : second.slot
              : null
        };
      })
    }));
}

/** The round the page opens on: the last one, where the play is. */
export function currentRound(views: readonly RoundView[]): number | null {
  return views.length > 0 ? views[views.length - 1].round : null;
}
