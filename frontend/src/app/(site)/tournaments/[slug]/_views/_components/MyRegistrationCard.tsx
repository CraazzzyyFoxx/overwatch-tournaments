"use client";

import {
  createElement,
  Fragment,
  useState
} from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Crown,
  ShieldBan,
  X,
  XCircle,
  ChevronDown,
  ChevronUp,
  Pencil
} from "lucide-react";

import { StatusDot } from "@/components/ui/status-dot";
import { cn, hexToRgba } from "@/lib/utils";
import { activeRequirements, formatAdmissionReason, formatRequirementName } from "@/lib/registration/admission";
import { formatShortfall } from "@/lib/registration/team-shortfall";
import { getRegistrationTeamStatus } from "@/lib/registration/team-tone";
import { normalizePlayerRole, playerRoleSlotCode } from "@/lib/roster/player-role";
import { reachedAtLeast } from "@/lib/tournament/lifecycle";
import { answerFlag, answerText } from "@/lib/forms/answers";
import { IDENTITY_PROVIDERS, identityKey, identityProvider } from "@/lib/forms/builtin-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationTeamService from "@/services/registration-team.service";
import MyRegistrationEditDialog from "@/components/registration/MyRegistrationEditDialog";
import type { Tournament } from "@/types/tournament.types";
import type {
  Registration,
  RegistrationForm,
  RegistrationStatus
} from "@/types/registration.types";

import { getRoleLabel, type ColumnDefinition } from "./participantsColumns.model";
import { ROLE_TINT } from "./RegistrationSummary";
import { useTranslations } from "next-intl";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { getStatusIcon } from "@/lib/registration/status-icons";
import { formatSubroleSlug } from "@/lib/roster/roles";
import { Spinner } from "@/components/ui/spinner";


// arbitrary values it can see verbatim in the source.
const STATUS_BAR_CONFIG: Record<RegistrationStatus, { icon: typeof Clock; color: string }> = {
  pending: {
    icon: Clock,
    color:
      "text-[color:var(--aqt-amber)] border-[color:color-mix(in_srgb,var(--aqt-amber)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)]"
  },
  approved: {
    icon: CheckCircle2,
    color:
      "text-[color:var(--aqt-emerald)] border-[color:color-mix(in_srgb,var(--aqt-emerald)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)]"
  },
  rejected: {
    icon: XCircle,
    color:
      "text-[color:var(--aqt-rose)] border-[color:color-mix(in_srgb,var(--aqt-rose)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_10%,transparent)]"
  },
  withdrawn: {
    icon: XCircle,
    color:
      "text-[color:var(--aqt-fg-dim)] border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)]"
  },
  banned: {
    icon: ShieldBan,
    color:
      "text-[color:var(--aqt-rose)] border-[color:color-mix(in_srgb,var(--aqt-rose)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_10%,transparent)]"
  },
  insufficient_data: {
    icon: AlertTriangle,
    color:
      "text-[color:var(--aqt-damage)] border-[color:color-mix(in_srgb,var(--aqt-damage)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-damage)_10%,transparent)]"
  }
};

const ROLE_ACCENT_CLASSES: Record<string, { bg: string; text: string; border: string }> = {
  tank: {
    bg: "bg-[color:color-mix(in_srgb,var(--aqt-tank)_10%,transparent)]",
    text: "text-[color:var(--aqt-tank)]",
    border: "border-[color:color-mix(in_srgb,var(--aqt-tank)_20%,transparent)]"
  },
  damage: {
    bg: "bg-[color:color-mix(in_srgb,var(--aqt-damage)_10%,transparent)]",
    text: "text-[color:var(--aqt-damage)]",
    border: "border-[color:color-mix(in_srgb,var(--aqt-damage)_20%,transparent)]"
  },
  support: {
    bg: "bg-[color:color-mix(in_srgb,var(--aqt-support)_10%,transparent)]",
    text: "text-[color:var(--aqt-support)]",
    border: "border-[color:color-mix(in_srgb,var(--aqt-support)_20%,transparent)]"
  },
  flex: {
    bg: "bg-[color:color-mix(in_srgb,var(--aqt-violet)_10%,transparent)]",
    text: "text-[color:var(--aqt-violet)]",
    border: "border-[color:color-mix(in_srgb,var(--aqt-violet)_20%,transparent)]"
  }
};

const ROLE_TO_ICON: Record<string, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex"
};

const DiscordIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 127.14 96.36" fill="currentColor" {...props}>
    <path d="M107.7,8.07A105.15,105.15,0,0,0,77.26,0a77.19,77.19,0,0,0-3.3,6.83A96.67,96.67,0,0,0,53.22,6.83,77.19,77.19,0,0,0,49.88,0,105.15,105.15,0,0,0,19.44,8.07C3.66,31.58-1.86,54.65,1,77.53A105.73,105.73,0,0,0,32,96.36a77.7,77.7,0,0,0,6.63-10.85,68.43,68.43,0,0,1-10.5-5c.87-.64,1.72-1.31,2.53-2a75.76,75.76,0,0,0,73,0c.81.69,1.66,1.36,2.53,2a68.43,68.43,0,0,1-10.5,5,77.7,77.7,0,0,0,6.63,10.85,105.73,105.73,0,0,0,31-18.83C129.86,49.2,123.63,26.54,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53S36.18,40.36,42.45,40.36,53.83,46,53.83,53,48.72,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.24,60,73.24,53S78.41,40.36,84.69,40.36,96.07,46,96.07,53,91,65.69,84.69,65.69Z" />
  </svg>
);

// lucide 1.x dropped brand icons; same local-SVG treatment as DiscordIcon above.
const TwitchIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
    <path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z" />
  </svg>
);

// Simple Icons (CC0), same path as public/boosty.svg.
const BoostyIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" fill="currentColor" {...props}>
    <path d="M2.661 14.337 6.801 0h6.362L11.88 4.444l-.038.077-3.378 11.733h3.15c-1.321 3.289-2.35 5.867-3.086 7.733-5.816-.063-7.442-4.228-6.02-9.155M8.554 24l7.67-11.035h-3.25l2.83-7.073c4.852.508 7.137 4.33 5.791 8.952C20.16 19.81 14.344 24 8.68 24h-.127z" />
  </svg>
);

/**
 * Brand icons for the identity chips on the registrant's own card. A provider
 * with no icon here is labelled instead — a bare handle beside four other
 * handles says nothing about where it lives.
 */
const IDENTITY_ICONS: Record<
  string,
  { Icon: (props: React.SVGProps<SVGSVGElement>) => React.ReactElement; className: string }
> = {
  discord: { Icon: DiscordIcon, className: "text-[color:var(--aqt-brand-discord)]" },
  twitch: { Icon: TwitchIcon, className: "text-[color:var(--aqt-brand-twitch)]" },
  boosty: { Icon: BoostyIcon, className: "text-[color:var(--aqt-brand-boosty)]" }
};

type RegistrationStepTone = "done" | "active" | "failed" | "idle";

interface RegistrationStep {
  key: string;
  label: string;
  tone: RegistrationStepTone;
  /** The reader is the one who can clear this step. Set only for requirement
   *  steps whose reason carries `actor: "player"`; an organizer's
   *  misconfiguration or a provider outage stays plain text. */
  actionable?: boolean;
}

const TERMINAL_REGISTRATION_STATUSES = new Set<string>(["rejected", "banned", "withdrawn"]);

function RegistrationStepMarker({ tone }: Readonly<{ tone: RegistrationStepTone }>) {
  switch (tone) {
    case "done":
      return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-[color:color-mix(in_srgb,var(--aqt-emerald)_40%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_15%,transparent)] text-[color:var(--aqt-emerald)]">
          <Check className="size-3.5" strokeWidth={3} aria-hidden />
        </span>
      );
    case "failed":
      return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_15%,transparent)] text-[color:var(--aqt-rose)]">
          <X className="size-3.5" strokeWidth={3} aria-hidden />
        </span>
      );
    case "active":
      return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-[color:color-mix(in_srgb,var(--aqt-amber)_50%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)]">
          <StatusDot pulse className="size-2 text-[color:var(--aqt-amber)]" />
        </span>
      );
    default:
      return (
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)]">
          <StatusDot className="text-[color:var(--aqt-fg-dim)]" />
        </span>
      );
  }
}

function RegistrationRoleChip({
  role,
  showPrimaryMark,
  t
}: Readonly<{
  role: Registration["roles"][number];
  showPrimaryMark: boolean;
  t: ReturnType<typeof useTranslations<never>>;
}>) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        ROLE_ACCENT_CLASSES[role.role]?.bg,
        ROLE_ACCENT_CLASSES[role.role]?.border,
        ROLE_ACCENT_CLASSES[role.role]?.text
      )}
    >
      <PlayerRoleIcon role={ROLE_TO_ICON[role.role] ?? role.role} size={12} decorative />
      <span>{getRoleLabel(role.role, t)}</span>
      {role.subrole && (
        <span className="text-label opacity-60">({formatSubroleSlug(role.subrole)})</span>
      )}
      {showPrimaryMark && (
        <span className="text-label uppercase tracking-wide opacity-70">
          · {t("registration.myCard.primaryRole")}
        </span>
      )}
    </div>
  );
}

/** Both queue chips wear the same shell; only their contents differ. */
const QUEUE_CHIP_CLASS =
  "rounded-full border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-1.5 py-px text-label font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]";

/** Answers the card lays out by hand — chips for roles, brand chips for the
 *  handles, a quote for the notes — so the generic details block skips them. */
const CARD_OWN_COLUMN_IDS: Record<string, true> = {
  battle_tag: true,
  roles: true,
  public_notes: true
};

function MyRegistrationCard({
  registration,
  canCheckIn,
  onCheckIn,
  onWithdraw,
  isCheckingIn,
  isWithdrawing,
  tournament,
  form,
  columns
}: Readonly<{
  registration: Registration;
  canCheckIn: boolean;
  onCheckIn: () => void;
  onWithdraw: () => void;
  isCheckingIn: boolean;
  isWithdrawing: boolean;
  tournament: Tournament;
  /** The CURRENT form. Self-edit needs its schema and version id, so the Edit
   *  action waits for it even when the server already said `can_edit`. */
  form: RegistrationForm | null;
  /** The roster's column model, UNFILTERED: it is one column per public
   *  question with the renderer the roster's own details panel uses, so the
   *  card shows the same answers the same way. Organizer-surface columns stay
   *  in — smurf tags are the reader's own answer here. */
  columns: readonly ColumnDefinition[];
}>) {
  const t = useTranslations();
  const tSlot = useTranslations("rosterShape.slotCodes");
  const [isExpanded, setIsExpanded] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);

  // §12.5 needs two facts the inline brief deliberately omits: the per-slot
  // shortfall ("what is still missing") and whether the team already made it
  // into the tournament. Both live on the public team read, fetched only for a
  // player who actually is on a team — solo tournaments send no request.
  const teamBrief = registration.team ?? null;
  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationTeams(tournament.workspace_id, tournament.id),
    queryFn: () => registrationTeamService.listPublic(tournament.id),
    enabled: teamBrief !== null
  });
  const myTeam = teamBrief
    ? (teamsQuery.data?.items.find((item) => item.id === teamBrief.id) ?? null)
    : null;

  // The role place, resolved once: the server sends the role its counts were
  // taken in, and the site's own slot vocabulary supplies the label and tint so
  // the chip reads like the role figures on the summary beside it.
  const roleQueue =
    registration.queue_role != null &&
    registration.queue_role_position != null &&
    registration.queue_role_total != null
      ? (() => {
          const slot = playerRoleSlotCode(normalizePlayerRole(registration.queue_role));
          return {
            label: t(`common.roles.${slot}`),
            tint: ROLE_TINT[slot],
            position: registration.queue_role_position,
            total: registration.queue_role_total
          };
        })()
      : null;
  const primaryRole = registration.roles.find((r) => r.is_primary);
  const secondaryRoles = registration.roles
    .filter((r) => !r.is_primary)
    .sort((a, b) => a.priority - b.priority);

  const statusConfig = STATUS_BAR_CONFIG[registration.status] ?? STATUS_BAR_CONFIG.pending;

  const statusMeta = registration.status_meta;
  const statusName =
    statusMeta?.name ??
    registration.status.charAt(0).toUpperCase() + registration.status.slice(1).replace(/_/g, " ");

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
      backgroundColor: hexToRgba(color, 0.12) ?? "transparent"
    };
  }

  const isCheckedIn = registration.checked_in === true;
  const isApproved = registration.status === "approved";
  const isTerminal = TERMINAL_REGISTRATION_STATUSES.has(registration.status);
  const checkInPhaseOver =
    !isCheckedIn && !canCheckIn && reachedAtLeast(tournament.status, "live");
  // Withdrawal closes at check-in: past that point the roster is balanced and
  // drafted against a confirmed attendee list (backend returns 409 too).
  const canWithdraw =
    !isCheckedIn && (registration.status === "pending" || registration.status === "approved");
  // SERVER-resolved, never re-derived: `can_edit` already folds in the schema's
  // per-question `editable` flags, the system floors and the window. The form
  // is the only local prerequisite — the dialog renders its schema.
  const canEdit = registration.can_edit && form !== null;
  // `nothing_editable` is the closed-by-default state of every tournament whose
  // organizer never opened a question, so it hides the action instead of
  // parking a permanently dead button on the card. The other three reasons mean
  // the entry WAS editable and something closed it — worth saying out loud.
  const editLockedReason =
    !canEdit && registration.edit_locked_reason !== "nothing_editable"
      ? registration.edit_locked_reason
      : null;
  // An availability note the registrant volunteered ("call me in if somebody
  // drops or I cannot make the start"), not a pool state: it rides `answers`
  // like any other public answer and changes nothing about the entry.
  const isReserve = answerFlag(registration.answers, "reserve");
  // D3: `ready` is the server's own "the data is complete" — approved AND holding
  // a rank in the balancer pool. It is deliberately NOT a requirement and is
  // never spent by check-in, which is why it travels beside the decision rather
  // than inside `requirements`. Read from there rather than re-tested against
  // `balancer_status === "ready"`: that literal was the last raw admission input
  // this card derived anything from, and it disagreed with the server whenever a
  // ranked player had not been approved yet.
  const balancerReady = registration.admission.ready;

  // Registration journey: submitted -> review/approved -> one step per active
  // requirement -> balancing (rank assignment) -> check-in.
  //
  // ONE map over what the server sent, not two hand-written blocks behind two
  // `require_*` flags. Those blocks were the sixth and seventh re-derivations of
  // the admission rule, and a third requirement would have added an eighth.
  // `not_applicable` verdicts are dropped here rather than server-side: the list
  // ships whole so that this is the only place that decides what to show.
  const requirementSteps: RegistrationStep[] = activeRequirements(registration.admission).map(
    (requirement) => {
      // A `satisfied` verdict can still carry reasons — under subscription `any`
      // mode every losing provider contributes one — so its label must come from
      // the requirement's name, never from a reason that no longer applies.
      const reason = requirement.state === "satisfied" ? null : (requirement.reasons[0] ?? null);
      return {
        key: `requirement:${requirement.key}`,
        label: reason
          ? formatAdmissionReason(t, reason)
          : formatRequirementName(t, requirement.key),
        // Only `blocked` is a failure. `undetermined` is the requirement failing
        // OPEN — a provider outage or an unfinished rank collection — and drawing
        // it red would tell a player they are out when they are not.
        tone:
          requirement.state === "satisfied"
            ? "done"
            : requirement.state === "blocked"
              ? "failed"
              : isTerminal
                ? "idle"
                : "active",
        // Only the player's own reasons get the call-to-action treatment. An
        // organizer's misconfiguration or a provider outage is not theirs to fix,
        // and inviting them to try is worse than saying nothing. The action
        // itself lives in the copy (the `player` messages are imperative) rather
        // than in a link: a per-code route map would be twenty-four guesses, and
        // "make your career profile public" is not even on this site.
        actionable: reason?.actor === "player"
      };
    }
  );

  // Check-in is the one step whose marker has four distinct outcomes, so it is
  // resolved here rather than inline: a completed check-in wins outright, a dead
  // registration has no step to run, an open window is the live call to action,
  // and a window that closed unused is a failure the reader has to see.
  let checkInTone: RegistrationStepTone;
  if (isCheckedIn) {
    checkInTone = "done";
  } else if (isTerminal) {
    checkInTone = "idle";
  } else if (canCheckIn) {
    checkInTone = "active";
  } else if (checkInPhaseOver) {
    checkInTone = "failed";
  } else {
    checkInTone = "idle";
  }

  const steps: RegistrationStep[] = [
    {
      key: "submitted",
      label: t("registration.myCard.steps.submitted"),
      tone: "done"
    },
    {
      key: "review",
      label:
        isApproved || isCheckedIn
          ? t("registration.myCard.steps.approved")
          : isTerminal
            ? statusName
            : t("registration.myCard.steps.review"),
      tone: isApproved || isCheckedIn ? "done" : isTerminal ? "failed" : "active"
    },
    ...requirementSteps,
    {
      key: "balancing",
      label: t(tournament.team_formation === "registration" ? "registrationTeams.myCard.playerEligibility" : "registration.myCard.steps.balancing"),
      tone: balancerReady
        ? "done"
        : isTerminal
          ? "idle"
          : isApproved || isCheckedIn
            ? "active"
            : "idle"
    },
    {
      key: "checkIn",
      label: t("registration.myCard.steps.checkIn"),
      tone: checkInTone
    }
  ];

  // §12.5: the people in a stuck team must learn it from their own card. The
  // sentence is resolved before the chain so the chain itself stays one branch
  // per outcome; the "forming" case waits for the roster read rather than
  // rendering "still missing: " with nothing after the colon.
  let teamHint: { text: string; tone: string } | null = null;
  if (teamBrief) {
    const teamValues = { team: teamBrief.name };
    if (myTeam && getRegistrationTeamStatus(myTeam) === "exported") {
      teamHint = {
        text: t("registrationTeams.myCard.exported", teamValues),
        tone: "font-medium text-[color:var(--aqt-emerald)]"
      };
    } else if (teamBrief.status === "rejected") {
      teamHint = {
        text: t("registrationTeams.myCard.rejected", teamValues),
        tone: "text-[color:var(--aqt-rose)]"
      };
    } else if (teamBrief.status === "disbanded") {
      teamHint = {
        text: t("registrationTeams.myCard.disbanded", teamValues),
        tone: "text-[color:var(--aqt-fg-dim)]"
      };
    } else if (teamBrief.status === "complete") {
      teamHint = {
        text: t("registrationTeams.myCard.complete", teamValues),
        tone: "text-[color:var(--aqt-fg-muted)]"
      };
    } else if (myTeam) {
      teamHint = {
        text: t("registrationTeams.myCard.incomplete", {
          ...teamValues,
          shortfall: formatShortfall(myTeam.open_slots, tSlot)
        }),
        tone: "font-medium text-[color:var(--aqt-amber)]"
      };
    }
  }

  // Single "what happens next" line next to the actions.
  let hintText: string;
  let hintClass = "text-[color:var(--aqt-fg-muted)]";
  if (isCheckedIn) {
    hintText = t("registration.myCard.checkInSuccess");
    hintClass = "font-medium text-[color:var(--aqt-emerald)]";
  } else if (canCheckIn) {
    hintText = t("registration.myCard.checkInOpenDesc");
    hintClass = "font-medium text-[color:var(--aqt-amber)]";
  } else if (isTerminal) {
    hintText = statusMeta?.description || t("registration.myCard.inactiveDesc");
    hintClass = "text-[color:var(--aqt-fg-dim)]";
  } else if (isApproved && checkInPhaseOver) {
    hintText = t("registration.myCard.checkInClosedDesc");
    hintClass = "text-[color:var(--aqt-rose)]";
  } else if (teamHint && !checkInPhaseOver) {
    // Above the balancer line on purpose: a player whose roster is short must be
    // told THAT, not that the organizer is still balancing. Below the terminal
    // and missed-check-in branches, which are about this player's own entry and
    // outrank any team news. Gated on the check-in phase still being open —
    // once the tournament is under way the roster is no longer actionable.
    hintText = teamHint.text;
    hintClass = teamHint.tone;
  } else if (isApproved && !balancerReady) {
    hintText = t("registration.myCard.balancerWaitingDesc");
  } else if (isApproved) {
    hintText = t("registration.myCard.pendingCheckInDesc");
  } else {
    hintText = statusMeta?.description || t("registration.myCard.pendingReviewDesc");
  }

  // Public answers only: this read is stripped against the registration's own
  // form version, so an organizers-only answer is not merely empty here, it is
  // absent — and nothing below may render a placeholder for one.
  const publicNotes = answerText(registration.answers, "public_notes");
  // Every question the form asks that the card does not lay out by hand, in
  // form order: meta columns are the roster's own state (status, check-in,
  // history) and already live in the header and the stepper above.
  const detailColumns = columns.filter(
    (column) =>
      column.category !== "meta" &&
      !CARD_OWN_COLUMN_IDS[column.id] &&
      identityProvider(column.id) === null
  );

  return (
    <div className="relative overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] shadow-md backdrop-blur-md">
      {/* Decorative gradient blurs */}
      <div
        aria-hidden
        className="absolute -right-16 -top-16 -z-10 size-32 rounded-full bg-[color:color-mix(in_srgb,var(--aqt-blue)_5%,transparent)] blur-2xl"
      />
      <div
        aria-hidden
        className="absolute -bottom-16 -left-16 -z-10 size-32 rounded-full bg-[color:color-mix(in_srgb,var(--aqt-violet)_5%,transparent)] blur-2xl"
      />

      {/* Hero header: big status icon, headline, next-step hint, actions */}
      <div className="flex flex-wrap items-start justify-between gap-3 p-4 sm:p-5">
        <div className="flex min-w-0 items-center gap-3.5">
          <span
            className={cn(
              "flex size-11 shrink-0 items-center justify-center rounded-xl border",
              statusChipStyle ? undefined : statusConfig.color
            )}
            style={statusChipStyle}
          >
            {createElement(StatusIcon, { className: "size-5", "aria-hidden": true })}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <p className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                {t("registration.myCard.title")}
              </p>
              {/* Where this entry sits in submission order. Server-sent, because a
                  tournament that hides its participants list gives this card no
                  rows to count — and counting rows was never the same number
                  anyway once a row was withdrawn. */}
              {registration.queue_position != null && registration.queue_total != null ? (
                <span
                  aria-label={t("registration.myCard.queuePositionLabel", {
                    position: registration.queue_position,
                    total: registration.queue_total
                  })}
                  className={QUEUE_CHIP_CLASS}
                >
                  {t("registration.myCard.queuePosition", {
                    position: registration.queue_position,
                    total: registration.queue_total
                  })}
                </span>
              ) : null}
              {/* The place that decides whether they get in: a field fills role
                  by role, so 2nd of 119 says little next to 42 other DPS. The
                  role comes from the server with the numbers rather than off
                  `roles` above — under the synthesized-role modes those two are
                  not the same answer. */}
              {roleQueue ? (
                <span
                  aria-label={t("registration.myCard.queueRolePositionLabel", {
                    role: roleQueue.label,
                    position: roleQueue.position,
                    total: roleQueue.total
                  })}
                  className={QUEUE_CHIP_CLASS}
                >
                  <StatusDot
                    className="mr-1 inline-block align-middle"
                    style={{ color: roleQueue.tint }}
                  />
                  {t("registration.myCard.queueRolePosition", {
                    role: roleQueue.label,
                    position: roleQueue.position,
                    total: roleQueue.total
                  })}
                </span>
              ) : null}
              {isReserve ? (
                <span
                  data-registration-reserve="true"
                  className="rounded-full border border-[color:color-mix(in_srgb,var(--aqt-blue)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-blue)_12%,transparent)] px-1.5 py-px text-label font-semibold uppercase tracking-label text-[color:var(--aqt-blue)]"
                >
                  {t("registration.reserve.badge")}
                </span>
              ) : null}
              {registration.submitted_late ? (
                <span
                  data-registration-late="true"
                  title={t("tournamentDetail.participants.lateHint")}
                  className="rounded-full border border-[color:var(--aqt-border)] px-1.5 py-px text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]"
                >
                  {t("tournamentDetail.participants.lateBadge")}
                </span>
              ) : null}
            </div>
            <h3 className="mt-0.5 text-lg font-bold leading-tight text-[color:var(--aqt-fg)]">
              {statusName}
            </h3>
            <p className={cn("mt-0.5 text-xs", hintClass)}>{hintText}</p>
            {/* What the registrant volunteered, in their own words: they play,
                and they are fine being called in. Info tone, never the amber
                warning it used to wear — nothing here needs fixing. */}
            {isReserve ? (
              <p className="mt-0.5 text-xs text-[color:var(--aqt-blue)]">
                {t("registration.reserve.explainer")}
              </p>
            ) : null}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {canCheckIn && (
            // Check-in is the one time-boxed action on this page and the only one
            // a player loses the tournament by missing, so it is sized and lit to
            // be the first thing the eye lands on rather than one more chip beside
            // Withdraw. The glow is a box-shadow rather than a scaling halo: the
            // card is `overflow-hidden`, so anything growing past the button
            // clips at the card edge.
            <button
              type="button"
              onClick={onCheckIn}
              disabled={isCheckingIn}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-[color:var(--aqt-emerald)] px-4 py-2 text-sm font-bold text-[color:var(--aqt-bg)] shadow-[0_0_18px_color-mix(in_srgb,var(--aqt-emerald)_40%,transparent)] transition-all hover:brightness-110 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
            >
              {isCheckingIn ? (
                <Spinner />
              ) : (
                <CheckCircle2 className="size-4" aria-hidden />
              )}
              {isCheckingIn ? t("common.checkingIn") : t("common.checkIn")}
            </button>
          )}
          {/* Edit sits before Withdraw: "fix my answer" is the cheaper of the
              two and the one a player reaches for first. Disabled-with-a-reason
              rather than silently absent, because a registrant who edited
              yesterday and cannot today is owed the reason. */}
          {canEdit || editLockedReason ? (
            <button
              type="button"
              data-registration-edit="true"
              onClick={() => setIsEditOpen(true)}
              disabled={!canEdit}
              aria-label={
                editLockedReason
                  ? `${t("registration.edit.action")} — ${t(`registration.edit.reason.${editLockedReason}`)}`
                  : undefined
              }
              title={
                editLockedReason
                  ? t(`registration.edit.reason.${editLockedReason}`)
                  : t("registration.edit.action")
              }
              className="inline-flex items-center justify-center gap-1 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-2.5 py-1.5 text-label font-semibold text-[color:var(--aqt-fg-muted)] transition-all hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
            >
              <Pencil className="size-3" aria-hidden />
              {t("registration.edit.action")}
            </button>
          ) : null}
          {canWithdraw && (
            <button
              type="button"
              onClick={onWithdraw}
              disabled={isWithdrawing || isCheckingIn}
              className="inline-flex items-center justify-center rounded-md border border-[color:color-mix(in_srgb,var(--aqt-rose)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_5%,transparent)] px-2.5 py-1.5 text-label font-semibold text-[color:var(--aqt-rose)] transition-all hover:border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)] hover:bg-[color:color-mix(in_srgb,var(--aqt-rose)_10%,transparent)] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50"
            >
              {isWithdrawing && (
                <Spinner className="mr-1 size-3" />
              )}
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
            {isExpanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
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
                    ? "bg-[color:color-mix(in_srgb,var(--aqt-emerald)_40%,transparent)]"
                    : "bg-[color:var(--aqt-border-2)]"
                )}
              />
            )}
            <div className="flex min-w-0 max-w-40 flex-col items-center gap-1.5 text-center">
              <RegistrationStepMarker tone={step.tone} />
              <span
                className={cn(
                  "text-label leading-tight",
                  step.tone === "done" && "text-[color:var(--aqt-emerald)]",
                  step.tone === "active" && "font-medium text-[color:var(--aqt-amber)]",
                  step.tone === "failed" && "text-[color:var(--aqt-rose)]",
                  step.tone === "idle" && "text-[color:var(--aqt-fg-dim)]",
                  // The affordance for "this one is yours": emphasis plus an
                  // underline, on a label already phrased as an instruction.
                  step.actionable &&
                    step.tone !== "done" &&
                    "font-semibold underline decoration-dotted underline-offset-2"
                )}
                title={step.actionable ? t("admission.playerActionable") : undefined}
              >
                {step.label}
              </span>
            </div>
          </Fragment>
        ))}
      </div>

      {/* Expanded details: the hand-laid groups in one row, every other answer
          as a label/value list below, notes as a quote last */}
      {isExpanded && (
        <div className="border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4 sm:px-5">
          <div className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2">
              <h4 className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                {t("common.rolesList")}
              </h4>
              {primaryRole || secondaryRoles.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {primaryRole && <RegistrationRoleChip role={primaryRole} showPrimaryMark t={t} />}
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

            {teamBrief && (
              <div className="space-y-2">
                <h4 className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                  {t("registrationTeams.myCard.teamLabel")}
                </h4>
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="font-semibold text-[color:var(--aqt-fg)]">{teamBrief.name}</span>
                  {teamBrief.is_captain && (
                    <span
                      className="inline-flex items-center text-[color:var(--aqt-amber)]"
                      title={t("registrationTeams.member.captain")}
                    >
                      <Crown className="size-3.5" aria-hidden />
                      <span className="sr-only">{t("registrationTeams.member.captain")}</span>
                    </span>
                  )}
                  {teamBrief.is_substitute && (
                    <span className="rounded border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] px-1.5 py-0.5 text-label font-semibold text-[color:var(--aqt-fg-dim)]">
                      {t("registrationTeams.member.substitute")}
                    </span>
                  )}
                </div>
              </div>
            )}

            <div className="space-y-2">
              <h4 className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                {t("registration.myCard.accounts")}
              </h4>
              <div className="flex flex-wrap gap-1.5 text-xs">
                {registration.battle_tag && (
                  <div className="flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-2 py-1">
                    {/* eslint-disable-next-line @next/next/no-img-element -- small static asset from /public */}
                    <img alt="Battle.net" className="size-3.5" src="/battlenet.svg" />
                    <span className="font-semibold text-[color:var(--aqt-fg)]">
                      {registration.battle_tag}
                    </span>
                  </div>
                )}
                {IDENTITY_PROVIDERS.map((provider) => {
                  const handle = answerText(registration.answers, identityKey(provider));
                  if (!handle) return null;
                  const brand = IDENTITY_ICONS[provider];
                  return (
                    <div
                      key={provider}
                      className="flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-2 py-1"
                    >
                      {brand ? (
                        <brand.Icon aria-hidden className={cn("size-3.5", brand.className)} />
                      ) : (
                        <span className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                          {t(`registration.accounts.${provider}`)}
                        </span>
                      )}
                      <span className="text-[color:var(--aqt-fg-muted)]">{handle}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {detailColumns.length > 0 ? (
            <div className="mt-4 space-y-2">
              <h4 className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                {t("registration.myCard.details")}
              </h4>
              <dl className="grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                {detailColumns.map((column) => (
                  <div key={column.id} className="min-w-0 space-y-1">
                    <dt className="text-label font-medium leading-snug text-[color:var(--aqt-fg-dim)]">
                      {column.label}
                    </dt>
                    <dd className="flex flex-wrap text-xs text-[color:var(--aqt-fg)]">
                      {column.render(registration, 0)}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}

          {publicNotes ? (
            <div className="mt-4 space-y-1.5">
              <h4 className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                {t("registration.details.notes")}
              </h4>
              <p className="border-l-2 border-[color:var(--aqt-border-2)] pl-3 text-xs italic leading-relaxed text-[color:var(--aqt-fg-muted)]">
                &ldquo;{publicNotes}&rdquo;
              </p>
            </div>
          ) : null}
        </div>
      )}

      {/* Mounted only once the form has loaded: the dialog renders its schema
          and echoes its version id back on save. */}
      {form ? (
        <MyRegistrationEditDialog
          open={isEditOpen}
          onOpenChange={setIsEditOpen}
          workspaceId={tournament.workspace_id}
          tournamentId={tournament.id}
          form={form}
          registration={registration}
        />
      ) : null}
    </div>
  );
}


export { MyRegistrationCard };
