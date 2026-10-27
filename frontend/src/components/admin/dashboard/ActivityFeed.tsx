"use client";

import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNow, useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import {
  auditEntityLabel,
  describeAuditAction,
  formatAuditActor,
  formatAuditTarget,
  formatAuditTimestamp,
  useAuditTranslator
} from "@/components/kit/audit-log";
import { formatRelative } from "@/components/kit/format-time";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import adminService from "@/services/admin.service";
import { Block, BlockError } from "./Block";
import { auditEntityHref, dayLabel, groupAuditActivity, groupByDay } from "./model";

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
/** Staff actions only: scheduler and system rows are the platform talking to itself. */
const STAFF_SOURCES = "admin,api_key,discord,challonge";

/**
 * What the rest of the staff did this week, own actions hidden by default.
 * One page of 50 rows is merged into at most 15 runs of one actor doing one
 * thing; a run about one entity links to it.
 */
export function ActivityFeed({ workspaceId, className }: Readonly<{ workspaceId: number; className?: string }>) {
  const t = useTranslations("adminShell.dashboard");
  const tAudit = useAuditTranslator();
  const format = useFormatter();
  const userId = useAuthProfile().user?.id ?? null;
  const toggleId = useId();
  const [includeMine, setIncludeMine] = useState(false);
  const excludeActorId = includeMine ? null : userId;
  const title = t("activity");
  const now = useNow();
  const words = { today: t("dayToday"), tomorrow: t("dayTomorrow"), yesterday: t("dayYesterday") };

  const query = useQuery({
    queryKey: adminQueryKeys.dashboardActivity(workspaceId, excludeActorId),
    queryFn: () =>
      adminService.listAudit({
        per_page: 50,
        sort: "created_at",
        order: "desc",
        since: new Date(Date.now() - WEEK_MS).toISOString(),
        source: STAFF_SOURCES,
        exclude_actor_user_id: excludeActorId
      })
  });

  const groups = query.data ? groupAuditActivity(query.data.results) : undefined;

  return (
    <Block
      title={title}
      className={className}
      description={t("activityDescription")}
      action={
        <div className="flex shrink-0 items-center gap-2">
          <Switch id={toggleId} checked={includeMine} onCheckedChange={setIncludeMine} />
          <Label htmlFor={toggleId} className="text-xs font-normal text-muted-foreground">
            {t("includeMine")}
          </Label>
        </div>
      }
    >
      {query.isError ? (
        <BlockError title={title} onRetry={() => void query.refetch()} />
      ) : !groups ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-10 rounded-md" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("activityEmpty")}</p>
      ) : (
        <div className="flex flex-col gap-4">
          {groupByDay(groups, (group) => group.head.created_at, format).map((day) => (
            <div key={day.key}>
              <Eyebrow as="h3" tone="muted">
                {dayLabel(format, day.date, now, words)}
              </Eyebrow>
              <ul className="mt-1 divide-y divide-border/50">
                {day.items.map((group) => {
                  const { head } = group;
                  const href = group.sameEntity ? auditEntityHref(head) : null;
                  const subject = [
                    group.sameEntity ? formatAuditTarget(head, tAudit) : auditEntityLabel(head.entity_type, tAudit),
                    group.count > 1 ? t("activityCount", { count: group.count }) : null
                  ]
                    .filter(Boolean)
                    .join(" · ");
                  const body = (
                    <>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-foreground">
                          <span className="font-medium">{formatAuditActor(head, tAudit)}</span>
                          {" · "}
                          {describeAuditAction(head.action, tAudit).label}
                        </span>
                        {subject ? (
                          <span className="block truncate text-xs text-muted-foreground">{subject}</span>
                        ) : null}
                      </span>
                      <time
                        dateTime={head.created_at}
                        title={formatAuditTimestamp(format, head.created_at)}
                        className="shrink-0 text-xs tabular-nums text-muted-foreground"
                      >
                        {formatRelative(format, head.created_at)}
                      </time>
                    </>
                  );
                  // Rows bleed to the card edge so the hover fill spans the card.
                  const shared = "-mx-6 flex items-start gap-3 px-6 py-2.5";
                  return (
                    <li key={head.id}>
                      {href ? (
                        <HoverPrefetchLink
                          href={href}
                          className={`${shared} transition-colors hover:bg-accent/30 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring`}
                        >
                          {body}
                        </HoverPrefetchLink>
                      ) : (
                        <div className={shared}>{body}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Block>
  );
}
