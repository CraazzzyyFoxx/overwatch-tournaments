"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { CheckCircle2, Circle, Lock, Minus, type LucideIcon } from "lucide-react";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { StatusPill } from "@/components/kit/StatusPill";
import { Card, CardContent, CardHeader, CardTitle } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import type { ChecklistItem, ChecklistPhase, ChecklistState } from "@/components/admin/tournament-checklist";

const PHASE_KEYS: ChecklistPhase[] = ["setup", "registration", "formation", "bracket", "matches", "wrap_up"];

/** Quiet states are an icon; `warn` wants attention and gets a pill; `info` has no verdict to show. */
const STATE_ICON: Record<Exclude<ChecklistState, "warn" | "info">, { icon: LucideIcon; variant: "success" | "muted" }> = {
  done: { icon: CheckCircle2, variant: "success" },
  todo: { icon: Circle, variant: "muted" },
  skipped: { icon: Minus, variant: "muted" },
  "no-access": { icon: Lock, variant: "muted" }
};

const STATE_LABEL_KEY = {
  done: "states.done",
  todo: "states.todo",
  warn: "states.warn",
  skipped: "states.skipped",
  "no-access": "states.noAccess"
} as const satisfies Record<Exclude<ChecklistState, "info">, string>;

function ChecklistRow({ item }: Readonly<{ item: ChecklistItem }>) {
  const t = useTranslations("adminTournament.lifecycle");
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/50 py-2 last:border-b-0">
      <div className="min-w-0">
        {item.href && item.state !== "no-access" ? (
          <Link href={item.href} className="text-sm hover:underline">
            {item.label}
          </Link>
        ) : (
          <span className="text-sm">{item.label}</span>
        )}
        {item.detail ? (
          <p className="truncate text-xs tabular-nums text-muted-foreground">{item.detail}</p>
        ) : null}
      </div>
      {item.state === "info" ? null : item.state === "warn" ? (
        <StatusPill tone="warning" className="shrink-0">
          {t(STATE_LABEL_KEY.warn)}
        </StatusPill>
      ) : (
        <StatusIcon
          icon={STATE_ICON[item.state].icon}
          label={t(STATE_LABEL_KEY[item.state])}
          variant={STATE_ICON[item.state].variant}
          className="shrink-0"
        />
      )}
    </div>
  );
}

/**
 * Living checklist of the Overview tab (§3, D22). Items come pre-computed
 * from `buildChecklist`; groups without applicable items are omitted, and a
 * status with no work at all (archived) renders nothing.
 *
 * This is the tab's `<h2>` section — the hub previously rendered no heading
 * above `<h3>`, leaving these group titles as the document's first headings.
 */
export function LifecycleChecklist({
  items,
  isLoading
}: Readonly<{ items: ChecklistItem[]; isLoading: boolean }>) {
  const t = useTranslations("adminTournament.lifecycle");
  const groups = PHASE_KEYS
    .map((phase) => ({ phase, rows: items.filter((item) => item.phase === phase) }))
    .filter((group) => group.rows.length > 0);
  if (!isLoading && groups.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle asChild>
          <h2>{t("title")}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Skeleton className="h-32 rounded-xl" />
            <Skeleton className="h-32 rounded-xl" />
            <Skeleton className="h-32 rounded-xl" />
          </div>
        ) : (
          <div className="grid gap-x-6 gap-y-4 md:grid-cols-2 xl:grid-cols-3">
            {groups.map((group) => (
              <section key={group.phase}>
                <h3 className={eyebrowClass("muted")}>{t(`phases.${group.phase}`)}</h3>
                <div className="mt-1">
                  {group.rows.map((item) => (
                    <ChecklistRow key={item.key} item={item} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
