"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { canConfirmPick } from "@/lib/draft-logic";
import type { DraftGating } from "@/lib/draft-logic";
import {
  draftPoolView,
  playerRoles,
  DRAFT_MOBILE_VIEWS,
  type DraftMobileView,
  type DraftViewParams
} from "@/lib/draft-workspace-model";
import { describeApiError } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import type {
  DraftBoard,
  DraftPickOptionsResponse,
  DraftPlayer,
  DraftRole
} from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { DivisionGrid } from "@/types/workspace.types";
import type { useDraftMutations } from "@/hooks/useDraftData";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";

import { CaptainShortlist } from "./CaptainShortlist";
import { DraftOrder } from "./DraftOrder";
import { PickCommandBar } from "./PickCommandBar";
import { PlayerInspector } from "./PlayerInspector";
import { PlayerPool } from "./PlayerPool";
import { TeamRosters } from "./TeamRosters";

interface CaptainDraftWorkspaceProps {
  board: DraftBoard;
  gating: DraftGating;
  options: DraftPickOptionsResponse | null;
  optionsLoading: boolean;
  onRetryOptions: () => void;
  connectionState: RealtimeConnectionState;
  viewParams: DraftViewParams;
  onViewParamsChange: (patch: Partial<DraftViewParams>) => void;
  mutations: ReturnType<typeof useDraftMutations>;
  divisionGrid: DivisionGrid;
  onlineCaptainIds?: Set<number>;
}

export function CaptainDraftWorkspace({
  board,
  gating,
  options,
  optionsLoading,
  onRetryOptions,
  connectionState,
  viewParams,
  onViewParamsChange,
  mutations,
  divisionGrid,
  onlineCaptainIds
}: Readonly<CaptainDraftWorkspaceProps>) {
  const t = useTranslations("draftRedesign");
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [selectedRole, setSelectedRole] = useState<DraftRole | null>(null);
  // Persisted per session so a reload (or an accidental tab close) keeps the shortlist.
  const [shortlistIds, setShortlistIds] = useLocalStorageState<number[]>(
    `aqt.draft.shortlist.${board.session.id}`,
    []
  );
  const shortlist = useMemo(() => new Set(shortlistIds), [shortlistIds]);
  const [announcement, setAnnouncement] = useState("");
  const pool = useMemo(() => draftPoolView(board.players, viewParams), [board.players, viewParams]);
  const selectedPlayer =
    selectedPlayerId == null
      ? null
      : pool.available.find((player) => player.id === selectedPlayerId) ?? null;
  const shortlistPlayers = pool.available.filter((player) => shortlist.has(player.id));
  const myTeam = board.teams.find((team) => team.id === gating.myTeamId) ?? null;
  const currentPick = board.current_pick;
  // Only claim a player is safe or blocked when the server's option list is
  // actually here. Without it every row would read as "no role keeps every
  // remaining roster feasible" — a verdict nobody computed.
  const safetyRequired = gating.isMyPick && options != null;
  const optionsUnavailable = gating.isMyPick && options == null && !optionsLoading;
  const selection = selectedPlayer && selectedRole
    ? { playerId: selectedPlayer.id, role: selectedRole }
    : null;
  const confirmAllowed =
    gating.isMyPick &&
    currentPick != null &&
    canConfirmPick(connectionState, currentPick.version, options, selection);
  const pickBarVisible =
    currentPick != null ||
    board.session.status === "live" ||
    board.session.status === "paused";

  const selectPlayer = (player: DraftPlayer, role: DraftRole | null = null) => {
    setSelectedPlayerId(player.id);
    setSelectedRole(role ?? playerRoles(player)[0] ?? null);
    setAnnouncement("");
  };
  const toggleShortlist = (playerId: number) => {
    setShortlistIds((current) =>
      current.includes(playerId) ? current.filter((id) => id !== playerId) : [...current, playerId]
    );
  };
  const confirm = () => {
    if (!confirmAllowed || !currentPick || !selectedPlayer || !selectedRole) return;
    mutations.makePick.mutate(
      {
        pickId: currentPick.id,
        playerId: selectedPlayer.id,
        version: currentPick.version,
        role: selectedRole
      },
      {
        onSuccess: () => {
          setAnnouncement(t("pickSuccess", { player: selectedPlayer.battle_tag ?? `#${selectedPlayer.id}` }));
          setSelectedPlayerId(null);
          setSelectedRole(null);
        },
        onError: (error) => {
          const described = describeApiError(error);
          setAnnouncement([described.title, described.description].filter(Boolean).join(". "));
        }
      }
    );
  };

  const renderPool = (poolHeadingId: string) => (
    <PlayerPool
      players={pool.filtered}
      totalPlayers={pool.available.length}
      roleCounts={pool.roleCounts}
      selectedPlayerId={selectedPlayerId}
      shortlist={shortlist}
      role={viewParams.role}
      sort={viewParams.sort}
      query={viewParams.query}
      options={options}
      safetyRequired={safetyRequired}
      onSelect={selectPlayer}
      onToggleShortlist={toggleShortlist}
      onFiltersChange={onViewParamsChange}
      onResetFilters={() => onViewParamsChange({ role: "all", sort: "rank", query: "" })}
      divisionGrid={divisionGrid}
      headingId={poolHeadingId}
    />
  );
  const renderInspectorAndShortlist = (variant: "mobile" | "desktop") => (
    <>
      <PlayerInspector
        player={selectedPlayer}
        role={selectedRole}
        options={options}
        safetyRequired={safetyRequired}
        headingId={`player-inspector-${variant}-heading`}
        onRoleChange={setSelectedRole}
        onClose={() => {
          setSelectedPlayerId(null);
          setSelectedRole(null);
        }}
        divisionGrid={divisionGrid}
      />
      <CaptainShortlist
        players={shortlistPlayers}
        onSelect={(player) => selectPlayer(player)}
        onRemove={toggleShortlist}
        divisionGrid={divisionGrid}
      />
    </>
  );
  const team = (
    <TeamRosters
      teams={board.teams}
      players={board.players}
      picks={board.picks}
      shape={board.session.roster_shape}
      myTeamId={gating.myTeamId}
      onClockTeamId={board.current_pick?.draft_team_id ?? null}
      divisionGrid={divisionGrid}
      onlineCaptainIds={onlineCaptainIds}
    />
  );

  return (
    <div className={cn("space-y-5", pickBarVisible && "pb-36 sm:pb-32")}>
      {optionsLoading && gating.isMyPick && (
        // `block`: <output> is inline, so the left rule would be drawn per
        // line box instead of down the whole notice.
        <output className="block border-l-2 border-[color:var(--aqt-teal)] pl-3 text-sm text-[color:var(--aqt-fg-muted)]">
          {t("checkingSafeOptions")}
        </output>
      )}
      {optionsUnavailable && (
        <output className="flex flex-wrap items-center gap-2 border-l-2 border-[color:var(--aqt-live)] pl-3 text-sm text-[color:var(--aqt-fg-muted)]">
          {t("safeOptionsUnavailable")}
          <button
            type="button"
            onClick={onRetryOptions}
            className="min-h-11 text-[color:var(--aqt-teal)] underline outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
          >
            {t("retry")}
          </button>
        </output>
      )}

      {/* Radix Tabs, not hand-rolled roles: it wires aria-controls, roving
          tabindex and arrow-key traversal that the previous button row lacked. */}
      <Tabs
        value={viewParams.view}
        onValueChange={(view) => onViewParamsChange({ view: view as DraftMobileView })}
        className="xl:hidden"
      >
        <TabsList
          className="flex h-auto w-full gap-1 rounded-xl bg-[color:var(--aqt-card-2)] p-1"
          aria-label={t("mobileViews")}
        >
          {DRAFT_MOBILE_VIEWS.map((view) => (
            <TabsTrigger
              key={view}
              value={view}
              className="min-h-11 flex-1 rounded-lg px-2 text-sm font-medium data-[state=active]:bg-[color:var(--aqt-card)] data-[state=active]:text-[color:var(--aqt-teal)] data-[state=active]:shadow-none"
            >
              {t(`mobileView.${view}`)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="pool" className="mt-5 space-y-6">
          {renderInspectorAndShortlist("mobile")}
          {renderPool("player-pool-mobile-heading")}
        </TabsContent>
        <TabsContent value="team" className="mt-5">
          {team}
        </TabsContent>
        <TabsContent value="order" className="mt-5">
          <DraftOrder
            picks={board.picks}
            teams={board.teams}
            players={board.players}
            compact
            divisionGrid={divisionGrid}
            headingId="draft-order-mobile-heading"
          />
        </TabsContent>
      </Tabs>

      <div className="hidden gap-4 xl:grid xl:grid-cols-[248px_minmax(0,1fr)_378px]">
        <aside className="sticky top-4 self-start space-y-4">
          <DraftOrder picks={board.picks} teams={board.teams} players={board.players} divisionGrid={divisionGrid} headingId="draft-order-desktop-heading" />
        </aside>
        {/* Not <main>: the route already exposes the page-level main landmark. */}
        <div className="flex min-w-0 flex-col gap-4">
          {renderInspectorAndShortlist("desktop")}
          {renderPool("player-pool-desktop-heading")}
        </div>
        <aside className="sticky top-4 max-h-[calc(100svh-2rem)] self-start overflow-y-auto">
          <TeamRosters
            teams={board.teams}
            players={board.players}
            picks={board.picks}
            shape={board.session.roster_shape}
            myTeamId={gating.myTeamId}
            onClockTeamId={board.current_pick?.draft_team_id ?? null}
            variant="column"
            divisionGrid={divisionGrid}
            onlineCaptainIds={onlineCaptainIds}
          />
        </aside>
      </div>

      {pickBarVisible && (
        <PickCommandBar
          player={selectedPlayer}
          role={selectedRole}
          teamName={myTeam?.name ?? t("myTeam")}
          canConfirm={confirmAllowed}
          pending={mutations.makePick.isPending}
          connectionState={connectionState}
          announcement={announcement}
          onConfirm={confirm}
          divisionGrid={divisionGrid}
          board={board}
          isMyPick={gating.isMyPick}
          myTeamId={gating.myTeamId}
        />
      )}
    </div>
  );
}
