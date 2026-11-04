"use client";

import { useQueryClient } from "@tanstack/react-query";

import { isMixHost } from "@/app/balancer/mix/pickup-lineup";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { usePermissions } from "@/hooks/usePermissions";
import { customGameKeys, type CustomGame } from "@/services/custom-game.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import type { IngestClient } from "@/types/discipline.types";

/**
 * What a viewer who may file match logs under a mix is handed: the mix, what to run once a log is accepted, whether
 * the mix's game parses an uploaded log file (`capabilities.log_upload`; Deadlock does not), whether it fetches
 * matches by id (`capabilities.match_fetch`), so a round may be filed by that id too, and whether a round's match can
 * be looked up by its players (`capabilities.match_search`), so its search may be started again, and whether the
 * game's matches reach that lookup through a player's uploader (descriptor `ingest_client`), so a waiting search links
 * to it.
 */
export type MixLogUpload = {
  customGameId: number;
  onUploaded: () => void;
  fileUpload: boolean;
  matchFetch: boolean;
  matchSearch: boolean;
  ingestClient: IngestClient | null;
};

/**
 * `null` unless the viewer may file a match log under this mix: the host, a co-host or a superuser (a closed mix
 * still takes logs, so unlike `canWriteMix` the status is not checked), or anyone holding `log.create` in the mix's
 * workspace -- the server's rule for `rpc.stats.logs.upload`. `onUploaded` refetches the mix's history: the parser's
 * own completion arrives as `workspace.logs` (which also stales the mix keys), but the chip should appear at once.
 */
export function useMixLogUpload(game: CustomGame | undefined): MixLogUpload | null {
  const queryClient = useQueryClient();
  const currentUserId = useAuthProfileStore((state) => state.user?.id ?? null);
  // The same read the mix screens already make for the game: one cache entry.
  const metadata = useDisciplineMetadata(game?.workspace_id ?? "all", game?.discipline ?? null);
  const { isSuperuser, canAccessPermission } = usePermissions();
  if (game == null) return null;
  if (!isMixHost(game, currentUserId, isSuperuser) && !canAccessPermission("log.create", game.workspace_id)) {
    return null;
  }
  return {
    customGameId: game.id,
    fileUpload: metadata.data?.discipline.capabilities.log_upload === true,
    matchFetch: metadata.data?.discipline.capabilities.match_fetch === true,
    matchSearch: metadata.data?.discipline.capabilities.match_search === true,
    ingestClient: metadata.data?.discipline.ingest_client ?? null,
    onUploaded: () =>
      void queryClient.invalidateQueries({ queryKey: customGameKeys.matches(game.workspace_id, game.id) })
  };
}
