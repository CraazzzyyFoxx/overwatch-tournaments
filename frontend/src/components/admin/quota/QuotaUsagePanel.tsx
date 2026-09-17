"use client";

import { useFormatter, useTranslations } from "next-intl";

import { EmptyNote } from "@/components/admin/kit/EmptyNote";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { QuotaScopeUsage, QuotaUsage } from "@/types/auth.types";
import { QUOTA_CAPS, QUOTA_COUNTERS } from "./dimensions";

const MEGABYTE = 1024 * 1024;

/**
 * Spent-versus-ceiling for one enforcement scope.
 *
 * Every scope is named, because a refusal names exactly one of them: without
 * the label a 429 on a key that is nowhere near its own ceiling reads as a
 * random failure rather than as "the workspace pool is empty".
 */
function QuotaScopeBars({ usage }: Readonly<{ usage: QuotaScopeUsage }>) {
  const t = useTranslations("quota");
  const format = useFormatter();
  // Reading the clock in render is impure and mismatches on hydration; the
  // window this counts down to is a minute or a day wide, so minute precision
  // is the honest resolution anyway.
  const now = useMinuteClock();

  return (
    <section className="rounded-xl border border-border/60 p-3">
      <h4 className="text-sm font-medium">{t(`scopes.${usage.scope}.label`)}</h4>
      <p className="mt-0.5 text-xs text-muted-foreground">{t(`scopes.${usage.scope}.hint`)}</p>

      <div className="mt-3 space-y-3">
        {QUOTA_COUNTERS.map((counter) => {
          const limit = usage[counter.dimension];
          const used = usage[counter.used] as number;
          const resetIn = counter.resetIn === null ? null : (usage[counter.resetIn] as number | null);
          const percent = limit && limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
          const label = t(`dimensions.${counter.dimension}.label`);

          return (
            <div key={counter.dimension}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium">{label}</span>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {limit === null
                    ? t("spentUnlimited", { used: format.number(used) })
                    : t("spent", { used: format.number(used), limit: format.number(limit) })}
                </span>
              </div>
              <Progress
                value={percent}
                aria-label={`${t(`scopes.${usage.scope}.label`)} — ${label}`}
                className={cn(
                  "mt-1.5 h-2",
                  percent >= 100 && "[&>div]:bg-danger",
                  percent >= 80 && percent < 100 && "[&>div]:bg-warning"
                )}
              />
              {resetIn !== null && now !== null ? (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {t("resetsIn", {
                    relative: format.relativeTime(new Date(now + resetIn * 1000), now)
                  })}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>

      <dl className="mt-3 grid gap-x-4 gap-y-1 border-t border-border/60 pt-3 sm:grid-cols-2">
        {QUOTA_CAPS.map((dimension) => {
          const value = usage[dimension];
          return (
            <div key={dimension} className="flex items-baseline justify-between gap-2">
              <dt className="text-xs text-muted-foreground">{t(`dimensions.${dimension}.label`)}</dt>
              <dd className="text-xs tabular-nums">
                {value === null
                  ? t("unlimited")
                  : dimension === "max_upload_bytes"
                    ? t("megabytes", {
                        value: format.number(value / MEGABYTE, { maximumFractionDigits: 1 })
                      })
                    : format.number(value)}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

/**
 * Every scope a principal is charged against, in one place (T4/F15 §5.5).
 *
 * The panel is deliberately not a single aggregate bar: the two budgets are
 * independent, and collapsing them would destroy the one distinction an admin
 * opens this screen for.
 */
export function QuotaUsagePanel({ usage }: Readonly<{ usage: QuotaUsage }>) {
  const t = useTranslations("quota");

  if (usage.scopes.length === 0) {
    return <EmptyNote size="sm">{t("usageEmpty")}</EmptyNote>;
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {usage.plan_slug ? t("plan", { slug: usage.plan_slug }) : t("planUnknown")}
      </p>
      {usage.scopes.map((scope) => (
        <QuotaScopeBars key={scope.scope} usage={scope} />
      ))}
    </div>
  );
}
