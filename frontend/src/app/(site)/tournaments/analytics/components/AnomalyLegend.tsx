"use client";

import React from "react";
import { Info } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";

/** Anomaly kinds with the same hues as the chips elsewhere on the page. */
const ANOMALY_KINDS: { term: GlossaryTerm; hue: string }[] = [
  { term: "smurf", hue: "350 84% 65%" },
  { term: "throw", hue: "2 75% 62%" },
  { term: "troll", hue: "38 92% 60%" },
  { term: "sandbag", hue: "275 72% 68%" },
];

/**
 * A click-to-open legend that explains every anomaly flag in one place, so an
 * organizer doesn't have to hover each chip to learn what "smurf" / "throw" /
 * "troll" / "sandbag" mean. Copy comes from the shared `analytics.glossary`
 * entries, so it stays in sync with the inline tooltips.
 */
export default function AnomalyLegend({ className }: { className?: string }) {
  const t = useTranslations();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className={cn("h-6 gap-1 px-1.5 text-xs font-normal text-muted-foreground", className)}
        >
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
          {t("analytics.anomalyLegend.trigger")}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80">
        <p className="text-sm font-semibold">{t("analytics.anomalyLegend.title")}</p>
        <ul className="mt-2 space-y-2">
          {ANOMALY_KINDS.map(({ term, hue }) => (
            <li key={term} className="text-xs">
              <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: `hsl(${hue})` }}
                  aria-hidden="true"
                />
                {t(`analytics.glossary.${term}.label`)}
              </span>
              <span className="mt-0.5 block leading-relaxed text-muted-foreground">
                {t(`analytics.glossary.${term}.plain`)}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 border-t border-border/60 pt-2 text-[11px] italic text-muted-foreground/80">
          {t("analytics.anomalyLegend.note")}
        </p>
      </PopoverContent>
    </Popover>
  );
}
