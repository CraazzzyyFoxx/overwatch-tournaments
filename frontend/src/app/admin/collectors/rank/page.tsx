"use client";

import { RankHealthDashboard } from "@/components/admin/collectors/rank-health";
import { RankTaskHistory } from "@/components/admin/collectors/rank-history";
import { RankSettingsPanel } from "@/components/admin/collectors/rank-settings";
import { useCollectorTab } from "@/components/admin/collectors/useCollectorTab";
import { LinkTabs } from "@/components/kit/LinkTabs";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";

/**
 * The OverFast rank collector: is the worker healthy, what has it been doing,
 * and how is it configured.
 *
 * Health and the fetch log are one view — a `?tab=history` slot used to hide
 * the log behind a third row of tabs under the hub's, and the two answer the
 * same question ("is it working?") for the same reader. Settings stays its own
 * slot: it is a form, and superuser-only. Health and history are gated on
 * `rank.read` and scoped to the active workspace (see `admin.service.ts`) —
 * which is what lets a workspace owner open them at all instead of 403ing on
 * a global role. Settings writes `parser.rank_collection` through
 * `PUT /api/v1/admin/settings/{key}`, which is superuser-only, so the slot is
 * offered only to a superuser rather than showing a form that 403s on save.
 *
 * Per-player inspection is deliberately absent: it lives on the person now
 * (People › person › Rank & subscription, F14 ·3), and the history table links
 * there.
 */
export default function RankCollectorPage() {
  const { canAccessPermission, isSuperuser } = usePermissions();
  const canRead = canAccessPermission("rank.read");

  const { activeKey, items } = useCollectorTab("rank", [
    { key: "status", label: "Status" },
    { key: "settings", label: "Settings", hidden: !isSuperuser }
  ]);

  if (!canRead) {
    return (
      <PageStateCard
        state="not-found"
        title="Not available"
        description="Reading rank collection health needs the rank.read permission in this workspace."
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* A one-tab bar is a heading with a hover state; non-superusers get none. */}
      {items.length > 1 && (
        <LinkTabs items={items} activeKey={activeKey} level={2} ariaLabel="Rank collector views" />
      )}
      {activeKey === "settings" ? (
        <RankSettingsPanel />
      ) : (
        <>
          <RankHealthDashboard />
          <RankTaskHistory />
        </>
      )}
    </div>
  );
}
