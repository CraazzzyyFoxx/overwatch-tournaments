"use client";

import type { ReactNode } from "react";
import { CheckCircle, CircleAlert, Clock } from "lucide-react";

import { StatusIcon } from "@/components/admin/StatusIcon";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { useFormatter } from "@/lib/datetime/client";
import type { Encounter } from "@/types/encounter.types";

/** The stage or stage item an encounter was scheduled under. */
export function encounterScopeLabel(encounter: Encounter): string {
  return encounter.stage_item?.name ?? encounter.stage?.name ?? "—";
}

export function EncounterStatusCell({ status }: Readonly<{ status?: string | null }>) {
  const upper = status?.toUpperCase() ?? "";
  if (upper === "COMPLETED") {
    return <StatusIcon icon={CheckCircle} label="Completed" variant="success" />;
  }
  if (upper === "PENDING") {
    return <StatusIcon icon={Clock} label="Pending" variant="warning" />;
  }
  return (
    <StatusIcon
      icon={CircleAlert}
      label={upper ? `${upper[0]}${upper.slice(1).toLowerCase()}` : "Unknown"}
      variant="muted"
    />
  );
}

/**
 * The planned start time, on the viewer's own clock (the app formatter's zone)
 * — the same zone the stage editor's round schedule is typed against. Its own
 * component so the column definitions stay independent of the formatter's
 * identity.
 */
export function ScheduledAtCell({ value }: Readonly<{ value: Encounter["scheduled_at"] }>) {
  const format = useFormatter();
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const at = new Date(value);
  return (
    <time
      className="text-sm tabular-nums"
      dateTime={at.toISOString()}
      title={format.dateTime(at, { dateStyle: "full", timeStyle: "short" })}
    >
      {format.dateTime(at, {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit"
      })}
    </time>
  );
}

export function InspectorField({
  label,
  children
}: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <div className="truncate text-sm">{children}</div>
    </div>
  );
}
