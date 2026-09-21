"use client";

import { AlertTriangle, ShieldCheck } from "lucide-react";
import { useMemo } from "react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { HeroFrame } from "@/components/site/PageHero";
import { Button } from "@/components/ui/button";
import { DraftBoardSkeleton } from "@/components/draft/DraftRoomSkeleton";
import { RoomChat } from "@/components/chat/RoomChat";
import { shouldShowInitialDraftSkeleton } from "@/components/draft/draft-loading-state";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import type { Tournament } from "@/types/tournament.types";
import type { DivisionGrid } from "@/types/workspace.types";

import {
  useDraftBoardQuery,
  useDraftMutations,
  useDraftPickOptionsQuery,
  useDraftRealtime
} from "@/hooks/useDraftData";
import { computeGating } from "@/lib/draft-logic";
import { draftChatRoom } from "@/lib/chat-rooms";
import { parseDraftViewParams, type DraftViewParams } from "@/lib/draft-workspace-model";
import { CaptainDraftWorkspace } from "./CaptainDraftWorkspace";
import { DraftPageHero } from "./DraftPageHero";
import { SpectatorDraftWorkspace } from "./SpectatorDraftWorkspace";

interface DraftBoardProps {
  tournament: Tournament;
}

export function DraftBoard({ tournament }: Readonly<DraftBoardProps>) {
  const t = useTranslations("draftRedesign");
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const boardQuery = useDraftBoardQuery(tournament.id);
  const board = boardQuery.data ?? null;
  const { presence, connectionState } = useDraftRealtime(tournament.id, board);
  const mutations = useDraftMutations(tournament.id);
  const { user } = useAuthProfile();
  const myPlayerIds = useMemo(
    () => (user?.linkedPlayers ?? []).map((player) => player.playerId),
    [user]
  );
  const gating = useMemo(
    () => (board ? computeGating(board, myPlayerIds, user?.id ?? null, false) : null),
    [board, myPlayerIds, user?.id]
  );
  const optionsQuery = useDraftPickOptionsQuery(
    board?.current_pick?.id ?? null,
    Boolean(board && gating?.isMyPick)
  );
  const viewParams = useMemo(
    () => parseDraftViewParams(new URLSearchParams(searchParams.toString())),
    [searchParams]
  );
  // Tournament grid first — a draft is seeded, balanced and displayed on the
  // grid its OWN tournament is configured with. The workspace default is the
  // next-best guess when the tournament pins no version of its own; only with
  // neither does this reach the hardcoded OW ladder inside `useDivisionGrid`.
  const workspaceGrid = useDivisionGrid();
  const divisionGrid: DivisionGrid = useMemo(
    () =>
      tournament.division_grid_version?.tiers
        ? { tiers: tournament.division_grid_version.tiers }
        : workspaceGrid,
    [tournament.division_grid_version, workspaceGrid]
  );

  const updateViewParams = (patch: Partial<DraftViewParams>) => {
    const next = new URLSearchParams(searchParams.toString());
    const values: DraftViewParams = { ...viewParams, ...patch };

    setOptionalParam(next, "role", values.role, "all");
    setOptionalParam(next, "sort", values.sort, "rank");
    setOptionalParam(next, "view", values.view, "pool");
    setOptionalParam(next, "q", values.query.trim(), "");

    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  if (shouldShowInitialDraftSkeleton(boardQuery)) {
    return <DraftBoardSkeleton />;
  }

  if (boardQuery.isError && !board) {
    return (
      <DraftStateFrame
        icon={<AlertTriangle className="h-6 w-6 text-[color:var(--aqt-warm)]" />}
        title={t("loadErrorTitle")}
        hint={t("loadErrorHint")}
        action={
          <Button variant="outline" onClick={() => boardQuery.refetch()}>
            {t("retry")}
          </Button>
        }
      />
    );
  }

  if (!board || !gating) {
    return (
      <DraftStateFrame
        icon={<ShieldCheck className="h-6 w-6 text-[color:var(--aqt-teal)]" />}
        title={t("emptyTitle")}
        hint={t("emptyHint")}
      />
    );
  }

  const onlineCaptainIds = new Set(
    board.teams
      .filter(
        (team) => team.captain_auth_user_id != null && presence.users[team.captain_auth_user_id] != null
      )
      .map((team) => team.captain_auth_user_id as number)
  );

  return (
    <div className="mx-auto w-full max-w-[min(2000px,96vw)] space-y-5 pb-[max(2rem,env(safe-area-inset-bottom))]">
      <DraftPageHero
        tournament={tournament}
        board={board}
        presence={presence}
        connectionState={connectionState}
      />
      {gating.isCaptain ? (
        <CaptainDraftWorkspace
          board={board}
          gating={gating}
          options={optionsQuery.data ?? null}
          optionsLoading={optionsQuery.isFetching}
          onRetryOptions={() => void optionsQuery.refetch()}
          connectionState={connectionState}
          viewParams={viewParams}
          onViewParamsChange={updateViewParams}
          mutations={mutations}
          divisionGrid={divisionGrid}
          onlineCaptainIds={onlineCaptainIds}
        />
      ) : (
        <SpectatorDraftWorkspace
          board={board}
          divisionGrid={divisionGrid}
          viewParams={viewParams}
          onViewParamsChange={updateViewParams}
          onlineCaptainIds={onlineCaptainIds}
        />
      )}
      {/* Docked over the page, not a column of the board: the board wants
          every pixel of width it can get. Keyed by the SESSION — a re-seed is
          a different draft and deserves its own conversation. */}
      <RoomChat room={draftChatRoom(board.session.id)} />
    </div>
  );
}

function setOptionalParam(
  params: URLSearchParams,
  key: string,
  value: string,
  defaultValue: string
) {
  if (value === defaultValue) params.delete(key);
  else params.set(key, value);
}

function DraftStateFrame({
  icon,
  title,
  hint,
  action
}: Readonly<{
  icon: ReactNode;
  title: string;
  hint: string;
  action?: ReactNode;
}>) {
  return (
    <HeroFrame>
      <div className="flex min-h-64 flex-col items-start justify-center gap-3 px-6 py-12 md:px-10">
        {icon}
        <h1 className="font-onest text-2xl font-semibold text-[color:var(--aqt-fg)]">{title}</h1>
        <p className="max-w-xl text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">{hint}</p>
        {action ? <div className="mt-2">{action}</div> : null}
      </div>
    </HeroFrame>
  );
}
