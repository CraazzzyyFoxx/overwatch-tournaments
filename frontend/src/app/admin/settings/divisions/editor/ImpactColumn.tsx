"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Check, Info } from "lucide-react";

import { EYEBROW_CLASS, TONE_TEXT } from "@/components/kit/tone";
import { cn } from "@/lib/utils";
import type { DivisionGridReadinessSource } from "@/types/workspace.types";

import type { PublishCheck } from "./publishChecks";

export interface ImpactColumnProps {
  checks: PublishCheck[];
  sources: DivisionGridReadinessSource[];
  edits: string[];
}

const SOURCE_STATUS_TEXT: Record<DivisionGridReadinessSource["status"], string> = {
  ok: "mapping complete",
  incomplete: "mapping incomplete",
  missing: "no mapping yet"
};

/**
 * Impact · Ready to publish? · Changes in the draft (F12 ·6…·8).
 *
 * The right rail on `xl`, and the "Impact" sub-tab below it — one component
 * either way, so the two do not drift.
 */
export function ImpactColumn({ checks, sources, edits }: Readonly<ImpactColumnProps>) {
  return (
    <div className="flex flex-col gap-3">
      <Panel title="Impact of this draft">
        <p className={EYEBROW_CLASS}>Players changing division</p>
        <p
          className="font-display text-xl font-semibold"
          title="The player-distribution endpoint is not built yet (backend gap G1), so this cannot be counted client-side."
        >
          &mdash;
        </p>
        {sources.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No other version is still read by a tournament.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5 text-xs">
            {sources.map((source) => (
              <li key={source.version_id}>
                <span className="font-mono">{source.version_label}</span>{" "}
                <span className="text-muted-foreground">
                  · {source.tournament_count}{" "}
                  {source.tournament_count === 1 ? "tournament" : "tournaments"}
                </span>
                <br />
                <span className="text-muted-foreground">{SOURCE_STATUS_TEXT[source.status]}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Ready to publish?">
        <ul className="flex flex-col gap-1.5 text-xs">
          {checks.map((check) => {
            const tone = check.ok ? "success" : check.blocking ? "warning" : "info";
            const Icon = check.ok ? Check : check.blocking ? AlertTriangle : Info;
            return (
              <li key={check.key} className="flex items-start gap-1.5">
                <Icon aria-hidden className={cn("mt-0.5 size-3.5 shrink-0", TONE_TEXT[tone])} />
                <span>{check.label}</span>
              </li>
            );
          })}
        </ul>
      </Panel>

      <Panel
        title="Changes in the draft"
        aside={`${edits.length} ${edits.length === 1 ? "edit" : "edits"}`}
      >
        {edits.length === 0 ? (
          <p className="text-xs text-muted-foreground">Nothing edited yet.</p>
        ) : (
          <ol className="flex flex-col gap-1 text-xs">
            {edits.map((edit, index) => (
              // Edits are positional history entries; two identical sentences
              // (the same rename undone and redone) are legitimately distinct.
              <li key={`${index}-${edit}`}>{edit}</li>
            ))}
          </ol>
        )}
      </Panel>
    </div>
  );
}

function Panel({
  title,
  aside,
  children
}: Readonly<{ title: string; aside?: string; children: ReactNode }>) {
  return (
    <section className="flex flex-col gap-2 rounded-xl border border-border bg-card p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-display text-sm font-semibold">{title}</h2>
        {aside ? <span className={cn(EYEBROW_CLASS, "font-mono")}>{aside}</span> : null}
      </div>
      {children}
    </section>
  );
}
