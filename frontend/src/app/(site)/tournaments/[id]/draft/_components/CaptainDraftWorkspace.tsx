"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { canConfirmPick } from "../_lib/draft-logic";
import type { DraftGating } from "../_lib/draft-logic";
import {
  filterDraftPlayers,
  playerRoles,
  type DraftViewParams
} from "../_lib/draft-workspace-model";
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
import type { useDraftMutations } from "../_hooks/useDraftData";

import { CaptainShortlist } from "./CaptainShortlist";
import { DraftEventFeed } from "./DraftEventFeed";
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
  connectionState: RealtimeConnectionState;
  viewParams: DraftViewParams;
  onViewParamsChange: (patch: Partial<DraftViewParams>) => void;
  mutations: ReturnType<typeof useDraftMutations>;
  divisionGrid: DivisionGrid;
  onlineCaptainIds?: Set<number>;
}

const MOBILE_VIEWS = ["pool", "team", "order"] as const;

export function CaptainDraftWorkspace({
  board,
  gating,
  options,
  optionsLoading,
  connectionState,
  viewParams,
  onViewParamsChange,
  mutations,
  divisionGrid,
  onlineCaptainIds
}: CaptainDraftWorkspaceProps) {
  const t = useTranslations("draftRedesign");
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [selectedRole, setSelectedRole] = useState<DraftRole | null>(null);
  const [shortlist, setShortlist] = useState<Set<number>>(() => new Set());
  const [announcement, setAnnouncement] = useState("");
  const availablePlayers = useMemo(
    () => board.players.filter((player) => player.status === "available"),
    [board.players]
  );
  const filteredPlayers = useMemo(
    () => filterDraftPlayers(availablePlayers, viewParams),
    [availablePlayers, viewParams]
  );
  const roleCounts = useMemo<Record<DraftRole, number>>(() => {
    const counts: Record<DraftRole, number> = { tank: 0, dps: 0, support: 0 };
    for (const player of availablePlayers) {
      for (const role of playerRoles(player)) {
        counts[role] += 1;
      }
    }
    return counts;
  }, [availablePlayers]);
  const selectedPlayer =
    selectedPlayerId == null
      ? null
      : availablePlayers.find((player) => player.id === selectedPlayerId) ?? null;
  const shortlistPlayers = availablePlayers.filter((player) => shortlist.has(player.id));
  const myTeam = board.teams.find((team) => team.id === gating.myTeamId) ?? null;
  const currentPick = board.current_pick;
  const safetyRequired = gating.isMyPick;
  const selection = selectedPlayer && selectedRole
    ? { playerId: selectedPlayer.id, role: selectedRole }
    : null;
  const confirmAllowed =
    gating.isMyPick &&
    currentPick != null &&
    canConfirmPick(connectionState, currentPick.version, options, selection);

  const selectPlayer = (player: DraftPlayer, role: DraftRole | null = null) => {
    setSelectedPlayerId(player.id);
    setSelectedRole(role ?? playerRoles(player)[0] ?? null);
    setAnnouncement("");
  };
  const toggleShortlist = (playerId: number) => {
    setShortlist((current) => {
      const next = new Set(current);
      if (next.has(playerId)) next.delete(playerId);
      else next.add(playerId);
      return next;
    });
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

  const pool = (
    <PlayerPool
      players={filteredPlayers}
      totalPlayers={availablePlayers.length}
      roleCounts={roleCounts}
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
    />
  );
  const team = (
    <TeamRosters
      teams={board.teams}
      players={board.players}
      picks={board.picks}
      teamSize={board.session.team_size}
      myTeamId={gating.myTeamId}
      onClockTeamId={board.current_pick?.draft_team_id ?? null}
      divisionGrid={divisionGrid}
      onlineCaptainIds={onlineCaptainIds}
    />
  );
  const order = (
    <DraftOrder
      picks={board.picks}
      teams={board.teams}
      players={board.players}
      compact
      divisionGrid={divisionGrid}
    />
  );

  return (
    <div className="space-y-5">
      {optionsLoading && gating.isMyPick && (
        <p className="border-l-2 border-[color:var(--aqt-teal)] pl-3 text-sm text-[color:var(--aqt-fg-muted)]" role="status">
          {t("checkingSafeOptions")}
        </p>
      )}

      <div className="flex gap-1 rounded-xl bg-[color:var(--aqt-card-2)] p-1 xl:hidden" role="tablist" aria-label={t("mobileViews")}>
        {MOBILE_VIEWS.map((view) => (
          <button
            key={view}
            type="button"
            role="tab"
            aria-selected={viewParams.view === view}
            onClick={() => onViewParamsChange({ view })}
            className={cn(
              "min-h-11 flex-1 rounded-lg px-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
              viewParams.view === view && "bg-[color:var(--aqt-card)] text-[color:var(--aqt-teal)]"
            )}
          >
            {t(`mobileView.${view}`)}
          </button>
        ))}
      </div>

      <div className="xl:hidden">
        <div role="tabpanel">
          {viewParams.view === "pool" ? (
            <div className="space-y-6">
              <PlayerInspector
                player={selectedPlayer}
                role={selectedRole}
                options={options}
                safetyRequired={safetyRequired}
                headingId="player-inspector-mobile-heading"
                onRoleChange={setSelectedRole}
                onClose={() => {
                  setSelectedPlayerId(null);
                  setSelectedRole(null);
                }}
                divisionGrid={divisionGrid}
              />
              <CaptainShortlist
                variant="chips"
                players={shortlistPlayers}
                onSelect={(player) => selectPlayer(player)}
                onRemove={toggleShortlist}
                divisionGrid={divisionGrid}
              />
              {pool}
            </div>
          ) : viewParams.view === "team" ? team : order}
        </div>
      </div>

      <div className="hidden gap-4 xl:grid xl:grid-cols-[248px_minmax(0,1fr)_378px]">
        <aside className="sticky top-4 self-start space-y-4">
          <DraftOrder picks={board.picks} teams={board.teams} players={board.players} divisionGrid={divisionGrid} />
          <DraftEventFeed picks={board.picks} teams={board.teams} players={board.players} />
        </aside>
        <main className="flex min-w-0 flex-col gap-4">
          <PlayerInspector
            player={selectedPlayer}
            role={selectedRole}
            options={options}
            safetyRequired={safetyRequired}
            headingId="player-inspector-desktop-heading"
            onRoleChange={setSelectedRole}
            onClose={() => {
              setSelectedPlayerId(null);
              setSelectedRole(null);
            }}
            divisionGrid={divisionGrid}
          />
          <CaptainShortlist
            variant="chips"
            players={shortlistPlayers}
            onSelect={(player) => selectPlayer(player)}
            onRemove={toggleShortlist}
            divisionGrid={divisionGrid}
          />
          {pool}
        </main>
        <aside className="sticky top-4 max-h-[calc(100svh-2rem)] self-start overflow-y-auto">
          <TeamRosters
            teams={board.teams}
            players={board.players}
            picks={board.picks}
            teamSize={board.session.team_size}
            myTeamId={gating.myTeamId}
            onClockTeamId={board.current_pick?.draft_team_id ?? null}
            variant="column"
            divisionGrid={divisionGrid}
            onlineCaptainIds={onlineCaptainIds}
          />
        </aside>
      </div>

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
    </div>
  );
}
