"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Check, Info } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card } from "@/components/ui/card";
import { TONE_TEXT } from "@/components/ui/tone";
import { cn } from "@/lib/utils";
import type { DivisionGridReadinessSource } from "@/types/workspace.types";

import type { EditNote } from "./draftReducer";
import type { PublishCheck } from "./publishChecks";

export interface ImpactColumnProps {
  checks: PublishCheck[];
  sources: DivisionGridReadinessSource[];
  edits: EditNote[];
}

/** A complete mapping is the norm and says nothing; only the gaps are named. */
const SOURCE_GAP_KEY = {
  incomplete: "impact.mappingIncomplete",
  missing: "impact.noMapping"
} as const;

/**
 * Impact · Ready to publish? · Changes in the draft (F12 ·6…·8).
 *
 * The right rail on `xl`, and the "Impact" sub-tab below it: one component
 * either way, so the two do not drift.
 */
export function ImpactColumn({ checks, sources, edits }: Readonly<ImpactColumnProps>) {
  const t = useTranslations("adminSettings.divisions");
  return (
    <Card className="flex flex-col divide-y divide-border">
      <Panel title={t("impact.title")}>
        {sources.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {t("impact.noOtherVersion")}
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5 text-xs">
            {sources.map((source) => (
              <li key={source.version_id}>
                {source.version_label}{" "}
                <span className="text-muted-foreground">
                  · {t("tournamentCount", { count: source.tournament_count })}
                </span>
                {source.status === "ok" ? null : (
                  <span className="block text-warning">{t(SOURCE_GAP_KEY[source.status])}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title={t("impact.readyToPublish")}>
        <ul className="flex flex-col gap-1.5 text-xs">
          {checks.map((check) => {
            const tone = check.ok ? "success" : check.blocking ? "warning" : "info";
            const Icon = check.ok ? Check : check.blocking ? AlertTriangle : Info;
            return (
              <li key={check.key} className="flex items-start gap-1.5">
                <Icon aria-hidden className={cn("mt-0.5 size-3.5 shrink-0", TONE_TEXT[tone])} />
                <span>{t(check.messageKey, check.values)}</span>
              </li>
            );
          })}
        </ul>
      </Panel>

      <Panel title={t("impact.changesInDraft")}>
        {edits.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("impact.nothingEdited")}</p>
        ) : (
          <ol className="flex flex-col gap-1 text-xs">
            {edits.map((edit, index) => (
              // Edits are positional history entries; two identical sentences
              // (the same rename undone and redone) are legitimately distinct.
              <li key={`${index}-${edit.key}`}>{t(edit.key, edit.values)}</li>
            ))}
          </ol>
        )}
      </Panel>
    </Card>
  );
}

function Panel({ title, children }: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <section className="flex flex-col gap-2 p-3">
      <h2 className="font-display text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}
