"use client";

import { useMemo, useState } from "react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useTranslations } from "next-intl";
import { ArrowRight, Users } from "lucide-react";
import { UserBestTeammate } from "@/types/user.types";
import { LogStatsName } from "@/types/stats.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { heroInitials } from "@/components/hero/heroRole";
import { getPlayerSlug } from "@/utils/player";
import { DataPagination } from "@/components/ui/data-pagination";
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

const TEAMMATE_COLORS = [
  "linear-gradient(135deg, hsl(210 85% 72%), hsl(210 65% 46%))",
  "linear-gradient(135deg, hsl(340 85% 72%), hsl(340 65% 46%))",
  "linear-gradient(135deg, hsl(142 70% 64%), hsl(142 52% 40%))",
  "linear-gradient(135deg, hsl(38 95% 66%), hsl(38 82% 46%))",
  "linear-gradient(135deg, hsl(270 75% 72%), hsl(270 58% 48%))",
  "linear-gradient(135deg, hsl(0 80% 70%), hsl(0 62% 46%))"
];

const formatStat = (value: number | null | undefined, digits: number) =>
  value != null && Number.isFinite(value) ? value.toFixed(digits) : "—";

const wrColorOf = (winrate: number): string =>
  winrate >= 0.55 ? "var(--aqt-emerald)" : winrate < 0.45 ? "var(--aqt-rose)" : "var(--aqt-amber)";

const OverviewTeammatesSynergy = ({ teammates, totalCount, totalMaps }: Props) => {
  const t = useTranslations();
  const [search, setSearch] = useState("");

  const top = teammates.slice(0, 6);
  if (top.length === 0) return null;

  return (
    <CardSurface
      flush
      title={t("users.overview.teammates.title")}
      icon={<Users size={15} />}
      action={
        <Dialog>
          <DialogTrigger asChild>
            <button type="button" className="aqt-seeall">
              {t("common.all")}
              <ArrowRight aria-hidden className="size-3" />
            </button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] p-0">
            <div className="aqt-player flex max-h-[80vh] flex-col">
              <DialogHeader className="border-b border-[color:var(--aqt-border)] px-5 py-4 text-left">
                <DialogTitle className="text-[color:var(--aqt-fg)]">{t("users.overview.teammates.title")}</DialogTitle>
                <DialogDescription className="text-[color:var(--aqt-fg-dim)]">
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
      {top.map((tm, i) => {
        const [nm, tag] = tm.user.name.split("#");
        const wrPct = Math.max(0, Math.min(100, tm.winrate * 100));
        const color = wrColorOf(tm.winrate);
        return (
          <HoverPrefetchLink
            key={tm.user.id}
            href={`/users/${getPlayerSlug(tm.user.name)}`}
            className="group grid grid-cols-[26px_minmax(0,1fr)_auto] items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-[18px] py-2.5 transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]"
          >
            <span
              className="aqt-display flex h-[26px] w-[26px] items-center justify-center rounded-full text-label font-extrabold"
              style={{ background: TEAMMATE_COLORS[i % TEAMMATE_COLORS.length], color: "hsl(220 30% 8%)" }}
              aria-hidden
            >
              {heroInitials(nm)}
            </span>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="truncate text-caption font-semibold text-[color:var(--aqt-fg)] group-hover:text-[color:var(--aqt-teal)]">
                  {nm}
                </span>
                {tag ? <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">#{tag}</span> : null}
              </div>
              <div className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                {t("users.overview.teammates.playedMaps", { count: tm.tournaments, maps: tm.maps })}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="h-[5px] w-[84px] overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]">
                <span className="block h-full rounded-full" style={{ width: `${wrPct}%`, background: color }} />
              </span>
              <span className="aqt-tnum w-9 text-right text-caption font-bold" style={{ color }}>
                {wrPct.toFixed(0)}%
              </span>
            </div>
          </HoverPrefetchLink>
        );
      })}
      <div className="aqt-tnum flex justify-between px-[18px] py-2.5 text-label text-[color:var(--aqt-fg-dim)]">
        <span>{t("users.overview.teammates.wrHint")}</span>
        <span>{t("users.overview.teammates.footer", { count: totalCount, maps: totalMaps })}</span>
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
                { id: "kda", label: t("users.overview.teammates.col.kda"), left: false },
                { id: "mvp", label: t("users.overview.teammates.col.mvp"), left: false }
              ].map((h) => (
                <th key={h.id} className={cnHeader(h.left)}>
                  {h.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.map((tm) => {
              const [tmName, tmTag] = tm.user.name.split("#");
              return (
                <tr key={tm.user.id} className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]">
                  <td className="px-3 py-2">
                    <HoverPrefetchLink href={`/users/${getPlayerSlug(tm.user.name)}`} className="inline-flex items-center gap-1.5 hover:text-[color:var(--aqt-teal)]">
                      <span className="font-semibold text-[color:var(--aqt-fg)]">{tmName}</span>
                      {tmTag ? <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">#{tmTag}</span> : null}
                    </HoverPrefetchLink>
                  </td>
                  <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{tm.tournaments}</td>
                  <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{tm.maps}</td>
                  <td
                    className="aqt-tnum px-3 py-2 text-right font-semibold"
                    style={{ color: wrColorOf(tm.winrate) }}
                  >
                    {(tm.winrate * 100).toFixed(0)}%
                  </td>
                  <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                    {formatStat(tm.stats?.[LogStatsName.KDA], 2)}
                  </td>
                  <td className="aqt-tnum px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                    {formatStat(tm.stats?.[LogStatsName.Performance], 1)}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-caption text-[color:var(--aqt-fg-dim)]">
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
          summary={
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

const cnHeader = (left: boolean) =>
  `aqt-tnum border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] px-3 py-2.5 text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)] ${
    left ? "text-left" : "text-right"
  }`;

export default OverviewTeammatesSynergy;
