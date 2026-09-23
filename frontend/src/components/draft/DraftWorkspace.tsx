"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useDraftTeamFitQuery,
  useDraftTeamQueue,
  type DraftMutations
} from "@/hooks/useDraftData";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { canConfirmPick, type DraftGating } from "@/lib/draft/logic";
import {
  actingTeamId,
  buildTeamViews,
  fitByPlayer,
  isOverrideAct,
  needRoles,
  onClockTeamId,
  seatOf,
  type PickTarget,
  type QueueControls,
  type RoomSelection,
  type TeamFilter,
  type TeamSort
} from "@/lib/draft/room-model";
import {
  draftPoolView,
  DRAFT_MOBILE_VIEWS,
  type DraftMobileView,
  type DraftViewParams
} from "@/lib/draft/workspace-model";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { DraftBoard, DraftPickOptionsResponse, DraftPresenceState, DraftRole } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { Tournament } from "@/types/tournament.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { AdminStrip } from "./AdminStrip";
import styles from "./DraftRoom.module.css";
import { PickIsland } from "./PickIsland";
import { PickPill } from "./PickPill";
import { PlayerPool } from "./PlayerPool";
import { RoomBanner } from "./RoomBanner";
import { RoomClockStrip } from "./RoomClockStrip";
import { RoomHeader } from "./RoomHeader";
import { TeamsPanel } from "./TeamsPanel";

interface DraftWorkspaceProps {
  tournament: Tournament;
  board: DraftBoard;
  gating: DraftGating;
  presence: DraftPresenceState;
  options: DraftPickOptionsResponse | null;
  optionsLoading: boolean;
  onRetryOptions: () => void;
  connectionState: RealtimeConnectionState;
  viewParams: DraftViewParams;
  onViewParamsChange: (patch: Partial<DraftViewParams>) => void;
  mutations: DraftMutations;
  divisionGrid: DivisionGrid;
  onlineCaptainIds: ReadonlySet<number>;
}

// Tailwind's `xl`. One tree at a time: the pool is the heaviest list in the
// app, and mounting it twice (desktop + tabs) doubled every re-render.
const WIDE_QUERY = "(min-width: 80rem)";
const subscribeWide = (onChange: () => void) => {
  const query = window.matchMedia(WIDE_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
};
const isWideNow = () => window.matchMedia(WIDE_QUERY).matches;
const NOT_WIDE_ON_SERVER = () => false;

/** Enter already activates these; the confirm shortcut must not fire on top. */
const INTERACTIVE =
  "a,button,input,textarea,select,summary,[role=button],[role=tab],[role=radio],[role=option],[role=checkbox],[contenteditable=true]";
/** Esc belongs to these first: a modal, popover or menu closes itself, not the card behind it. */
const OWNS_ESCAPE = "[role=dialog][data-state],[role=alertdialog],[role=listbox],[role=menu],#dock-stack";

const NO_FOLLOWED: number[] = [];

/**
 * ONE live draft room for every seat, and the owner of all the state its
 * panels share. Spectator, captain and admin read the same board with
 * different rights, so the same tree renders for all of them and `gating`
 * decides which affordances exist. An admin who is also a captain gets both.
 */
export function DraftWorkspace({
  tournament,
  board,
  gating,
  presence,
  options,
  optionsLoading,
  onRetryOptions,
  connectionState,
  viewParams,
  onViewParamsChange,
  mutations,
  divisionGrid,
  onlineCaptainIds
}: Readonly<DraftWorkspaceProps>) {
  const t = useTranslations("draftRedesign");
  const sessionId = board.session.id;
  const seat = seatOf(gating);
  const wide = useSyncExternalStore(subscribeWide, isWideNow, NOT_WIDE_ON_SERVER);

  const [pendingSelection, setSelection] = useState<RoomSelection | null>(null);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [target, setTarget] = useState<PickTarget>("mine");
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("all");
  const [teamSort, setTeamSort] = useState<TeamSort>("order");
  const [followedIds, setFollowedIds] = useLocalStorageState<number[]>(`aqt.draft.follow.${sessionId}`, NO_FOLLOWED);
  const followed = useMemo(() => new Set(followedIds), [followedIds]);

  const teamViews = useMemo(() => buildTeamViews(board), [board]);
  const actingId = actingTeamId(board, gating, target);
  const actingTeam = actingId == null ? null : (teamViews.get(actingId) ?? null);
  const overrideMode = isOverrideAct(board, gating, actingId);
  const clockId = onClockTeamId(board);
  const showTargets =
    seat === "captain_admin" && clockId != null && clockId !== gating.myTeamId && actingTeam != null;

  // Only a captain has a list. The server narrows it to available players.
  const queueTeamId = gating.isCaptain ? gating.myTeamId : null;
  const { query: queueQuery, playerIds: queueIds, setQueue } = useDraftTeamQueue(sessionId, queueTeamId);
  const mutateQueue = setQueue.mutate;
  const queue = useMemo<QueueControls | null>(() => {
    if (queueTeamId == null) return null;
    const save = (ids: number[]) => mutateQueue(ids, { onError: (error) => notify.apiError(error) });
    return {
      ids: queueIds,
      toggle: (playerId) =>
        save(queueIds.includes(playerId) ? queueIds.filter((id) => id !== playerId) : [...queueIds, playerId]),
      move: (playerId, direction) => {
        const from = queueIds.indexOf(playerId);
        const to = from + direction;
        if (from < 0 || to < 0 || to >= queueIds.length) return;
        const next = [...queueIds];
        [next[from], next[to]] = [next[to], next[from]];
        save(next);
      }
    };
  }, [queueTeamId, queueIds, mutateQueue]);
  const autopickPreview = queueQuery.data?.autopick_preview ?? null;

  const fitQuery = useDraftTeamFitQuery(sessionId, actingId, actingId != null);
  const fitScores = fitQuery.data?.scores;
  const fit = useMemo(
    () => (fitScores ? fitByPlayer(fitScores, viewParams.role) : null),
    [fitScores, viewParams.role]
  );

  // "My list" is a captain's; a shared link carrying `pool=shortlist` shows
  // everyone else the available players instead of an empty, tab-less list.
  // A finished draft has nobody available, so its default tab is everyone.
  const finished = board.session.status === "completed";
  const poolParams = useMemo<DraftViewParams>(() => {
    if (!gating.isCaptain && viewParams.pool === "shortlist") return { ...viewParams, pool: finished ? "all" : "available" };
    if (finished && viewParams.pool === "available") return { ...viewParams, pool: "all" };
    return viewParams;
  }, [finished, gating.isCaptain, viewParams]);
  const pool = useMemo(
    () => draftPoolView(board.players, poolParams, queueIds, actingTeam ? needRoles(actingTeam) : null),
    [board.players, poolParams, queueIds, actingTeam]
  );

  // A captain may line a pick up BEFORE their turn; the board can take that
  // player away in the meantime. The stored pair is only LIVE while its player
  // is still available — derived here rather than cleared in an effect, which
  // would render one frame with the stale pick enabled.
  const storedPlayer =
    pendingSelection == null ? null : (board.players.find((player) => player.id === pendingSelection.playerId) ?? null);
  const takenPlayer = storedPlayer != null && storedPlayer.status !== "available" ? storedPlayer : null;
  const selection = takenPlayer == null ? pendingSelection : null;
  const subjectId = profileId ?? selection?.playerId ?? null;
  const subject = subjectId == null ? null : (board.players.find((player) => player.id === subjectId) ?? null);

  const currentPick = board.current_pick;
  // Only claim a player is safe or blocked when the server's option list is
  // actually here. Without it every row would read as "no role keeps every
  // remaining roster feasible" — a verdict nobody computed.
  const safetyRequired = gating.isMyPick && options != null;
  const optionsUnavailable = gating.isMyPick && options == null && !optionsLoading;
  const canConfirm =
    gating.isMyPick &&
    currentPick != null &&
    actingId === gating.myTeamId &&
    canConfirmPick(connectionState, currentPick.version, options, selection);

  useEffect(() => {
    // Not when I am the one who just drafted them: that is a success, and it
    // already said so.
    if (takenPlayer && takenPlayer.drafted_by_team_id !== gating.myTeamId) {
      notify.info(t("selectionTaken", { player: takenPlayer.battle_tag ?? `#${takenPlayer.id}` }));
    }
  }, [takenPlayer, gating.myTeamId, t]);

  const clearAll = () => {
    setSelection(null);
    setProfileId(null);
  };
  // A card showing someone other than the selection closes first (back to the
  // selection's card); the next dismissal drops the selection too.
  const dismiss = () => {
    if (profileId != null && profileId !== selection?.playerId) setProfileId(null);
    else clearAll();
  };
  const onSelect = (playerId: number, role: DraftRole) => {
    if (selection?.playerId === playerId && selection.role === role) {
      clearAll();
      return;
    }
    setSelection({ playerId, role });
    setProfileId(playerId);
  };
  const onSelectRole = (role: DraftRole) => {
    if (!subject) return;
    setSelection(
      selection?.playerId === subject.id && selection.role === role ? null : { playerId: subject.id, role }
    );
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat) return;
      const el = event.target instanceof Element ? event.target : null;
      if (event.key === "Escape") {
        if (subjectId == null || el?.closest(OWNS_ESCAPE)) return;
        dismiss();
        return;
      }
      if (event.key !== "Enter" || !canConfirm || el?.closest(INTERACTIVE)) return;
      // The island's confirm button owns the pick, its toasts and its live
      // region; the shortcut only presses it.
      const confirm = document.querySelector<HTMLButtonElement>("[data-draft-confirm]:not(:disabled)");
      if (!confirm) return;
      event.preventDefault();
      confirm.click();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // The panels fill the viewport under the header, whatever the header holds
  // right now (admin strip, open journal, banner). Written as a CSS variable
  // so a header resize never re-renders the room.
  const rootRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const root = rootRef.current;
    const header = headerRef.current;
    if (!root || !header) return;
    const sync = () => root.style.setProperty("--draft-header-h", `${header.offsetHeight}px`);
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(header);
    return () => observer.disconnect();
  }, []);

  // The pool reserves the floating layer's height so its last rows stay reachable.
  const layerRef = useRef<HTMLDivElement>(null);
  const [bottomInset, setBottomInset] = useState(96);
  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return;
    const observer = new ResizeObserver(() => setBottomInset(Math.ceil(layer.offsetHeight) + 16));
    observer.observe(layer);
    return () => observer.disconnect();
  }, []);

  const renderPool = (headingId: string) => (
    <PlayerPool
      board={board}
      pool={pool}
      viewParams={poolParams}
      onViewParamsChange={onViewParamsChange}
      teamViews={teamViews}
      actingTeam={actingTeam}
      selection={selection}
      profileId={profileId}
      onSelect={onSelect}
      onOpenProfile={setProfileId}
      queue={queue}
      fit={fit}
      options={options}
      safetyRequired={safetyRequired}
      divisionGrid={divisionGrid}
      headingId={headingId}
      bottomInset={bottomInset}
    />
  );
  const renderTeams = (headingId: string) => (
    <TeamsPanel
      board={board}
      teamViews={teamViews}
      tab={viewParams.teams}
      onTabChange={(teams) => onViewParamsChange({ teams })}
      filter={teamFilter}
      onFilterChange={setTeamFilter}
      sort={teamSort}
      onSortChange={setTeamSort}
      followed={followed}
      onToggleFollow={(teamId) =>
        setFollowedIds((current) =>
          current.includes(teamId) ? current.filter((id) => id !== teamId) : [...current, teamId]
        )
      }
      myTeamId={gating.myTeamId}
      onlineCaptainIds={onlineCaptainIds}
      onOpenProfile={setProfileId}
      onSlotFilter={gating.isCaptain ? (role) => onViewParamsChange({ role, view: "pool" }) : undefined}
      divisionGrid={divisionGrid}
      headingId={headingId}
    />
  );

  return (
    <div ref={rootRef} className="min-h-svh tabular-nums">
      <header
        ref={headerRef}
        className="relative z-30 border-b border-[color:var(--aqt-border)] bg-[color:color-mix(in_srgb,var(--aqt-bg)_88%,transparent)] backdrop-blur-xl"
      >
        <RoomHeader
          tournament={tournament}
          board={board}
          gating={gating}
          presence={presence}
          connectionState={connectionState}
        />
        <RoomClockStrip
          board={board}
          gating={gating}
          followed={followed}
          onlineCaptainIds={onlineCaptainIds}
          onViewParamsChange={onViewParamsChange}
        />
        {gating.isAdmin && <AdminStrip board={board} mutations={mutations} onlineCaptainIds={onlineCaptainIds} />}
        <RoomBanner board={board} gating={gating} autopickPreview={autopickPreview} />
        {optionsLoading && gating.isMyPick && (
          <output className="mx-auto block max-w-[1720px] px-4 pb-2 text-sm text-[color:var(--aqt-fg-muted)] sm:px-6">
            {t("checkingSafeOptions")}
          </output>
        )}
        {optionsUnavailable && (
          <output className="mx-auto flex max-w-[1720px] flex-wrap items-center gap-2 px-4 pb-2 text-sm text-[color:var(--aqt-fg-muted)] sm:px-6">
            {t("safeOptionsUnavailable")}
            <button
              type="button"
              onClick={onRetryOptions}
              className="min-h-11 rounded-sm text-[color:var(--aqt-teal)] underline outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
            >
              {t("retry")}
            </button>
          </output>
        )}
      </header>

      <div className="mx-auto max-w-[1720px] px-4 pb-5 pt-3.5 sm:px-6">
        {wide ? (
          <div className="flex items-start gap-3.5">
            <div className={cn("min-w-0 flex-[1_1_600px]", styles.roomPanel)}>{renderPool("player-pool-heading")}</div>
            <div className={cn("min-w-[520px] flex-[0_1_600px]", styles.roomPanel)}>
              {renderTeams("teams-panel-heading")}
            </div>
          </div>
        ) : (
          // Radix Tabs, not hand-rolled roles: it wires aria-controls, roving
          // tabindex and arrow-key traversal that a plain button row lacks.
          <Tabs value={viewParams.view} onValueChange={(view) => onViewParamsChange({ view: view as DraftMobileView })}>
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
                  {t(`shell.tabs.${view}`)}
                </TabsTrigger>
              ))}
            </TabsList>
            <TabsContent value="pool" className="mt-3.5">
              {renderPool("player-pool-heading")}
            </TabsContent>
            <TabsContent value="teams" className="mt-3.5">
              {renderTeams("teams-panel-heading")}
            </TabsContent>
          </Tabs>
        )}
      </div>

      {/* Bottom-centre, above everything but modals. From `lg` the layer is
          centred in the space left of the RoomChat dock (bottom-end, 22rem)
          so the card never covers the conversation. Below `sm` it is a
          full-width sheet. */}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex justify-center sm:px-4 sm:pb-[max(1rem,env(safe-area-inset-bottom))] lg:pe-[24rem]">
        <div ref={layerRef} className="pointer-events-auto w-full sm:w-[min(780px,100%)]">
          {/* Always mounted: with `player = null` it keeps only its live
              region, so a pick's announcement outlives the card closing. */}
          <PickIsland
            board={board}
            gating={gating}
            player={subject}
            selection={selection}
            onSelectRole={onSelectRole}
            onClose={dismiss}
            actingTeam={actingTeam}
            overrideMode={overrideMode}
            showTargets={showTargets}
            target={target}
            onTargetChange={setTarget}
            canConfirm={canConfirm}
            connectionState={connectionState}
            mutations={mutations}
            autopickPreview={autopickPreview}
            queue={queue}
            divisionGrid={divisionGrid}
            onPicked={clearAll}
          />
          {subject == null && actingTeam != null && currentPick != null && (
            <div className="px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:p-0">
              <PickPill board={board} gating={gating} actingTeam={actingTeam} overrideMode={overrideMode} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
