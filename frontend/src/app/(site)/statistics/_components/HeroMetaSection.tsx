import type { ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { characterClassOf, classRank } from "@/components/pick-ban/pick-ban-model";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { OpenEmptyRow, OpenLoadError, Section, SectionHead } from "@/components/site/open-layout";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { findRole, ratedDimension, roleName, roleTint } from "@/lib/roster/ontology";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import disciplineService from "@/services/discipline.service";
import statisticsService from "@/services/statistics.service";
import type { CharacterPlaytime } from "@/types/user.types";

const TITLE_ID = "stats-heroes-title";
const GRID_CLASS = "grid grid-cols-1 gap-3 lg:grid-cols-3 lg:items-start";
const SKELETON_COLUMNS = 3;
const SKELETON_ROWS = 8;

function Shell({ children }: Readonly<{ children: ReactNode }>) {
  const t = useTranslations("statistics.heroes");
  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead title={t("title")} titleId={TITLE_ID} sub={t("sub")} />
      {children}
    </Section>
  );
}

/**
 * What one game is played on: every character's share of the observed playtime, one ranked column per class in the
 * game's declared order. A class that is a rated role of the game wears that role's name, glyph and colour.
 */
export async function HeroMetaSection({ discipline, axis }: Readonly<{ discipline: string; axis: WorkspaceAxis }>) {
  const [t, tRoles, format, playtime, ontology] = await Promise.all([
    getTranslations("statistics.heroes"),
    getTranslations("common.roles"),
    getFormatter(),
    statisticsService.getCharacterPlaytime(discipline, { axis, perPage: -1 }).catch(() => null),
    disciplineService.metadata("all", discipline).catch(() => null)
  ]);

  if (playtime === null) {
    return (
      <Shell>
        <OpenLoadError what={t("what")} dashed />
      </Shell>
    );
  }
  if (playtime.results.length === 0) {
    return (
      <Shell>
        <OpenEmptyRow>{t("empty")}</OpenEmptyRow>
      </Shell>
    );
  }

  const byClass = new Map<string | null, CharacterPlaytime[]>();
  for (const row of [...playtime.results].sort((a, b) => b.playtime - a.playtime)) {
    const group = characterClassOf(row.entity);
    byClass.set(group, [...(byClass.get(group) ?? []), row]);
  }
  const declared = ontology?.discipline.character_classes ?? [];
  const columns = [...byClass].sort(
    ([left], [right]) => classRank(left, declared) - classRank(right, declared) || (left ?? "").localeCompare(right ?? "")
  );
  const dimension = ontology ? (ratedDimension(ontology)?.code ?? null) : null;
  const percent = { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 } as const;

  return (
    <Shell>
      <div className={GRID_CLASS}>
        {columns.map(([group, rows]) => {
          const role = ontology && dimension && group ? findRole(ontology, { dimension, role: group }) : null;
          const label = role
            ? roleName(role, (key) => (tRoles.has(key as never) ? tRoles(key as never) : null))
            : (group ?? t("noClass"));
          // A role's own colour; a class that is no role of the game gets the accent, never a borrowed role hue.
          const color = role && group ? roleTint(ontology, group) : "var(--aqt-teal)";
          const leader = rows[0].playtime;
          return (
            <TournamentTeamCardFrame
              key={group ?? ""}
              aria-label={label}
              name={
                <span className="inline-flex items-center gap-2">
                  {role && dimension && group ? (
                    <PlayerRoleIcon role={{ dimension, role: group }} ontology={ontology} size={18} decorative />
                  ) : null}
                  <span className="capitalize">{label}</span>
                  <span className="aqt-tnum font-normal text-[color:var(--aqt-fg-dim)]">
                    · {format.number(rows.reduce((sum, row) => sum + row.playtime, 0), percent)}
                  </span>
                </span>
              }
            >
              <ol className="py-1.5">
                {rows.map((row, index) => {
                  const share = format.number(row.playtime, percent);
                  return (
                    <li
                      key={row.entity.id}
                      className="relative grid grid-cols-[1.25rem_24px_minmax(0,1fr)_3.5rem] items-center gap-x-2.5 px-3.5 py-1.5 transition-colors hover:bg-[color:var(--aqt-overlay-2)]"
                    >
                      <span aria-hidden className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <CatalogEntityImage entity={row.entity} size={24} decorative />
                      <span className="flex min-w-0 flex-col gap-1">
                        <Link
                          href={`/users/heroes-compare?hero_id=${row.entity.id}&discipline=${encodeURIComponent(discipline)}`}
                          prefetch={false}
                          title={t("compare", { name: row.entity.name })}
                          className="truncate text-caption font-semibold text-[color:var(--aqt-fg)] after:absolute after:inset-0 hover:text-[color:var(--aqt-teal)] focus-visible:outline-hidden focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-[color:var(--aqt-teal)]"
                        >
                          {row.entity.name}
                        </Link>
                        <span
                          role="progressbar"
                          aria-label={row.entity.name}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={Math.round(row.playtime * 1000) / 10}
                          aria-valuetext={share}
                          className="block h-1.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]"
                        >
                          <span
                            className="block h-full rounded-full"
                            style={{
                              width: `${leader > 0 ? (row.playtime / leader) * 100 : 0}%`,
                              backgroundColor: color
                            }}
                          />
                        </span>
                      </span>
                      <span className="aqt-tnum text-right text-caption font-semibold text-[color:var(--aqt-fg)]">
                        {share}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </TournamentTeamCardFrame>
          );
        })}
      </div>
    </Shell>
  );
}

export function HeroMetaSkeleton() {
  return (
    <Shell>
      <div aria-hidden className={GRID_CLASS}>
        {Array.from({ length: SKELETON_COLUMNS }, (_, column) => (
          <TournamentTeamCardFrame key={column} name={<Skeleton className="h-4 w-28" />}>
            <div className="grid gap-2.5 px-3.5 py-3">
              {Array.from({ length: SKELETON_ROWS }, (_, row) => (
                <Skeleton key={row} className="h-6 w-full" />
              ))}
            </div>
          </TournamentTeamCardFrame>
        ))}
      </div>
    </Shell>
  );
}
