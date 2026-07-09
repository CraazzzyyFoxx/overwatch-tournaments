"use client";

import { Fragment, useMemo, useState, createElement } from "react";
import Image from "next/image";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  Search,
  ShieldBan,
  UserPlus,
  XCircle,
  Gamepad2,
  Tv,
  Twitch,
  MessageSquare,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn, hexToRgba } from "@/lib/utils";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useColumnVisibility } from "@/hooks/useColumnVisibility";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import registrationService from "@/services/registration.service";
import type { Tournament } from "@/types/tournament.types";
import type { Registration, RegistrationStatus } from "@/types/registration.types";

import ColumnPicker from "./_components/ColumnPicker";
import { buildParticipantColumns } from "./_components/participantsColumns";
import { useTranslations, useLocale } from "next-intl";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import BattleTagRankHistory from "@/components/BattleTagRankHistory";
import { getStatusIcon } from "@/lib/status-icons";
import { formatSubroleSlug } from "@/lib/roles";

// ---------------------------------------------------------------------------
// Responsive class helper
// ---------------------------------------------------------------------------

const RESPONSIVE_CLASS: Record<string, string> = {
  always: "",
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
};

const ALIGN_CLASS: Record<"left" | "center", string> = {
  left: "text-left",
  center: "text-center",
};

// ---------------------------------------------------------------------------
// My registration status bar / card configs
// ---------------------------------------------------------------------------



const STATUS_BAR_CONFIG: Record<
  RegistrationStatus,
  { icon: typeof Clock; color: string }
> = {
  pending: {
    icon: Clock,
    color: "text-amber-400 border-amber-500/20 bg-amber-500/10",
  },
  approved: {
    icon: CheckCircle2,
    color: "text-emerald-400 border-emerald-500/20 bg-emerald-500/10",
  },
  rejected: {
    icon: XCircle,
    color: "text-red-400 border-red-500/20 bg-red-500/10",
  },
  withdrawn: {
    icon: XCircle,
    color: "text-white/40 border-white/10 bg-white/5",
  },
  banned: {
    icon: ShieldBan,
    color: "text-red-400 border-red-500/20 bg-red-500/10",
  },
  insufficient_data: {
    icon: AlertTriangle,
    color: "text-orange-400 border-orange-500/20 bg-orange-500/10",
  },
};

const ROLE_ACCENT_CLASSES: Record<string, { bg: string; text: string; border: string }> = {
  tank: { bg: "bg-sky-500/10", text: "text-sky-300", border: "border-sky-500/20" },
  dps: { bg: "bg-orange-500/10", text: "text-orange-300", border: "border-orange-500/20" },
  support: { bg: "bg-emerald-500/10", text: "text-emerald-300", border: "border-emerald-500/20" },
  flex: { bg: "bg-violet-500/10", text: "text-violet-300", border: "border-violet-500/20" },
};

const ROLE_TO_ICON: Record<string, string> = {
  tank: "Tank",
  dps: "Damage",
  support: "Support",
  flex: "Flex",
};

function getRoleLabel(
  role: string,
  t: ReturnType<typeof useTranslations<never>>,
): string {
  switch (role.toLowerCase()) {
    case "tank":
      return t("common.roles.tank");
    case "dps":
      return t("common.roles.dps");
    case "support":
      return t("common.roles.support");
    case "flex":
      return t("common.roles.flex");
    default:
      return role.charAt(0).toUpperCase() + role.slice(1);
  }
}

const DiscordIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 127.14 96.36" fill="currentColor" {...props}>
    <path d="M107.7,8.07A105.15,105.15,0,0,0,77.26,0a77.19,77.19,0,0,0-3.3,6.83A96.67,96.67,0,0,0,53.22,6.83,77.19,77.19,0,0,0,49.88,0,105.15,105.15,0,0,0,19.44,8.07C3.66,31.58-1.86,54.65,1,77.53A105.73,105.73,0,0,0,32,96.36a77.7,77.7,0,0,0,6.63-10.85,68.43,68.43,0,0,1-10.5-5c.87-.64,1.72-1.31,2.53-2a75.76,75.76,0,0,0,73,0c.81.69,1.66,1.36,2.53,2a68.43,68.43,0,0,1-10.5,5,77.7,77.7,0,0,0,6.63,10.85,105.73,105.73,0,0,0,31-18.83C129.86,49.2,123.63,26.54,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53S36.18,40.36,42.45,40.36,53.83,46,53.83,53,48.72,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.24,60,73.24,53S78.41,40.36,84.69,40.36,96.07,46,96.07,53,91,65.69,84.69,65.69Z" />
  </svg>
);

const STATUS_FILTER_META: Record<RegistrationStatus, { dot: string }> = {
  approved: { dot: "var(--aqt-emerald)" },
  pending: { dot: "var(--aqt-amber)" },
  insufficient_data: { dot: "var(--aqt-amber)" },
  rejected: { dot: "var(--aqt-rose)" },
  banned: { dot: "var(--aqt-rose)" },
  withdrawn: { dot: "var(--aqt-fg-dim)" },
};

const STATUS_FILTER_ORDER: RegistrationStatus[] = [
  "approved",
  "pending",
  "insufficient_data",
  "rejected",
  "banned",
  "withdrawn",
];

// localeKeyMap removed to support DB status names without hardcoded translation

type StatusFilter = "all" | RegistrationStatus;

function MyRegistrationCard({
  registration,
  canCheckIn,
  onCheckIn,
  onWithdraw,
  isCheckingIn,
  isWithdrawing,
  tournament,
}: {
  registration: Registration;
  canCheckIn: boolean;
  onCheckIn: () => void;
  onWithdraw: () => void;
  isCheckingIn: boolean;
  isWithdrawing: boolean;
  tournament: Tournament;
}) {
  const t = useTranslations();
  const [isExpanded, setIsExpanded] = useState(false);
  
  const primaryRole = registration.roles.find((r) => r.is_primary);
  const secondaryRoles = registration.roles
    .filter((r) => !r.is_primary)
    .sort((a, b) => a.priority - b.priority);

  const statusConfig =
    STATUS_BAR_CONFIG[registration.status] ?? STATUS_BAR_CONFIG.pending;
  
  const statusMeta = registration.status_meta;
  const statusName = statusMeta?.name ?? (
    registration.status.charAt(0).toUpperCase() + registration.status.slice(1).replace(/_/g, " ")
  );

  let StatusIcon = Clock;
  if (statusMeta?.icon_slug) {
    try {
      StatusIcon = getStatusIcon(statusMeta.icon_slug);
    } catch {
      StatusIcon = statusConfig.icon ?? Clock;
    }
  } else {
    StatusIcon = statusConfig.icon ?? Clock;
  }

  // Color styles
  let statusBadgeStyle: React.CSSProperties | undefined = undefined;
  let statusBadgeClass = cn(
    "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
    statusConfig.color
  );

  if (statusMeta?.icon_color) {
    const color = statusMeta.icon_color;
    statusBadgeClass = "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium";
    statusBadgeStyle = {
      color: color,
      borderColor: hexToRgba(color, 0.35) ?? color,
      backgroundColor: hexToRgba(color, 0.12) ?? "transparent",
    };
  }

  const isCheckedIn = registration.checked_in === true;

  let checkInBadgeClass = "bg-white/5 border-white/10 text-white/50";
  let checkInBadgeText = t("registration.myCard.checkInNotStarted");

  if (isCheckedIn) {
    checkInBadgeClass = "bg-emerald-500/10 border-emerald-500/20 text-emerald-400";
    checkInBadgeText = t("registration.myCard.checkedIn");
  } else if (canCheckIn) {
    checkInBadgeClass = "bg-amber-500/10 border-amber-500/20 text-amber-400 animate-pulse";
    checkInBadgeText = t("registration.myCard.checkInRequired");
  } else if (
    tournament.status === "live" ||
    tournament.status === "completed" ||
    tournament.status === "playoffs" ||
    tournament.status === "archived"
  ) {
    checkInBadgeClass = "bg-red-500/10 border-red-500/20 text-red-400";
    checkInBadgeText = t("registration.myCard.checkInClosed");
  }

  return (
    <div className="relative overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.02] shadow-md backdrop-blur-md transition-all duration-200">
      {/* Decorative gradient blurs */}
      <div className="absolute -right-16 -top-16 -z-10 size-32 rounded-full bg-blue-500/5 blur-2xl" />
      <div className="absolute -bottom-16 -left-16 -z-10 size-32 rounded-full bg-violet-500/5 blur-2xl" />

      {/* Main Bar (Always Visible) */}
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        {/* Left Side: Title, Status, Primary Role */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-white/90 uppercase tracking-wider">
              {t("registration.myCard.title")}
            </span>
            <span
              className={statusBadgeClass}
              style={statusBadgeStyle}
            >
              {createElement(StatusIcon, { className: "size-3" })}
              {statusName}
            </span>
          </div>

          {/* Primary Role indicator */}
          {primaryRole && (
            <div className="flex items-center gap-2 border-l border-white/10 pl-4 text-xs">
              <span className="text-white/40">{t("registration.myCard.primaryRole")}:</span>
              <div
                className={cn(
                  "inline-flex items-center gap-1.5 rounded px-2 py-0.5 font-medium border",
                  ROLE_ACCENT_CLASSES[primaryRole.role]?.bg,
                  ROLE_ACCENT_CLASSES[primaryRole.role]?.border,
                  ROLE_ACCENT_CLASSES[primaryRole.role]?.text,
                )}
              >
                <PlayerRoleIcon
                  role={ROLE_TO_ICON[primaryRole.role] ?? primaryRole.role}
                  size={12}
                />
                <span>{getRoleLabel(primaryRole.role, t)}</span>
                {primaryRole.subrole && (
                  <span className="opacity-60 text-[10px]">
                    ({formatSubroleSlug(primaryRole.subrole)})
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right Side: Check-in button/badge and toggle */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Check-in status indicator */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-white/40">{t("registration.myCard.checkInStatus")}:</span>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-semibold uppercase tracking-wide text-[10px]",
                checkInBadgeClass,
              )}
            >
              {checkInBadgeText}
            </span>
          </div>

          {/* Inline Check-in Button if required */}
          {canCheckIn && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onCheckIn();
              }}
              disabled={isCheckingIn}
              className="inline-flex items-center justify-center gap-1 rounded-md bg-emerald-500 px-3 py-1 text-xs font-semibold text-white shadow shadow-emerald-500/20 transition-all hover:bg-emerald-400 hover:shadow-emerald-500/30 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
            >
              {isCheckingIn && <Loader2 className="size-3 animate-spin" />}
              {isCheckingIn ? t("common.checkingIn") : t("common.checkIn")}
            </button>
          )}

          {/* Toggle details */}
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-2.5 py-1 text-xs font-medium text-white/70 hover:bg-white/[0.06] hover:text-white/95 transition-colors"
          >
            <span>{isExpanded ? t("registration.myCard.hideDetails") : t("registration.myCard.showDetails")}</span>
            {isExpanded ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
          </button>
        </div>
      </div>

      {/* Expanded Content Details */}
      {isExpanded && (
        <div className="border-t border-white/[0.06] bg-white/[0.01] p-4 transition-all duration-200">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            {/* Left Column: Fallbacks & Accounts */}
            <div className="space-y-4">
              {/* Secondary roles */}
              <div className="space-y-1.5">
                <h4 className="text-[10px] font-medium uppercase tracking-wider text-white/40">
                  {t("registration.myCard.secondaryRoles")}
                </h4>
                {secondaryRoles.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {secondaryRoles.map((r) => (
                      <div
                        key={r.role}
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
                          ROLE_ACCENT_CLASSES[r.role]?.bg,
                          ROLE_ACCENT_CLASSES[r.role]?.border,
                          ROLE_ACCENT_CLASSES[r.role]?.text,
                        )}
                      >
                        <PlayerRoleIcon
                          role={ROLE_TO_ICON[r.role] ?? r.role}
                          size={11}
                        />
                        <span>{getRoleLabel(r.role, t)}</span>
                        {r.subrole && (
                          <span className="text-[10px] opacity-60">
                            ({formatSubroleSlug(r.subrole)})
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs italic text-white/30">
                    {t("registration.myCard.noSecondaryRoles")}
                  </p>
                )}
              </div>

              {/* Linked accounts */}
              <div className="space-y-1.5">
                <h4 className="text-[10px] font-medium uppercase tracking-wider text-white/40">
                  {t("registration.myCard.accounts")}
                </h4>
                <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs">
                  {registration.battle_tag && (
                    <div className="flex items-center gap-1.5 rounded border border-white/[0.05] bg-white/[0.02] px-2 py-1">
                      <Gamepad2 className="size-3.5 text-white/40" />
                      <span className="font-semibold text-white/85">{registration.battle_tag}</span>
                    </div>
                  )}
                  {registration.discord_nick && (
                    <div className="flex items-center gap-1.5 rounded border border-white/[0.05] bg-white/[0.02] px-2 py-1">
                      <DiscordIcon className="size-3.5 text-[#5865F2]" />
                      <span className="text-white/70">{registration.discord_nick}</span>
                    </div>
                  )}
                  {registration.twitch_nick && (
                    <div className="flex items-center gap-1.5 rounded border border-white/[0.05] bg-white/[0.02] px-2 py-1">
                      <Twitch className="size-3.5 text-[#9146FF]" />
                      <span className="text-white/70">{registration.twitch_nick}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Right Column: POV, Notes & Cancel Action */}
            <div className="space-y-4 flex flex-col justify-between">
              {/* POV and Notes */}
              <div className="space-y-2.5">
                <div className="flex items-center gap-2 text-xs">
                  <Tv className="size-3.5 text-white/40" />
                  <span
                    className={cn(
                      "font-medium",
                      registration.stream_pov ? "text-emerald-400" : "text-white/50",
                    )}
                  >
                    {registration.stream_pov
                      ? t("registration.myCard.streamPovActive")
                      : t("registration.myCard.streamPovInactive")}
                  </span>
                </div>

                <div className="rounded-lg border border-white/[0.04] bg-white/[0.02] p-2.5 text-xs">
                  {registration.notes ? (
                    <p className="italic text-white/60 leading-normal">
                      &ldquo;{registration.notes}&rdquo;
                    </p>
                  ) : (
                    <span className="italic text-white/30">
                      {t("registration.myCard.noNotes")}
                    </span>
                  )}
                </div>
              </div>

              {/* Action row at bottom of details */}
              <div className="flex items-center justify-between border-t border-white/[0.04] pt-3 mt-2">
                {/* Pending check-in state helper text */}
                <div className="text-[11px] text-white/40">
                  {isCheckedIn ? (
                    <span className="text-emerald-400 font-medium">
                      {t("registration.myCard.checkInSuccess")}
                    </span>
                  ) : registration.status === "approved" ? (
                    <span>{t("registration.myCard.pendingCheckInDesc")}</span>
                  ) : (
                    <span>{t("registration.myCard.pendingReviewDesc")}</span>
                  )}
                </div>

                {/* Withdraw button */}
                {(registration.status === "pending" ||
                  registration.status === "approved") && (
                  <button
                    type="button"
                    onClick={onWithdraw}
                    disabled={isWithdrawing || isCheckingIn}
                    className="inline-flex items-center justify-center rounded-md border border-red-500/20 bg-red-500/5 px-2.5 py-1.5 text-[11px] font-semibold text-red-400/90 transition-all hover:border-red-500/40 hover:bg-red-500/10 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
                  >
                    {isWithdrawing && <Loader2 className="size-3 animate-spin mr-1" />}
                    {isWithdrawing ? t("common.withdrawing") : t("common.withdraw")}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function isCheckInWindowActive(tournament: Tournament) {
  if (tournament.status !== "check_in") return false;

  const now = Date.now();
  const opensAt = tournament.check_in_opens_at
    ? new Date(tournament.check_in_opens_at).getTime()
    : null;
  const closesAt = tournament.check_in_closes_at
    ? new Date(tournament.check_in_closes_at).getTime()
    : null;

  return (opensAt === null || opensAt <= now) && (closesAt === null || now <= closesAt);
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function TournamentParticipantsPage({
  tournament,
}: {
  tournament: Tournament;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const { user, status: authStatus } = useAuthProfile();
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useLocalStorageState<string>(
    `tournament-participants-${tournament.id}-search`,
    "",
  );
  const [statusFilter, setStatusFilter] = useLocalStorageState<StatusFilter>(
    `tournament-participants-${tournament.id}-status`,
    "all",
  );
  const [isWithdrawDialogOpen, setIsWithdrawDialogOpen] = useState(false);
  const [isCheckInDialogOpen, setIsCheckInDialogOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const toggleExpanded = (registrationId: number) =>
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(registrationId)) {
        next.delete(registrationId);
      } else {
        next.add(registrationId);
      }
      return next;
    });

  const isAuthenticated = authStatus === "authenticated" && user !== null;

  const myRegQuery = useQuery({
    queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getMyRegistration(tournament.id),
    enabled: isAuthenticated,
  });

  const listQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.listRegistrations(tournament.id),
  });

  const formQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationForm(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getForm(tournament.id),
  });

  const withdrawMutation = useMutation({
    mutationFn: () => registrationService.withdrawMyRegistration(tournament.id),
    onSuccess: async () => {
      setIsWithdrawDialogOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationForm(tournament.workspace_id, tournament.id),
        }),
      ]);
    },
  });

  const checkInMutation = useMutation({
    mutationFn: () => registrationService.checkInMyRegistration(tournament.id),
    onSuccess: async () => {
      setIsCheckInDialogOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id),
        }),
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id),
        }),
      ]);
    },
  });

  const registrations = listQuery.data ?? [];
  const myRegistration = myRegQuery.data;
  const form = formQuery.data ?? null;
  const canCheckIn =
    Boolean(myRegistration) &&
    myRegistration?.status === "approved" &&
    myRegistration.checked_in !== true &&
    isCheckInWindowActive(tournament);

  const divisionGrid = useDivisionGrid();

  // Dynamic columns
  const allColumns = useMemo(
    () => buildParticipantColumns(form, t, locale, divisionGrid),
    [form, t, locale, divisionGrid],
  );
  const { visibleColumns, visibility, toggleColumn, resetToDefaults } =
    useColumnVisibility("participants-table-columns", allColumns);

  // Status counts + chips present in the data.
  const statusCounts = useMemo(() => {
    const counts: Partial<Record<RegistrationStatus, number>> = {};
    for (const reg of registrations) {
      counts[reg.status] = (counts[reg.status] ?? 0) + 1;
    }
    return counts;
  }, [registrations]);

  const presentStatuses = useMemo(() => {
    // Collect all unique statuses actually present in registrations
    const uniqueStatuses = Array.from(new Set(registrations.map((r) => r.status)));
    
    // Sort them so that built-in ones in STATUS_FILTER_ORDER come first, and any others (custom) come after
    return uniqueStatuses.sort((a, b) => {
      const idxA = STATUS_FILTER_ORDER.indexOf(a);
      const idxB = STATUS_FILTER_ORDER.indexOf(b);
      
      if (idxA !== -1 && idxB !== -1) {
        return idxA - idxB;
      }
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;
      
      // Both are custom, sort alphabetically
      return a.localeCompare(b);
    });
  }, [registrations]);

  const statusMetaMap = useMemo(() => {
    const map: Record<string, { name: string; dot: string }> = {};
    for (const reg of registrations) {
      if (!map[reg.status]) {
        // Resolve name: prefer status_meta.name, fallback to humanized value
        let name = reg.status_meta?.name ?? reg.status;
        if (name === reg.status) {
          name = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
        }

        // Resolve dot color: prefer status_meta.icon_color, fallback to STATUS_FILTER_META, fallback to gray
        let dot = reg.status_meta?.icon_color ?? "";
        if (!dot) {
          dot = STATUS_FILTER_META[reg.status as RegistrationStatus]?.dot ?? "var(--aqt-fg-dim)";
        }

        map[reg.status] = { name, dot };
      }
    }
    return map;
  }, [registrations]);

  // Status filter + dynamic search across all searchable columns.
  const filtered = useMemo(() => {
    const byStatus =
      statusFilter === "all"
        ? registrations
        : registrations.filter((r) => r.status === statusFilter);

    if (!searchQuery.trim()) return byStatus;
    const q = searchQuery.trim().toLowerCase();
    return byStatus.filter((r) =>
      visibleColumns.some((col) => {
        if (!col.searchValue) return false;
        const val = col.searchValue(r);
        return val?.toLowerCase().includes(q) ?? false;
      }),
    );
  }, [registrations, searchQuery, statusFilter, visibleColumns]);

  return (
    <div className="space-y-5">
      {/* My registration status */}
      {myRegistration && (
        <MyRegistrationCard
          registration={myRegistration}
          canCheckIn={canCheckIn}
          onCheckIn={() => setIsCheckInDialogOpen(true)}
          onWithdraw={() => setIsWithdrawDialogOpen(true)}
          isCheckingIn={checkInMutation.isPending}
          isWithdrawing={withdrawMutation.isPending}
          tournament={tournament}
        />
      )}

      <AlertDialog
        open={isCheckInDialogOpen}
        onOpenChange={setIsCheckInDialogOpen}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("common.confirmCheckIn")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("common.checkInDesc")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={checkInMutation.isPending}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                event.preventDefault();
                checkInMutation.mutate();
              }}
              disabled={checkInMutation.isPending}
              className="border border-emerald-500/30 bg-emerald-600 text-white hover:bg-emerald-500"
            >
              {checkInMutation.isPending ? t("common.checkingIn") : t("common.checkIn")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={isWithdrawDialogOpen}
        onOpenChange={setIsWithdrawDialogOpen}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("common.withdrawReg")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("common.withdrawDesc")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={withdrawMutation.isPending}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                event.preventDefault();
                withdrawMutation.mutate();
              }}
              disabled={withdrawMutation.isPending}
              className="bg-red-600 text-white hover:bg-red-500"
            >
              {withdrawMutation.isPending ? t("common.withdrawing") : t("common.confirmWithdraw")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Header */}
      <div className="section-head">
        <h2>
          {t("common.participants")} <span className="count-tag">{registrations.length}</span>
        </h2>
      </div>

      {/* Status filter chips + search + column picker */}
      {registrations.length > 0 && (
        <div className="filters">
          <button
            type="button"
            className={cn("filter-chip", statusFilter === "all" && "active")}
            onClick={() => setStatusFilter("all")}
          >
            {t("common.all")} <span className="count">{registrations.length}</span>
          </button>
          {presentStatuses.map((status) => {
            const meta = statusMetaMap[status];
            return (
              <button
                key={status}
                type="button"
                className={cn("filter-chip", statusFilter === status && "active")}
                onClick={() => setStatusFilter(statusFilter === status ? "all" : status)}
              >
                <span className="dot" style={{ background: meta?.dot ?? "var(--aqt-fg-dim)" }} />
                {meta?.name ?? status}{" "}
                <span className="count">{statusCounts[status] ?? 0}</span>
              </button>
            );
          })}
          <div className="filter-search">
            <Search size={13} />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t("common.searchParticipants")}
            />
          </div>
          <ColumnPicker
            columns={allColumns}
            visibility={visibility}
            onToggle={toggleColumn}
            onReset={resetToDefaults}
          />
        </div>
      )}

      {/* Participants list */}
      {listQuery.isLoading ? (
        <div className="tn-card" style={{ padding: "48px 24px", textAlign: "center" }}>
          <Loader2 className="mx-auto size-6 animate-spin text-white/30" />
        </div>
      ) : filtered.length > 0 ? (
        <div className="tn-card">
          <div className="data-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="w-10" aria-hidden />
                  {visibleColumns.map((col) => (
                    <th
                      key={col.id}
                      className={cn(
                        RESPONSIVE_CLASS[col.responsive ?? "always"],
                        ALIGN_CLASS[col.align ?? "left"],
                        col.widthClass,
                      )}
                    >
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((reg, idx) => {
                  const isExpanded = expandedIds.has(reg.id);
                  const hiddenColumns = allColumns.filter(
                    (col) => col.id !== "_index" && !visibleColumns.some((vc) => vc.id === col.id)
                  );
                  return (
                    <Fragment key={reg.id}>
                      <tr>
                        <td className="align-middle">
                          <button
                            type="button"
                            onClick={() => toggleExpanded(reg.id)}
                            className="inline-flex size-6 items-center justify-center rounded text-white/40 transition-colors hover:bg-white/5 hover:text-white"
                            aria-label={isExpanded ? t("common.collapse") : t("common.expand")}
                            aria-expanded={isExpanded}
                          >
                            {isExpanded ? (
                              <ChevronUp className="size-4" />
                            ) : (
                              <ChevronDown className="size-4" />
                            )}
                          </button>
                        </td>
                        {visibleColumns.map((col) => (
                          <td
                            key={col.id}
                            className={cn(
                              RESPONSIVE_CLASS[col.responsive ?? "always"],
                              ALIGN_CLASS[col.align ?? "left"],
                              col.widthClass,
                            )}
                          >
                            {col.render(reg, idx)}
                          </td>
                        ))}
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td
                            colSpan={visibleColumns.length + 1}
                            className="border-t border-white/[0.06] bg-white/[0.015] p-4"
                          >
                            <div className="grid gap-4 lg:grid-cols-4">
                              <div className="space-y-2 lg:col-span-3">
                                <div className="text-[11px] font-semibold uppercase tracking-wider text-white/45">
                                  {t("tournamentDetail.rankHistory")}
                                </div>
                                <BattleTagRankHistory
                                  userId={reg.user_id}
                                  battleTag={reg.battle_tag}
                                />
                              </div>
                              <div className="rounded-xl border border-white/[0.05] bg-black/10 p-4 space-y-3.5 text-xs lg:col-span-1">
                                <div className="text-[11px] font-bold uppercase tracking-widest text-white/80 border-b border-white/[0.06] pb-1.5 mb-2">
                                  {t("registration.myCard.details")}
                                </div>
                                {hiddenColumns.length === 0 ? (
                                  <div className="text-white/30 italic py-1 text-center">
                                    {t("tournamentDetail.allFieldsVisible")}
                                  </div>
                                ) : (
                                  <div className="grid grid-cols-2 gap-x-4 gap-y-3 lg:grid-cols-1">
                                    {hiddenColumns.map((col) => (
                                      <div key={col.id} className="space-y-1">
                                        <div className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
                                          {col.label}
                                        </div>
                                        <div className="text-white/80">
                                          {col.render(reg, idx)}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="tn-card" style={{ padding: "56px 24px", textAlign: "center" }}>
          <UserPlus className="mx-auto size-9 text-white/15" />
          <p className="mt-3 text-sm" style={{ color: "var(--fg-dim)" }}>
            {t("common.noParticipants")}
          </p>
        </div>
      )}
    </div>
  );
}

