"use client";

import { useState } from "react";
import { useFormatter } from "next-intl";
import {
  AlertTriangle,
  CheckCircle2,
  CircleOff,
  Clock3,
  Loader2,
  X,
  XCircle,
  type LucideIcon
} from "lucide-react";

import { StatusPill } from "@/components/admin/kit/StatusPill";
import { EYEBROW_CLASS, TONE_TEXT, type Tone } from "@/components/admin/tone";
import { Button } from "@/components/ui/button";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { EvaluationRunRead } from "@/types/admin.types";

/** One reason a rule was skipped, plus every rule it skipped. */
export interface RunFailureGroup {
  /** The engine's own sentence, verbatim. */
  cause: string;
  /** Rules skipped for that reason; empty when the run aborted as a whole. */
  slugs: string[];
}

export interface EvaluationRunDigest {
  tone: Tone;
  icon: LucideIcon;
  /** What happened, in one sentence. */
  headline: string;
  /** Only when the state needs explaining — a queued run is waiting on something. */
  note: string | null;
  failures: RunFailureGroup[];
  /** Rules the run did not get through. */
  skipped: number;
}

const STATUS_TONE: Record<EvaluationRunRead["status"], Tone> = {
  queued: "info",
  running: "info",
  done: "success",
  partial: "warning",
  failed: "danger",
  cancelled: "neutral"
};

const STATUS_ICON: Record<EvaluationRunRead["status"], LucideIcon> = {
  queued: Clock3,
  running: Loader2,
  done: CheckCircle2,
  partial: AlertTriangle,
  failed: XCircle,
  cancelled: CircleOff
};

/** Left edge only: the panel keeps `bg-card`, so a partial run reads without shouting. */
const TONE_EDGE: Record<Tone, string> = {
  neutral: "border-l-border",
  accent: "border-l-primary",
  success: "border-l-success",
  warning: "border-l-warning",
  info: "border-l-info",
  danger: "border-l-danger"
};

/** Tinted problem panel: border and wash from the tone, prose stays foreground. */
const TONE_PANEL: Record<Tone, string> = {
  neutral: "border-border/60 bg-muted/20",
  accent: "border-primary/40 bg-primary/5",
  success: "border-success/40 bg-success/5",
  warning: "border-warning/40 bg-warning/5",
  info: "border-info/40 bg-info/5",
  danger: "border-danger/40 bg-danger/5"
};

/** How many slugs a cause shows before the rest collapse behind a disclosure. */
const SLUG_PREVIEW = 8;

// The runner writes failures as `slug[, slug]: reason`, joined with "; ". A
// reason contains ": " of its own ("…base version 19: [20]"), so an entry breaks
// only where a slug list follows the separator.
// ponytail: a flat string parsed back apart. A JSON column would end the
// guesswork; it is a migration for one banner, so this stays until a second
// reader needs the structure.
const ENTRY_BOUNDARY = /;\s+(?=[a-z\d][\w-]*(?:,\s*[a-z\d][\w-]*)*:\s)/;
const ENTRY = /^([a-z\d][\w-]*(?:,\s*[a-z\d][\w-]*)*):\s+([\s\S]+)$/;

/**
 * Split `error_message` into one group per distinct reason.
 *
 * Only a `partial` run names rules: `failed` stores a bare `str(exc)`, whose
 * own "word: detail" shape would otherwise be mistaken for a slug.
 */
export function parseRunFailures(
  run: Pick<EvaluationRunRead, "status" | "error_message">
): RunFailureGroup[] {
  const message = run.error_message?.trim();
  if (!message) return [];
  if (run.status !== "partial") return [{ cause: message, slugs: [] }];

  const byCause = new Map<string, string[]>();
  for (const entry of message.split(ENTRY_BOUNDARY)) {
    const match = ENTRY.exec(entry.trim());
    const cause = (match?.[2] ?? entry).trim();
    const slugs = match ? match[1].split(",").map((slug) => slug.trim()) : [];
    const seen = byCause.get(cause);
    if (seen) seen.push(...slugs.filter((slug) => !seen.includes(slug)));
    else byCause.set(cause, slugs);
  }
  return [...byCause].map(([cause, slugs]) => ({ cause, slugs }));
}

/** The one place a run's outcome is put into words; the banner and the toast share it. */
export function describeEvaluationRun(run: EvaluationRunRead): EvaluationRunDigest {
  const failures = parseRunFailures(run);
  const skipped = failures.reduce((count, group) => count + group.slugs.length, 0);
  const base = { tone: STATUS_TONE[run.status], icon: STATUS_ICON[run.status], failures, skipped };

  switch (run.status) {
    case "queued":
      return { ...base, headline: "Evaluation is queued", note: "It starts once this workspace is verified." };
    case "running":
      return { ...base, headline: "Evaluation is running", note: null };
    case "partial": {
      const total = run.rules_evaluated + skipped;
      return {
        ...base,
        headline:
          skipped === 0
            ? "Some rules could not run"
            : total === 1
              ? "The rule could not run"
              : `${skipped} of ${total} rules could not run`,
        note: null
      };
    }
    case "failed":
      return { ...base, headline: "Evaluation stopped before it finished", note: null };
    case "cancelled":
      return { ...base, headline: "Evaluation was cancelled", note: null };
    default:
      return {
        ...base,
        headline:
          run.results_created + run.results_removed === 0
            ? "Evaluation finished with no changes"
            : "Evaluation finished",
        note: null
      };
  }
}

const TONE_NOTIFY: Record<Tone, (message: string, options?: { description?: string }) => unknown> = {
  neutral: notify.message,
  accent: notify.info,
  success: notify.success,
  warning: notify.warning,
  info: notify.info,
  danger: notify.error
};

/** Toast form of the same digest, for screens too small to hold the panel. */
export function notifyEvaluationRun(run: EvaluationRunRead) {
  const digest = describeEvaluationRun(run);
  const description =
    digest.failures[0]?.cause ??
    `${run.results_created} added, ${run.results_removed} removed`;
  return TONE_NOTIFY[digest.tone](digest.headline, { description });
}

function formatDuration(run: EvaluationRunRead): string | null {
  if (!run.finished_at) return null;
  const ms = Date.parse(run.finished_at) - Date.parse(run.started_at);
  if (!Number.isFinite(ms) || ms < 0) return null;
  // Non-breaking: a value that wraps away from its unit reads as a bare number.
  if (ms < 1000) return `${ms}\u00a0ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}\u00a0s`;
  return `${Math.floor(seconds / 60)}\u00a0min ${Math.round(seconds % 60)}\u00a0s`;
}

/** A delta reads `+12` or `−3`; an unchanged count is neither, so it reads `0`. */
function signed(value: number, sign: string, format: (value: number) => string): string {
  return value === 0 ? "0" : `${sign}${format(value)}`;
}

function Figure({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div>
      <dt className={EYEBROW_CLASS}>{label}</dt>
      <dd className="mt-1 text-heading font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function SlugList({ slugs }: Readonly<{ slugs: string[] }>) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? slugs : slugs.slice(0, SLUG_PREVIEW);
  const hidden = slugs.length - shown.length;

  return (
    <ul className="mt-2 flex flex-wrap items-center gap-1.5">
      {shown.map((slug) => (
        <li
          key={slug}
          className="rounded border border-border/60 px-1.5 py-0.5 font-mono text-label text-muted-foreground"
        >
          {slug}
        </li>
      ))}
      {hidden > 0 || expanded ? (
        <li>
          <Button
            variant="link"
            size="sm"
            className="h-auto px-1 py-0"
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Show fewer" : `Show ${hidden} more`}
          </Button>
        </li>
      ) : null}
    </ul>
  );
}

export interface EvaluationRunSummaryProps {
  run: EvaluationRunRead;
  onDismiss: () => void;
  /** Name of the tournament the run was scoped to, when the caller knows it. */
  tournamentName?: string;
}

/**
 * The result of an evaluation run, read cause-first.
 *
 * The engine reports a failure per rule, and one missing grid mapping fails
 * dozens of rules with the same sentence. Printing that list as it arrives
 * buries the single thing to fix under its own repetitions, so the reason is
 * the heading here and the rules are its members.
 */
export function EvaluationRunSummary({
  run,
  onDismiss,
  tournamentName
}: Readonly<EvaluationRunSummaryProps>) {
  const format = useFormatter();
  const digest = describeEvaluationRun(run);
  const Icon = digest.icon;
  const settled = run.status !== "queued" && run.status !== "running";

  const scope = tournamentName
    ? `Tournament: ${tournamentName}`
    : run.tournament_id
      ? `Tournament #${run.tournament_id}`
      : "Whole workspace";
  const meta = [scope, formatDuration(run)].filter(Boolean).join(" · ");

  return (
    <section
      role="status"
      className={cn("space-y-4 rounded-lg border border-l-4 bg-card p-4", TONE_EDGE[digest.tone])}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <Icon
            className={cn(
              "mt-0.5 size-5 shrink-0",
              TONE_TEXT[digest.tone],
              run.status === "running" && "motion-safe:animate-spin"
            )}
            aria-hidden
          />
          <div className="min-w-0">
            <p className="text-body font-medium">{digest.headline}</p>
            <p className="text-caption text-muted-foreground">{meta}</p>
            {digest.note ? <p className="text-caption text-muted-foreground">{digest.note}</p> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusPill tone={digest.tone} dot={run.status === "running"}>
            {run.status}
          </StatusPill>
          <Button
            variant="ghost"
            size="icon"
            onClick={onDismiss}
            aria-label="Dismiss the evaluation summary"
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>
      </div>

      {settled ? (
        <dl className="flex flex-wrap gap-x-10 gap-y-3">
          <Figure label="Rules run" value={format.number(run.rules_evaluated)} />
          <Figure label="Results added" value={signed(run.results_created, "+", format.number)} />
          <Figure
            label="Results removed"
            value={signed(run.results_removed, "\u2212", format.number)}
          />
        </dl>
      ) : null}

      {digest.failures.length > 0 ? (
        <ul className="space-y-2">
          {digest.failures.map((group) => (
            <li
              key={group.cause}
              className={cn("rounded-md border p-3", TONE_PANEL[digest.tone])}
            >
              <p className="text-body text-foreground">{group.cause}</p>
              {group.slugs.length > 0 ? <SlugList slugs={group.slugs} /> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
