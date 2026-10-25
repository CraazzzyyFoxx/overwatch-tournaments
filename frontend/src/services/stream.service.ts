import { apiFetch } from "@/lib/api/fetch";
import type { StreamVods, TournamentStreams } from "@/types/stream.types";

export default class streamService {
  /**
   * Live/offline state of a tournament's streams. Public read — `skipWorkspace`
   * so a cookie-less visitor (crawler, first hit, tenant host) is not asked for
   * a workspace id the endpoint does not scope by.
   */
  static async getTournamentStreams(tournamentId: number): Promise<TournamentStreams> {
    return apiFetch(`/api/v1/streams/tournament/${tournamentId}`, {
      skipWorkspace: true,
    }).then((response) => response.json());
  }

  /** Participants' past broadcasts with their match chapters, newest first. Public read, as above. */
  static async getTournamentVods(tournamentId: number): Promise<StreamVods> {
    return apiFetch(`/api/v1/streams/tournament/${tournamentId}/vods`, {
      skipWorkspace: true,
    }).then((response) => response.json());
  }

  /** The past broadcasts that cover one encounter, chapters limited to it. Public read, as above. */
  static async getEncounterVods(encounterId: number): Promise<StreamVods> {
    return apiFetch(`/api/v1/streams/encounter/${encounterId}/vods`, {
      skipWorkspace: true,
    }).then((response) => response.json());
  }

  /** Ask the poller for an out-of-band re-poll. Requires `stream.update`; 202. */
  static async repollTournament(tournamentId: number): Promise<void> {
    await apiFetch(`/api/v1/streams/tournament/${tournamentId}/repoll`, {
      method: "POST",
    });
  }
}
