"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { Check, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { columnMeta } from "@craazzzyyfoxx/admin-kit/data-table";
import { IconTooltip } from "@craazzzyyfoxx/admin-kit/ui/icon-tooltip";
import { TONE_TEXT } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { Badge } from "@/components/ui/badge";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { CareerSignal, CareerUserSignals } from "@/types/career-signals.types";

import { signalTone, sortSignals } from "./careerSignals";

/** A signal's wording in the UI language; a code the bundle does not know reads as itself. */
export function useSignalLabel() {
  const t = useTranslations("registrationsAdmin.career");
  return (kind: "short" | "full", signal: CareerSignal, values: Record<string, string | number> = {}) => {
    const key = `${kind}.${signal.code}`;
    return t.has(key as never) ? t(key as never, values as never) : signal.code;
  };
}

/** ✓ with no signals, the one signal's short label, or a count with the list on hover. */
function CareerSignalsCell({ signals }: Readonly<{ signals: CareerSignal[] }>) {
  const t = useTranslations("registrationsAdmin.career");
  const label = useSignalLabel();
  if (signals.length === 0) {
    return <Check className={`mx-auto size-4 ${TONE_TEXT.success}`} role="img" aria-label={t("column.none")} />;
  }
  const sorted = sortSignals(signals);
  if (sorted.length === 1) {
    return (
      <Badge tone={signalTone(sorted[0].code)} size="sm">
        {label("short", sorted[0])}
      </Badge>
    );
  }
  return (
    <IconTooltip
      label={t("column.many", { count: sorted.length })}
      hint={
        <ul className="space-y-0.5 text-left">
          {sorted.map((signal, index) => (
            <li key={`${signal.code}-${signal.social_account_id ?? index}`}>{label("short", signal)}</li>
          ))}
        </ul>
      }
    >
      <Badge tone="warning" size="sm">
        <TriangleAlert className="size-3" aria-hidden />
        {t("column.many", { count: sorted.length })}
      </Badge>
    </IconTooltip>
  );
}

/** The «Ladder» column: what the collected game career says about the registrant. */
export function careerSignalsColumn({
  header,
  byUser
}: {
  header: string;
  byUser: ReadonlyMap<number, CareerUserSignals>;
}): ColumnDef<AdminRegistration> {
  const signalsOf = (registration: AdminRegistration) =>
    registration.user_id == null ? undefined : byUser.get(registration.user_id)?.signals;
  return {
    id: "career_signals",
    header,
    // Most signals last, so "no signals" and "unknown" group at the top.
    accessorFn: (registration) => signalsOf(registration)?.length ?? -1,
    cell: ({ row }) => {
      const signals = signalsOf(row.original);
      if (signals) return <CareerSignalsCell signals={signals} />;
      // No linked user: nothing to read. A linked one whose answer is still in flight draws nothing yet.
      return row.original.user_id == null ? <span className="text-[color:var(--aqt-fg-faint)]">—</span> : null;
    },
    meta: columnMeta<AdminRegistration>({
      category: "meta",
      defaultHidden: false,
      responsive: "lg",
      align: "center",
      searchValue: (registration) => signalsOf(registration)?.map((signal) => signal.code).join(" ") ?? null
    })
  };
}
