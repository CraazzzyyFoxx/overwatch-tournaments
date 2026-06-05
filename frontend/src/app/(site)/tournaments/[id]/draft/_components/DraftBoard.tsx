"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Ban,
  Check,
  Clock3,
  Crown,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
  Users,
  X,
} from "lucide-react";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useQuery } from "@tanstack/react-query";
import heroService from "@/services/hero.service";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { useTranslation } from "@/i18n/LanguageContext";
import { getRoleIconName, ROLE_LABELS } from "@/lib/roles";
import { resolveDivisionFromRank, DEFAULT_DIVISION_GRID, getDivisionLabel } from "@/lib/division-grid";
import { cn } from "@/lib/utils";
import type {
  DraftBoard as DraftBoardData,
  DraftPick,
  DraftPlayer,
  DraftRole,
  DraftSession,
  DraftStatus,
  DraftTeam,
} from "@/types/draft.types";
import type { Tournament } from "@/types/tournament.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl, getPlayerSlug } from "@/utils/player";

import { useDraftBoardQuery, useDraftMutations, useDraftRealtime } from "../_hooks/useDraftData";
import { computeGating, isUrgent, remainingMs } from "../_lib/draft-logic";
import { DraftClock } from "./DraftClock";
import styles from "./DraftBoard.module.css";

interface DraftBoardProps {
  tournament: Tournament;
}

type Translate = (key: string) => string;
type DraftMutations = ReturnType<typeof useDraftMutations>;
type RoleFilter = DraftRole | "all";
type SortMode = "rank" | "name";
type RoleCounts = Record<DraftRole, number>;
type TeamAccent = "teal" | "amber" | "rose" | "violet" | "blue";

const ROLE_ORDER: DraftRole[] = ["tank", "dps", "support"];
const ROLE_CLASS: Record<DraftRole, string> = {
  tank: styles.roleTank,
  dps: styles.roleDps,
  support: styles.roleSupport,
};
const TEAM_ACCENTS: TeamAccent[] = ["teal", "amber", "rose", "violet", "blue"];
const TEAM_ACCENT_CLASS: Record<TeamAccent, string> = {
  teal: styles.teamTeal,
  amber: styles.teamAmber,
  rose: styles.teamRose,
  violet: styles.teamViolet,
  blue: styles.teamBlue,
};
const FINAL_PICK_STATUSES = new Set<DraftPick["status"]>(["completed", "autopicked", "skipped"]);

export function DraftBoard({ tournament }: DraftBoardProps) {
  const { t } = useTranslation();
  const tournamentId = tournament.id;
  const boardQuery = useDraftBoardQuery(tournamentId);
  const board = boardQuery.data ?? null;
  useDraftRealtime(tournamentId, board);
  const mutations = useDraftMutations(tournamentId);

  const { user } = useAuthProfile();
  const { isSuperuser, isWorkspaceAdmin } = usePermissions();
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [selectedRole, setSelectedRole] = useState<DraftRole | null>(null);

  const isAdmin = isSuperuser || isWorkspaceAdmin(tournament.workspace_id);
  const myPlayerIds = useMemo(
    () => (user?.linkedPlayers ?? []).map((player) => player.playerId),
    [user]
  );

  const handleSelectPlayer = (id: number | null, role: DraftRole | null) => {
    setSelectedPlayerId(id);
    setSelectedRole(role);
  };

  if (boardQuery.isLoading) {
    return (
      <div className={cn(styles.surface, styles.stateCard)}>
        <Loader2 className={styles.spinIcon} aria-hidden />
        <span>{t("draft.loading")}</span>
      </div>
    );
  }

  if (!board) {
    return (
      <div className={cn(styles.surface, styles.emptyCard)}>
        <ShieldCheck aria-hidden />
        <p className={styles.emptyTitle}>{t("draft.empty.title")}</p>
        <p className={styles.emptyBody}>{t("draft.empty.body")}</p>
      </div>
    );
  }

  return (
    <DraftBoardView
      board={board}
      tournamentGrid={tournament.division_grid_version}
      myPlayerIds={myPlayerIds}
      myAuthUserId={user?.id ?? null}
      isAdmin={isAdmin}
      selectedPlayerId={selectedPlayerId}
      onSelectPlayer={handleSelectPlayer}
      selectedRole={selectedRole}
      onRoleSelect={setSelectedRole}
      mutations={mutations}
      t={t}
    />
  );
}

interface DraftBoardViewProps {
  board: DraftBoardData;
  tournamentGrid: DivisionGridVersion | null;
  myPlayerIds: number[];
  myAuthUserId: number | null;
  isAdmin: boolean;
  selectedPlayerId: number | null;
  onSelectPlayer: (id: number | null, role: DraftRole | null) => void;
  selectedRole: DraftRole | null;
  onRoleSelect: (role: DraftRole | null) => void;
  mutations: DraftMutations;
  t: Translate;
}

function DraftBoardView({
  board,
  tournamentGrid,
  myPlayerIds,
  myAuthUserId,
  isAdmin,
  selectedPlayerId,
  onSelectPlayer,
  selectedRole,
  onRoleSelect,
  mutations,
  t,
}: DraftBoardViewProps) {
  const { session, current_pick } = board;
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("rank");
  const [searchQuery, setSearchQuery] = useState("");
  const gating = computeGating(board, myPlayerIds, myAuthUserId, isAdmin);

  const { data: heroesData } = useQuery({
    queryKey: ["heroes-all"],
    queryFn: () => heroService.getAll({ perPage: -1 }),
    staleTime: 5 * 60_000,
  });

  const heroesMap = useMemo(() => {
    const map = new Map<string, any>();
    if (heroesData?.results) {
      for (const h of heroesData.results) {
        map.set(h.slug, h);
      }
    }
    return map;
  }, [heroesData]);

  const sortedTeams = useMemo(
    () => [...board.teams].sort((a, b) => a.draft_position - b.draft_position || a.id - b.id),
    [board.teams]
  );
  const sortedPicks = useMemo(
    () => [...board.picks].sort((a, b) => a.overall_no - b.overall_no || a.id - b.id),
    [board.picks]
  );
  const teamById = useMemo(() => new Map(sortedTeams.map((team) => [team.id, team])), [sortedTeams]);
  const playerById = useMemo(
    () => new Map(board.players.map((player) => [player.id, player])),
    [board.players]
  );
  const rosterByTeam = useMemo(() => buildRosterByTeam(board.players), [board.players]);
  const picksByTeam = useMemo(() => buildPicksByTeam(sortedPicks), [sortedPicks]);
  const availablePlayers = useMemo(
    () => board.players.filter((player) => player.status === "available"),
    [board.players]
  );
  const availableByRole = useMemo(() => countRoles(availablePlayers), [availablePlayers]);
  const filteredPlayers = useMemo(
    () => filterAndSortPlayers(availablePlayers, roleFilter, sortMode, searchQuery),
    [availablePlayers, roleFilter, searchQuery, sortMode]
  );
  const selectedPlayer =
    selectedPlayerId == null ? null : playerById.get(selectedPlayerId) ?? null;
  const onClockTeam =
    current_pick == null ? null : teamById.get(current_pick.draft_team_id) ?? null;
  const totalPicks = sortedPicks.length || session.rounds * sortedTeams.length;
  const completedCount = sortedPicks.filter(isFinalPick).length;
  const currentPickNumber =
    current_pick != null
      ? sortedPicks.findIndex((pick) => pick.id === current_pick.id) + 1
      : Math.min(completedCount + 1, Math.max(totalPicks, 1));

  const onClockTeamRoster = useMemo(() => {
    if (!onClockTeam) return [];
    return rosterByTeam.get(onClockTeam.id) ?? [];
  }, [onClockTeam, rosterByTeam]);

  const onClockTeamPicks = useMemo(() => {
    if (!onClockTeam) return [];
    return picksByTeam.get(onClockTeam.id) ?? [];
  }, [onClockTeam, picksByTeam]);

  const onClockTeamRoleCounts = useMemo(() => {
    const c: RoleCounts = { tank: 0, dps: 0, support: 0 };
    for (const player of onClockTeamRoster) {
      const pick = onClockTeamPicks.find((p) => p.picked_player_id === player.id);
      const draftedRole = (pick ? pick.target_role : player.primary_role) as DraftRole;
      if (c[draftedRole] !== undefined) {
        c[draftedRole] += 1;
      }
    }
    return c;
  }, [onClockTeamRoster, onClockTeamPicks]);

  const targets = useMemo(() => roleTargets(session.team_size), [session.team_size]);

  const isRoleFilled = (role: DraftRole) => {
    return onClockTeamRoleCounts[role] >= targets[role];
  };

  // Admins may pick on behalf of the on-clock captain (backend allows it via the
  // is_admin bypass), so the confirm UI is enabled for the on-clock captain OR an admin.
  const canConfirm = (gating.isMyPick || gating.isAdmin) && session.status === "live";

  const confirmPick = () => {
    if (!canConfirm || current_pick == null || selectedPlayerId == null || !selectedRole || isRoleFilled(selectedRole)) return;
    mutations.makePick.mutate({
      pickId: current_pick.id,
      playerId: selectedPlayerId,
      version: current_pick.version,
      role: selectedRole,
    });
    onSelectPlayer(null, null);
  };

  const runLifecycle = (action: "start" | "pause" | "resume" | "cancel" | "export") =>
    mutations.lifecycle.mutate({ sessionId: session.id, action });

  const runAutopick = () => {
    if (!current_pick) return;
    mutations.autopick.mutate({ pickId: current_pick.id, version: current_pick.version });
  };

  return (
    <div className={styles.surface}>
      <DraftHero
        session={session}
        sortedPicks={sortedPicks}
        currentPick={current_pick}
        currentPickNumber={currentPickNumber}
        completedCount={completedCount}
        totalPicks={totalPicks}
        onClockTeam={onClockTeam}
        teamsCount={sortedTeams.length}
        availableCount={availablePlayers.length}
        isAdmin={isAdmin}
        mutations={mutations}
        onLifecycle={runLifecycle}
        onAutopick={runAutopick}
        t={t}
      />

      <ViewerBanner gating={gating} onClockTeam={onClockTeam} t={t} />

      <div className={styles.boardGrid}>
        <DraftOrderPanel
          session={session}
          picks={sortedPicks}
          teamById={teamById}
          playerById={playerById}
          tournamentGrid={tournamentGrid}
          t={t}
        />

        <section className={styles.poolColumn} aria-label={label(t, "draft.pool.title", "Available players")}>
          <PoolToolbar
            availableCount={availablePlayers.length}
            filteredCount={filteredPlayers.length}
            availableByRole={availableByRole}
            roleFilter={roleFilter}
            sortMode={sortMode}
            searchQuery={searchQuery}
            onRoleFilterChange={setRoleFilter}
            onSortModeChange={setSortMode}
            onSearchChange={setSearchQuery}
            t={t}
          />

          <SelectedPlayerPanel
            selectedPlayer={selectedPlayer}
            tournamentGrid={tournamentGrid}
            canPick={canConfirm}
            isPending={mutations.makePick.isPending}
            selectedRole={selectedRole}
            onRoleSelect={onRoleSelect}
            onConfirm={confirmPick}
            onClear={() => onSelectPlayer(null, null)}
            isRoleFilled={isRoleFilled}
            t={t}
          />

          <PlayerPool
            players={filteredPlayers}
            selectedPlayerId={selectedPlayerId}
            tournamentGrid={tournamentGrid}
            onSelectPlayer={(id) => {
              const player = playerById.get(id);
              if (!player) {
                onSelectPlayer(null, null);
                return;
              }
              const roles = [player.primary_role, ...(player.secondary_roles_json ?? [])] as DraftRole[];
              const firstAvailableRole = roles.find((r) => !isRoleFilled(r));
              onSelectPlayer(id, firstAvailableRole ?? player.primary_role);
            }}
            t={t}
            heroesMap={heroesMap}
          />
        </section>

        <TeamsPanel
          session={session}
          teams={sortedTeams}
          rosterByTeam={rosterByTeam}
          picksByTeam={picksByTeam}
          currentPick={current_pick}
          myTeamId={gating.myTeamId}
          tournamentGrid={tournamentGrid}
          t={t}
        />
      </div>

      {canConfirm && selectedPlayer != null && (
        <div className={styles.floatingBar}>
          <div>
            <span className={styles.floatingLabel}>{label(t, "draft.pool.selected", "Selected")}</span>
            <strong>{playerName(selectedPlayer)}</strong>
            {(() => {
              const secondaryRoles = selectedPlayer.secondary_roles_json ?? [];
              const selectedPlayerRoles = [selectedPlayer.primary_role, ...secondaryRoles];
              return selectedPlayerRoles.length > 1 && selectedRole ? (
                <div className="flex items-center gap-1 mt-0.5 text-xs text-white/50">
                  Drafting as:
                  <span className="flex items-center gap-1 font-bold uppercase text-emerald-400">
                    <PlayerRoleIcon role={getRoleIconName(selectedRole)} size={16} />
                    {roleLabel(selectedRole)}
                  </span>
                </div>
              ) : null;
            })()}
          </div>
          <button
            type="button"
            className={cn(styles.actionButton, styles.actionPrimary)}
            disabled={mutations.makePick.isPending || !selectedRole || isRoleFilled(selectedRole)}
            onClick={confirmPick}
          >
            {mutations.makePick.isPending ? <Loader2 className={styles.smallSpin} aria-hidden /> : <Check aria-hidden />}
            {t("draft.actions.confirm")}
          </button>
        </div>
      )}
    </div>
  );
}

interface DraftHeroProps {
  session: DraftSession;
  sortedPicks: DraftPick[];
  currentPick: DraftPick | null;
  currentPickNumber: number;
  completedCount: number;
  totalPicks: number;
  onClockTeam: DraftTeam | null;
  teamsCount: number;
  availableCount: number;
  isAdmin: boolean;
  mutations: DraftMutations;
  onLifecycle: (action: "start" | "pause" | "resume" | "cancel" | "export") => void;
  onAutopick: () => void;
  t: Translate;
}

function DraftHero({
  session,
  sortedPicks,
  currentPick,
  currentPickNumber,
  completedCount,
  totalPicks,
  onClockTeam,
  teamsCount,
  availableCount,
  isAdmin,
  mutations,
  onLifecycle,
  onAutopick,
  t,
}: DraftHeroProps) {
  return (
    <section className={styles.hero}>
      <div className={styles.hex} />
      <div className={styles.glowOne} />
      <div className={styles.glowTwo} />

      <div className={styles.heroGrid}>
        <div className={styles.heroCell}>
          <div className={styles.label}>{label(t, "draft.live.progress", "Draft progress")}</div>
          <div className={styles.pickNumberLine}>
            <span className={styles.pickNumber}>#{currentPickNumber}</span>
            <span className={styles.pickTotal}>
              {completedCount}/{totalPicks} {t("draft.pick")}
            </span>
          </div>
          <div className={styles.roundMeta}>
            {t("draft.round")} {currentPick?.round_no ?? "-"} / {session.rounds}
            <span className={styles.metaDot} />
            {session.format.toUpperCase()}
          </div>
          <div className={styles.pips} aria-label={label(t, "draft.live.pickMap", "Pick map")}>
            {sortedPicks.map((pick) => (
              <span
                key={pick.id}
                className={cn(
                  styles.pip,
                  isFinalPick(pick) && styles.pipDone,
                  pick.id === currentPick?.id && styles.pipNow,
                  pick.status === "upcoming" && styles.pipUpcoming
                )}
                title={`${t("draft.pick")} #${pick.overall_no}: ${pickStatusLabel(t, pick.status)}`}
              />
            ))}
          </div>
        </div>

        <div className={styles.heroCell}>
          <div className={styles.label}>{t("draft.onTheClock")}</div>
          <div className={styles.onClock}>
            <div className={styles.onClockInfo}>
              <span className={styles.teamName}>
                {onClockTeam?.name ?? label(t, "draft.live.noActivePick", "No active pick")}
              </span>
              <span className={styles.onClockMeta}>
                {onClockTeam
                  ? `${label(t, "draft.team.position", "Seed")} #${onClockTeam.draft_position}`
                  : pickStatusLabel(t, session.status === "completed" ? "completed" : "upcoming")}
              </span>
              <span className={styles.roleTarget}>
                {label(t, "draft.order.targetRole", "Target")}:
                <RolePill role={currentPick?.target_role ?? null} />
              </span>
            </div>
          </div>
        </div>

        <div className={cn(styles.heroCell, styles.timerCell)}>
          <TimerRing session={session} currentPick={currentPick} />
          <div className={styles.timerMeta}>
            <span>
              <Users aria-hidden />
              {teamsCount} {label(t, "draft.team.title", "Teams")}
            </span>
            <span>
              <Sparkles aria-hidden />
              {availableCount} {label(t, "draft.pool.short", "Pool")}
            </span>
          </div>
        </div>
      </div>

      <div className={styles.heroFooter}>
        <span className={cn(styles.statusPill, styles[`status_${session.status}`])}>
          {session.status === "live" && <span className={styles.liveDot} />}
          {t(`draft.state.${session.status}`)}
        </span>
        <span className={styles.footerMeta}>
          {label(t, "draft.live.pickTime", "Pick time")} {session.pick_time_seconds}s
        </span>
        <span className={styles.footerMeta}>
          {label(t, "draft.live.teamSize", "Team size")} {session.team_size}
        </span>
        <AdminControls
          isAdmin={isAdmin}
          session={session}
          currentPick={currentPick}
          mutations={mutations}
          onLifecycle={onLifecycle}
          onAutopick={onAutopick}
          completedCount={completedCount}
          t={t}
        />
      </div>
    </section>
  );
}

interface AdminControlsProps {
  isAdmin: boolean;
  session: DraftSession;
  currentPick: DraftPick | null;
  mutations: DraftMutations;
  onLifecycle: (action: "start" | "pause" | "resume" | "cancel" | "export" | "rollback") => void;
  onAutopick: () => void;
  completedCount: number;
  t: Translate;
}

function AdminControls({
  isAdmin,
  session,
  currentPick,
  mutations,
  onLifecycle,
  onAutopick,
  completedCount,
  t,
}: AdminControlsProps) {
  if (!isAdmin) return null;

  const lifecycleBusy = mutations.lifecycle.isPending;
  const autopickBusy = mutations.autopick.isPending;
  const canAutopick = session.status === "live" && currentPick?.status === "on_clock";

  return (
    <div className={styles.adminControls} aria-label={label(t, "draft.admin.controls", "Admin controls")}>
      {(session.status === "setup" || session.status === "ready") && (
        <AdminButton disabled={lifecycleBusy} onClick={() => onLifecycle("start")} icon={<Play aria-hidden />}>
          {t("draft.admin.start")}
        </AdminButton>
      )}
      {session.status === "live" && (
        <AdminButton
          disabled={lifecycleBusy}
          onClick={() => onLifecycle("pause")}
          icon={<Pause aria-hidden />}
        >
          {t("draft.admin.pause")}
        </AdminButton>
      )}
      {session.status === "paused" && (
        <AdminButton disabled={lifecycleBusy} onClick={() => onLifecycle("resume")} icon={<Play aria-hidden />}>
          {t("draft.admin.resume")}
        </AdminButton>
      )}
      {canAutopick && (
        <AdminButton disabled={autopickBusy} onClick={onAutopick} icon={<Sparkles aria-hidden />}>
          {label(t, "draft.admin.autopick", "Autopick")}
        </AdminButton>
      )}
      {completedCount > 0 && (session.status === "live" || session.status === "paused" || session.status === "completed") && (
        <AdminButton
          disabled={lifecycleBusy}
          onClick={() => onLifecycle("rollback")}
          icon={<RotateCcw aria-hidden />}
        >
          {t("draft.admin.rollback")}
        </AdminButton>
      )}
      {(session.status === "live" || session.status === "paused" || session.status === "ready") && (
        <AdminButton
          tone="danger"
          disabled={lifecycleBusy}
          onClick={() => onLifecycle("cancel")}
          icon={<Ban aria-hidden />}
        >
          {t("draft.admin.cancel")}
        </AdminButton>
      )}
      {session.status === "completed" && (
        <AdminButton
          disabled={lifecycleBusy}
          onClick={() => onLifecycle("export")}
          icon={<Upload aria-hidden />}
        >
          {t("draft.admin.export")}
        </AdminButton>
      )}
    </div>
  );
}

interface AdminButtonProps {
  children: ReactNode;
  disabled: boolean;
  icon: ReactNode;
  tone?: "default" | "danger";
  onClick: () => void;
}

function AdminButton({ children, disabled, icon, tone = "default", onClick }: AdminButtonProps) {
  return (
    <button
      type="button"
      className={cn(styles.adminButton, tone === "danger" && styles.adminButtonDanger)}
      disabled={disabled}
      onClick={onClick}
    >
      {disabled ? <Loader2 className={styles.smallSpin} aria-hidden /> : icon}
      {children}
    </button>
  );
}

interface TimerRingProps {
  session: DraftSession;
  currentPick: DraftPick | null;
}

function TimerRing({ session, currentPick }: TimerRingProps) {
  const paused = session.status === "paused";
  const now = useNow(!paused && currentPick?.clock_expires_at != null);
  const totalMs = Math.max(session.pick_time_seconds * 1000, 1);
  const msLeft = remainingMs(currentPick?.clock_expires_at ?? null, now);
  const progress = currentPick?.clock_expires_at ? Math.max(0, Math.min(1, msLeft / totalMs)) : 0;
  const circumference = 2 * Math.PI * 54;
  const dashOffset = circumference * (1 - progress);
  const urgent = isUrgent(msLeft);
  const warn = msLeft > 0 && msLeft <= 20_000;

  return (
    <div
      className={cn(
        styles.timerRing,
        paused && styles.timerPaused,
        warn && styles.timerWarn,
        urgent && styles.timerCritical
      )}
    >
      <svg viewBox="0 0 128 128" aria-hidden>
        <circle className={styles.timerTrack} cx="64" cy="64" r="54" />
        <circle
          className={styles.timerFill}
          cx="64"
          cy="64"
          r="54"
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: dashOffset,
          }}
        />
      </svg>
      <div className={styles.timerCenter}>
        <DraftClock
          expiresAt={currentPick?.clock_expires_at ?? null}
          paused={paused}
          compact
        />
        <span>{session.status === "paused" ? "PAUSED" : "CLOCK"}</span>
      </div>
    </div>
  );
}

function useNow(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [enabled]);

  return now;
}

interface ViewerBannerProps {
  gating: ReturnType<typeof computeGating>;
  onClockTeam: DraftTeam | null;
  t: Translate;
}

function ViewerBanner({ gating, onClockTeam, t }: ViewerBannerProps) {
  const copy = gating.isMyPick
    ? {
        className: styles.bannerPick,
        icon: <Crown aria-hidden />,
        title: label(t, "draft.view.myPickTitle", "You are on the clock"),
        body: label(t, "draft.view.myPickBody", "Select a player from the pool and confirm the pick."),
      }
    : gating.isAdmin
      ? {
          className: styles.bannerAdmin,
          icon: <ShieldCheck aria-hidden />,
          title: label(t, "draft.view.adminTitle", "Admin view"),
          body: label(t, "draft.view.adminBody", "You can manage draft lifecycle while captains make picks."),
        }
      : gating.isCaptain
        ? {
            className: styles.bannerWaiting,
            icon: <Clock3 aria-hidden />,
            title: label(t, "draft.view.waitingTitle", "Waiting for your turn"),
            body: `${label(t, "draft.onTheClock", "On the clock")}: ${
              onClockTeam?.name ?? label(t, "draft.live.noActivePick", "No active pick")
            }.`,
          }
        : {
            className: styles.bannerSpectator,
            icon: <Users aria-hidden />,
            title: label(t, "draft.view.spectatorTitle", "Spectator view"),
            body: label(t, "draft.view.spectatorBody", "Follow the board live. Pick actions are hidden for spectators."),
          };

  return (
    <section className={cn(styles.viewerBanner, copy.className)}>
      <span className={styles.bannerIcon}>{copy.icon}</span>
      <div>
        <strong>{copy.title}</strong>
        <p>{copy.body}</p>
      </div>
    </section>
  );
}

interface DraftOrderPanelProps {
  session: DraftSession;
  picks: DraftPick[];
  teamById: Map<number, DraftTeam>;
  playerById: Map<number, DraftPlayer>;
  tournamentGrid: DivisionGridVersion | null;
  t: Translate;
}

function DraftOrderPanel({ session, picks, teamById, playerById, tournamentGrid, t }: DraftOrderPanelProps) {
  const groups = useMemo(() => groupPicksByRound(picks), [picks]);

  return (
    <aside className={styles.orderPanel}>
      <PanelHeader
        title={label(t, "draft.order.title", "Draft order")}
        meta={`${picks.length} ${t("draft.pick")}`}
      />
      <div className={styles.orderBody}>
        {groups.map(([roundNo, roundPicks]) => {
          const getRoundLabel = () => {
            if (session.format === "custom") {
              const rules = session.settings_json?.round_rules || [];
              const rule = rules[roundNo - 1] || "linear";
              switch (rule) {
                case "linear": return "FWD";
                case "reverse": return "REV";
                case "weakest_first": return "WEAKEST";
                case "strongest_first": return "STRONGEST";
                case "team_avg_asc": return "LOW AVG";
                case "team_avg_desc": return "HIGH AVG";
                default: return rule.toUpperCase();
              }
            }
            return session.format === "snake" && roundNo % 2 === 0 ? "REV" : "FWD";
          };
          const ruleLabel = getRoundLabel();
          return (
            <div key={roundNo} className={styles.roundGroup}>
              <div className={styles.roundHeader}>
                <span>
                  {t("draft.round")} {roundNo}
                </span>
                <span className="text-[10px] bg-white/10 px-1.5 py-0.5 rounded font-mono uppercase tracking-wider">
                  {ruleLabel}
                </span>
              </div>
              {roundPicks.map((pick) => (
                <PickRow
                  key={pick.id}
                  pick={pick}
                  team={teamById.get(pick.draft_team_id) ?? null}
                  pickedPlayer={pick.picked_player_id == null ? null : playerById.get(pick.picked_player_id) ?? null}
                  tournamentGrid={tournamentGrid}
                  t={t}
                />
              ))}
            </div>
          );
        })}
      </div>
    </aside>
  );
}

interface PickRowProps {
  pick: DraftPick;
  team: DraftTeam | null;
  pickedPlayer: DraftPlayer | null;
  tournamentGrid: DivisionGridVersion | null;
  t: Translate;
}

function PickRow({ pick, team, pickedPlayer, tournamentGrid, t }: PickRowProps) {
  const displayPlayer =
    pickedPlayer != null
      ? playerName(pickedPlayer)
      : pick.status === "on_clock"
        ? t("draft.onTheClock")
        : label(t, "draft.order.pending", "Pending");
  const role = pickedPlayer?.primary_role ?? pick.target_role;
  const pickedDivision = pickedPlayer
    ? pickedPlayer.division_number ??
      (pickedPlayer.rank_value != null
        ? resolveDivisionFromRank(tournamentGrid || DEFAULT_DIVISION_GRID, pickedPlayer.rank_value)
        : null)
    : null;

  return (
    <div className={cn(styles.pickRow, pickStatusClass(pick.status))}>
      <span className={styles.pickNum}>{pick.overall_no}</span>
      <div className={styles.pickMain}>
        {pickedPlayer?.battle_tag ? (
          <a
            href={`/users/${getPlayerSlug(pickedPlayer.battle_tag)}`}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(styles.pickName, "hover:underline hover:text-emerald-400 transition")}
          >
            {displayPlayer}
          </a>
        ) : (
          <span className={styles.pickName}>{displayPlayer}</span>
        )}
        <span className={styles.pickMeta}>
          {team?.name ?? label(t, "draft.team.unknown", "Unknown team")}
          {pickedDivision != null && (
            <span className="inline-flex items-center gap-1 ml-1 align-middle text-white/50" title={`${getDivisionLabel(tournamentGrid || DEFAULT_DIVISION_GRID, pickedDivision)} (${formatRank(pickedPlayer?.rank_value)})`}>
              <span>/</span>
              <PlayerDivisionIcon
                division={pickedDivision}
                width={20}
                height={20}
                tournamentGrid={tournamentGrid}
              />
            </span>
          )}
        </span>
      </div>
      <div className={styles.pickSide}>
        <RolePill role={role} />
        {pick.status === "completed" || pick.status === "autopicked" ? (
          <Check className="w-3.5 h-3.5 text-emerald-400 mt-0.5" aria-hidden />
        ) : (
          <span className={styles.pickState}>{pickStatusLabel(t, pick.status)}</span>
        )}
      </div>
    </div>
  );
}

interface PoolToolbarProps {
  availableCount: number;
  filteredCount: number;
  availableByRole: RoleCounts;
  roleFilter: RoleFilter;
  sortMode: SortMode;
  searchQuery: string;
  onRoleFilterChange: (role: RoleFilter) => void;
  onSortModeChange: (mode: SortMode) => void;
  onSearchChange: (query: string) => void;
  t: Translate;
}

function PoolToolbar({
  availableCount,
  filteredCount,
  availableByRole,
  roleFilter,
  sortMode,
  searchQuery,
  onRoleFilterChange,
  onSortModeChange,
  onSearchChange,
  t,
}: PoolToolbarProps) {
  return (
    <div className={styles.poolToolbar}>
      <div className={styles.toolbarTitle}>
        <strong>{t("draft.pool.title")}</strong>
        <span>
          {filteredCount}/{availableCount}
        </span>
      </div>

      <div className={styles.roleFilters} aria-label={label(t, "draft.pool.roleFilter", "Role filter")}>
        <RoleFilterButton
          active={roleFilter === "all"}
          label={label(t, "draft.pool.allRoles", "All")}
          count={availableCount}
          onClick={() => onRoleFilterChange("all")}
        />
        {ROLE_ORDER.map((role) => (
          <RoleFilterButton
            key={role}
            role={role}
            active={roleFilter === role}
            label={roleLabel(role)}
            count={availableByRole[role]}
            onClick={() => onRoleFilterChange(role)}
          />
        ))}
      </div>

      <label className={styles.searchBox}>
        <Search aria-hidden />
        <input
          value={searchQuery}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={label(t, "draft.pool.search", "Search player")}
        />
      </label>

      <div className={styles.sortBox}>
        <span>{label(t, "draft.pool.sort", "Sort")}</span>
        <Select
          value={sortMode}
          onValueChange={(value) => onSortModeChange(value as SortMode)}
        >
          <SelectTrigger className="border-0 bg-transparent h-8 px-0 shadow-none focus:ring-0 gap-1.5 text-xs font-extrabold text-[var(--draft-fg)] [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:opacity-80">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="rank">{label(t, "draft.pool.sortRank", "Rank")}</SelectItem>
            <SelectItem value="name">{label(t, "draft.pool.sortName", "Name")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

interface RoleFilterButtonProps {
  active: boolean;
  label: string;
  count: number;
  role?: DraftRole;
  onClick: () => void;
}

function RoleFilterButton({ active, label: text, count, role, onClick }: RoleFilterButtonProps) {
  return (
    <button
      type="button"
      className={cn(styles.roleFilter, active && styles.roleFilterActive, role && ROLE_CLASS[role])}
      onClick={onClick}
    >
      {role && <PlayerRoleIcon role={getRoleIconName(role)} size={18} />}
      <span>{text}</span>
      <em>{count}</em>
    </button>
  );
}

interface SelectedPlayerPanelProps {
  selectedPlayer: DraftPlayer | null;
  tournamentGrid: DivisionGridVersion | null;
  canPick: boolean;
  isPending: boolean;
  selectedRole: DraftRole | null;
  onRoleSelect: (role: DraftRole) => void;
  onConfirm: () => void;
  onClear: () => void;
  isRoleFilled: (role: DraftRole) => boolean;
  t: Translate;
}

function SelectedPlayerPanel({
  selectedPlayer,
  tournamentGrid,
  canPick,
  isPending,
  selectedRole,
  onRoleSelect,
  onConfirm,
  onClear,
  isRoleFilled,
  t,
}: SelectedPlayerPanelProps) {
  if (!selectedPlayer) {
    return (
      <div className={styles.selectedEmpty}>
        <Sparkles aria-hidden />
        <div>
          <strong>{label(t, "draft.pool.selectPromptTitle", "Select a player")}</strong>
          <p>
            {canPick
              ? label(t, "draft.pool.selectPromptPick", "Pick cards are live. Choose a player to prepare confirmation.")
              : label(t, "draft.pool.selectPromptReadOnly", "Click a card to inspect the player pool.")}
          </p>
        </div>
      </div>
    );
  }

  const division = selectedPlayer.division_number ?? (selectedPlayer.rank_value != null ? resolveDivisionFromRank(tournamentGrid || DEFAULT_DIVISION_GRID, selectedPlayer.rank_value) : null);
  const secondaryRoles = selectedPlayer.secondary_roles_json ?? [];
  const selectedPlayerRoles = [selectedPlayer.primary_role, ...secondaryRoles] as DraftRole[];

  return (
    <section className={cn(styles.selectedCard, "relative")} style={{ display: "flex", flexDirection: "column", alignItems: "stretch", gap: "16px", position: "relative" }}>
      <button
        type="button"
        className="absolute top-3 right-3 text-white/40 hover:text-white/80 transition p-1.5 rounded-full hover:bg-white/5"
        onClick={onClear}
        aria-label="Close"
      >
        <X size={16} />
      </button>

      <div style={{ display: "flex", flexDirection: "column", gap: "8px", paddingRight: "24px" }}>
        <div className={styles.selectedNameRow} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px" }}>
          {selectedPlayer.battle_tag ? (
            <a
              href={`/users/${getPlayerSlug(selectedPlayer.battle_tag)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xl font-bold uppercase tracking-wide text-white hover:underline hover:text-emerald-400 transition"
            >
              {playerName(selectedPlayer)}
            </a>
          ) : (
            <strong className="text-xl font-bold uppercase tracking-wide text-white">{playerName(selectedPlayer)}</strong>
          )}
          <RolePill role={selectedPlayer.primary_role} />
          {division != null && (
            <span className="inline-flex items-center gap-1 bg-white/5 border border-white/10 px-2 py-0.5 rounded text-xs font-semibold text-white/80">
              <PlayerDivisionIcon
                division={division}
                width={20}
                height={20}
                tournamentGrid={tournamentGrid}
              />
              <span>{getDivisionLabel(tournamentGrid || DEFAULT_DIVISION_GRID, division)}</span>
            </span>
          )}
          <span className="text-[10px] font-mono bg-white/5 border border-white/10 px-1.5 py-0.5 rounded text-white/40">
            ID: #{selectedPlayer.id}
          </span>
          {selectedPlayer.is_captain && (
            <span className={styles.captainTag}>
              <Crown aria-hidden />
              {label(t, "draft.player.captain", "Captain")}
            </span>
          )}
          {!canPick && (
            <span className="text-[9px] tracking-wider uppercase font-bold bg-white/5 border border-white/10 px-1.5 py-0.5 rounded text-white/30">
              {label(t, "draft.pool.readOnly", "Read-only")}
            </span>
          )}
        </div>

        {/* Subtitles / Tags row: Sub-roles, Flex, Secondary roles */}
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-white/50">
          {selectedPlayer.sub_role && (
            <span className="bg-white/[0.03] border border-white/5 px-2 py-0.5 rounded">
              {formatSubRoleLabel(selectedPlayer.sub_role)}
            </span>
          )}
          {selectedPlayer.is_flex && (
            <span className="bg-violet-500/10 border border-violet-500/20 text-violet-400 px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase">
              {label(t, "draft.player.flex", "Flex")}
            </span>
          )}
          {secondaryRoles.length > 0 && (
            <div className="flex items-center gap-1.5 ml-1">
              <span>Secondary:</span>
              {secondaryRoles.map((role) => (
                <span key={role} className={cn(styles.roleNeed, ROLE_CLASS[role as DraftRole])} style={{ padding: "3px 4px" }} title={roleLabel(role as DraftRole)}>
                  <PlayerRoleIcon role={getRoleIconName(role as DraftRole)} size={15} />
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Draft Role Selector */}
      {canPick && selectedPlayerRoles.length > 1 && (
        <div className="flex flex-col gap-1.5 border-t border-white/[0.05] pt-3 w-full">
          <span className="text-xs font-bold text-white/40">{label(t, "draft.actions.chooseRole", "Draft as role:")}</span>
          <div className="flex items-center gap-2">
            {selectedPlayerRoles.map((role) => {
              const filled = isRoleFilled(role);
              return (
                <button
                  key={role}
                  type="button"
                  disabled={filled}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition",
                    selectedRole === role
                      ? "bg-white/10 border-white/30 text-emerald-400"
                      : "bg-transparent border-white/5 text-white/40 hover:border-white/10 hover:text-white/60",
                    filled && "opacity-40 cursor-not-allowed border-dashed"
                  )}
                  onClick={() => onRoleSelect(role)}
                  title={filled ? "Role is filled" : undefined}
                >
                  <PlayerRoleIcon role={getRoleIconName(role)} size={16} />
                  <span>{roleLabel(role)} {filled && "(Filled)"}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {canPick && (
        <div className={styles.selectedActions} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", marginTop: 0 }}>
          {selectedRole && isRoleFilled(selectedRole) ? (
            <span className="text-rose-400 text-xs font-semibold">
              Role {roleLabel(selectedRole)} is filled
            </span>
          ) : <span />}
          <button
            type="button"
            className={cn(styles.actionButton, styles.actionPrimary)}
            disabled={selectedPlayer.status !== "available" || isPending || !selectedRole || isRoleFilled(selectedRole)}
            onClick={onConfirm}
          >
            {isPending ? <Loader2 className={styles.smallSpin} aria-hidden /> : <Check aria-hidden />}
            {t("draft.actions.confirm")}
          </button>
        </div>
      )}
    </section>
  );
}

interface PlayerPoolProps {
  players: DraftPlayer[];
  selectedPlayerId: number | null;
  tournamentGrid: DivisionGridVersion | null;
  onSelectPlayer: (id: number) => void;
  t: Translate;
  heroesMap: Map<string, any>;
}

function PlayerPool({
  players,
  selectedPlayerId,
  tournamentGrid,
  onSelectPlayer,
  t,
  heroesMap,
}: PlayerPoolProps) {
  if (players.length === 0) {
    return (
      <div className={styles.poolEmpty}>
        <Search aria-hidden />
        <span>{t("draft.pool.empty")}</span>
      </div>
    );
  }

  return (
    <div className={styles.playerGrid}>
      {players.map((player) => (
        <PlayerCard
          key={player.id}
          player={player}
          selected={player.id === selectedPlayerId}
          tournamentGrid={tournamentGrid}
          onSelect={() => onSelectPlayer(player.id)}
          t={t}
          heroesMap={heroesMap}
        />
      ))}
    </div>
  );
}

interface PlayerCardProps {
  player: DraftPlayer;
  selected: boolean;
  tournamentGrid: DivisionGridVersion | null;
  onSelect: () => void;
  t: Translate;
  heroesMap: Map<string, any>;
}

function PlayerCard({ player, selected, tournamentGrid, onSelect, t, heroesMap }: PlayerCardProps) {
  const allRoles = [player.primary_role, ...(player.secondary_roles_json ?? [])] as DraftRole[];
  const roleLabel = (r: DraftRole) => {
    if (r === "tank") return t("common.roles.tank");
    if (r === "dps") return t("common.roles.dps");
    return t("common.roles.support");
  };

  const handleNameClick = (e: React.MouseEvent) => {
    if (player.battle_tag) {
      e.stopPropagation();
      window.open(`/users/${getPlayerSlug(player.battle_tag)}`, "_blank", "noopener,noreferrer");
    }
  };

  return (
    <button
      type="button"
      className={cn(styles.playerCard, selected && styles.playerCardSelected, ROLE_CLASS[player.primary_role], "relative")}
      onClick={onSelect}
      style={{ position: "relative" }}
    >
      <div className={styles.playerTopline}>
        <span className={styles.playerIdentity} style={{ paddingRight: "24px" }}>
          {player.battle_tag ? (
            <strong
              className="hover:underline cursor-pointer hover:text-emerald-400 transition"
              onClick={handleNameClick}
            >
              {playerName(player)}
            </strong>
          ) : (
            <strong>{playerName(player)}</strong>
          )}
        </span>
        <div className="absolute top-2.5 right-2.5 flex items-center gap-1.5">
          {player.sub_role && (
            <span
              className="px-2 py-0.5 rounded text-[9px] font-extrabold uppercase tracking-wide"
              style={{
                backgroundColor: "color-mix(in srgb, var(--role-color) 16%, transparent)",
                border: "1px solid color-mix(in srgb, var(--role-color) 35%, transparent)",
                color: "white",
                textShadow: "0 0 8px color-mix(in srgb, var(--role-color) 50%, transparent)",
              }}
            >
              {formatSubRoleLabel(player.sub_role)}
            </span>
          )}
          <div
            className="p-1.5 rounded-md flex items-center justify-center"
            style={{
              backgroundColor: "color-mix(in srgb, var(--role-color) 12%, transparent)",
              border: "1px solid color-mix(in srgb, var(--role-color) 25%, transparent)",
              color: "var(--role-color)",
            }}
            title={roleLabel(player.primary_role)}
          >
            <PlayerRoleIcon role={getRoleIconName(player.primary_role)} size={11} />
          </div>
        </div>
      </div>
      <div className={styles.playerMetrics} style={{ display: "flex", flexDirection: "column", alignItems: "stretch", gap: "6px" }}>
        {allRoles.map((role) => {
          const roleRank = getRoleRank(player, role);
          const roleDiv = roleRank.division_number ?? (roleRank.rank_value != null ? resolveDivisionFromRank(tournamentGrid || DEFAULT_DIVISION_GRID, roleRank.rank_value) : null);
          return (
            <div key={role} className="flex items-center justify-between w-full">
              <div className="flex items-center">
                <PlayerRoleIcon role={getRoleIconName(role)} size={22} />
              </div>
              {roleDiv != null ? (
                <div className="flex items-center gap-1" title={formatRank(roleRank.rank_value)}>
                  {roleRank.top_heroes && roleRank.top_heroes.length > 0 && (
                    <span className="aqt-hero-strip mr-1.5">
                      {roleRank.top_heroes.slice(0, 5).map((hero) => {
                        const slug = typeof hero === "string" ? hero : hero.slug;
                        const heroObj = heroesMap.get(slug);
                        const imagePath = heroObj?.image_path || (typeof hero === "string" ? undefined : hero.image_path);
                        return (
                          <Avatar key={slug} className="w-8 h-8 rounded-full aqt-hero-av shrink-0 select-none">
                            <AvatarImage
                              src={getHeroIconUrl(slug, imagePath)}
                              alt={slug}
                              className="object-cover"
                            />
                            <AvatarFallback className="text-[8px] bg-white/5 uppercase">
                              {slug.slice(0, 2)}
                            </AvatarFallback>
                          </Avatar>
                        );
                      })}
                    </span>
                  )}
                  <PlayerDivisionIcon
                    division={roleDiv}
                    width={26}
                    height={26}
                    tournamentGrid={tournamentGrid}
                  />
                </div>
              ) : (
                <span className="text-xs text-white/30">&mdash;</span>
              )}
            </div>
          );
        })}
        {player.is_flex && <span className={styles.flexMark} style={{ alignSelf: "flex-start", marginTop: "2px" }}>FLEX</span>}
      </div>
    </button>
  );
}

interface TeamsPanelProps {
  session: DraftSession;
  teams: DraftTeam[];
  rosterByTeam: Map<number, DraftPlayer[]>;
  picksByTeam: Map<number, DraftPick[]>;
  currentPick: DraftPick | null;
  myTeamId: number | null;
  tournamentGrid: DivisionGridVersion | null;
  t: Translate;
}

function TeamsPanel({
  session,
  teams,
  rosterByTeam,
  picksByTeam,
  currentPick,
  myTeamId,
  tournamentGrid,
  t,
}: TeamsPanelProps) {
  return (
    <aside className={styles.teamsPanel}>
      <PanelHeader title={label(t, "draft.team.title", "Teams")} meta={`${teams.length}`} />
      <div className={styles.teamsList}>
        {teams.map((team) => {
          const roster = sortRoster(rosterByTeam.get(team.id) ?? []);
          const picks = picksByTeam.get(team.id) ?? [];
          return (
            <TeamCard
              key={team.id}
              session={session}
              team={team}
              roster={roster}
              picks={picks}
              current={team.id === currentPick?.draft_team_id}
              mine={team.id === myTeamId}
              tournamentGrid={tournamentGrid}
              t={t}
            />
          );
        })}
      </div>
    </aside>
  );
}

interface TeamCardProps {
  session: DraftSession;
  team: DraftTeam;
  roster: DraftPlayer[];
  picks: DraftPick[];
  current: boolean;
  mine: boolean;
  tournamentGrid: DivisionGridVersion | null;
  t: Translate;
}

function TeamCard({
  session,
  team,
  roster,
  picks,
  current,
  mine,
  tournamentGrid,
  t,
}: TeamCardProps) {
  const counts = useMemo(() => {
    const c: RoleCounts = { tank: 0, dps: 0, support: 0 };
    for (const player of roster) {
      const pick = picks.find((p) => p.picked_player_id === player.id);
      const draftedRole = (pick ? pick.target_role : player.primary_role) as DraftRole;
      if (c[draftedRole] !== undefined) {
        c[draftedRole] += 1;
      }
    }
    return c;
  }, [roster, picks]);
  const targets = roleTargets(session.team_size);
  const slots = Array.from({ length: Math.max(session.team_size, roster.length) }, (_, index) => roster[index] ?? null);
  const completedPicks = picks.filter(isFinalPick).length;

  return (
    <article className={cn(styles.teamCard, current && styles.teamCardCurrent, mine && styles.teamCardMine)}>
      <div className={styles.teamCardHead}>
        <div className={styles.teamTitle}>
          <strong>{team.name}</strong>
          <span>
            #{team.draft_position}
            {current && ` / ${t("draft.onTheClock")}`}
            {mine && ` / ${label(t, "draft.team.yours", "Your team")}`}
          </span>
        </div>
      </div>

      <div className={styles.teamStats}>
        <Stat label={label(t, "draft.team.roster", "Roster")} value={`${roster.length}/${session.team_size}`} />
        <Stat
          label={label(t, "draft.team.avgRank", "Avg rank")}
          value={
            (() => {
              const avgRank = averageRank(roster);
              const avgDivision = avgRank != null ? resolveDivisionFromRank(tournamentGrid || DEFAULT_DIVISION_GRID, Math.round(avgRank)) : null;
              return avgDivision != null ? (
                <div className="flex items-center justify-center h-[32px]" title={`${getDivisionLabel(tournamentGrid || DEFAULT_DIVISION_GRID, avgDivision)} (${formatRank(avgRank)})`}>
                  <PlayerDivisionIcon
                    division={avgDivision}
                    width={32}
                    height={32}
                    tournamentGrid={tournamentGrid}
                  />
                </div>
              ) : (
                formatRank(avgRank)
              );
            })()
          }
        />
        <Stat label={t("draft.pick")} value={`${completedPicks}/${picks.length}`} />
      </div>

      <div className={styles.roleMix}>
        {ROLE_ORDER.map((role) => (
          <span key={role} className={cn(styles.roleNeed, ROLE_CLASS[role])}>
            <PlayerRoleIcon role={getRoleIconName(role)} size={15} />
            <span>{counts[role]}/{targets[role]}</span>
          </span>
        ))}
      </div>

      <div className={styles.rosterSlots}>
        {slots.map((player, index) => {
          if (!player) {
            return (
              <div key={`empty-${index}`} className={styles.emptySlot}>
                <span>{index + 1}</span>
                <em>{label(t, "draft.team.emptySlot", "Open slot")}</em>
              </div>
            );
          }
          const pick = picks.find((p) => p.picked_player_id === player.id);
          const draftedRole = pick ? pick.target_role : player.primary_role;
          return (
            <RosterPlayer
              key={player.id}
              player={player}
              draftedRole={draftedRole}
              tournamentGrid={tournamentGrid}
              t={t}
            />
          );
        })}
      </div>
    </article>
  );
}

interface RosterPlayerProps {
  player: DraftPlayer;
  draftedRole: DraftRole | null;
  tournamentGrid: DivisionGridVersion | null;
  t: Translate;
}

function RosterPlayer({ player, draftedRole, tournamentGrid, t }: RosterPlayerProps) {
  const division = player.division_number ?? (player.rank_value != null ? resolveDivisionFromRank(tournamentGrid || DEFAULT_DIVISION_GRID, player.rank_value) : null);
  const roleLabel = (r: DraftRole) => {
    if (r === "tank") return t("common.roles.tank");
    if (r === "dps") return t("common.roles.dps");
    return t("common.roles.support");
  };

  return (
    <div className={styles.rosterPlayer}>
      <div className="flex items-center gap-2 min-w-0">
        {draftedRole && (
          <div
            className={cn("flex-shrink-0 flex items-center justify-center p-1.5 rounded-md bg-white/5", ROLE_CLASS[draftedRole])}
            style={{
              color: "var(--role-color)",
              border: "1px solid color-mix(in srgb, var(--role-color) 20%, transparent)",
            }}
            title={roleLabel(draftedRole)}
          >
            <PlayerRoleIcon role={getRoleIconName(draftedRole)} size={15} />
          </div>
        )}
        <div className="min-w-0">
          <strong className="block truncate text-xs font-bold text-white">
            {player.is_captain && <Crown aria-hidden className="inline mr-1 text-amber-400" />}
            {player.battle_tag ? (
              <a
                href={`/users/${getPlayerSlug(player.battle_tag)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline hover:text-emerald-400 transition"
              >
                {playerName(player)}
              </a>
            ) : (
              playerName(player)
            )}
          </strong>
          {player.sub_role && (
            <span className="block text-xs font-semibold text-white/65 truncate mt-0.5">
              {formatSubRoleLabel(player.sub_role)}
            </span>
          )}
        </div>
      </div>
      {division != null ? (
        <div className="flex items-center flex-shrink-0" title={`${getDivisionLabel(tournamentGrid || DEFAULT_DIVISION_GRID, division)} (${formatRank(player.rank_value)})`}>
          <PlayerDivisionIcon
            division={division}
            width={26}
            height={26}
            tournamentGrid={tournamentGrid}
          />
        </div>
      ) : (
        <span className={styles.rosterRank} title={formatRank(player.rank_value)}>&mdash;</span>
      )}
    </div>
  );
}

interface PanelHeaderProps {
  title: string;
  meta: string;
}

function PanelHeader({ title, meta }: PanelHeaderProps) {
  return (
    <div className={styles.panelHeader}>
      <strong>{title}</strong>
      <span>{meta}</span>
    </div>
  );
}

interface StatProps {
  label: string;
  value: ReactNode;
}

function Stat({ label: text, value }: StatProps) {
  return (
    <span className={styles.stat}>
      <em>{text}</em>
      <strong>{value}</strong>
    </span>
  );
}

interface RolePillProps {
  role: DraftRole | null;
}

function RolePill({ role }: RolePillProps) {
  if (!role) {
    return <span className={styles.rolePill}>FLEX</span>;
  }
  return (
    <span className={cn(styles.rolePill, ROLE_CLASS[role])} style={{ padding: "4px" }} title={roleLabel(role)}>
      <PlayerRoleIcon role={getRoleIconName(role)} size={16} />
    </span>
  );
}

interface TeamCrestProps {
  team: DraftTeam | null;
  size: "small" | "medium" | "large";
}

function TeamCrest({ team, size }: TeamCrestProps) {
  const accent = team ? TEAM_ACCENTS[(Math.max(team.draft_position, 1) - 1) % TEAM_ACCENTS.length] : "teal";
  return (
    <span className={cn(styles.crest, styles[`crest_${size}`], TEAM_ACCENT_CLASS[accent])}>
      {team ? teamInitials(team.name) : "--"}
    </span>
  );
}

function label(t: Translate, key: string, fallback: string): string {
  const translated = t(key);
  return translated === key ? fallback : translated;
}

function roleLabel(role: DraftRole): string {
  return ROLE_LABELS[role] ?? role.toUpperCase();
}

function shortRole(role: DraftRole): string {
  if (role === "tank") return "T";
  if (role === "dps") return "D";
  return "S";
}

function getRoleRank(player: DraftPlayer, role: DraftRole): {
  rank_value: number | null;
  division_number: number | null;
  top_heroes?: Array<string | { slug: string; image_path: string | null }>;
} {
  const rolesRanks = player.anomaly_flags?.roles_ranks as Record<string, {
    rank_value: number | null;
    division_number: number | null;
    top_heroes?: Array<string | { slug: string; image_path: string | null }>;
  }> | undefined;
  if (rolesRanks && rolesRanks[role]) {
    return rolesRanks[role];
  }
  if (role === player.primary_role) {
    return { rank_value: player.rank_value, division_number: player.division_number, top_heroes: [] };
  }
  return { rank_value: null, division_number: null, top_heroes: [] };
}

function playerName(player: DraftPlayer): string {
  return player.battle_tag ?? `Player #${player.id}`;
}

function playerInitials(player: DraftPlayer): string {
  const name = playerName(player).replace(/#\d+$/, "");
  return name
    .split(/[\s_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("") || String(player.id).slice(-2);
}

function teamInitials(name: string): string {
  const initials = name
    .split(/[\s_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
  return initials || name.slice(0, 2).toUpperCase();
}

function formatRank(value: number | null | undefined): string {
  return typeof value === "number" ? Math.round(value).toLocaleString("en-US") : "-";
}

function averageRank(players: DraftPlayer[]): number | null {
  const ranks = players
    .map((player) => player.rank_value)
    .filter((value): value is number => typeof value === "number");
  if (ranks.length === 0) return null;
  return ranks.reduce((sum, value) => sum + value, 0) / ranks.length;
}

function buildRosterByTeam(players: DraftPlayer[]): Map<number, DraftPlayer[]> {
  const map = new Map<number, DraftPlayer[]>();
  for (const player of players) {
    if (player.drafted_by_team_id == null) continue;
    const list = map.get(player.drafted_by_team_id) ?? [];
    list.push(player);
    map.set(player.drafted_by_team_id, list);
  }
  return map;
}

function buildPicksByTeam(picks: DraftPick[]): Map<number, DraftPick[]> {
  const map = new Map<number, DraftPick[]>();
  for (const pick of picks) {
    const list = map.get(pick.draft_team_id) ?? [];
    list.push(pick);
    map.set(pick.draft_team_id, list);
  }
  return map;
}

function countRoles(players: DraftPlayer[]): RoleCounts {
  return players.reduce<RoleCounts>(
    (counts, player) => {
      counts[player.primary_role] += 1;
      return counts;
    },
    { tank: 0, dps: 0, support: 0 }
  );
}

function roleTargets(teamSize: number): RoleCounts {
  if (teamSize >= 5) {
    return { tank: 1, dps: 2, support: Math.max(2, teamSize - 3) };
  }
  if (teamSize <= 0) return { tank: 0, dps: 0, support: 0 };
  const tank = Math.min(1, teamSize);
  const dps = Math.min(2, Math.max(teamSize - tank, 0));
  return { tank, dps, support: Math.max(teamSize - tank - dps, 0) };
}

function sortRoster(players: DraftPlayer[]): DraftPlayer[] {
  return [...players].sort((a, b) => {
    if (a.is_captain !== b.is_captain) return a.is_captain ? -1 : 1;
    return (b.rank_value ?? -1) - (a.rank_value ?? -1) || playerName(a).localeCompare(playerName(b));
  });
}

function filterAndSortPlayers(
  players: DraftPlayer[],
  roleFilter: RoleFilter,
  sortMode: SortMode,
  searchQuery: string
): DraftPlayer[] {
  const query = searchQuery.trim().toLowerCase();
  const filtered = players.filter((player) => {
    if (roleFilter !== "all" && player.primary_role !== roleFilter) return false;
    if (!query) return true;
    return [
      playerName(player),
      player.sub_role ?? "",
      roleLabel(player.primary_role),
      ...(player.secondary_roles_json ?? []),
    ]
      .join(" ")
      .toLowerCase()
      .includes(query);
  });

  return filtered.sort((a, b) => {
    if (sortMode === "name") {
      return playerName(a).localeCompare(playerName(b));
    }
    return (b.rank_value ?? -1) - (a.rank_value ?? -1) || playerName(a).localeCompare(playerName(b));
  });
}

function groupPicksByRound(picks: DraftPick[]): Array<[number, DraftPick[]]> {
  const map = new Map<number, DraftPick[]>();
  for (const pick of picks) {
    const list = map.get(pick.round_no) ?? [];
    list.push(pick);
    map.set(pick.round_no, list);
  }
  return [...map.entries()].sort(([a], [b]) => a - b);
}

function isFinalPick(pick: DraftPick): boolean {
  return FINAL_PICK_STATUSES.has(pick.status);
}

function pickStatusClass(status: DraftPick["status"]): string {
  const map: Record<DraftPick["status"], string> = {
    upcoming: styles.pickUpcoming,
    on_clock: styles.pickNow,
    completed: styles.pickDone,
    skipped: styles.pickSkipped,
    autopicked: styles.pickAuto,
  };
  return map[status];
}

function pickStatusLabel(t: Translate, status: DraftPick["status"] | DraftStatus): string {
  const fallback: Record<string, string> = {
    upcoming: "Upcoming",
    on_clock: "On clock",
    completed: "Completed",
    skipped: "Skipped",
    autopicked: "Autopick",
    setup: "Setup",
    ready: "Ready",
    live: "Live",
    paused: "Paused",
    cancelled: "Cancelled",
  };
  const key = status in fallback && status.includes("_")
    ? `draft.pickState.${status}`
    : status in fallback && ["upcoming", "completed", "skipped", "autopicked"].includes(status)
      ? `draft.pickState.${status}`
      : `draft.state.${status}`;
  return label(t, key, fallback[status] ?? status);
}
