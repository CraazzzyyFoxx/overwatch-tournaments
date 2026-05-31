"use client";

import type { ReactNode } from "react";
import {
  CheckCircle2,
  Circle,
  XCircle,
} from "lucide-react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import StatusMetaBadge from "@/components/status/StatusMetaBadge";
import { cn } from "@/lib/utils";
import { ROLE_LABELS, getRoleIconName, getSubroleLabel } from "@/lib/roles";
import type {
  AdminRegistration,
  AdminRegistrationRole,
} from "@/types/balancer-admin.types";
import type { SubroleCatalog } from "@/types/registration.types";

export interface BalancerRegistrationColumnDefinition {
  id: string;
  label: string;
  category: "core" | "meta" | "admin";
  defaultVisible: boolean;
  render: (registration: AdminRegistration, index: number) => ReactNode;
  searchValue?: (registration: AdminRegistration) => string | null;
  responsive?: "always" | "sm" | "md" | "lg";
  widthClass?: string;
  align?: "left" | "center" | "right";
}

function formatTimestamp(dateString: string | null | undefined): string | null {
  if (!dateString) {
    return null;
  }

  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatFullTimestamp(dateString: string | null | undefined): string | null {
  if (!dateString) {
    return null;
  }

  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function ParticipantCell({ registration }: { registration: AdminRegistration }) {
  const primary =
    registration.battle_tag ??
    registration.display_name ??
    `Registration #${registration.id}`;

  const secondaryParts = [
    registration.battle_tag && registration.display_name && registration.display_name !== registration.battle_tag
      ? registration.display_name
      : null,
    registration.discord_nick,
    registration.twitch_nick,
    registration.source_record_key,
  ].filter(Boolean);

  return (
    <div className="min-w-0 space-y-1">
      <div className="truncate font-medium text-white/90" title={primary}>
        {primary}
      </div>
      <div
        className="truncate text-xs text-white/40"
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

function RolesCell({
  roles,
  catalog,
}: {
  roles: AdminRegistrationRole[];
  catalog?: SubroleCatalog;
}) {
  if (!roles || roles.length === 0) {
    return <span className="text-white/30">—</span>;
  }

  const sortedRoles = roles
    .filter((role) => role.is_active)
    .slice()
    .sort((left, right) => left.priority - right.priority);

  if (sortedRoles.length === 0) {
    return <span className="text-white/30">—</span>;
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
                  : "text-white/70",
              )}
            >
              <PlayerRoleIcon role={getRoleIconName(role.role)} size={20} />
            </span>
            <span className="text-center text-[9px] font-semibold uppercase leading-none tracking-[0.12em] text-white/45">
              {subroleLabel ?? role.rank_value ?? ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function SourceCell({ source }: { source: AdminRegistration["source"] }) {
  const isSheets = source === "google_sheets";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        isSheets
          ? "border-sky-500/20 bg-sky-500/10 text-sky-300"
          : "border-white/10 bg-white/5 text-white/55",
      )}
    >
      {isSheets ? "Sheets" : "Manual"}
    </span>
  );
}

function CompactListCell({ values }: { values: string[] }) {
  if (values.length === 0) {
    return <span className="text-white/30">—</span>;
  }

  const visibleValues = values.slice(0, 2);
  const hiddenCount = values.length - visibleValues.length;

  return (
    <div className="max-w-[220px] space-y-1">
      {visibleValues.map((value, index) => (
        <div key={`${value}-${index}`} className="truncate text-xs text-white/55" title={value}>
          {value}
        </div>
      ))}
      {hiddenCount > 0 ? (
        <div className="text-[11px] font-medium text-emerald-300/75">
          +{hiddenCount} more
        </div>
      ) : null}
    </div>
  );
}

function TextBlockCell({ value }: { value: string | null | undefined }) {
  if (!value) {
    return <span className="text-white/30">—</span>;
  }

  return (
    <span className="block max-w-[240px] truncate text-xs text-white/55" title={value}>
      {value}
    </span>
  );
}

function StatusBadge({ registration }: { registration: AdminRegistration }) {
  return <StatusMetaBadge meta={registration.status_meta} fallbackValue={registration.status} />;
}

function BalancerBadge({ registration }: { registration: AdminRegistration }) {
  return <StatusMetaBadge meta={registration.balancer_status_meta} fallbackValue={registration.balancer_status} />;
}

function CheckInBadge({ checkedIn }: { checkedIn: boolean }) {
  const label = checkedIn ? "Checked In" : "Not Checked In";
  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex size-5 items-center justify-center",
        checkedIn ? "text-emerald-400" : "text-white/35",
      )}
    >
      {checkedIn ? <CheckCircle2 className="size-4" /> : <Circle className="size-4" />}
    </span>
  );
}

function AdmissionBadge({ registration }: { registration: AdminRegistration }) {
  const admitted =
    registration.status === "approved" &&
    registration.balancer_status === "ready" &&
    registration.checked_in === true;

  return (
    <span
      title={admitted ? "Admitted" : "Not Admitted"}
      aria-label={admitted ? "Admitted" : "Not Admitted"}
      className={cn(
        "inline-flex size-5 items-center justify-center",
        admitted ? "text-emerald-400" : "text-red-400",
      )}
    >
      {admitted ? <CheckCircle2 className="size-4" /> : <XCircle className="size-4" />}
    </span>
  );
}

function SubmittedCell({ submittedAt }: { submittedAt: string | null }) {
  const shortValue = formatTimestamp(submittedAt);
  const fullValue = formatFullTimestamp(submittedAt);

  return (
    <span title={fullValue ?? undefined} className="whitespace-nowrap text-xs tabular-nums text-white/50">
      {shortValue ?? "—"}
    </span>
  );
}

function ReviewedCell({ registration }: { registration: AdminRegistration }) {
  const reviewedAt = formatTimestamp(registration.reviewed_at);
  if (!reviewedAt && !registration.reviewed_by_username) {
    return <span className="text-white/30">—</span>;
  }

  const summary = [registration.reviewed_by_username, reviewedAt].filter(Boolean).join(" · ");
  return (
    <span className="block max-w-[220px] truncate text-xs text-white/55" title={summary}>
      {summary}
    </span>
  );
}

function ExclusionCell({ registration }: { registration: AdminRegistration }) {
  if (!registration.exclude_from_balancer) {
    return <span className="text-white/30">—</span>;
  }

  const reason = registration.exclude_reason ?? "Excluded";
  return (
    <span
      className="inline-flex max-w-[220px] truncate rounded-md border border-orange-500/20 bg-orange-500/10 px-1.5 py-0.5 text-[11px] font-medium text-orange-300"
      title={reason}
    >
      {reason}
    </span>
  );
}

export function buildBalancerRegistrationColumns(
  subroleCatalog?: SubroleCatalog,
): BalancerRegistrationColumnDefinition[] {
  return [
    {
      id: "participant",
      label: "Participant",
      category: "core",
      defaultVisible: true,
      responsive: "always",
      widthClass: "min-w-[240px]",
      render: (registration) => <ParticipantCell registration={registration} />,
      searchValue: (registration) =>
        [
          registration.battle_tag,
          registration.display_name,
          registration.discord_nick,
          registration.twitch_nick,
          registration.source_record_key,
        ]
          .filter(Boolean)
          .join(" "),
    },
    {
      id: "smurfs",
      label: "Smurfs",
      category: "admin",
      defaultVisible: true,
      responsive: "md",
      widthClass: "min-w-[180px]",
      render: (registration) => <CompactListCell values={registration.smurf_tags_json ?? []} />,
      searchValue: (registration) => registration.smurf_tags_json.join(" "),
    },
    {
      id: "roles",
      label: "Roles",
      category: "core",
      defaultVisible: true,
      responsive: "always",
      align: "center",
      render: (registration) => <RolesCell roles={registration.roles} catalog={subroleCatalog} />,
      searchValue: (registration) =>
        registration.roles
          .map((role) => [role.role, role.subrole, role.rank_value].filter(Boolean).join(" "))
          .join(" "),
    },
    {
      id: "status",
      label: "Status",
      category: "core",
      defaultVisible: true,
      responsive: "always",
      align: "center",
      render: (registration) => <StatusBadge registration={registration} />,
      searchValue: (registration) => registration.status,
    },
    {
      id: "balancer",
      label: "Balancer",
      category: "core",
      defaultVisible: true,
      responsive: "always",
      align: "center",
      render: (registration) => <BalancerBadge registration={registration} />,
      searchValue: (registration) => registration.balancer_status,
    },
    {
      id: "checkin",
      label: "Check-in",
      category: "core",
      defaultVisible: true,
      responsive: "always",
      align: "center",
      render: (registration) => <CheckInBadge checkedIn={registration.checked_in} />,
      searchValue: (registration) => (registration.checked_in ? "checked in" : "not checked in"),
    },
    {
      id: "admission",
      label: "Admission",
      category: "meta",
      defaultVisible: true,
      responsive: "md",
      align: "center",
      render: (registration) => <AdmissionBadge registration={registration} />,
      searchValue: (registration) =>
        registration.status === "approved" &&
        registration.balancer_status === "ready" &&
        registration.checked_in
          ? "admitted"
          : "not admitted",
    },
    {
      id: "submitted",
      label: "Submitted",
      category: "meta",
      defaultVisible: true,
      responsive: "md",
      render: (registration) => <SubmittedCell submittedAt={registration.submitted_at} />,
      searchValue: (registration) => registration.submitted_at,
    },
    {
      id: "source",
      label: "Source",
      category: "admin",
      defaultVisible: false,
      responsive: "md",
      render: (registration) => <SourceCell source={registration.source} />,
      searchValue: (registration) => `${registration.source} ${registration.source_record_key ?? ""}`.trim(),
    },
    {
      id: "notes",
      label: "Notes",
      category: "admin",
      defaultVisible: false,
      responsive: "lg",
      widthClass: "min-w-[220px]",
      render: (registration) => <TextBlockCell value={registration.notes} />,
      searchValue: (registration) => registration.notes,
    },
    {
      id: "admin_notes",
      label: "Admin Notes",
      category: "admin",
      defaultVisible: false,
      responsive: "lg",
      widthClass: "min-w-[220px]",
      render: (registration) => <TextBlockCell value={registration.admin_notes} />,
      searchValue: (registration) => registration.admin_notes,
    },
    {
      id: "reviewed",
      label: "Reviewed",
      category: "admin",
      defaultVisible: false,
      responsive: "lg",
      widthClass: "min-w-[180px]",
      render: (registration) => <ReviewedCell registration={registration} />,
      searchValue: (registration) =>
        [registration.reviewed_by_username, registration.reviewed_at].filter(Boolean).join(" "),
    },
    {
      id: "excluded",
      label: "Exclusion",
      category: "admin",
      defaultVisible: false,
      responsive: "lg",
      widthClass: "min-w-[180px]",
      render: (registration) => <ExclusionCell registration={registration} />,
      searchValue: (registration) =>
        registration.exclude_from_balancer
          ? [registration.exclude_reason, "excluded from balancer"].filter(Boolean).join(" ")
          : null,
    },
  ];
}
