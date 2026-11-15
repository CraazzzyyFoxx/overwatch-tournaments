"use client";

import { AlertTriangle, ChevronLeft, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { HeroFrame } from "@/components/site/PageHero";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { DraftBoardSkeleton } from "@/components/draft/DraftRoomSkeleton";
import { RoomChat } from "@/components/chat/RoomChat";
import { shouldShowInitialDraftSkeleton } from "@/components/draft/draft-loading-state";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import type { DivisionGrid } from "@/types/workspace.types";

import {
  useDraftBoardQuery,
  useDraftMutations,
  useDraftPickOptionsQuery,
  useDraftRealtime
} from "@/hooks/useDraftData";
import { computeGating } from "@/lib/draft/logic";
import { draftChatRoom } from "@/lib/realtime/chat-rooms";
import { poolRoleColumns } from "@/lib/draft/room-model";
import { parseDraftViewParams, type DraftViewParams } from "@/lib/draft/workspace-model";
import { DraftWorkspace } from "./DraftWorkspace";

/** Who a draft belongs to, as the room needs it (spec §9.6): a tournament or a mix lobby. */
export type DraftOwner = {
  workspaceId: number;
  discipline: string;
  /** The back link's label and target. */
  name: string;
  href: string;
  /** The owner's own grid when it pins one (a tournament's version); null reads the game's workspace grid. */
  divisionGrid: DivisionGrid | null;
  /** Whoever runs this draft: a tournament's `team.create` holder, a mix's host or co-host. */
  isOrganizer: boolean;
};

interface DraftBoardProps {
  sessionId: number;
  owner: DraftOwner;
}

export function DraftBoard({ sessionId, owner }: Readonly<DraftBoardProps>) {
  const t = useTranslations("draftRedesign");
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const boardKey = tournamentQueryKeys.draftSessionBoard(sessionId);
  const boardQuery = useDraftBoardQuery(sessionId);
  const board = boardQuery.data ?? null;
  const { presence, connectionState } = useDraftRealtime(boardKey, board);
  const mutations = useDraftMutations(boardKey);
  const { user } = useAuthProfile();
  // An organizer's affordances are additive — one who also captains keeps the captain's confirm button.
  const isAdmin = owner.isOrganizer;
  const myPlayerIds = useMemo(
    () => (user?.linkedPlayers ?? []).map((player) => player.playerId),
    [user]
  );
  const gating = useMemo(
    () => (board ? computeGating(board, myPlayerIds, user?.id ?? null, isAdmin) : null),
    [board, myPlayerIds, user?.id, isAdmin]
  );
  const optionsQuery = useDraftPickOptionsQuery(
    board?.current_pick?.id ?? null,
    Boolean(board && gating?.isMyPick)
  );
  // The owner game's role dictionary (owner scope, never the browsing choice): names, glyphs, colours and order.
  const ontology = useDisciplineMetadata(owner.workspaceId, owner.discipline).data ?? null;
  // `?role=` is a filter only for a role this draft's pool has a column for.
  const roleColumns = useMemo(
    () => (board ? poolRoleColumns(board.session.roster_shape, board.players) : []),
    [board]
  );
  const viewParams = useMemo(
    () => parseDraftViewParams(new URLSearchParams(searchParams.toString()), roleColumns),
    [searchParams, roleColumns]
  );
  // The owner's grid first — a draft is seeded, balanced and displayed on the
  // grid its OWN owner is configured with. The workspace default is the
  // fallback when the owner pins no version, scoped to the same game.
  const workspaceGrid = useDivisionGrid(owner.discipline);
  const divisionGrid: DivisionGrid = owner.divisionGrid ?? workspaceGrid;

  const updateViewParams = (patch: Partial<DraftViewParams>) => {
    const next = new URLSearchParams(searchParams.toString());
    const values: DraftViewParams = { ...viewParams, ...patch };

    setOptionalParam(next, "role", values.role, "all");
    setOptionalParam(next, "sort", values.sort, "rank");
    setOptionalParam(next, "view", values.view, "pool");
    setOptionalParam(next, "pool", values.pool, "available");
    setOptionalParam(next, "teams", values.teams, "rosters");
    setOptionalParam(next, "q", values.query.trim(), "");

    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  if (shouldShowInitialDraftSkeleton(boardQuery)) {
    return <DraftBoardSkeleton />;
  }

  // Every dead end keeps a way out: the room has no site navigation around it.
  const back = { href: owner.href, label: t("room.back") };

  if (boardQuery.isError && !board) {
    return (
      <DraftStateFrame
        icon={<AlertTriangle className="h-6 w-6 text-[color:var(--aqt-warm)]" />}
        title={t("loadErrorTitle")}
        hint={t("loadErrorHint")}
        back={back}
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
        back={back}
      />
    );
  }

  const onlineCaptainIds = new Set(
    board.teams
      .filter(
        (team) =>
          team.captain_auth_user_id != null && presence.users[team.captain_auth_user_id] != null
      )
      .map((team) => team.captain_auth_user_id as number)
  );

  return (
    <div className="w-full pb-[env(safe-area-inset-bottom)]">
      <DraftWorkspace
        owner={owner}
        board={board}
        gating={gating}
        presence={presence}
        options={optionsQuery.data ?? null}
        optionsLoading={optionsQuery.isFetching}
        onRetryOptions={() => void optionsQuery.refetch()}
        connectionState={connectionState}
        viewParams={viewParams}
        onViewParamsChange={updateViewParams}
        mutations={mutations}
        divisionGrid={divisionGrid}
        ontology={ontology}
        onlineCaptainIds={onlineCaptainIds}
      />
      {/* Docked over the page, not a column of the board: the board wants
          every pixel of width it can get. Keyed by the SESSION — a re-seed is
          a different draft and deserves its own conversation. Collapsed on
          arrival: open, it covers the teams panel (the whole room on a phone). */}
      <RoomChat room={draftChatRoom(board.session.id)} defaultOpen={false} />
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

/** A draft state with nothing to show yet: what happened, and a way out. Shared by the route's own error. */
export function DraftStateFrame({
  icon,
  title,
  hint,
  action,
  back
}: Readonly<{
  icon: ReactNode;
  title: string;
  hint: string;
  action?: ReactNode;
  back?: { href: string; label: string };
}>) {
  return (
    <div className="mx-auto max-w-[1720px] px-4 py-5 sm:px-6">
      <HeroFrame>
        <div className="flex min-h-64 flex-col items-start justify-center gap-3 px-6 py-12 md:px-10">
          {icon}
          <h1 className="font-onest text-title font-semibold text-[color:var(--aqt-fg)]">
            {title}
          </h1>
          <p className="max-w-xl text-body text-[color:var(--aqt-fg-muted)]">{hint}</p>
          {action || back ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {action}
              {back ? (
                // Alone, the ghost button's padding would indent it off the
                // heading's edge; after an action it sits in the button row.
                <Button asChild variant="ghost" className={action ? undefined : "-ml-3"}>
                  <Link href={back.href}>
                    <ChevronLeft className="h-4 w-4" aria-hidden />
                    {back.label}
                  </Link>
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      </HeroFrame>
    </div>
  );
}
