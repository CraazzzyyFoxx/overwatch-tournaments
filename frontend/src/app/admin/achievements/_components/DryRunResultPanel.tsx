"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

import type { DryRunResult } from "../_hooks/useAchievementRuleActions";

/**
 * Who would qualify for a rule right now, without awarding anything. `result: null` while the run is pending.
 * The test starts from a row's menu, possibly far down the table: the panel scrolls into view when it appears
 * and takes focus when the result lands, so the outcome is never off-screen. Shown until dismissed.
 */
export function DryRunResultPanel({
  result,
  onDismiss,
}: Readonly<{ result: DryRunResult | null; onDismiss: () => void }>) {
  const t = useTranslations("adminAchievements");
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    // Focus waits for the result: the row menu that started the run returns focus to its trigger as it closes.
    if (result) ref.current?.focus({ preventScroll: true });
  }, [result]);

  return (
    <Card asChild>
      <section
        ref={ref}
        tabIndex={-1}
        aria-labelledby="dry-run-title"
        aria-busy={result === null}
        className="space-y-3 p-4 outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        {result === null ? (
          <h2 id="dry-run-title" className="flex items-center gap-2 text-sm font-semibold">
            <Spinner />
            {t("common.testing")}
          </h2>
        ) : (
          <>
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1">
                <h2 id="dry-run-title" className="text-sm font-semibold">
                  {t("dryRun.title", { slug: result.slug })}
                </h2>
                <p className="text-sm text-muted-foreground">{t("dryRun.qualifies", { count: result.count })}</p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={onDismiss}
                aria-label={t("dryRun.dismiss")}
                title={t("dryRun.dismiss")}
              >
                <X className="h-4 w-4" aria-hidden />
              </Button>
            </div>
            {result.sample.length > 0 && (
              <div className="space-y-1 border-t border-border/60 pt-3">
                <p className="text-caption font-medium" id="dry-run-sample">
                  {t("dryRun.sample")}
                </p>
                <ul
                  className="max-h-48 overflow-auto text-sm tabular-nums"
                  tabIndex={0}
                  aria-labelledby="dry-run-sample"
                >
                  {result.sample.map((tuple, i) => (
                    <li key={i}>
                      {t("dryRun.sampleRow", {
                        user: tuple[0],
                        hasTournament: tuple[1] ? "yes" : "no",
                        tournament: tuple[1] ?? "",
                        hasMatch: tuple[2] ? "yes" : "no",
                        match: tuple[2] ?? "",
                      })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>
    </Card>
  );
}
