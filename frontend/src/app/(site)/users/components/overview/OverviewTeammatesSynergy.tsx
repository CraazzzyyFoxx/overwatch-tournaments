"use client";

import { useMemo, useState } from "react";
import { HandleLabel } from "@/components/HandleLabel";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { useTranslations } from "next-intl";
import { ArrowRight } from "lucide-react";
import { UserBestTeammate } from "@/types/user.types";
import { CardSurface } from "@/components/profile/atoms";
import { winrateColor } from "@/lib/colors";
import { cn } from "@/lib/utils";
import { getPlayerSlug } from "@/lib/player";
import { Button } from "@/components/ui/button";
import { DataPagination } from "@/components/ui/data-pagination";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { SearchField } from "@/components/ui/search-field";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";

interface Props {
  teammates: UserBestTeammate[];
  totalCount: number;
  totalMaps: number;
}

const formatStat = (value: number | null | undefined, digits: number) =>
  value != null && Number.isFinite(value) ? value.toFixed(digits) : "—";

const OverviewTeammatesSynergy = ({ teammates, totalCount, totalMaps }: Props) => {
  const t = useTranslations();
  const [search, setSearch] = useState("");

  const top = teammates.slice(0, 6);
  if (top.length === 0) return null;

  return (
    <CardSurface
      flush
      title={t("users.overview.teammates.title")}
      action={
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="link" size="inline" className="[&_svg]:size-3">
              {t("common.all")}
              <ArrowRight aria-hidden />
            </Button>
          </DialogTrigger>
          <DialogContent variant="panel" className="max-w-2xl">
            <div className="aqt-player flex max-h-[80vh] flex-col">
              <DialogHeader variant="panel">
                <DialogTitle>{t("users.overview.teammates.title")}</DialogTitle>
                <DialogDescription>
                  {t("users.overview.teammates.dialogSubtitle", { count: totalCount, maps: totalMaps })}
                </DialogDescription>
              </DialogHeader>
              <AllTeammatesTable teammates={teammates} search={search} onSearchChange={setSearch} />
            </div>
          </DialogContent>
        </Dialog>
      }
    >
      <TeammateRows top={top} totalCount={totalCount} totalMaps={totalMaps} />
    </CardSurface>
  );
};

// ─── Best-teammates rows (design-book §3f) ──────────────────────────────────────
// One row per teammate: colour avatar + name + games/maps-together + a win-rate
// mini-bar (fuller = higher). Marked `data-players` so hero-popover wiring skips
// these player avatars (design-book §11).

const TeammateRows = ({
  top,
  totalCount,
  totalMaps
}: {
  top: UserBestTeammate[];
  totalCount: number;
  totalMaps: number;
}) => {
  const t = useTranslations();
  return (
    <div data-players>
      {top.map((tm) => {
        const wrPct = Math.max(0, Math.min(100, tm.winrate * 100));
        const color = winrateColor(wrPct);
        return (
          <HoverPrefetchLink
            key={tm.user.id}
            href={`/users/${getPlayerSlug(tm.user.name)}`}
            className="group grid grid-cols-[26px_minmax(0,1fr)_auto] items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-[18px] py-2.5 transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]"
          >
            <PlayerAvatar user={tm.user} size={26} />
            <div className="min-w-0">
              <HandleLabel
                handle={tm.user.name}
                className="block text-caption font-semibold text-[color:var(--aqt-fg)] group-hover:text-[color:var(--aqt-teal)]"
                tagClassName="aqt-tnum text-label"
              />
              <div className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                {t("users.overview.teammates.playedMaps", { count: tm.tournaments, maps: tm.maps })}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span
                className="h-[5px] w-[84px] overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]"
                title={t("users.overview.teammates.wrHint")}
              >
                <span className="block h-full rounded-full" style={{ width: `${wrPct}%`, background: color }} />
              </span>
              <span className="aqt-tnum w-9 text-right text-caption font-bold" style={{ color }}>
                {wrPct.toFixed(0)}%
              </span>
            </div>
          </HoverPrefetchLink>
        );
      })}
      <div className="aqt-tnum px-[18px] py-2.5 text-right text-label text-[color:var(--aqt-fg-dim)]">
        {t("users.overview.teammates.footer", { count: totalCount, maps: totalMaps })}
      </div>
    </div>
  );
};

// ─── Full teammates table (in the "All" modal) ──────────────────────────────────

const AllTeammatesTable = ({
  teammates,
  search,
  onSearchChange
}: {
  teammates: UserBestTeammate[];
  search: string;
  onSearchChange: (value: string) => void;
}) => {
  const t = useTranslations();
  // The teammate read's per-match averages (`kda`, MVP `performance`) exist only for games that record them: a
  // column shows when some teammate has a value, never as a column of dashes for a game without that vocabulary.
  const hasKda = teammates.some((tm) => tm.stats?.kda != null);
  const hasMvp = teammates.some((tm) => tm.stats?.performance != null);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = [...teammates].sort((a, b) => b.tournaments - a.tournaments);
    if (!q) return rows;
    return rows.filter((tm) => tm.user.name.toLowerCase().includes(q));
  }, [teammates, search]);

  const perPage = 12;
  const [page, setPage] = useState(1);
  // Reset to first page when the search changes (render-time adjustment).
  const [prevSearch, setPrevSearch] = useState(search);
  if (search !== prevSearch) {
    setPrevSearch(search);
    setPage(1);
  }
  const pages = Math.max(1, Math.ceil(filtered.length / perPage));
  const safePage = Math.min(page, pages);
  const paged = filtered.slice((safePage - 1) * perPage, safePage * perPage);

  return (
    <div className="flex min-h-0 flex-col">
      <div className="border-b border-[color:var(--aqt-border)] px-5 py-3">
        <SearchField
          label={t("users.overview.teammates.searchLabel")}
          placeholder={t("users.overview.teammates.searchPlaceholder")}
          value={search}
          onValueChange={onSearchChange}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <table className="aqt-tnum w-full border-collapse text-caption">
          <thead className="sticky top-0 z-[1] bg-[color:var(--aqt-bg)]">
            <tr>
              {[
                { id: "player", label: t("users.overview.teammates.col.player"), left: true },
                { id: "played", label: t("users.overview.teammates.col.played"), left: false },
                { id: "maps", label: t("users.overview.teammates.col.maps"), left: false },
                { id: "wr", label: t("users.overview.teammates.col.wr"), left: false },
                ...(hasKda ? [{ id: "kda", label: t("users.overview.teammates.col.kda"), left: false }] : []),
                ...(hasMvp ? [{ id: "mvp", label: t("users.overview.teammates.col.mvp"), left: false }] : [])
              ].map((h) => (
                <th
                  key={h.id}
                  className={cn(
                    eyebrowClass(),
                    "aqt-tnum border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] px-3 py-2.5",
                    h.left ? "text-left" : "text-right"
                  )}
                >
                  {h.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.map((tm) => (
                <tr key={tm.user.id} className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]">
                  <td className="px-3 py-2">
                    <HoverPrefetchLink href={`/users/${getPlayerSlug(tm.user.name)}`} className="hover:text-[color:var(--aqt-teal)]">
                      <HandleLabel
                        handle={tm.user.name}
                        className="font-semibold text-[color:var(--aqt-fg)]"
                        tagClassName="aqt-tnum text-label"
                      />
                    </HoverPrefetchLink>
                  </td>
                  <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{tm.tournaments}</td>
                  <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{tm.maps}</td>
                  <td
                    className="aqt-tnum px-3 py-2 text-right font-semibold"
                    style={{ color: winrateColor(tm.winrate * 100) }}
                  >
                    {(tm.winrate * 100).toFixed(0)}%
                  </td>
                  {hasKda ? (
                    <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                      {formatStat(tm.stats?.kda, 2)}
                    </td>
                  ) : null}
                  {hasMvp ? (
                    <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                      {formatStat(tm.stats?.performance, 1)}
                    </td>
                  ) : null}
                </tr>
            ))}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={4 + Number(hasKda) + Number(hasMvp)} className="px-3 py-6 text-center text-caption text-[color:var(--aqt-fg-dim)]">
                  {t("users.overview.teammates.noMatch")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {filtered.length > perPage ? (
        <DataPagination
          page={safePage}
          totalPages={pages}
          onPageChange={setPage}
          className="border-t border-[color:var(--aqt-border)] px-5 py-2.5"
          leading={
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
              {t("users.overview.teammates.pageRange", {
                start: String((safePage - 1) * perPage + 1),
                end: String(Math.min(safePage * perPage, filtered.length)),
                total: String(filtered.length)
              })}
            </span>
          }
        />
      ) : null}
    </div>
  );
};

export default OverviewTeammatesSynergy;
