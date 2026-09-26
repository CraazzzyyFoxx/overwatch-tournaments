"use client";

import type { SortingFn } from "@tanstack/react-table";
import { useTranslations, type DateTimeFormatOptions } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { StatusPill } from "@/components/kit/StatusPill";
import { TONE_CLASS } from "@/components/kit/tone";
import { Badge } from "@/components/ui/badge";
import { formatAdmissionReason, primaryAdmissionReason } from "@/lib/registration/admission";
import { cn } from "@/lib/utils";
import { ROLE_LABELS, getRoleIconName, getSubroleLabel } from "@/lib/roster/roles";
import { answerText } from "@/lib/forms/answers";
import type { AdminRegistration, AdminRegistrationRole } from "@/types/balancer-admin.types";
import type { SubroleCatalog } from "@/types/registration.types";

/**
 * Labels for the builtin questions, shared by the columns and the row
 * inspector. A builtin carries no label of its own — the server owns its
 * wording and each client localises it — and this table is English throughout,
 * like every other header here.
 */
export const BUILTIN_ANSWER_LABELS: Record<string, string> = {
  smurf_tags: "Smurfs",
  stream_pov: "Stream POV",
  reserve: "On call",
  public_notes: "Notes",
  organizer_notes: "Organizer Notes",
  identity_discord: "Discord",
  identity_twitch: "Twitch",
  identity_boosty: "Boosty",
  identity_vk: "VK",
  identity_youtube: "YouTube",
};

/** The answers that had a visible column before the schema existed. Every other
 *  question starts hidden: a form may ask a dozen of them. */
export const DEFAULT_VISIBLE_ANSWER_KEYS: Record<string, true> = { smurf_tags: true };

/** The identity handles this form asks for, in schema order, off the row's own
 *  answers — a form that asks for VK shows VK without a code change here. */
export function identityHandles(
  registration: AdminRegistration,
  keys: readonly string[],
): string[] {
  return keys
    .map((key) => answerText(registration.answers, key))
    .filter((handle): handle is string => handle !== null);
}

/**
 * The slice of next-intl's formatter the timestamp cells need. These helpers are
 * plain functions, so they cannot call `useFormatter()` themselves — and an
 * `en-GB` literal here printed English dates into the `ru` default UI. The cell
 * components below supply the formatter instead.
 */
interface DateFormatter {
  dateTime: (value: Date, options?: DateTimeFormatOptions) => string;
}

/**
 * Locale-aware compare shared by every text column. Sorting used to live in one
 * `switch` in the table; the options here are the ones that switch used, so the
 * order organizers are used to does not change.
 */
export const localeTextSort: SortingFn<AdminRegistration> = (rowA, rowB, columnId) =>
  String(rowA.getValue(columnId) ?? "").localeCompare(
    String(rowB.getValue(columnId) ?? ""),
    undefined,
    { sensitivity: "base", numeric: true },
  );

export function parseValidDate(dateString: string | null | undefined): Date | null {
  if (!dateString) {
    return null;
  }

  const date = new Date(dateString);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatTimestamp(format: DateFormatter, dateString: string | null | undefined): string | null {
  const date = parseValidDate(dateString);
  if (!date) {
    return null;
  }

  return format.dateTime(date, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatFullTimestamp(format: DateFormatter, dateString: string | null | undefined): string | null {
  const date = parseValidDate(dateString);
  if (!date) {
    return null;
  }

  return format.dateTime(date, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function ParticipantCell({
  registration,
  identityKeys,
}: Readonly<{ registration: AdminRegistration; identityKeys: readonly string[] }>) {
  const primary =
    registration.battle_tag ??
    registration.display_name ??
    `Registration #${registration.id}`;

  const secondaryParts = [
    registration.battle_tag && registration.display_name && registration.display_name !== registration.battle_tag
      ? registration.display_name
      : null,
    ...identityHandles(registration, identityKeys),
    registration.source_record_key,
  ].filter(Boolean);

  return (
    <div className="min-w-0 space-y-1">
      <div className="truncate font-medium text-[color:var(--aqt-fg)]" title={primary}>
        {primary}
      </div>
      <div
        className="truncate text-xs text-[color:var(--aqt-fg-dim)]"
        title={secondaryParts.length > 0 ? secondaryParts.join(" · ") : undefined}
      >
        {secondaryParts.length > 0
          ? secondaryParts.join(" · ")
          : registration.source === "google_sheets"
            ? "Google Sheets import"
            : "Manual registration"}
      </div>
    </div>
  );
}

export function RolesCell({
  roles,
  catalog,
}: Readonly<{
  roles: AdminRegistrationRole[];
  catalog?: SubroleCatalog;
}>) {
  if (!roles || roles.length === 0) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  const sortedRoles = roles
    .filter((role) => role.is_active)
    .slice()
    .sort((left, right) => left.priority - right.priority);

  if (sortedRoles.length === 0) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  return (
    <div className="flex flex-wrap items-start justify-center gap-x-1 gap-y-2">
      {sortedRoles.map((role) => {
        const subroleLabel = role.subrole ? getSubroleLabel(catalog, role.role, role.subrole) : null;
        return (
          <div
            key={`${role.role}-${role.subrole ?? "base"}-${role.priority}`}
            className="inline-flex min-w-8 flex-col items-center gap-0.5"
            title={[
              ROLE_LABELS[role.role] ?? role.role,
              subroleLabel,
              role.rank_value != null ? `${role.rank_value}` : null,
              role.is_primary ? "Primary" : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          >
            <span
              className={cn(
                "relative inline-flex h-8 w-8 items-center justify-center p-1",
                role.is_primary
                  ? "after:absolute after:bottom-0 after:left-1/2 after:h-0.5 after:w-4 after:-translate-x-1/2 after:rounded-full after:bg-emerald-300/90"
                  : "text-[color:var(--aqt-fg-muted)]",
              )}
            >
              <PlayerRoleIcon role={getRoleIconName(role.role)} size={20} />
            </span>
            <span className="text-center text-label font-semibold uppercase leading-none tracking-label text-[color:var(--aqt-fg-dim)]">
              {subroleLabel ?? role.rank_value ?? ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function SourceCell({ source }: Readonly<{ source: AdminRegistration["source"] }>) {
  const isSheets = source === "google_sheets";
  return (
    <Badge
      variant="outline"
      className={cn("font-medium", isSheets ? TONE_CLASS.info : TONE_CLASS.neutral)}
    >
      {isSheets ? "Sheets" : "Manual"}
    </Badge>
  );
}

export function TextBlockCell({ value }: Readonly<{ value: string | null | undefined }>) {
  if (!value) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  return (
    <span className="block max-w-[240px] truncate text-xs text-[color:var(--aqt-fg-muted)]" title={value}>
      {value}
    </span>
  );
}



export function SubmittedCell({ submittedAt }: Readonly<{ submittedAt: string | null }>) {
  const format = useFormatter();
  const shortValue = formatTimestamp(format, submittedAt);
  const fullValue = formatFullTimestamp(format, submittedAt);

  return (
    <span title={fullValue ?? undefined} className="whitespace-nowrap text-xs tabular-nums text-[color:var(--aqt-fg-muted)]">
      {shortValue ?? "—"}
    </span>
  );
}

export function ReviewedCell({ registration }: Readonly<{ registration: AdminRegistration }>) {
  const format = useFormatter();
  const reviewedAt = formatTimestamp(format, registration.reviewed_at);
  if (!reviewedAt && !registration.reviewed_by_username) {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  const summary = [registration.reviewed_by_username, reviewedAt].filter(Boolean).join(" · ");
  return (
    <span className="block max-w-[220px] truncate text-xs text-[color:var(--aqt-fg-muted)]" title={summary}>
      {summary}
    </span>
  );
}

/**
 * "Call me in if somebody drops or I cannot make the start" — the registrant's
 * own availability note, not a pool verdict.
 *
 * It rides beside the balancer chip rather than replacing it because the two
 * answer different questions: the chip says where the row stands in the pool,
 * this says who the organizer can ring when a slot opens up mid-tournament. A
 * player wearing it plays like anybody else.
 */
export function ReserveBadge() {
  const t = useTranslations();
  return (
    <StatusPill tone="info" title={t("common.reserveHint")}>
      {t("common.reserve")}
    </StatusPill>
  );
}

export function ExclusionCell({ registration }: Readonly<{ registration: AdminRegistration }>) {
  if (registration.balancer_status !== "excluded") {
    return <span className="text-[color:var(--aqt-fg-dim)]">—</span>;
  }

  const reason = registration.exclude_reason ?? "Excluded";
  return (
    <StatusPill tone="warning" className="max-w-[220px]" title={reason}>
      <span className="truncate">{reason}</span>
    </StatusPill>
  );
}

/**
 * The reason behind one row's admission verdict.
 *
 * Amber for a blocker, muted for a requirement that is merely failing open — the
 * second is not keeping anybody out today, but it will keep doing so silently
 * until somebody looks, so it must be visible without reading as a refusal.
 */
export function AdmissionReasonCell({ registration }: Readonly<{ registration: AdminRegistration }>) {
  const t = useTranslations();
  const reason = primaryAdmissionReason(registration.admission);
  if (!reason) {
    return <span className="text-[color:var(--aqt-fg-faint)]">—</span>;
  }

  const text = formatAdmissionReason(t, reason);
  const isBlocking = registration.admission.blockers.length > 0;
  return (
    <span
      className={cn(
        "block max-w-[240px] truncate text-xs",
        isBlocking ? "text-[color:var(--aqt-amber)]" : "text-[color:var(--aqt-fg-dim)]",
      )}
      title={text}
    >
      {text}
    </span>
  );
}
