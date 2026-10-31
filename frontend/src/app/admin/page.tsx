"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus } from "lucide-react";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { ActivityFeed } from "@/components/admin/dashboard/ActivityFeed";
import { Backlog } from "@/components/admin/dashboard/Backlog";
import { BLOCK_TITLE, BlockError } from "@/components/admin/dashboard/Block";
import { DashboardRealtime } from "@/components/admin/dashboard/DashboardRealtime";
import { PhaseCards, PhaseCardsSkeleton } from "@/components/admin/dashboard/PhaseCards";
import { PlatformHealth } from "@/components/admin/dashboard/PlatformHealth";
import { Timeline } from "@/components/admin/dashboard/Timeline";
import { Trends } from "@/components/admin/dashboard/Trends";
import { WorkQueue } from "@/components/admin/dashboard/WorkQueue";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useCurrentWorkspaceId } from "@/hooks/useCurrentWorkspace";
import { usePermissions, type AppPermission } from "@/hooks/usePermissions";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";

/** `GET /api/v1/admin/dashboard` answers anyone holding one of these in the workspace. */
const DASHBOARD_PERMISSIONS: AppPermission[] = [
  "tournament.read",
  "team.read",
  "match.read",
  "user.read",
  "achievement.read"
];

/**
 * The organizer's home: one card per tournament in a live phase, what the next
 * seven days hold, what to do now, what the staff did, and how the last
 * tournaments went. Every block loads, fails and hides on its own; a block the
 * reader's role cannot see is absent, never zero.
 */
export default function AdminDashboard() {
  const t = useTranslations("adminShell.dashboard");
  const { canAccessPermission, isSuperuser } = usePermissions();
  const workspaceId = useCurrentWorkspaceId();
  const { user } = useAuthProfile();
  const hour = new Date().getHours();
  const greetingPeriod = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";

  const canReadDashboard = DASHBOARD_PERMISSIONS.some((permission) => canAccessPermission(permission, workspaceId));
  const canReadTournaments = canAccessPermission("tournament.read", workspaceId);
  const canReadAudit = canAccessPermission("audit.read", workspaceId);
  const canCreateTournaments = canAccessPermission("tournament.create", workspaceId);

  const dashboardQuery = useQuery({
    queryKey: adminQueryKeys.dashboard(workspaceId),
    queryFn: () => adminService.getDashboard(),
    enabled: workspaceId != null && canReadDashboard
  });

  const createButton = (
    <Button asChild size="sm">
      <Link href="/admin/tournaments?create=1">
        <Plus className="size-3.5" aria-hidden />
        {t("createTournament")}
      </Link>
    </Button>
  );
  // The breadcrumb already names the page, so the h1 stays in the outline only
  // and the visible line is the greeting, set in the display face.
  const header = (
    <AdminPageHeader
      title={t("dashboardTitle")}
      titleHidden
      meta={
        <p className="min-w-0 font-display text-title font-semibold text-foreground sm:text-headline">
          {t("greeting", { period: greetingPeriod, username: user?.username ?? t("defaultAdmin") })}
        </p>
      }
      actions={workspaceId != null && canCreateTournaments ? createButton : null}
    />
  );

  // "All workspaces": nothing here is workspace-wide except platform health.
  if (workspaceId == null) {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <EmptyNote className="text-center">{t("pickWorkspace")}</EmptyNote>
        {isSuperuser ? <PlatformHealth workspaceId={null} /> : null}
      </div>
    );
  }

  const data = dashboardQuery.data;
  // A failed background refetch keeps the last good data on screen.
  const failed = dashboardQuery.isError && data === undefined;
  const retry = () => void dashboardQuery.refetch();
  const cards = data?.tournaments;
  // Timeline and queue rows carry their tournament's game and hidden flag through its card.
  const cardOf = new Map(data?.tournaments.map((card) => [card.id, card] as const));
  // `null` is no `tournament.read`: the block is absent, not loading.
  const timelineHidden = data?.timeline === null;
  const betweenTournaments = data?.tournaments.length === 0;
  // In the live phase the queue is what an organizer opens the page for.
  const liveFirst = cards?.some((card) => card.phase === "live") ?? false;
  // No queue between tournaments; without a queue and an activity feed the
  // left column takes the full width.
  const showQueue = canReadDashboard && !betweenTournaments;
  const hasRail = showQueue || canReadAudit;

  return (
    <div className="flex flex-col gap-4">
      {header}
      {!canReadDashboard && !canReadAudit && !isSuperuser ? <EmptyNote>{t("noAccess")}</EmptyNote> : null}
      {canReadDashboard ? (
        <DashboardRealtime workspaceId={workspaceId} tournamentIds={data?.tournaments.map((card) => card.id) ?? []} />
      ) : null}

      {/* At `xl`: a main column ("work", the tournament cards first) and a
          right rail ("attention": to do, activity), both from the top. Below
          `xl` both column wrappers are `contents`, so every block is a sibling
          in one column and `order` sorts them: cards, queue, timeline, trends,
          activity, backlog, health; on phones the queue leads in the live phase.
          `minmax(0, …)`: a bare `fr` track grows to its widest child's
          min-content, pushing the rail off-screen. */}
      <div className="flex flex-col gap-4 xl:grid xl:grid-cols-[minmax(0,7fr)_minmax(0,3fr)] xl:items-start">
        <div className={cn("contents xl:flex xl:flex-col xl:gap-4", !hasRail && "xl:col-span-2")}>
          {canReadDashboard ? (
            <div className="max-xl:order-1">
              {failed ? (
                <BlockError title={t("cardsTitle")} onRetry={retry} />
              ) : !cards ? (
                <PhaseCardsSkeleton />
              ) : betweenTournaments ? (
                // "Create tournament" lives in the header: one CTA per intent.
                <NoCards />
              ) : (
                <PhaseCards cards={cards} />
              )}
            </div>
          ) : null}
          {canReadTournaments && !timelineHidden && !betweenTournaments ? (
            <Timeline
              events={data?.timeline ?? undefined}
              cardOf={cardOf}
              failed={failed}
              onRetry={retry}
              className="max-xl:order-3"
            />
          ) : null}
          {canReadTournaments ? <Trends workspaceId={workspaceId} className="max-xl:order-4" /> : null}
          {canReadDashboard ? (
            <Backlog backlog={data?.backlog} failed={failed} onRetry={retry} className="max-xl:order-6" />
          ) : null}
          {isSuperuser ? <PlatformHealth workspaceId={workspaceId} className="max-xl:order-7" /> : null}
        </div>

        {hasRail ? (
          // `contain: size`: the rail adds no height to the row, so the main
          // column alone sets it; `self-stretch` then fills it and the
          // activity feed scrolls inside instead of lengthening the page.
          <div className="contents xl:flex xl:flex-col xl:gap-4 xl:self-stretch xl:[contain:size]">
            {showQueue ? (
              <WorkQueue
                issues={data?.issues}
                cardOf={cardOf}
                failed={failed}
                onRetry={retry}
                className={cn("max-xl:order-2", liveFirst && "max-md:order-first")}
              />
            ) : null}
            {canReadAudit ? <ActivityFeed workspaceId={workspaceId} className="max-xl:order-5" /> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** The cards row between tournaments: one line and the way to the full list. */
function NoCards() {
  const t = useTranslations("adminShell.dashboard");
  return (
    <Card className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 px-6 py-4">
      <div className="min-w-0">
        <h2 className={BLOCK_TITLE}>{t("betweenTitle")}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t("betweenBody")}</p>
      </div>
      <Button asChild variant="outline" size="sm">
        <Link href="/admin/tournaments">
          {t("allTournaments")}
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </Button>
    </Card>
  );
}
