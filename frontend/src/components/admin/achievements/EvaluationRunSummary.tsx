"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import type { Formatter } from "@/lib/datetime";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  X,
  XCircle,
  type LucideIcon
} from "lucide-react";

import { FactList } from "@/components/kit/FactList";
import { TONE_TEXT, type Tone } from "@/components/ui/tone";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { EvaluationRunRead } from "@/types/admin.types";

/** One reason a rule was skipped, plus every rule it skipped. */
interface RunFailureGroup {
  /** The engine's own sentence, verbatim. */
  cause: string;
  /** Rules skipped for that reason; empty when the run aborted as a whole. */
  slugs: string[];
}

export interface EvaluationRunDigest {
  tone: Tone;
  /** `null` while the run is in progress: that state is drawn as the `Spinner`. */
  icon: LucideIcon | null;
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
  failed: "danger"
};

const STATUS_ICON: Record<EvaluationRunRead["status"], LucideIcon | null> = {
  queued: Clock3,
  running: null,
  done: CheckCircle2,
  partial: AlertTriangle,
  failed: XCircle
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
function parseRunFailures(
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
type Translate = (key: string, values?: Record<string, string | number>) => string;

function describeEvaluationRun(run: EvaluationRunRead, t: Translate): EvaluationRunDigest {
  const failures = parseRunFailures(run);
  const skipped = failures.reduce((count, group) => count + group.slugs.length, 0);
  const base = { tone: STATUS_TONE[run.status], icon: STATUS_ICON[run.status], failures, skipped };

  switch (run.status) {
    case "queued":
      return { ...base, headline: t("evaluation.queued"), note: t("evaluation.queuedNote") };
    case "running":
      return { ...base, headline: t("evaluation.running"), note: null };
    case "partial": {
      const total = run.rules_evaluated + skipped;
      return {
        ...base,
        headline:
          skipped === 0
            ? t("evaluation.someFailed")
            : total === 1
              ? t("evaluation.oneFailed")
              : t("evaluation.manyFailed", { count: skipped, total }),
        note: null
      };
    }
    case "failed":
      return { ...base, headline: t("evaluation.stopped"), note: null };
    default:
      return {
        ...base,
        headline:
          run.results_created + run.results_removed === 0
            ? t("evaluation.noChanges")
            : t("evaluation.finished"),
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
export function notifyEvaluationRun(run: EvaluationRunRead, t: Translate) {
  const digest = describeEvaluationRun(run, t as unknown as Translate);
  const description =
    digest.failures[0]?.cause ??
    t("evaluation.addedRemoved", { added: run.results_created, removed: run.results_removed });
  return TONE_NOTIFY[digest.tone](digest.headline, { description });
}

function formatDuration(run: EvaluationRunRead, format: Formatter): string | null {
  if (!run.finished_at) return null;
  const ms = Date.parse(run.finished_at) - Date.parse(run.started_at);
  if (!Number.isFinite(ms) || ms < 0) return null;
  const unit = (value: number, name: string, digits = 0) =>
    format.number(value, {
      style: "unit",
      unit: name,
      unitDisplay: "short",
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  if (ms < 1000) return unit(ms, "millisecond");
  const seconds = ms / 1000;
  if (seconds < 60) return unit(seconds, "second", 1);
  return `${unit(Math.floor(seconds / 60), "minute")} ${unit(Math.round(seconds % 60), "second")}`;
}

/** A delta reads `+12` or `−3`; an unchanged count is neither, so it reads `0`. */
function signed(value: number, sign: string, format: (value: number) => string): string {
  return value === 0 ? "0" : `${sign}${format(value)}`;
}

function SlugList({ slugs, t }: Readonly<{ slugs: string[]; t: Translate }>) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? slugs : slugs.slice(0, SLUG_PREVIEW);
  const hidden = slugs.length - shown.length;

  return (
    <p className="mt-1 text-caption text-muted-foreground">
      <span className="font-mono">{shown.join(", ")}</span>
      {hidden > 0 || expanded ? (
        <>
          {" "}
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0 text-caption"
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? t("evaluation.showFewer") : t("evaluation.showMore", { count: hidden })}
          </Button>
        </>
      ) : null}
    </p>
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
  const t = useTranslations("adminAchievements");
  const format = useFormatter();
  const digest = describeEvaluationRun(run, t as unknown as Translate);
  const Icon = digest.icon;
  const iconClass = cn("mt-0.5 size-5 shrink-0", TONE_TEXT[digest.tone]);
  const settled = run.status !== "queued" && run.status !== "running";

  const scope = tournamentName
    ? t("evaluation.tournamentScope", { name: tournamentName })
    : run.tournament_id
      ? t("evaluation.tournamentIdScope", { id: run.tournament_id })
      : t("evaluation.wholeWorkspace");
  const meta = [scope, formatDuration(run, format)].filter(Boolean).join(" · ");

  return (
    <Card asChild>
      <section role="status" className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            {Icon ? <Icon className={iconClass} aria-hidden /> : <Spinner className={iconClass} />}
            <div className="min-w-0">
              <p className="text-body font-medium">{digest.headline}</p>
              <p className="text-caption text-muted-foreground">{meta}</p>
              {digest.note ? <p className="text-caption text-muted-foreground">{digest.note}</p> : null}
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0"
            onClick={onDismiss}
            aria-label={t("evaluation.dismissSummary")}
            title={t("evaluation.dismissSummary")}
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        {settled ? (
          <FactList
            facts={[
              { label: t("evaluation.rulesRun"), value: format.number(run.rules_evaluated) },
              {
                label: t("evaluation.resultsAdded"),
                value: signed(run.results_created, "+", format.number)
              },
              {
                label: t("evaluation.resultsRemoved"),
                value: signed(run.results_removed, "\u2212", format.number)
              }
            ]}
          />
        ) : null}

        {digest.failures.length > 0 ? (
          <ul className="divide-y border-t">
            {digest.failures.map((group) => (
              <li key={group.cause} className="py-3 last:pb-0">
                <p className="text-body">{group.cause}</p>
                {group.slugs.length > 0 ? <SlugList slugs={group.slugs} t={t as unknown as Translate} /> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </Card>
  );
}
