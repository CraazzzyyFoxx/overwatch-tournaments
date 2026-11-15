"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { lobbyIndexFromLetter } from "@/app/balancer/mix/pickup-chrome";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { customGameKeys, customGameService } from "@/services/custom-game.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

import { MixRoom } from "./MixRoom";

/**
 * The room's route (`/balancer/mix/[gameId]/lobby/[A-F]`): the mix read the overview uses, then the room of the lobby
 * the letter names. Public like the overview -- a spectator opens the link signed out. A letter the mix does not run
 * renders the not-found card.
 */
export function MixRoomScreen() {
  const params = useParams<{ gameId: string; letter: string }>();
  const routeGameId = Number(params.gameId);
  const gameId = Number.isSafeInteger(routeGameId) && routeGameId > 0 ? routeGameId : null;
  const lobbyIndex = lobbyIndexFromLetter(params.letter);
  const hostWorkspaceId = useWorkspaceStore((state) => state.hostLockedWorkspaceId);
  const t = useTranslations("mixes");
  const entityQuery = useQuery({
    queryKey: customGameKeys.byId(gameId ?? 0, hostWorkspaceId),
    queryFn: () => customGameService.getById(gameId as number, hostWorkspaceId),
    enabled: gameId != null
  });

  if (gameId == null || entityQuery.isError) {
    return (
      <PageStateCard
        state="error"
        headingLevel={1}
        title={t("list.errorTitle")}
        description={t("list.errorDescription")}
        actionLabel={t("retry")}
        onAction={() => void entityQuery.refetch()}
      />
    );
  }
  if (!entityQuery.data) {
    // Room-shaped: a title row, then the two team columns around the centre.
    return (
      <div role="status" className="mx-auto flex w-full max-w-[1440px] flex-col gap-4">
        <span className="sr-only">{t("loading")}</span>
        <Skeleton aria-hidden className="h-8 w-72 rounded-lg" />
        <div
          aria-hidden
          className="grid grid-cols-2 gap-2.5 lg:grid-cols-[minmax(240px,300px)_minmax(0,1fr)_minmax(240px,300px)] lg:gap-5"
        >
          <Skeleton className="h-72 rounded-xl" />
          <Skeleton className="col-span-2 row-start-2 h-96 rounded-xl lg:col-span-1 lg:row-start-1" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      </div>
    );
  }
  if (lobbyIndex == null || lobbyIndex >= entityQuery.data.lobby_count) {
    return <PageStateCard state="not-found" headingLevel={1} description={t("room.notFound")} />;
  }
  return <MixRoom key={entityQuery.data.id} initialGame={entityQuery.data} lobbyIndex={lobbyIndex} />;
}
