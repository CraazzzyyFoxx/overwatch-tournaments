"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronDown, Link2, RotateCcw } from "lucide-react";
import { useFormatter } from "@/lib/datetime/client";
import { columnMeta, createKebabColumn } from "@/components/data-table";
import { disclosureChevronClass } from "@/components/ui/chevron";
import { StatusPill } from "@/components/kit/StatusPill";
import { RawLogStatus } from "@/components/match/MatchLogIndicator";
import { cn } from "@/lib/utils";
import type { LogProcessingRecord } from "@/types/admin.types";
import { getLogFileName, getRetryKind } from "../logs.helpers";
import {
  SOURCE_LABELS,
  STATUS_META,
  canBindExplicitly,
  formatDuration,
  formatLogTime,
  getErrorDetail,
  getErrorSummary,
  getRetryRefusal,
  isRetryable
} from "./model";

/** The log job row: what was filed, where it landed, how processing went, and what can be done about it. */
export function useLogColumns({
  noEncounters,
  onRetry,
  onAttach
}: Readonly<{
  /** The hub has no encounter to file a log under; the workspace console picks a tournament instead. */
  noEncounters: boolean;
  /** Stable identity required: the kebab column closes over both. */
  onRetry: (records: LogProcessingRecord[]) => void;
  onAttach: (record: LogProcessingRecord) => void;
}>): ColumnDef<LogProcessingRecord>[] {
  const t = useTranslations("adminTournament.logs");
  const tx = useTranslations("adminTournament.logsExtra");
  const format = useFormatter();
  return useMemo<ColumnDef<LogProcessingRecord>[]>(
    () => [
      {
        id: "file",
        header: t("file"),
        accessorFn: (record) => getLogFileName(record.filename),
        enableSorting: false,
        cell: ({ row }) => {
          const record = row.original;
          const sourceLabel = Object.hasOwn(SOURCE_LABELS, record.source) ? SOURCE_LABELS[record.source] : undefined;
          return (
            <div className="space-y-1">
            <p
              className="max-w-[22rem] truncate font-mono text-xs"
              title={record.source === "historical_reference"
                ? `${record.filename}\n${t("sourceHistoricalReference")}`
                : tx("titleHint", { filename: record.filename, source: sourceLabel ? t(sourceLabel) : record.source, uploader: record.uploader_name ?? t("unknownUploader"), attempts: record.attempts > 1 ? record.attempts : 0 })}
            >
              {getLogFileName(record.filename)}
            </p>
              {record.source === "historical_reference" ? (
                <p className="text-xs text-muted-foreground">{t("sourceHistoricalReference")}</p>
              ) : null}
            </div>
          );
        }
      },
      {
        id: "encounter",
        header: t("encounter"),
        accessorFn: (record) => record.attached_encounter_name ?? "",
        enableSorting: false,
        cell: ({ row }) => (
          <p className="max-w-[16rem] truncate text-xs text-muted-foreground">
            {row.original.attached_encounter_name}
          </p>
        )
      },
      {
        // Pill only for the states that want attention (failed, awaiting a link,
        // processing); queued is a muted word, processed is nothing. Below it,
        // at most one line: why nothing can be done, or what is awaited.
        id: "status",
        header: t("status"),
        accessorFn: (record) => t(STATUS_META[record.status].key),
        size: 136,
        enableSorting: false,
        cell: ({ row }) => {
          const record = row.original;
          const meta = STATUS_META[record.status];
          const refusal = getRetryRefusal(record);
          const note = !record.raw_available ? (
            <RawLogStatus raw_status={record.raw_status} raw_available={record.raw_available} />
          ) : refusal ? (
            tx(refusal)
          ) : record.status === "awaiting_link" ? (
            tx("awaitingLinkHint")
          ) : null;
          return (
            <div className="max-w-[22rem] space-y-1">
              <div className="flex items-center gap-1.5">
                {meta.tone ? (
                  <StatusPill tone={meta.tone}>{t(meta.key)}</StatusPill>
                ) : record.status === "pending" ? (
                  <span className="text-xs text-muted-foreground">{t(meta.key)}</span>
                ) : null}
                {record.attempts > 1 ? (
                  <span className="text-xs tabular-nums text-muted-foreground">×{record.attempts}</span>
                ) : null}
              </div>
              {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
            </div>
          );
        }
      },
      {
        id: "error",
        header: t("error"),
        accessorFn: (record) => record.error_message ?? "",
        enableSorting: false,
        cell: ({ row }) => {
          const summary = getErrorSummary(row.original);
          if (!summary) return null;
          return (
            <details className="group/disclosure max-w-[28rem]">
              <summary className={cn(
                "inline-flex cursor-pointer list-none items-center gap-1 rounded text-xs focus-visible:outline-2 focus-visible:outline-offset-2",
                row.original.status === "failed" ? "text-danger" : "text-muted-foreground"
              )}>
                <ChevronDown className={cn(disclosureChevronClass, "size-3")} aria-hidden />
                {"code" in summary ? tx(`opError.${summary.code}`) : summary.message}
              </summary>
              <pre
                tabIndex={0}
                className="mt-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/20 p-2 text-xs text-muted-foreground"
              >
                {getErrorDetail(row.original)}
              </pre>
            </details>
          );
        }
      },
      {
        id: "created_at",
        header: t("uploaded"),
        accessorFn: (record) => record.created_at,
        size: 128,
        enableSorting: false,
        meta: columnMeta<LogProcessingRecord>({ align: "right", numeric: true }),
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatLogTime(format, row.original.created_at)}
          </span>
        )
      },
      {
        id: "duration",
        header: t("duration"),
        accessorFn: (record) => formatDuration(record) ?? "",
        size: 88,
        enableSorting: false,
        meta: columnMeta<LogProcessingRecord>({ align: "right", numeric: true }),
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">{formatDuration(row.original)}</span>
        )
      },
      // Pending jobs can be requeued; an actively processing job cannot be retried.
      createKebabColumn<LogProcessingRecord>(
        (record) => [
          {
            label: getRetryKind(record) === "reparse"
              ? tx("reparseLog")
              : record.status === "failed" ? tx("retryLog") : tx("requeueLog"),
            icon: RotateCcw,
            hidden: !isRetryable(record),
            onSelect: () => {
              if (isRetryable(record)) onRetry([record]);
            }
          },
          // One entry for both ways a log reaches a game: the dialog binds with an explicit team map when the
          // job kept its document teams (not gated by the ordinary-retry refusal: a hint without a game is not
          // an observation), and otherwise re-files it through a hint. A processed log already filed its match.
          // The workspace-wide console holds no encounter list: its dialog picks a tournament first.
          {
            label: tx("attachToGame"),
            icon: Link2,
            hidden:
              noEncounters ||
              !(
                canBindExplicitly(record) ||
                (record.status !== "done" && record.status !== "processing" && getRetryRefusal(record) == null)
              ),
            onSelect: () => onAttach(record)
          }
        ],
        { rowLabel: (record) => getLogFileName(record.filename) }
      )
    ],
    [noEncounters, onRetry, onAttach, format, t, tx]
  );
}
