"use client";

import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleSlash,
  HelpCircle,
  type LucideIcon
} from "lucide-react";

import { StatusIcon } from "@/components/admin/StatusIcon";
import {
  PROVIDER_LABELS,
  StateBadge,
  useSubscriptionLabels
} from "@/components/admin/collectors/subscription-shared";
import { collapseCheckRuns } from "@/components/admin/people/check-runs";
import { EmptyNote, LoadErrorNote } from "@/components/kit/EmptyNote";
import { SettingGroup } from "@/components/kit/SettingRow";
import { formatDate, formatRelative } from "@/components/kit/format-time";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { SubscriptionCheckLogRow } from "@/types/admin.types";

const STATE_ICON: Record<string, { icon: LucideIcon; variant: "success" | "warning" | "info" | "destructive" }> = {
  active: { icon: CircleCheck, variant: "success" },
  inactive: { icon: CircleSlash, variant: "warning" },
  unknown: { icon: HelpCircle, variant: "info" },
  error: { icon: CircleAlert, variant: "destructive" }
};

const ROW_CLASS = "flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5";

/** One check state as a toned glyph, its word as the tooltip: for lines and logs, not tables. */
export function SubscriptionStateIcon({ state }: Readonly<{ state: string }>) {
  const labels = useSubscriptionLabels();
  const meta = STATE_ICON[state] ?? STATE_ICON.unknown;
  return <StatusIcon icon={meta.icon} label={labels.state[state] ?? state} variant={meta.variant} />;
}

/** Skeleton rows on the list's own hairlines, so nothing reflows when data lands. */
function RowsSkeleton({ rows }: Readonly<{ rows: number }>) {
  return (
    <ul aria-hidden className="divide-y divide-border/60">
      {Array.from({ length: rows }, (_, index) => (
        <li key={index} className="py-2.5">
          <Skeleton className="h-6 w-full max-w-xl" />
        </li>
      ))}
    </ul>
  );
}

// ─── Per-player check timeline ───────────────────────────────────────────────

/**
 * One run of identical checks: a plain row for a single check, an expanding
 * row (DESIGN.md §8) listing every check's time for a run of several.
 */
function CheckRunRow({ run }: Readonly<{ run: SubscriptionCheckLogRow[] }>) {
  const t = useTranslations("adminPeople.subscription");
  const format = useFormatter();
  const labels = useSubscriptionLabels();
  const latest = run[0];
  const oldest = run[run.length - 1];
  const folded = run.length > 1;
  const reason = latest.error ?? (latest.reason ? labels.reason(latest.reason) : null);
  const meta = [
    latest.tier_label ?? (latest.tier_rank != null ? t("tierValue", { rank: latest.tier_rank }) : null),
    folded ? t("checks", { count: run.length }) : null,
    labels.source[latest.source] ?? latest.source
  ]
    .filter(Boolean)
    .join(" · ");
  const when = (iso: string) => (
    <time dateTime={iso} title={formatDate(format, iso)}>
      {formatRelative(format, iso)}
    </time>
  );

  const line = (
    <>
      <SubscriptionStateIcon state={latest.state} />
      <span className="text-body font-medium">{PROVIDER_LABELS[latest.provider] ?? latest.provider}</span>
      <span className="text-caption tabular-nums text-muted-foreground">{meta}</span>
      {folded ? (
        <ChevronDown
          aria-hidden
          className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180 motion-reduce:transition-none"
        />
      ) : null}
      {reason ? (
        <span className={cn("text-caption", latest.error ? "text-danger" : "text-muted-foreground")}>
          {reason}
        </span>
      ) : null}
      <span className="ml-auto text-caption tabular-nums text-muted-foreground">
        {folded ? <>{when(oldest.created_at)} – </> : null}
        {when(latest.created_at)}
      </span>
    </>
  );

  if (!folded) return <li className={ROW_CLASS}>{line}</li>;
  return (
    <li>
      <details className="group">
        <summary
          className={cn(
            ROW_CLASS,
            "cursor-pointer list-none rounded-md transition-colors hover:bg-[color:var(--aqt-overlay-2)] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring motion-reduce:transition-none [&::-webkit-details-marker]:hidden"
          )}
        >
          {line}
        </summary>
        <ol className="flex flex-wrap gap-x-3 gap-y-1 pb-2.5 pl-7 text-caption tabular-nums text-muted-foreground">
          {run.map((row) => (
            <li key={row.id}>{when(row.created_at)}</li>
          ))}
        </ol>
      </details>
    </li>
  );
}

/**
 * That player's own slice of the check log, newest first, runs of identical
 * results folded into one row.
 *
 * The counterpart of `RankHistory` on the rank tab: the entitlement table only
 * holds the latest verdict, so this is the only place a flap ("active on Monday,
 * inactive on Friday, active again after a re-subscribe") is visible at all.
 */
function PlayerCheckTimeline({ userId }: Readonly<{ userId: number }>) {
  const t = useTranslations("adminPeople.subscription");
  // Scoped server-side to the injected workspace; see `admin.service.ts`.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const query = useQuery({
    queryKey: adminQueryKeys.subscriptionsUserHistory(workspaceId, userId),
    queryFn: () => adminService.getSubscriptionCheckLog({ user_id: userId, limit: 100 })
  });
  const runs = collapseCheckRuns(query.data ?? []);

  return (
    <SettingGroup id="check-history" title={t("history")}>
      {query.isLoading ? (
        <RowsSkeleton rows={4} />
      ) : query.isError ? (
        <LoadErrorNote onRetry={() => void query.refetch()} />
      ) : runs.length === 0 ? (
        <EmptyNote>{t("emptyHistory")}</EmptyNote>
      ) : (
        <ol className="divide-y divide-border/60">
          {runs.map((run) => (
            <CheckRunRow key={run[0].id} run={run} />
          ))}
        </ol>
      )}
    </SettingGroup>
  );
}

// ─── Per-player entitlements ─────────────────────────────────────────────────

/**
 * One player's subscription verdicts, with the re-check controls, then the log
 * that led to them.
 *
 * Moved out of the subscription collector screen: a person's entitlements
 * belong on their hub (People › Subscriptions).
 */
export function SubscriptionPlayerPanel({
  userId,
  label
}: Readonly<{ userId: number; label: string }>) {
  const t = useTranslations("adminPeople.subscription");
  const format = useFormatter();
  const labels = useSubscriptionLabels();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const statusQuery = useQuery({
    queryKey: adminQueryKeys.subscriptionsCollection(workspaceId, userId),
    queryFn: () => adminService.getSubscriptionCollectionStatus(userId)
  });
  const rows = statusQuery.data ?? [];

  const triggerMutation = useMutation({
    mutationFn: (providers: string[] | null) =>
      adminService.triggerSubscriptionCollection({ user_id: userId, providers }),
    onSuccess: (result) => {
      notify.success(
        result.checked === 0
          ? t("nothingToCheck")
          : t("checked", { count: result.checked })
      );
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.subscriptions() });
    },
    onError: (error) =>
      notify.apiError(error, { title: t("recheckError") })
  });

  return (
    // One provider per workspace: a full-width row put «Проверить» a screen away from what it checks.
    <div className="max-w-3xl space-y-4">
      <SettingGroup
        id="entitlements"
        title={t("entitlements")}
        actions={
          <Button
            size="sm"
            disabled={triggerMutation.isPending}
            onClick={() => triggerMutation.mutate(null)}
          >
            {triggerMutation.isPending ? <Spinner className="mr-1.5 size-3.5" /> : null}
            {t("recheckAll")}
          </Button>
        }
      >
        {statusQuery.isLoading ? (
          <RowsSkeleton rows={1} />
        ) : statusQuery.isError ? (
          <LoadErrorNote onRetry={() => void statusQuery.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyNote>{t("empty")}</EmptyNote>
        ) : (
          <ul className="divide-y divide-border/60">
            {rows.map((row) => {
              const provider = PROVIDER_LABELS[row.provider] ?? row.provider;
              const tier =
                row.tier_label ?? (row.tier_rank != null ? t("tierValue", { rank: row.tier_rank }) : null);
              return (
                <li key={`${row.workspace_id}-${row.provider}`} className={ROW_CLASS}>
                  <span className="text-body font-medium">
                    {provider}
                    {row.workspace_name ? (
                      <span className="font-normal text-muted-foreground"> · {row.workspace_name}</span>
                    ) : null}
                  </span>
                  {/* Active is the norm: only a verdict that wants attention gets a pill. */}
                  {row.state === "active" ? null : <StateBadge state={row.state} />}
                  {tier || row.checked_at ? (
                    <span className="text-caption tabular-nums text-muted-foreground">
                      {tier}
                      {tier && row.checked_at ? " · " : null}
                      {row.checked_at ? (
                        <time dateTime={row.checked_at} title={formatDate(format, row.checked_at)}>
                          {t("checkedAgo", { time: formatRelative(format, row.checked_at) })}
                        </time>
                      ) : null}
                    </span>
                  ) : null}
                  {row.reason ? (
                    <span className="text-caption text-muted-foreground">{labels.reason(row.reason)}</span>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    disabled={triggerMutation.isPending}
                    onClick={() => triggerMutation.mutate([row.provider])}
                    aria-label={t("recheckFor", { provider, label })}
                  >
                    {t("recheck")}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </SettingGroup>

      <PlayerCheckTimeline userId={userId} />
    </div>
  );
}
