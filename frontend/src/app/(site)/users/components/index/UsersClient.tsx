"use client";

import { useTranslations } from "next-intl";
import { BarChart3, LayoutGrid, Trophy } from "lucide-react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

import { SORT_OPTIONS, type ViewMode } from "./users-index.model";
import { useUsersIndexParams } from "./useUsersIndexParams";
import { useUsersIndexData } from "./useUsersIndexData";
import { UsersIndexHero } from "./UsersIndexHero";
import { UsersIndexFilters } from "./UsersIndexFilters";
import { UsersAnalyticsView } from "./UsersAnalyticsView";
import { UsersCatalogView } from "./UsersCatalogView";
import styles from "./Users.module.css";

/**
 * The player index. Both views share one set of URL-backed filters, and both
 * stay mounted — switching is a CSS toggle, so returning to a view keeps its
 * scroll position and its already-fetched page.
 */
const UsersClient = () => {
  const t = useTranslations();
  const controls = useUsersIndexParams();
  const data = useUsersIndexData(controls.params);
  const { view, sort } = controls.params;
  const sortLabel = t(
    SORT_OPTIONS.find((option) => option.value === sort)?.labelKey ?? "users.list.sort.name"
  );

  return (
    <div className={styles.surface}>
      <UsersIndexHero stats={data.statsQuery.data} />

      <section className={styles.toolbar}>
        <ToggleGroup
          type="single"
          variant="pill"
          size="sm"
          value={view}
          onValueChange={(next) => next && controls.setView(next as ViewMode)}
          aria-label={t("users.list.a11y.viewMode")}
        >
          <ToggleGroupItem value="analytics">
            <BarChart3 size={14} aria-hidden /> {t("users.list.view.analytics")}
            <span className="text-muted-foreground">{t("users.list.view.analyticsBadge")}</span>
          </ToggleGroupItem>
          <ToggleGroupItem value="catalog">
            <LayoutGrid size={14} aria-hidden /> {t("users.list.view.catalog")}
            <span className="text-muted-foreground">{t("users.list.view.catalogBadge")}</span>
          </ToggleGroupItem>
        </ToggleGroup>
        <div className={styles.toolbarActions}>
          <span className={styles.pill}>
            <Trophy size={11} aria-hidden /> {t("users.list.view.rosterLive")}
          </span>
        </div>
      </section>

      <UsersIndexFilters controls={controls} stats={data.statsQuery.data} />

      <div className={cn(styles.viewBlock, view === "analytics" && styles.viewBlockActive)}>
        <UsersAnalyticsView controls={controls} data={data} sortLabel={sortLabel} />
      </div>

      <div className={cn(styles.viewBlock, view === "catalog" && styles.viewBlockActive)}>
        <UsersCatalogView controls={controls} data={data} />
      </div>
    </div>
  );
};

export default UsersClient;
