"use client";

import { SubscriptionHealthDashboard } from "@/components/admin/collectors/subscription-health";
import { SubscriptionTaskHistory } from "@/components/admin/collectors/subscription-history";
import { SubscriptionSettingsPanel } from "@/components/admin/collectors/subscription-settings";
import { useCollectorTab } from "@/components/admin/collectors/useCollectorTab";
import { AdminTabs } from "@/components/admin/kit/AdminTabs";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { useInvalidation } from "@/hooks/useInvalidation";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * The Boosty/Twitch subscription collector: health, check history and config.
 *
 * Health and the check log share one view (see the rank collector for why);
 * Settings is the only other slot and is superuser-only. Same two gates as the
 * rank collector — `subscription.read` scoped to the active workspace for
 * health and history, superuser for the config that
 * `PUT /api/v1/admin/settings/{key}` will only accept from one.
 *
 * Provider configuration and the workspace admission rule are NOT here: they
 * are workspace settings, and live at /admin/settings/subscriptions.
 */
export default function SubscriptionCollectorPage() {
  const { canAccessPermission, isSuperuser } = usePermissions();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const canRead = canAccessPermission("subscription.read");

  const { activeKey, items } = useCollectorTab("subscriptions", [
    { key: "status", label: "Status" },
    { key: "settings", label: "Settings", hidden: !isSuperuser }
  ]);

  // Every query on this page lives under the `["admin","subscriptions"]` prefix,
  // which is exactly what `workspace.subscriptions` stales — health and the
  // check log in one drop. `canRead` gates the subscription too: without the
  // permission the page renders a placeholder and has nothing to refresh.
  useInvalidation({
    scopeKind: "workspace",
    scopeId: canRead ? currentWorkspaceId : null
  });

  if (!canRead) {
    return (
      <PageStateCard
        state="not-found"
        title="Not available"
        description="Reading subscription collection health needs the subscription.read permission in this workspace."
      />
    );
  }

  return (
    <div className="space-y-4">
      {items.length > 1 && (
        <AdminTabs
          items={items}
          activeKey={activeKey}
          level={2}
          ariaLabel="Subscription collector views"
        />
      )}
      {activeKey === "settings" ? (
        <SubscriptionSettingsPanel />
      ) : (
        <>
          <SubscriptionHealthDashboard />
          <SubscriptionTaskHistory />
        </>
      )}
    </div>
  );
}
