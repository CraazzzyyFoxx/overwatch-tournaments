"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { rankHealthDot } from "@/components/admin/collectors/rank-shared";
import { diagnoseStreamHealth } from "@/components/admin/collectors/stream-shared";
import { subscriptionHealthDot } from "@/components/admin/collectors/subscription-shared";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { usePermissions } from "@/hooks/usePermissions";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { adminQueryKeys } from "@/lib/admin/query-keys";

const COLLECTORS = ["rank", "subscriptions", "streams"] as const;

/**
 * The collectors hub (F14): one screen for three background pollers.
 *
 * Navigation and chrome only — each collector page owns its own slots, data and
 * polling. The tab bar carries a health dot per collector, which is the whole
 * point of putting them on one screen: an operator who came for the rank worker
 * sees that the subscription one is failing without visiting it.
 *
 * The dot queries address the same keys the dashboards do, so mounting this bar
 * costs no extra request for the collector being looked at — TanStack dedupes
 * the observers. The other two cost one read each, which is what a health
 * marker is for. Each is gated on the permission its own route requires, so a
 * `rank.read`-only holder never fires a request that would 403.
 */
export default function CollectorsLayout({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const t = useTranslations("collectors.hub");
  const tHealth = useTranslations("collectors.common.health");
  const tStream = useTranslations("collectors.streams.status");
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const canReadRank = canAccessPermission("rank.read");
  const canReadSubscriptions = canAccessPermission("subscription.read");
  // GLOBAL, not workspace-scoped: one poller, one Redis key, and
  // `adminRoutePermissions` gates `/admin/collectors/streams` the same way.
  const canReadStreams = canAccessPermission("stream.read", null);

  const rankQuery = useQuery({
    queryKey: adminQueryKeys.rankStats(workspaceId),
    queryFn: () => adminService.getRankCollectionStats(),
    enabled: canReadRank
  });
  const subscriptionQuery = useQuery({
    queryKey: adminQueryKeys.subscriptionsStats(workspaceId),
    queryFn: () => adminService.getSubscriptionCollectionStats(),
    enabled: canReadSubscriptions
  });
  const streamQuery = useQuery({
    queryKey: adminQueryKeys.streamsHealth(),
    queryFn: () => adminService.getStreamPollHealth(),
    enabled: canReadStreams
  });

  const active = COLLECTORS.find((key) => pathname.startsWith(`/admin/collectors/${key}`));

  // The word, not just the colour: `LinkTabs` renders it `sr-only`.
  const rankHealth = rankQuery.data ? rankHealthDot(rankQuery.data) : undefined;
  const subscriptionHealth = subscriptionQuery.data
    ? subscriptionHealthDot(subscriptionQuery.data)
    : undefined;
  const streamHealth = streamQuery.data ? diagnoseStreamHealth(streamQuery.data) : undefined;

  const items: LinkTabItem[] = [
    {
      key: "rank",
      label: t("tabs.rank"),
      href: "/admin/collectors/rank",
      hidden: !canReadRank,
      dot: rankHealth ? { tone: rankHealth.tone, label: tHealth(rankHealth.state) } : undefined
    },
    {
      key: "subscriptions",
      label: t("tabs.subscriptions"),
      href: "/admin/collectors/subscriptions",
      hidden: !canReadSubscriptions,
      dot: subscriptionHealth
        ? { tone: subscriptionHealth.tone, label: tHealth(subscriptionHealth.state) }
        : undefined
    },
    {
      key: "streams",
      label: t("tabs.streams"),
      href: "/admin/collectors/streams",
      hidden: !canReadStreams,
      dot: streamHealth
        ? { tone: streamHealth.tone, label: tStream(`${streamHealth.key}.label`) }
        : undefined
    }
  ];

  return (
    <div className="space-y-4">
      <AdminPageHeader title={t("title")} description={t("description")} />
      <LinkTabs items={items} activeKey={active ?? "rank"} ariaLabel={t("title")} />
      {children}
    </div>
  );
}
