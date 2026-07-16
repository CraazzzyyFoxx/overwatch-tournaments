"use client";

import {
  createElement,
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Loader2,
  Search,
  ShieldBan,
  X,
  XCircle,
  Tv,
  Twitch,
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
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import registrationService from "@/services/registration.service";
import type { Tournament } from "@/types/tournament.types";
import type { Registration, RegistrationStatus } from "@/types/registration.types";

import ColumnPicker from "./_components/ColumnPicker";
import { buildParticipantColumns } from "./_components/participantsColumns";
import {
  PARTICIPANT_SEARCH_MAX_LENGTH,
  isMandatoryParticipantColumnId,
  parseStoredParticipantColumnIds,
  participantColumnsStorageKey,
  participantDefaultColumnIds,
  participantResultsScrollTarget,
  participantResultsTransitionSignature,
  readParticipantUrlState,
  shouldScrollParticipantResults,
  subscribeParticipantColumnsStorage,
  updateParticipantUrlState,
  writeStoredParticipantColumnIds,
  type ParticipantUrlUpdate,
} from "./_components/participants-url-state";
import { useParticipantSearchInput } from "./_components/useParticipantSearchInput";
import VirtualParticipantsList from "./_components/VirtualParticipantsList";
import { useTranslations, useLocale } from "next-intl";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { getStatusIcon } from "@/lib/status-icons";
import { formatSubroleSlug } from "@/lib/roles";
import { TournamentParticipantsSkeleton } from "../_components/TournamentSkeletons";
import { TournamentPageState } from "../_components/TournamentPageState";
import styles from "../TournamentDetail.module.css";

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
    color: "text-[color:var(--aqt-fg-dim)] border-[color:var(--aqt-border-2)] bg-white/5",
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

type RegistrationStepTone = "done" | "active" | "failed" | "idle";

interface RegistrationStep {
  key: string;
  label: string;
  tone: RegistrationStepTone;
}

/** Statuses that permanently take the registration out of the tournament. */
const TERMINAL_REGISTRATION_STATUSES = new Set<string>([
  "rejected",
  "banned",
  "withdrawn",
]);

const CHECK_IN_OVER_TOURNAMENT_STATUSES = new Set<string>([
  "live",
  "playoffs",
  "completed",
  "archived",
]);

function RegistrationStepMarker({ tone }: { tone: RegistrationStepTone }) {
  switch (tone) {
    case "done":
      return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-emerald-500/40 bg-emerald-500/15 text-emerald-400">
          <Check className="size-3.5" strokeWidth={3} />
        </span>
      );
    case "failed":
      return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-red-500/40 bg-red-500/15 text-red-400">
          <X className="size-3.5" strokeWidth={3} />
        </span>
      );
    case "active":
      return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-amber-400/50 bg-amber-500/10">
          <span className="size-2 animate-pulse rounded-full bg-amber-400" />
        </span>
      );
    default:
      return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-[color:var(--aqt-border-2)] bg-white/5">
          <span className="size-1.5 rounded-full bg-[color:var(--aqt-fg-dim)]" />
        </span>
      );
  }
}

function RegistrationRoleChip({
  role,
  showPrimaryMark,
  t,
}: {
  role: Registration["roles"][number];
  showPrimaryMark: boolean;
  t: ReturnType<typeof useTranslations<never>>;
}) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        ROLE_ACCENT_CLASSES[role.role]?.bg,
        ROLE_ACCENT_CLASSES[role.role]?.border,
        ROLE_ACCENT_CLASSES[role.role]?.text,
      )}
    >
      <PlayerRoleIcon role={ROLE_TO_ICON[role.role] ?? role.role} size={12} />
      <span>{getRoleLabel(role.role, t)}</span>
      {role.subrole && (
        <span className="text-[10px] opacity-60">
          ({formatSubroleSlug(role.subrole)})
        </span>
      )}
      {showPrimaryMark && (
        <span className="text-[10px] uppercase tracking-wide opacity-70">
          · {t("registration.myCard.primaryRole")}
        </span>
      )}
    </div>
  );
}

function MyRegistrationCard({
  registration,
  canCheckIn,
  onCheckIn,
  onWithdraw,
  isCheckingIn,
  isWithdrawing,
  tournament,
  requireOpenProfile,
}: {
  registration: Registration;
  canCheckIn: boolean;
  onCheckIn: () => void;
  onWithdraw: () => void;
  isCheckingIn: boolean;
  isWithdrawing: boolean;
  tournament: Tournament;
  requireOpenProfile: boolean;
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
  const statusName =
    statusMeta?.name ??
    registration.status.charAt(0).toUpperCase() +
      registration.status.slice(1).replace(/_/g, " ");

  let StatusIcon = statusConfig.icon ?? Clock;
  if (statusMeta?.icon_slug) {
    try {
      StatusIcon = getStatusIcon(statusMeta.icon_slug);
    } catch {
      StatusIcon = statusConfig.icon ?? Clock;
    }
  }

  // Custom statuses carry their own accent color; builtin ones use the
  // Tailwind classes from STATUS_BAR_CONFIG.
  let statusChipStyle: React.CSSProperties | undefined = undefined;
  if (statusMeta?.icon_color) {
    const color = statusMeta.icon_color;
    statusChipStyle = {
      color: color,
      borderColor: hexToRgba(color, 0.35) ?? color,
      backgroundColor: hexToRgba(color, 0.12) ?? "transparent",
    };
  }

  const isCheckedIn = registration.checked_in === true;
  const isApproved = registration.status === "approved";
  const isTerminal = TERMINAL_REGISTRATION_STATUSES.has(registration.status);
  const checkInPhaseOver =
    !isCheckedIn &&
    !canCheckIn &&
    CHECK_IN_OVER_TOURNAMENT_STATUSES.has(tournament.status);
  const canWithdraw =
    registration.status === "pending" || registration.status === "approved";
  // "ready" is the terminal balancer state: the organizers added the player to
  // the pool and assigned a rank. Anything else (not_in_balancer, incomplete,
  // custom slugs, missing field) means the rank is still pending.
  const balancerReady = registration.balancer_status === "ready";

  // Registration journey: submitted -> review/approved -> profile visibility
  // (when required) -> balancing (rank assignment) -> check-in.
  const profileStep: RegistrationStep | null = requireOpenProfile
    ? {
        key: "profile",
        label:
          registration.profiles_open === true
            ? t("common.profileOpen")
            : registration.profiles_open === false
              ? t("common.profileClosed")
              : t("common.profileNotChecked"),
        tone:
          registration.profiles_open === true
            ? "done"
            : registration.profiles_open === false
              ? "failed"
              : isTerminal
                ? "idle"
                : "active",
      }
    : null;

  const steps: RegistrationStep[] = [
    {
      key: "submitted",
      label: t("registration.myCard.steps.submitted"),
      tone: "done",
    },
    {
      key: "review",
      label:
        isApproved || isCheckedIn
          ? t("registration.myCard.steps.approved")
          : isTerminal
            ? statusName
            : t("registration.myCard.steps.review"),
      tone: isApproved || isCheckedIn ? "done" : isTerminal ? "failed" : "active",
    },
    ...(profileStep ? [profileStep] : []),
    {
      key: "balancing",
      label: t("registration.myCard.steps.balancing"),
      tone: balancerReady
        ? "done"
        : isTerminal
          ? "idle"
          : isApproved || isCheckedIn
            ? "active"
            : "idle",
    },
    {
      key: "checkIn",
      label: t("registration.myCard.steps.checkIn"),
      tone: isCheckedIn
        ? "done"
        : isTerminal
          ? "idle"
          : canCheckIn
            ? "active"
            : checkInPhaseOver
              ? "failed"
              : "idle",
    },
  ];

  // Single "what happens next" line next to the actions.
  let hintText: string;
  let hintClass = "text-[color:var(--aqt-fg-muted)]";
  if (isCheckedIn) {
    hintText = t("registration.myCard.checkInSuccess");
    hintClass = "text-emerald-400 font-medium";
  } else if (canCheckIn) {
    hintText = t("registration.myCard.checkInOpenDesc");
    hintClass = "text-amber-400 font-medium";
  } else if (isTerminal) {
    hintText = statusMeta?.description || t("registration.myCard.inactiveDesc");
    hintClass = "text-[color:var(--aqt-fg-dim)]";
  } else if (isApproved && checkInPhaseOver) {
    hintText = t("registration.myCard.checkInClosedDesc");
    hintClass = "text-red-400/90";
  } else if (isApproved && !balancerReady) {
    hintText = t("registration.myCard.balancerWaitingDesc");
  } else if (isApproved) {
    hintText = t("registration.myCard.pendingCheckInDesc");
  } else {
    hintText =
      statusMeta?.description || t("registration.myCard.pendingReviewDesc");
  }

  return (
    <div className="relative overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-white/[0.02] shadow-md backdrop-blur-md">
      {/* Decorative gradient blurs */}
      <div className="absolute -right-16 -top-16 -z-10 size-32 rounded-full bg-blue-500/5 blur-2xl" />
      <div className="absolute -bottom-16 -left-16 -z-10 size-32 rounded-full bg-violet-500/5 blur-2xl" />

      {/* Hero header: big status icon, headline, next-step hint, actions */}
      <div className="flex flex-wrap items-start justify-between gap-3 p-4 sm:p-5">
        <div className="flex min-w-0 items-center gap-3.5">
          <span
            className={cn(
              "flex size-11 shrink-0 items-center justify-center rounded-xl border",
              statusChipStyle ? undefined : statusConfig.color,
            )}
            style={statusChipStyle}
          >
            {createElement(StatusIcon, { className: "size-5" })}
          </span>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-dim)]">
              {t("registration.myCard.title")}
            </p>
            <h3 className="mt-0.5 text-lg font-bold leading-tight text-[color:var(--aqt-fg)]">
              {statusName}
            </h3>
            <p className={cn("mt-0.5 text-xs", hintClass)}>{hintText}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {canCheckIn && (
            <button
              type="button"
              onClick={onCheckIn}
              disabled={isCheckingIn}
              className="inline-flex items-center justify-center gap-1 rounded-md bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-[color:var(--aqt-fg)] shadow shadow-emerald-500/20 transition-all hover:bg-emerald-400 hover:shadow-emerald-500/30 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
            >
              {isCheckingIn && <Loader2 className="size-3 animate-spin" />}
              {isCheckingIn ? t("common.checkingIn") : t("common.checkIn")}
            </button>
          )}
          {canWithdraw && (
            <button
              type="button"
              onClick={onWithdraw}
              disabled={isWithdrawing || isCheckingIn}
              className="inline-flex items-center justify-center rounded-md border border-red-500/20 bg-red-500/5 px-2.5 py-1.5 text-[11px] font-semibold text-red-400/90 transition-all hover:border-red-500/40 hover:bg-red-500/10 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
            >
              {isWithdrawing && <Loader2 className="mr-1 size-3 animate-spin" />}
              {isWithdrawing ? t("common.withdrawing") : t("common.withdraw")}
            </button>
          )}
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            aria-expanded={isExpanded}
            aria-label={
              isExpanded
                ? t("registration.myCard.hideDetails")
                : t("registration.myCard.showDetails")
            }
            title={
              isExpanded
                ? t("registration.myCard.hideDetails")
                : t("registration.myCard.showDetails")
            }
            className="flex size-8 shrink-0 items-center justify-center text-[color:var(--aqt-fg-dim)] transition-colors hover:text-[color:var(--aqt-fg)]"
          >
            {isExpanded ? (
              <ChevronUp className="size-4" />
            ) : (
              <ChevronDown className="size-4" />
            )}
          </button>
        </div>
      </div>

      {/* Progress stepper */}
      <div className="flex items-start px-4 pb-4 sm:px-6">
        {steps.map((step, index) => (
          <Fragment key={step.key}>
            {index > 0 && (
              <div
                aria-hidden="true"
                className={cn(
                  "mx-2 mt-3 h-px flex-1",
                  steps[index - 1].tone === "done"
                    ? "bg-emerald-500/40"
                    : "bg-[color:var(--aqt-border-2)]",
                )}
              />
            )}
            <div className="flex min-w-0 max-w-40 flex-col items-center gap-1.5 text-center">
              <RegistrationStepMarker tone={step.tone} />
              <span
                className={cn(
                  "text-[11px] leading-tight",
                  step.tone === "done" && "text-emerald-300/90",
                  step.tone === "active" && "font-medium text-amber-300/90",
                  step.tone === "failed" && "text-red-400/90",
                  step.tone === "idle" && "text-[color:var(--aqt-fg-dim)]",
                )}
              >
                {step.label}
              </span>
            </div>
          </Fragment>
        ))}
      </div>

      {/* Expanded details: even groups in one row, notes as a quote below */}
      {isExpanded && (
        <div className="border-t border-[color:var(--aqt-border)] bg-white/[0.01] p-4 sm:px-5">
          <div className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2">
              <h4 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-dim)]">
                {t("common.rolesList")}
              </h4>
              {primaryRole || secondaryRoles.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {primaryRole && (
                    <RegistrationRoleChip
                      role={primaryRole}
                      showPrimaryMark
                      t={t}
                    />
                  )}
                  {secondaryRoles.map((r) => (
                    <RegistrationRoleChip
                      key={`${r.role}-${r.subrole ?? "base"}-${r.priority}`}
                      role={r}
                      showPrimaryMark={false}
                      t={t}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-xs italic text-[color:var(--aqt-fg-dim)]">
                  {t("registration.myCard.noSecondaryRoles")}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <h4 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-dim)]">
                {t("registration.myCard.accounts")}
              </h4>
              <div className="flex flex-wrap gap-1.5 text-xs">
                {registration.battle_tag && (
                  <div className="flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border)] bg-white/[0.02] px-2 py-1">
                    {/* eslint-disable-next-line @next/next/no-img-element -- small static asset from /public */}
                    <img alt="Battle.net" className="size-3.5" src="/battlenet.svg" />
                    <span className="font-semibold text-[color:var(--aqt-fg)]">
                      {registration.battle_tag}
                    </span>
                  </div>
                )}
                {registration.discord_nick && (
                  <div className="flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border)] bg-white/[0.02] px-2 py-1">
                    <DiscordIcon className="size-3.5 text-[#5865F2]" />
                    <span className="text-[color:var(--aqt-fg-muted)]">
                      {registration.discord_nick}
                    </span>
                  </div>
                )}
                {registration.twitch_nick && (
                  <div className="flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border)] bg-white/[0.02] px-2 py-1">
                    <Twitch className="size-3.5 text-[#9146FF]" />
                    <span className="text-[color:var(--aqt-fg-muted)]">
                      {registration.twitch_nick}
                    </span>
                  </div>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <h4 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-dim)]">
                {t("registration.details.streamPov")}
              </h4>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium",
                  registration.stream_pov
                    ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                    : "border-[color:var(--aqt-border)] bg-white/[0.02] text-[color:var(--aqt-fg-dim)]",
                )}
              >
                <Tv className="size-3.5" />
                {registration.stream_pov
                  ? t("registration.myCard.streamPovActive")
                  : t("registration.myCard.streamPovInactive")}
              </span>
            </div>
          </div>

          {registration.notes ? (
            <div className="mt-4 space-y-1.5">
              <h4 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-dim)]">
                {t("registration.details.notes")}
              </h4>
              <p className="border-l-2 border-[color:var(--aqt-border-2)] pl-3 text-xs italic leading-relaxed text-[color:var(--aqt-fg-muted)]">
                &ldquo;{registration.notes}&rdquo;
              </p>
            </div>
          ) : null}
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
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchParamsString = searchParams.toString();
  const resultsHeadingRef = useRef<HTMLDivElement>(null);
  const previousResultsSignatureRef = useRef<string | null>(null);
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
  const allowedStatuses = useMemo(
    () => Array.from(new Set([...STATUS_FILTER_ORDER, ...presentStatuses])),
    [presentStatuses],
  );

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

  const defaultColumnIds = useMemo(
    () => participantDefaultColumnIds(allColumns),
    [allColumns],
  );
  // Optional column ids persisted per tournament. localStorage is an external
  // store: the raw entry is read via useSyncExternalStore (server snapshot is
  // null, so SSR/hydration never touches it) and writers notify subscribers.
  const storedColumnsRaw = useSyncExternalStore(
    subscribeParticipantColumnsStorage,
    () => {
      try {
        return window.localStorage.getItem(
          participantColumnsStorageKey(tournament.id),
        );
      } catch {
        return null;
      }
    },
    () => null,
  );
  const storedColumnIds = useMemo(
    () => parseStoredParticipantColumnIds(storedColumnsRaw),
    [storedColumnsRaw],
  );
  const persistColumns = useCallback(
    (visibleIds: readonly string[]) => {
      writeStoredParticipantColumnIds(
        typeof window === "undefined" ? null : window.localStorage,
        tournament.id,
        visibleIds,
        defaultColumnIds,
      );
    },
    [defaultColumnIds, tournament.id],
  );
  const participantUrl = useMemo(
    () =>
      readParticipantUrlState(
        new URLSearchParams(searchParamsString),
        allowedStatuses,
        allColumns,
        storedColumnIds,
      ),
    [allColumns, allowedStatuses, searchParamsString, storedColumnIds],
  );
  const latestParamsRef = useRef(searchParamsString);
  const searchQuery = participantUrl.state.search;
  const statusFilter = participantUrl.state.status as StatusFilter;
  const displayedStatuses = useMemo(
    () =>
      statusFilter !== "all" && !presentStatuses.includes(statusFilter)
        ? [...presentStatuses, statusFilter]
        : presentStatuses,
    [presentStatuses, statusFilter],
  );
  const visibleColumnIds = participantUrl.state.visibleColumnIds;
  const visibleColumnIdSet = useMemo(() => new Set(visibleColumnIds), [visibleColumnIds]);
  const visibleColumns = useMemo(
    () => allColumns.filter((column) => visibleColumnIdSet.has(column.id)),
    [allColumns, visibleColumnIdSet],
  );
  const visibility = useMemo(
    () =>
      Object.fromEntries(
        allColumns.map((column) => [column.id, visibleColumnIdSet.has(column.id)]),
      ),
    [allColumns, visibleColumnIdSet],
  );

  useEffect(() => {
    latestParamsRef.current = searchParamsString;
  }, [searchParamsString]);

  const navigateParticipantUrl = useCallback(
    (update: ParticipantUrlUpdate) => {
      const result = updateParticipantUrlState(
        new URLSearchParams(latestParamsRef.current),
        update,
      );
      const query = result.params.toString();
      const href = query ? `${pathname}?${query}` : pathname;
      latestParamsRef.current = query;
      if (result.history === "replace") router.replace(href, { scroll: false });
      else router.push(href, { scroll: false });
    },
    [pathname, router],
  );
  const commitSearch = useCallback(
    (value: string) => navigateParticipantUrl({ type: "search", value }),
    [navigateParticipantUrl],
  );
  const {
    inputRef: participantSearchInputRef,
    onChange: handleParticipantSearchChange,
  } = useParticipantSearchInput({
    canonicalSearch: searchQuery,
    canonicalUrl: searchParamsString,
    onCommit: commitSearch,
  });

  useEffect(() => {
    if (!listQuery.isFetched || !formQuery.isFetched || !participantUrl.needsNormalization) {
      return;
    }
    const query = participantUrl.params.toString();
    const href = query ? `${pathname}?${query}` : pathname;
    latestParamsRef.current = query;
    router.replace(href, { scroll: false });
  }, [
    formQuery.isFetched,
    listQuery.isFetched,
    participantUrl.needsNormalization,
    participantUrl.params,
    pathname,
    router,
  ]);

  const toggleColumn = useCallback(
    (columnId: string) => {
      if (isMandatoryParticipantColumnId(columnId)) return;
      const nextIds = visibleColumnIdSet.has(columnId)
        ? visibleColumnIds.filter((id) => id !== columnId)
        : allColumns
            .filter((column) =>
              column.id === columnId || visibleColumnIdSet.has(column.id),
            )
            .map((column) => column.id);
      persistColumns(nextIds);
      navigateParticipantUrl({
        type: "columns",
        value: nextIds,
        defaultValue: defaultColumnIds,
      });
    }, [
      allColumns,
      defaultColumnIds,
      navigateParticipantUrl,
      persistColumns,
      visibleColumnIdSet,
      visibleColumnIds,
    ],
  );
  const resetToDefaults = useCallback(() => {
    persistColumns(defaultColumnIds);
    navigateParticipantUrl({
      type: "columns",
      value: defaultColumnIds,
      defaultValue: defaultColumnIds,
    });
  }, [defaultColumnIds, navigateParticipantUrl, persistColumns]);

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

  const resultsSignature = useMemo(
    () =>
      participantResultsTransitionSignature({
        search: searchQuery,
        status: statusFilter,
        visibleColumnIds,
      }),
    [searchQuery, statusFilter, visibleColumnIds],
  );
  useEffect(() => {
    if (previousResultsSignatureRef.current === null) {
      previousResultsSignatureRef.current = resultsSignature;
      return;
    }
    if (previousResultsSignatureRef.current === resultsSignature) return;
    previousResultsSignatureRef.current = resultsSignature;

    const frame = window.requestAnimationFrame(() => {
      const heading = resultsHeadingRef.current;
      if (!heading) return;
      const headingDocumentTop = heading.getBoundingClientRect().top + window.scrollY;
      const stickyOffset = 112;
      if (
        shouldScrollParticipantResults({
          scrollY: window.scrollY,
          headingDocumentTop,
          stickyOffset,
        })
      ) {
        window.scrollTo({
          top: participantResultsScrollTarget(headingDocumentTop, stickyOffset),
          behavior: "auto",
        });
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, [resultsSignature]);

  const trueEmpty = listQuery.data !== undefined && registrations.length === 0;
  const filteredEmpty = !trueEmpty && filtered.length === 0;

  if (listQuery.isPending && listQuery.data === undefined) {
    return <TournamentParticipantsSkeleton />;
  }

  if (listQuery.isError && listQuery.data === undefined) {
    return (
      <TournamentPageState
        state="initial-error"
        onRetry={() => void listQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-5" data-participant-layout="true">
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
          requireOpenProfile={formQuery.data?.require_open_profile ?? false}
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
              className="border border-emerald-500/30 bg-emerald-600 text-[color:var(--aqt-fg)] hover:bg-emerald-500"
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
              className="bg-red-600 text-[color:var(--aqt-fg)] hover:bg-red-500"
            >
              {withdrawMutation.isPending ? t("common.withdrawing") : t("common.confirmWithdraw")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>


      <p aria-atomic="true" aria-live="polite" className="sr-only">
        {t("tournamentDetail.participants.resultCount", { count: filtered.length })}
      </p>

      {/* Status filter chips + search + column picker */}
      {!trueEmpty && (
        <div className="filters" ref={resultsHeadingRef}>
          <button
            type="button"
            className={cn("filter-chip", statusFilter === "all" && "active")}
            onClick={() => navigateParticipantUrl({ type: "status", value: "all" })}
          >
            {t("common.all")} <span className="count">{registrations.length}</span>
          </button>
          {displayedStatuses.map((status) => {
            const meta = statusMetaMap[status];
            return (
              <button
                key={status}
                type="button"
                className={cn("filter-chip", statusFilter === status && "active")}
                onClick={() =>
                  navigateParticipantUrl({
                    type: "status",
                    value: statusFilter === status ? "all" : status,
                  })
                }
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
              aria-label={t("common.searchParticipants")}
              defaultValue={searchQuery}
              maxLength={PARTICIPANT_SEARCH_MAX_LENGTH}
              onChange={handleParticipantSearchChange}
              placeholder={t("common.searchParticipants")}
              ref={participantSearchInputRef}
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
      {filtered.length > 0 ? (
        <VirtualParticipantsList
          allColumns={allColumns}
          expandedIds={expandedIds}
          onToggleExpanded={toggleExpanded}
          registrations={filtered}
          visibleColumns={visibleColumns}
        />
      ) : filteredEmpty ? (
        <TournamentPageState
          state="filtered-empty"
          onReset={() => {
            persistColumns(defaultColumnIds);
            navigateParticipantUrl({ type: "reset" });
          }}
        />
      ) : (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.participants.empty.title")}
          description={t("tournamentDetail.participants.empty.description")}
        />
      )}

      {listQuery.isError && listQuery.data !== undefined ? (
        <div className={styles.refreshMessage} role="alert">
          <span>
            <strong>{t("tournamentDetail.pageState.refreshError.title")}</strong>
            {" — "}
            {t("tournamentDetail.pageState.refreshError.description")}
          </span>
          <button
            className={styles.stateAction}
            onClick={() => void listQuery.refetch()}
            type="button"
          >
            {t("tournamentDetail.pageState.retry")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
