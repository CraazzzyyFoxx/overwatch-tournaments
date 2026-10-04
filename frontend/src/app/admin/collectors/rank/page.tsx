"use client";

import { useTranslations } from "next-intl";

import { RankHealthDashboard } from "@/components/admin/collectors/rank-health";
import { RankTaskHistory } from "@/components/admin/collectors/rank-history";
import { RankMappingPanel } from "@/components/admin/collectors/rank-mapping";
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
 * same question ("is it working?") for the same reader. Settings and Mapping
 * are their own slots: each is a form with its own save bar, and both are
 * superuser-only. Health and history are gated on `rank.read` and scoped to
 * the active workspace (see `admin.service.ts`) — which is what lets a
 * workspace owner open them at all instead of 403ing on a global role. Both
 * forms write through `PUT /api/v1/admin/settings/{key}`, which is
 * superuser-only, so the slots are offered only to a superuser rather than
 * showing a form that 403s on save.
 *
 * Per-player inspection is deliberately absent: it lives on the person now
 * (People › person › Rank & subscription, F14 ·3), and the history table links
 * there.
 */
export default function RankCollectorPage() {
  const t = useTranslations("collectors");
  const { canAccessPermission, isSuperuser } = usePermissions();
  const canRead = canAccessPermission("rank.read");

  const { activeKey, items } = useCollectorTab("rank", [
    { key: "status", label: t("views.status") },
    { key: "settings", label: t("views.settings"), hidden: !isSuperuser },
    { key: "mapping", label: t("views.mapping"), hidden: !isSuperuser }
  ]);

  if (!canRead) {
    return (
      <PageStateCard
        state="not-found"
        title={t("access.title")}
        description={t("access.rank")}
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* A one-tab bar is a heading with a hover state; non-superusers get none. */}
      {items.length > 1 && (
        <LinkTabs items={items} activeKey={activeKey} level={2} ariaLabel={t("views.rankAria")} />
      )}
      {activeKey === "settings" ? (
        <RankSettingsPanel />
      ) : activeKey === "mapping" ? (
        <RankMappingPanel />
      ) : (
        <>
          <RankHealthDashboard />
          <RankTaskHistory />
        </>
      )}
    </div>
  );
}
