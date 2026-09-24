"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { rankHealthDot } from "@/components/admin/collectors/rank-shared";
import { streamHealthDot } from "@/components/admin/collectors/stream-shared";
import { subscriptionHealthDot } from "@/components/admin/collectors/subscription-shared";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { usePermissions } from "@/hooks/usePermissions";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

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
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const canReadRank = canAccessPermission("rank.read");
  const canReadSubscriptions = canAccessPermission("subscription.read");
  // GLOBAL, not workspace-scoped: one poller, one Redis key, and
  // `adminRoutePermissions` gates `/admin/collectors/streams` the same way.
  const canReadStreams = canAccessPermission("stream.read", null);

  const rankQuery = useQuery({
    queryKey: ["admin", "rank", "stats", workspaceId],
    queryFn: () => adminService.getRankCollectionStats(),
    enabled: canReadRank
  });
  const subscriptionQuery = useQuery({
    queryKey: ["admin", "subscriptions", "stats", workspaceId],
    queryFn: () => adminService.getSubscriptionCollectionStats(),
    enabled: canReadSubscriptions
  });
  const streamQuery = useQuery({
    queryKey: ["admin", "streams", "health"],
    queryFn: () => adminService.getStreamPollHealth(),
    enabled: canReadStreams
  });

  const active = COLLECTORS.find((key) => pathname.startsWith(`/admin/collectors/${key}`));

  const items: LinkTabItem[] = [
    {
      key: "rank",
      label: "Rank",
      href: "/admin/collectors/rank",
      hidden: !canReadRank,
      dot: rankQuery.data ? rankHealthDot(rankQuery.data) : undefined
    },
    {
      key: "subscriptions",
      label: "Subscriptions",
      href: "/admin/collectors/subscriptions",
      hidden: !canReadSubscriptions,
      dot: subscriptionQuery.data ? subscriptionHealthDot(subscriptionQuery.data) : undefined
    },
    {
      key: "streams",
      label: "Streams",
      href: "/admin/collectors/streams",
      hidden: !canReadStreams,
      dot: streamQuery.data ? streamHealthDot(streamQuery.data) : undefined
    }
  ];

  return (
    <div className="space-y-4">
      <AdminPageHeader
        title="Collectors"
        description="Background pollers: OverFast ranks, Boosty/Twitch subscriptions, Twitch live status."
      />
      <LinkTabs items={items} activeKey={active ?? "rank"} ariaLabel="Collectors" />
      {children}
    </div>
  );
}
