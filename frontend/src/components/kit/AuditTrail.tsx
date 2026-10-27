"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChevronDown, Lock } from "lucide-react";
import { useFormatter } from "@/lib/datetime/client";

import {
  AUDIT_TRAIL_PAGE_SIZE,
  auditDiffRows,
  auditEntityLabel,
  auditHistoryStartQuery,
  auditSourceLabel,
  auditTrailQueryKey,
  describeAuditAction,
  formatAuditActor,
  formatAuditDate,
  formatAuditTimestamp,
  hasUncapturedBefore,
  isMachineActor,
  type AuditDiffKind,
  type AuditDiffRow,
  type AuditTrailScope,
  useAuditTranslator
} from "@/components/kit/audit-log";
import { Button } from "@/components/ui/button";
import { triggerChevronClass } from "@/components/ui/chevron";
import { ApiError } from "@/lib/api/error";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { AuditLogRead } from "@/types/admin.types";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

/**
 * Per-line marker for the field diff.
 *
 * The symbol and the screen-reader word carry the difference; the colour only
 * reinforces it. Colour-only encoding is out of bounds — `docs/design-book.md`
 * ("никогда color-only") — and this diff is read on exactly the occasions
 * someone is checking whether a value was raised or lowered. `word` is a
 * `kitAudit.audit.diffLine` key.
 */
const DIFF_LINES: Record<
  AuditDiffKind,
  Array<{ side: "before" | "after"; symbol: string; word: "added" | "removed" | "set" | "was" | "now"; className: string }>
> = {
  added: [{ side: "after", symbol: "+", word: "added", className: "text-success" }],
  removed: [{ side: "before", symbol: "\u2212", word: "removed", className: "text-danger" }],
  set: [{ side: "after", symbol: "+", word: "set", className: "text-info" }],
  changed: [
    { side: "before", symbol: "\u2212", word: "was", className: "text-danger" },
    { side: "after", symbol: "+", word: "now", className: "text-success" },
  ],
};

/**
 * One level of the diff; nested values recurse under an indent. A nested row's
 * kind word shows only where it differs from its parent's — a role added inside
 * a changed list — since repeating "changed" at every level says nothing.
 */
function AuditDiffList({
  rows,
  parentKind,
}: Readonly<{ rows: AuditDiffRow[]; parentKind?: AuditDiffKind }>) {
  const t = useTranslations("kitAudit.audit");
  return (
    <dl className="space-y-1.5">
      {rows.map((row) => (
        <div key={row.field} className="grid gap-0.5">
          <dt className="flex items-baseline gap-1.5">
            <span className="font-mono text-xs text-foreground">{row.field}</span>
            {row.kind === parentKind ? null : (
              <span className={eyebrowClass("muted")}>{t(`diffKind.${row.kind}`)}</span>
            )}
          </dt>
          {row.children ? (
            <dd className="border-l border-border/60 pl-2.5">
              <AuditDiffList rows={row.children} parentKind={row.kind} />
            </dd>
          ) : (
            <dd className="grid gap-0.5">
              {DIFF_LINES[row.kind].map((line) => (
                <span key={line.side} className="flex items-baseline gap-1.5 font-mono text-xs">
                  <span aria-hidden className={cn("w-3 shrink-0 text-center", line.className)}>
                    {line.symbol}
                  </span>
                  <span className="sr-only">{t(`diffLine.${line.word}`)}:</span>
                  <span className="min-w-0 break-all text-muted-foreground">
                    {line.side === "before" ? row.before : row.after}
                  </span>
                </span>
              ))}
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

/**
 * Field-level diff of a row's `before_json` / `after_json`.
 *
 * Writers assemble both sides from named domain fields rather than capturing the
 * request, so a field missing from a populated side is a fact worth its own
 * wording instead of a hole in the capture.
 */
export function AuditFieldDiff({
  before,
  after,
}: Readonly<{
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}>) {
  const t = useTranslations("kitAudit.audit");
  const auditT = useAuditTranslator();
  const rows = auditDiffRows(before, after, auditT);

  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        {t("noFieldChanges")}
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      <AuditDiffList rows={rows} />
      {hasUncapturedBefore(rows) ? (
        // Said once, rather than dressed up per field as "added": a
        // service-backed update stages the requested values with no before-image,
        // so the previous values are genuinely not on record. Anyone comparing
        // two entries needs to know that before drawing a conclusion from them.
        <p className="text-xs text-muted-foreground">
          {t("onlySetValues")}
        </p>
      ) : null}
    </div>
  );
}

/** Everything the compact line leaves out, shown only when asked for. */
function AuditEntryDetail({ entry }: Readonly<{ entry: AuditLogRead }>) {
  const t = useTranslations("kitAudit.audit");
  const auditT = useAuditTranslator();
  const meta: Array<{ label: string; value: string }> = [
    { label: t("source"), value: auditSourceLabel(entry.source, auditT) },
    ...(entry.ip_address ? [{ label: "IP", value: entry.ip_address }] : []),
    ...(entry.user_agent ? [{ label: t("device"), value: entry.user_agent }] : []),
    ...(entry.correlation_id ? [{ label: t("correlation"), value: entry.correlation_id }] : []),
  ];

  return (
    <div className="mt-2 space-y-2 rounded-md border border-border/50 bg-muted/20 p-2.5">
      {entry.reason ? (
        <p className="text-xs text-foreground">
          <span className="text-muted-foreground">{t("reason")} </span>
          {entry.reason}
        </p>
      ) : null}

      <AuditFieldDiff before={entry.before_json} after={entry.after_json} />

      <dl className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border/40 pt-2 text-xs text-muted-foreground">
        {meta.map((item) => (
          <div key={item.label} className="flex min-w-0 items-baseline gap-1">
            <dt>{item.label}:</dt>
            <dd className="min-w-0 truncate font-mono text-foreground/80" title={item.value}>
              {item.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function AuditEntry({ entry }: Readonly<{ entry: AuditLogRead }>) {
  const t = useTranslations("kitAudit.audit");
  const auditT = useAuditTranslator();
  const [open, setOpen] = useState(false);
  const format = useFormatter();
  const action = describeAuditAction(entry.action, auditT);
  const hasDetail =
    entry.before_json != null ||
    entry.after_json != null ||
    entry.reason != null ||
    entry.ip_address != null ||
    entry.correlation_id != null;

  return (
    <li className="py-2">
      {/* Two columns, not one wrapping row. In the 576px drawer a long actor
          name used to push "Details" onto a line of its own on some entries and
          not others, so the list read as ragged rows of unequal height. The
          disclosure now keeps one trailing edge and the actor truncates into it. */}
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <time
              dateTime={entry.created_at}
              className="shrink-0 tabular-nums text-xs text-muted-foreground"
            >
              {formatAuditTimestamp(format, entry.created_at)}
            </time>
            <span
              className="text-sm font-medium text-foreground"
              title={action.recognised ? undefined : action.raw}
            >
              {action.label}
            </span>
            {action.recognised ? null : (
              // A phrase we had to derive from the string must not pass for a
              // curated one: the raw action stays readable in the tooltip.
              <span className="text-xs text-muted-foreground" title={action.raw}>
                {t("unrecognised")}
              </span>
            )}
          </div>
          {/* `title` keeps the full actor readable once it truncates. */}
          <p
            className="mt-0.5 truncate text-xs text-muted-foreground"
            title={formatAuditActor(entry, auditT)}
          >
            {t.rich("byActor", {
              actor: (chunks) => (
                <span className={cn("text-foreground", isMachineActor(entry) && "italic")}>
                  {chunks}
                </span>
              ),
              actorName: formatAuditActor(entry, auditT)
            })}
          </p>
        </div>

        {hasDetail ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={open}
            onClick={() => setOpen((current) => !current)}
            className="group/trigger shrink-0 gap-1 text-muted-foreground"
          >
            {open ? t("hideDetails") : t("details")}
            <ChevronDown aria-hidden className={triggerChevronClass} />
          </Button>
        ) : null}
      </div>

      {open ? <AuditEntryDetail entry={entry} /> : null}
    </li>
  );
}

/** Three entry-shaped rows while the trail (or its start date) loads. */
const TRAIL_SKELETON = (
  <div aria-busy="true" className="space-y-3">
    {[0, 1, 2].map((row) => (
      <div key={row} className="space-y-1.5">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-3 w-1/3" />
      </div>
    ))}
  </div>
);

/**
 * "Who changed this" for a single entity.
 *
 * Same endpoint as the feed (FR6), scoped to this entity. A compact list rather
 * than a table: one entity's history is read top-to-bottom, not sorted and
 * filtered — that is what the feed at `/admin/audit` is for. The chrome around
 * this list belongs to `AuditTrailSheet`, which is the only thing that mounts it.
 */
export function AuditTrailBody({ scope }: Readonly<{ scope: AuditTrailScope }>) {
  const t = useTranslations("kitAudit.audit");
  const auditT = useAuditTranslator();
  const entityNoun = (auditEntityLabel(scope.entityType, auditT) ?? t("record")).toLowerCase();
  const format = useFormatter();

  const trailQuery = useInfiniteQuery({
    queryKey: auditTrailQueryKey(scope),
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      adminService.listAudit({
        workspace_id: scope.workspaceId,
        entity_type: scope.entityType,
        entity_id: scope.entityId,
        page: pageParam,
        per_page: AUDIT_TRAIL_PAGE_SIZE,
      }),
    // An empty page ends the trail even when `total` still claims more: rows
    // deleted between requests would otherwise leave a "Load more" that can
    // never advance.
    getNextPageParam: (lastPage, pages) => {
      if (lastPage.results.length === 0) return undefined;
      const loaded = pages.reduce((sum, page) => sum + page.results.length, 0);
      return loaded < lastPage.total ? pages.length + 1 : undefined;
    },
    retry: false,
  });

  const entries = trailQuery.data?.pages.flatMap((page) => page.results) ?? [];
  const total = trailQuery.data?.pages[0]?.total ?? 0;

  // Only asked for once the trail comes back empty, because that is the only
  // case whose wording depends on it.
  const historyStart = useQuery({
    ...auditHistoryStartQuery({ workspaceId: scope.workspaceId }),
    enabled: trailQuery.isSuccess && entries.length === 0,
    retry: false,
  });

  if (trailQuery.isLoading) {
    return TRAIL_SKELETON;
  }

  if (trailQuery.isError) {
    return renderTrailError(trailQuery.error, entityNoun, (key, values) => t(key as never, values as never));
  }

  // The three empty states below are distinct claims about history, so they are
  // never collapsed into one.
  if (entries.length === 0) {
    if (historyStart.isLoading) {
      return TRAIL_SKELETON;
    }
    if (historyStart.data) {
      // Empty state 1 of 3: the journal runs, this entity is simply older than
      // it. There is no backfill, so for the first months this is the common
      // case — and saying only "no changes" here would assert that nobody
      // touched the record, which is the one claim the audit log exists to be
      // able to make truthfully.
      return (
        <p className="text-sm text-muted-foreground">
          {t.rich("noChangesWithStart", {
            entity: entityNoun,
            date: (chunks) => <span className="text-foreground">{chunks}</span>,
            dateValue: formatAuditDate(format, historyStart.data)
          })}
        </p>
      );
    }
    // Empty state 2 of 3: nothing anywhere in this workspace yet, so there is
    // no start date to quote and no claim to make about this entity.
    return (
      <p className="text-sm text-muted-foreground">
        {t("noEntries")}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-border/30">
        {entries.map((entry) => (
          <AuditEntry key={entry.id} entry={entry} />
        ))}
      </ul>

      {/* Rendered from the first page onwards whenever the trail is longer than
          one page, so the status region exists before the first "Load more"
          rather than being inserted by it — a region that appears with its own
          text is announced unreliably. */}
      {total > AUDIT_TRAIL_PAGE_SIZE ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border/40 pt-3">
          <p role="status" className="text-xs tabular-nums text-muted-foreground">
            {t("showing", { shown: entries.length, total: t("changeCount", { count: total }) })}
          </p>
          {trailQuery.hasNextPage ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="ms-auto"
              disabled={trailQuery.isFetchingNextPage}
              onClick={() => trailQuery.fetchNextPage()}
            >
              {trailQuery.isFetchingNextPage ? (
                <Spinner className="size-3.5" />
              ) : null}
              {t("loadMore")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Full templated strings, so the singular is not "1 changes". */
/**
 * Empty state 3 of 3 lives here: a refusal is not an absence of history.
 *
 * `entity_type` + `entity_id` filter INSIDE the reader's workspace scope rather
 * than reaching around it, so pointing a trail at another tenant's entity is a
 * refusal or an empty page — never their history. Reading that refusal as "no
 * changes" would be the same false reassurance the empty states above avoid.
 */
function renderTrailError(error: unknown, entityNoun: string, t: (key: string, values?: Record<string, unknown>) => string) {
  const status = error instanceof ApiError ? error.status : 0;

  if (status === 401 || status === 403) {
    return (
      <p className="flex items-start gap-2 text-sm text-muted-foreground">
        <Lock aria-hidden className="mt-0.5 size-4 shrink-0" />
        <span>
          {t("accessHidden", { entity: entityNoun })}
        </span>
      </p>
    );
  }

  return (
    <p className="text-sm text-danger">
      {error instanceof Error && error.message
        ? t("loadFailedWithReason", { reason: error.message })
        : t("loadFailedWithPeriod")}
    </p>
  );
}
