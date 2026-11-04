"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { customGameKeys, customGameService, type CustomGame } from "@/services/custom-game.service";

/** `null` = unknown: the source did not answer, or the member has no linked player -- never read as "inactive". */
export type IngestState = "active" | "inactive" | null;

/** The upstream read is cached for minutes server-side, so the room asks once in a while, not on every mix echo. */
const STALE_MS = 5 * 60_000;

/**
 * Who of a mix's roster uploaded matches through the game's ingest tool lately (`capabilities.ingest_status`), by
 * workspace member. Off (`enabled` false: another game, or a viewer without a session) it asks nothing and every
 * member is unknown. A failed read is not an error worth a toast: the badges just stay away.
 */
export function useMixIngest(game: CustomGame | undefined, enabled: boolean) {
  const query = useQuery({
    queryKey: customGameKeys.ingestStatus(game?.workspace_id ?? 0, game?.id ?? 0),
    queryFn: ({ signal }) =>
      customGameService.getIngestStatus((game as CustomGame).workspace_id, (game as CustomGame).id, { signal }),
    enabled: enabled && game != null,
    staleTime: STALE_MS,
    retry: false,
    meta: { suppressErrorToast: true }
  });
  const players = game?.players;
  const statuses = query.data?.players;
  return useMemo(
    () => ({
      /** True once the read answered: a lobby's "nobody uploads" is only worth saying then. */
      ready: statuses != null,
      of: (memberId: number | null): IngestState => {
        const playerId = players?.find((row) => row.workspace_member_id === memberId)?.player_id;
        const status = playerId == null ? null : (statuses?.[String(playerId)] ?? null);
        return status == null ? null : status.active ? "active" : "inactive";
      }
    }),
    [players, statuses]
  );
}
