import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { ImageOff } from "lucide-react";

import { OpenEmptyRow, OpenLoadError, Section, SectionHead } from "@/components/site/open-layout";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import Image from "@/components/ui/image";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getFormatter } from "@/lib/datetime/server";
import { isTenantHost } from "@/lib/site/tenant-host";
import statisticsService from "@/services/statistics.service";

import { clock } from "./statistics.model";

const TITLE_ID = "stats-maps-title";
const GRID_CLASS = "grid grid-cols-1 gap-3 lg:grid-cols-2 lg:items-start";
const SKELETON_MODES = 2;
const SKELETON_ROWS = 5;

function Shell({ children }: Readonly<{ children: ReactNode }>) {
  const t = useTranslations("statistics.maps");
  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead title={t("title")} titleId={TITLE_ID} sub={t("sub")} />
      {children}
    </Section>
  );
}

/** Which maps one game's finished series were played on, a group per mode, most played first. */
export async function MapsSection({ discipline }: Readonly<{ discipline: string }>) {
  const skipWorkspace = !(await isTenantHost());
  const [t, format, data] = await Promise.all([
    getTranslations("statistics.maps"),
    getFormatter(),
    statisticsService.getMaps(discipline, { skipWorkspace }).catch(() => null)
  ]);

  if (data === null) {
    return (
      <Shell>
        <OpenLoadError what={t("what")} dashed />
      </Shell>
    );
  }
  if (data.total_games === 0) {
    return (
      <Shell>
        <OpenEmptyRow>{t("empty")}</OpenEmptyRow>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className={GRID_CLASS}>
        {data.modes.map(({ mode, games, maps }) => {
          const leader = Math.max(...maps.map((row) => row.share));
          return (
            <TournamentTeamCardFrame
              key={mode?.id ?? "none"}
              aria-label={mode?.name ?? t("noMode")}
              name={
                <span className="inline-flex items-center gap-2">
                  {mode?.image_path ? (
                    <Image src={mode.image_path} alt="" width={16} height={16} aria-hidden />
                  ) : null}
                  {mode?.name ?? t("noMode")}
                </span>
              }
              metricLabel={t("col.games")}
              metricValue={format.number(games)}
            >
              <Table>
                <TableHeader>
                  <TableRow className="whitespace-nowrap border-[color:var(--aqt-overlay-border)]">
                    <TableHead scope="col" className="h-auto py-2 pl-3.5 pr-3 font-medium">
                      {t("col.map")}
                    </TableHead>
                    <TableHead scope="col" className="h-auto py-2 pl-0 pr-3 text-right font-medium">
                      {t("col.games")}
                    </TableHead>
                    <TableHead scope="col" className="h-auto py-2 pl-0 pr-3 text-right font-medium">
                      {t("col.share")}
                    </TableHead>
                    <TableHead scope="col" className="h-auto py-2 pl-0 pr-3.5 text-right font-medium">
                      {t("col.avgDuration")}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {maps.map((row) => (
                    <TableRow key={row.map.id} className="border-[color:var(--aqt-overlay-border)]">
                      <TableCell className="w-full max-w-0 py-1.5 pl-3.5 pr-3">
                        <span className="flex min-w-0 items-center gap-3">
                          <span className="relative hidden aspect-video w-14 shrink-0 overflow-hidden rounded border border-[color:var(--aqt-border)] sm:block">
                            {row.map.image_path ? (
                              <Image src={row.map.image_path} alt="" fill sizes="56px" className="object-cover" />
                            ) : (
                              <span className="grid h-full place-items-center text-[color:var(--aqt-fg-faint)]">
                                <ImageOff aria-hidden width={12} height={12} />
                              </span>
                            )}
                          </span>
                          <span className="truncate font-semibold text-[color:var(--aqt-fg)]" title={row.map.name}>
                            {row.map.name}
                          </span>
                        </span>
                      </TableCell>
                      <TableCell className="aqt-tnum py-1.5 pl-0 pr-3 text-right">{format.number(row.games)}</TableCell>
                      <TableCell className="py-1.5 pl-0 pr-3">
                        <span className="flex items-center justify-end gap-2.5">
                          {/* The bar is the glance; under 640px the share alone keeps the row on screen. */}
                          <span
                            aria-hidden
                            className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)] sm:block"
                          >
                            <span
                              className="block h-full rounded-full bg-[color:var(--aqt-teal)]"
                              style={{ width: `${leader > 0 ? (row.share / leader) * 100 : 0}%` }}
                            />
                          </span>
                          <span className="aqt-tnum w-12 text-right">
                            {format.number(row.share, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                          </span>
                        </span>
                      </TableCell>
                      <TableCell className="aqt-tnum py-1.5 pl-0 pr-3.5 text-right text-[color:var(--aqt-fg-muted)]">
                        {row.avg_duration_s === null ? "—" : clock(row.avg_duration_s)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TournamentTeamCardFrame>
          );
        })}
      </div>
    </Shell>
  );
}

export function MapsSkeleton() {
  return (
    <Shell>
      <div aria-hidden className={GRID_CLASS}>
        {Array.from({ length: SKELETON_MODES }, (_, mode) => (
          <TournamentTeamCardFrame key={mode} name={<Skeleton className="h-4 w-32" />}>
            <div className="grid gap-2.5 px-3.5 py-3">
              {Array.from({ length: SKELETON_ROWS }, (_, row) => (
                <Skeleton key={row} className="h-8 w-full" />
              ))}
            </div>
          </TournamentTeamCardFrame>
        ))}
      </div>
    </Shell>
  );
}
