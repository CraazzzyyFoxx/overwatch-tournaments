import type { ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { ArrowDown } from "lucide-react";

import { HandleLabel } from "@/components/HandleLabel";
import { OpenEmptyRow, OpenLoadError, Section, SectionHead } from "@/components/site/open-layout";
import { PlaceBadge } from "@/components/ui/place-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { winrateColor } from "@/lib/colors";
import { getFormatter } from "@/lib/datetime/server";
import { getPlayerSlug } from "@/lib/player";
import { isTenantHost } from "@/lib/site/tenant-host";
import { cn } from "@/lib/utils";
import statisticsService from "@/services/statistics.service";
import type { PlayerSort } from "@/types/statistics.types";

import { PlayersNotFound, PlayersPagination, PlayersSearch } from "./PlayersControls";
import { PLAYERS_PER_PAGE, playersSortHref, type PlayersParams } from "./statistics.model";

const TITLE_ID = "stats-players-title";
const SKELETON_ROWS = 10;

/** A dense data block: framed, and scrolling inside its own labelled region on a phone. */
const FRAME_CLASS =
  "overflow-x-auto rounded-[12px] border border-[color:var(--aqt-overlay-border)] bg-[color:var(--aqt-overlay-1)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]";
const ROW_CLASS = "border-b border-[color:var(--aqt-overlay-border)] last:border-b-0";

/** The numeric columns, left to right; each sorts the table by itself. */
const COLUMNS = [
  { sort: "titles", label: "col.titles" },
  { sort: "tournaments", label: "col.tournaments" },
  { sort: "maps_won", label: "col.maps" },
  { sort: "winrate", label: "col.winrate" }
] as const satisfies readonly { sort: PlayerSort; label: string }[];

function Shell({
  sort,
  aside = null,
  children
}: Readonly<{ sort: PlayerSort; aside?: ReactNode; children: ReactNode }>) {
  const t = useTranslations("statistics.players");
  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        title={t("title")}
        titleId={TITLE_ID}
        sub={sort === "winrate" ? t("subWinrate") : t("sub")}
        aside={aside}
      />
      {children}
    </Section>
  );
}

/**
 * Who is best: every player with a qualifying tournament, ranked by the chosen column (titles by default). The rank
 * is the server's over the whole population, so a search shows each player's real place.
 */
export async function PlayersSection({
  discipline,
  urlDiscipline,
  params
}: Readonly<{ discipline: string | null; urlDiscipline: string | string[] | undefined; params: PlayersParams }>) {
  const skipWorkspace = !(await isTenantHost());
  const [t, format, data] = await Promise.all([
    getTranslations("statistics.players"),
    getFormatter(),
    statisticsService
      .getPlayers(discipline, { ...params, perPage: PLAYERS_PER_PAGE }, { skipWorkspace })
      .catch(() => null)
  ]);

  if (data === null) {
    return (
      <Shell sort={params.sort}>
        <OpenLoadError what={t("what")} dashed />
      </Shell>
    );
  }
  if (data.total === 0 && params.query === "") {
    return (
      <Shell sort={params.sort}>
        <OpenEmptyRow>{t("empty")}</OpenEmptyRow>
      </Shell>
    );
  }

  const search = <PlayersSearch label={t("search")} placeholder={t("searchPlaceholder")} />;
  if (data.results.length === 0) {
    return (
      <Shell sort={params.sort} aside={search}>
        <PlayersNotFound
          title={t("notFoundTitle")}
          description={t("notFound", { query: params.query })}
          actionLabel={t("resetSearch")}
        />
      </Shell>
    );
  }

  return (
    <Shell sort={params.sort} aside={search}>
      <div role="region" aria-labelledby={TITLE_ID} tabIndex={0} className={FRAME_CLASS}>
        <Table wrapperClassName="overflow-visible" className="min-w-[34rem]">
          <TableHeader>
            <TableRow className="whitespace-nowrap border-[color:var(--aqt-overlay-border)]">
              <TableHead scope="col" className="h-auto w-14 py-2.5 pl-3.5 pr-2 font-medium">
                {t("col.rank")}
              </TableHead>
              <TableHead scope="col" className="h-auto py-2.5 pl-0 pr-3 font-medium">
                {t("col.player")}
              </TableHead>
              {COLUMNS.map((column) => {
                const active = column.sort === params.sort;
                return (
                  <TableHead
                    key={column.sort}
                    scope="col"
                    aria-sort={active ? "descending" : undefined}
                    className="h-auto py-2.5 pl-4 pr-3 text-right font-medium last:pr-3.5 sm:pl-8"
                  >
                    <Link
                      href={playersSortHref(column.sort, { discipline: urlDiscipline, query: params.query })}
                      scroll={false}
                      prefetch={false}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-sm transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]",
                        active && "text-[color:var(--aqt-teal)]"
                      )}
                    >
                      {active ? <ArrowDown aria-hidden className="size-3" /> : null}
                      {t(column.label)}
                    </Link>
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.results.map((row) => (
                <TableRow key={row.id} className={ROW_CLASS}>
                  <TableCell className="py-2 pl-3.5 pr-2">
                    {row.rank <= 3 ? (
                      <PlaceBadge place={row.rank} />
                    ) : (
                      <span className="aqt-tnum text-[color:var(--aqt-fg-faint)]">#{row.rank}</span>
                    )}
                  </TableCell>
                  <TableCell className="w-full max-w-0 py-2 pl-0 pr-3">
                    <Link
                      href={`/users/${getPlayerSlug(row.name)}`}
                      prefetch={false}
                      title={row.name}
                      className="block truncate rounded-sm text-body font-semibold text-[color:var(--aqt-fg)] transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
                    >
                      <HandleLabel handle={row.name} />
                    </Link>
                  </TableCell>
                  <TableCell
                    className={cn(
                      "aqt-tnum py-2 pl-0 pr-3 text-right font-semibold",
                      row.titles === 0 && "font-normal text-[color:var(--aqt-fg-faint)]"
                    )}
                  >
                    {format.number(row.titles)}
                  </TableCell>
                  <TableCell className="aqt-tnum py-2 pl-0 pr-3 text-right">{format.number(row.tournaments)}</TableCell>
                  <TableCell
                    className="aqt-tnum whitespace-nowrap py-2 pl-0 pr-3 text-right text-[color:var(--aqt-fg-muted)]"
                    title={t("mapsRecord", { won: row.maps_won, lost: row.maps_lost })}
                  >
                    {format.number(row.maps_won)}–{format.number(row.maps_lost)}
                  </TableCell>
                  <TableCell
                    className="aqt-tnum py-2 pl-0 pr-3.5 text-right font-semibold"
                    title={row.low_sample ? t("lowSample") : undefined}
                    style={{
                      color:
                        row.winrate === null
                          ? "var(--aqt-fg-faint)"
                          : winrateColor(row.winrate * 100, row.low_sample)
                    }}
                  >
                    {row.winrate === null
                      ? "—"
                      : format.number(row.winrate, {
                          style: "percent",
                          minimumFractionDigits: 1,
                          maximumFractionDigits: 1
                        })}
                  </TableCell>
                </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <PlayersPagination
        page={data.page}
        totalPages={Math.max(1, Math.ceil(data.total / PLAYERS_PER_PAGE))}
        summary={t("total", { count: data.total })}
      />
    </Shell>
  );
}

export function PlayersSkeleton({ sort }: Readonly<{ sort: PlayerSort }>) {
  return (
    <Shell sort={sort} aside={<Skeleton className="h-8 w-full sm:w-64" />}>
      <div aria-hidden className={FRAME_CLASS}>
        <div className="h-10 border-b border-[color:var(--aqt-overlay-border)]" />
        {Array.from({ length: SKELETON_ROWS }, (_, index) => (
          <div key={index} className={cn(ROW_CLASS, "flex h-11 items-center gap-4 px-3.5")}>
            <Skeleton className="h-5 w-7" />
            <Skeleton className="h-4 w-full max-w-48" />
            <Skeleton className="ml-auto h-4 w-40 max-w-[40%]" />
          </div>
        ))}
      </div>
    </Shell>
  );
}
