"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronUp, Trophy } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { HeroStrip } from "@/components/hero/HeroImage";
import { DataPagination } from "@/components/ui/data-pagination";
import { cn, initials } from "@/lib/utils";
import { getPlayerSlug } from "@/utils/player";
import { formatOptional } from "@/app/(site)/users/components/shared/list-utils";
import type { UserOverviewRow } from "@/types/user.types";

import { DivisionHex } from "./DivisionHex";
import { UserDetailsRow } from "./UserDetailsRow";
import { placementWidth, primaryRoleLabel, splitTag } from "./users-index.model";
import type { UsersIndexData } from "./useUsersIndexData";
import type { UsersIndexParamControls } from "./useUsersIndexParams";
import styles from "./Users.module.css";

/** The ranked, paginated player table with its expandable per-player detail. */
export function UsersAnalyticsView({
  controls,
  data,
  sortLabel
}: Readonly<{
  controls: UsersIndexParamControls;
  data: UsersIndexData;
  sortLabel: string;
}>) {
  const t = useTranslations();
  const [expandedRows, setExpandedRows] = useState<Set<number>>(() => new Set());
  const { page, perPage, order } = controls.params;
  const { overviewQuery, maxPage, range } = data;
  const rows = overviewQuery.data;
  // `isPending`, not `isLoading`: the server never fetches, so there `isLoading`
  // is false and SSR used to paint the "no players" row, which the skeleton then
  // pushed down. Pending holds on both sides until the first page lands.
  const showLoadingRows = overviewQuery.isPending;

  const toggleRow = (id: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <section>
      <div className={styles.sectionHead}>
        <h2>{t("users.list.table.allPlayers")}</h2>
        <span className={styles.sectionMeta}>
          {rows
            ? t("users.list.table.pageMeta", {
                page: String(rows.page),
                maxPage: String(maxPage),
                x: `${sortLabel.toLowerCase()} ${order === "asc" ? "▴" : "▾"}`
              })
            : t("common.loading")}
        </span>
      </div>

      <div className={styles.card}>
        {overviewQuery.isError ? (
          <p className={styles.errorMsg}>
            {(overviewQuery.error as Error)?.message || t("users.list.errors.overview")}
          </p>
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th style={{ width: "22%" }}>{t("users.list.table.player")}</th>
                  <th className="center">{t("users.list.table.divisions")}</th>
                  <th className="center">{t("common.tournaments")}</th>
                  <th className="center">{t("users.list.table.achievements")}</th>
                  <th>{t("users.list.table.avgPlacement")}</th>
                  <th className={cn(styles.hideMd, "center")}>
                    {t("users.list.table.topHeroes")}
                  </th>
                  <th className="center">{t("users.list.table.details")}</th>
                </tr>
              </thead>
              <tbody>
                {showLoadingRows ? (
                  Array.from({ length: perPage }).map((_, idx) => (
                    <tr key={`skel-${idx}`}>
                      <td colSpan={7} className={styles.skelRow} />
                    </tr>
                  ))
                ) : rows && rows.results.length > 0 ? (
                  rows.results.map((user: UserOverviewRow, index: number) => (
                    <React.Fragment key={user.id}>
                      <PlayerRow
                        user={user}
                        globalRank={(rows.page - 1) * rows.per_page + index + 1}
                        expanded={expandedRows.has(user.id)}
                        onToggle={() => toggleRow(user.id)}
                      />
                      {expandedRows.has(user.id) ? <UserDetailsRow user={user} /> : null}
                    </React.Fragment>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className={styles.empty}>
                      {t("users.list.empty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {rows && rows.results.length > 0 ? (
          <DataPagination
            className={styles.paginationBar}
            page={page}
            totalPages={maxPage}
            onPageChange={(next) => controls.setPage(Math.max(1, Math.min(maxPage, next)))}
            summary={
              <>
                {range
                  ? t("users.list.pagination.showingPlayers", {
                      start: range.start,
                      end: range.end,
                      total: rows.total
                    })
                  : null}
                {overviewQuery.isFetching
                  ? ` · ${t("users.list.pagination.refreshing")}`
                  : null}
              </>
            }
          />
        ) : null}
      </div>
    </section>
  );
}

function PlayerRow({
  user,
  globalRank,
  expanded,
  onToggle
}: Readonly<{
  user: UserOverviewRow;
  globalRank: number;
  expanded: boolean;
  onToggle: () => void;
}>) {
  const t = useTranslations();
  const { handle, tag } = splitTag(user.name);
  const placement = user.averages.avg_placement;
  const bar = placementWidth(placement);

  return (
    <tr>
      <td>
        <div className={styles.playerCell}>
          <span className={styles.playerRank}>#{globalRank}</span>
          <div className={styles.playerAvatar} aria-hidden>
            {initials(user.name)}
          </div>
          <div className={styles.playerInfo}>
            <HoverPrefetchLink
              className={styles.playerName}
              href={`/users/${getPlayerSlug(user.name)}`}
              title={user.name}
            >
              {handle}
              {tag ? <span className="tag">{tag}</span> : null}
            </HoverPrefetchLink>
            <span className={styles.playerSub}>{primaryRoleLabel(user.roles, t)}</span>
          </div>
        </div>
      </td>

      <td className="center">
        {user.roles.length === 0 ? (
          <span className={styles.playerSub}>—</span>
        ) : (
          <div className={styles.divisionCluster}>
            {user.roles.map((roleRow) => (
              <DivisionHex
                key={`${user.id}-${roleRow.role}-${roleRow.division}`}
                role={roleRow.role}
                division={roleRow.division}
              />
            ))}
          </div>
        )}
      </td>

      <td className={cn("center", styles.tnum)}>{user.tournaments_count}</td>

      <td className="center">
        <span className={styles.achievementsCell}>
          <Trophy size={12} aria-hidden /> {user.achievements_count}
        </span>
      </td>

      <td>
        <div className={styles.placementBar}>
          <div className={styles.placementTrack}>
            <div
              className={cn(styles.placementFill, bar.warn && styles.placementFillWarn)}
              style={{ width: `${bar.width}%` }}
            />
          </div>
          <span className={styles.placementNum}>{formatOptional(placement)}</span>
        </div>
      </td>

      <td className={cn(styles.hideMd, "center")}>
        <HeroStrip heroes={user.top_heroes.slice(0, 3).map((h) => h.hero)} />
      </td>

      <td className="center">
        <button
          type="button"
          aria-label={
            expanded ? t("users.list.a11y.collapseDetails") : t("users.list.a11y.expandDetails")
          }
          onClick={onToggle}
          className={styles.expandButton}
        >
          {expanded ? <ChevronUp size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
        </button>
      </td>
    </tr>
  );
}
