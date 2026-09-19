"use client";

import { StreamHealthDashboard } from "@/components/admin/collectors/stream-health";
import { StreamSettingsPanel } from "@/components/admin/collectors/stream-settings";
import { useCollectorTab } from "@/components/admin/collectors/useCollectorTab";
import { AdminTabs } from "@/components/kit/AdminTabs";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";

/**
 * The Twitch live-status poller: health and its runtime configuration.
 *
 * Two slots, not three with one greyed out — there is no per-channel check log
 * to show, so the collector does not pretend to have a History (F14 ·2).
 *
 * Status is gated on `stream.read` and on the GLOBAL grant, not a
 * workspace-scoped one, because there is one poller and one Redis key behind
 * `GET /api/streams/health`; `canAccessPermission(..., null)` is what asks for
 * the global form, and `adminRoutePermissions` gates the route the same way.
 * That is also why this page has no workspace dimension: the numbers carry
 * none. Settings writes `stream.collection` through
 * `PUT /api/v1/admin/settings/{key}`, which is superuser-only.
 */
export default function StreamCollectorPage() {
  const { canAccessPermission, isSuperuser } = usePermissions();
  const canReadHealth = canAccessPermission("stream.read", null);

  const { activeKey, items } = useCollectorTab("streams", [
    { key: "status", label: "Status" },
    { key: "settings", label: "Settings", hidden: !isSuperuser }
  ]);

  // Defensive rather than routine: `adminRoutePermissions` already turns this
  // away at the route, and a superuser satisfies the permission outright — so
  // the only holder who gets here is one whose global grant was revoked mid
  // session. Saying why beats an empty page or a bare 403 toast, and without
  // health there is no other slot to offer (Settings is superuser-only).
  if (!canReadHealth) {
    return (
      <PageStateCard
        state="not-found"
        title="Not available"
        description="Reading poller health needs the global stream.read permission — the poller is platform-wide, so a workspace-scoped grant does not reach it."
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
          ariaLabel="Stream collector views"
        />
      )}
      {activeKey === "settings" ? <StreamSettingsPanel /> : <StreamHealthDashboard />}
    </div>
  );
}
