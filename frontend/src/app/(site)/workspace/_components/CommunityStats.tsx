import type { CSSProperties } from "react";
import { getTranslations } from "next-intl/server";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Column, ColumnHead, LoadError, Section, SectionHead } from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import heroService from "@/services/hero.service";
import statisticsService from "@/services/statistics.service";
import type { HeroPlaytime } from "@/types/hero.types";
import type {
  TournamentDivisionStatistics,
  TournamentStatistics
} from "@/types/statistics.types";
import type { Workspace } from "@/types/workspace.types";

import { ScopedMoreLink } from "./WorkspaceScopeLink";

const TITLE_ID = "cs-title";
/** How many tournaments fit the activity chart before the bars get unreadable. */
const ACTIVITY_SPAN = 24;
const TOP_HEROES = 5;

const ROLES = [
  { key: "Tank", color: "var(--aqt-tank)", avg: "tank_avg_div" },
  { key: "Damage", color: "var(--aqt-damage)", avg: "damage_avg_div" },
  { key: "Support", color: "var(--aqt-support)", avg: "support_avg_div" }
] as const;

const BAR_CLASS = "flex-1 min-w-[3px] max-w-9 rounded-t-[3px]";

async function Shell({
  workspace,
  children
}: Readonly<{ workspace: Workspace; children: React.ReactNode }>) {
  const t = await getTranslations("workspace");
  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        rubric={t("stats.rubric")}
        title={t("stats.title")}
        titleId={TITLE_ID}
        sub={t("stats.sub")}
        aside={
          <ScopedMoreLink workspaceId={workspace.id} href="/statistics">
            {t("stats.all")}
          </ScopedMoreLink>
        }
      />
      {children}
    </Section>
  );
}

function StatsGrid({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="grid grid-cols-1 gap-x-10 gap-y-7 md:grid-cols-2 min-[1280px]:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)] [&>:first-child]:md:col-span-2 [&>:first-child]:min-[1280px]:col-span-1">
      {children}
    </div>
  );
}

export async function CommunityStatsSkeleton({
  workspace
}: Readonly<{ workspace: Workspace }>) {
  return (
    <Shell workspace={workspace}>
      <StatsGrid>
        <Column>
          <ColumnHead title={<Skeleton className="h-3 w-40" />} />
          <Skeleton className="mt-4 h-32 w-full" />
        </Column>
        <Column>
          <ColumnHead title={<Skeleton className="h-3 w-44" />} />
          <div className="mt-4 grid gap-2.5">
            {ROLES.map((role) => (
              <Skeleton key={role.key} className="h-10 w-full" />
            ))}
          </div>
        </Column>
        <Column>
          <ColumnHead title={<Skeleton className="h-3 w-36" />} />
          <div className="mt-4 grid gap-2.5">
            {Array.from({ length: TOP_HEROES }, (_, row) => (
              <Skeleton key={row} className="h-8 w-full" />
            ))}
          </div>
        </Column>
      </StatsGrid>
    </Shell>
  );
}

/** Three readings of the community's whole history: turnout, skill, heroes. */
export async function CommunityStats({ workspace }: Readonly<{ workspace: Workspace }>) {
  const workspaceId = workspace.id;
  const t = await getTranslations("workspace");

  const [history, division, heroes] = await Promise.all([
    statisticsService.getTournaments({ workspaceId }).catch(() => null),
    statisticsService.getTournamentsDivision({ workspaceId }).catch(() => null),
    heroService
      .getHeroPlaytime(1, TOP_HEROES, "all", null, { workspaceId })
      .catch(() => null)
  ]);

  if (history === null && division === null && heroes === null) {
    return (
      <Shell workspace={workspace}>
        <LoadError what={t("stats.what")} dashed />
      </Shell>
    );
  }

  return (
    <Shell workspace={workspace}>
      <StatsGrid>
        <ActivityColumn history={history} />
        <DivisionColumn workspace={workspace} division={division} />
        <HeroesColumn heroes={heroes?.results ?? null} />
      </StatsGrid>
    </Shell>
  );
}

/** Turnout per tournament, newest on the right and highlighted. */
async function ActivityColumn({
  history
}: Readonly<{ history: TournamentStatistics[] | null }>) {
  const [t, format] = await Promise.all([getTranslations("workspace"), getFormatter()]);
  const rows = (history ?? []).slice(-ACTIVITY_SPAN);

  if (history === null || rows.length === 0) {
    return (
      <Column>
        <ColumnHead title={t("stats.perTournament")} />
        {history === null ? <LoadError /> : null}
      </Column>
    );
  }

  const counts = rows.map((row) => row.players_count);
  const peak = Math.max(...counts);
  const low = Math.min(...counts);
  // At most eight labels under the bars, and always the newest one.
  const every = Math.ceil(rows.length / 8);

  return (
    <Column>
      <ColumnHead
        title={t("stats.perTournament")}
        sub={
          <>
            {t("stats.peak")}{" "}
            <b className="font-semibold tabular-nums text-[color:var(--aqt-fg)]">
              {format.number(peak)}
            </b>
          </>
        }
      />
      <div
        role="img"
        aria-label={t("stats.activityAlt", { count: rows.length, low, peak })}
        className="mt-4 flex h-32 items-end gap-1"
      >
        {rows.map((row, index) => (
          <span
            key={row.id}
            title={`${row.name}: ${t("participants", { count: row.players_count })}`}
            style={{ height: `${Math.max(3, (row.players_count / peak) * 100)}%` }}
            className={`${BAR_CLASS} ${
              index === rows.length - 1
                ? "bg-[color:var(--aqt-teal)]"
                : "bg-[color:color-mix(in_srgb,var(--aqt-teal)_28%,transparent)] hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_60%,transparent)]"
            }`}
          />
        ))}
      </div>
      <div className="mt-1.5 flex gap-1" aria-hidden>
        {rows.map((row, index) => (
          <span
            key={row.id}
            className={`${BAR_CLASS} overflow-visible whitespace-nowrap text-center font-[family-name:var(--aqt-data)] text-label font-medium leading-none tabular-nums text-[color:var(--aqt-fg-faint)]`}
          >
            {index % every === 0 || index === rows.length - 1 ? shortLabel(row.name, index) : ""}
          </span>
        ))}
      </div>
    </Column>
  );
}

/**
 * A tournament's number as the bar's label: "#42" from "Турнир Сабов Anakq #42",
 * "Д3" from a league's "Day 3", else its position in the run.
 */
function shortLabel(name: string, index: number): string {
  const numbered = /#(\d+)/.exec(name);
  if (numbered) return numbered[0];
  const day = /day\s*(\d+)/i.exec(name);
  if (day) return `Д${day[1]}`;
  return String(index + 1);
}

/** The community's average division, per role. */
async function DivisionColumn({
  workspace,
  division
}: Readonly<{ workspace: Workspace; division: TournamentDivisionStatistics[] | null }>) {
  const [t, format] = await Promise.all([getTranslations("workspace"), getFormatter()]);

  if (division === null) {
    return (
      <Column>
        <ColumnHead title={t("stats.divisions")} />
        <LoadError />
      </Column>
    );
  }

  const averages = ROLES.map((role) => {
    // A tournament with no players in a role reports null (or a 0 placeholder).
    const values = division
      .map((row) => row[role.avg])
      .filter((value): value is number => typeof value === "number" && value > 0);
    return {
      ...role,
      value: values.length === 0 ? null : values.reduce((sum, v) => sum + v, 0) / values.length
    };
  });

  return (
    <Column>
      <ColumnHead title={t("stats.divisions")} />
      <ul className="mt-4 grid gap-2.5">
        {averages.map((role) => (
          <li
            key={role.key}
            className="grid min-h-10 grid-cols-[22px_minmax(0,1fr)_36px_48px] items-center gap-2.5"
          >
            <PlayerRoleIcon role={role.key} size={20} color={role.color} decorative />
            <span className="text-[color:var(--aqt-fg-muted)]">{t(`roles.${role.key}`)}</span>
            {role.value === null ? (
              <span />
            ) : (
              <DivisionIcon
                division={Math.round(role.value)}
                tournamentGrid={workspace.default_division_grid_version}
                width={32}
                height={32}
                className="size-8 object-contain"
              />
            )}
            <span
              className="text-right font-[family-name:var(--aqt-data)] text-ui font-bold leading-none tabular-nums"
              style={{ color: role.color }}
            >
              {role.value === null
                ? "—"
                : format.number(role.value, {
                    minimumFractionDigits: 1,
                    maximumFractionDigits: 1
                  })}
            </span>
          </li>
        ))}
      </ul>
    </Column>
  );
}

/** Which heroes the community's matches are actually spent on. */
async function HeroesColumn({ heroes }: Readonly<{ heroes: HeroPlaytime[] | null }>) {
  const [t, format] = await Promise.all([getTranslations("workspace"), getFormatter()]);

  if (heroes === null || heroes.length === 0) {
    return (
      <Column>
        <ColumnHead title={t("stats.topHeroes")} sub={t("stats.topHeroesSub")} />
        {heroes === null ? <LoadError /> : null}
      </Column>
    );
  }

  // `playtime` is already a share of the community's total play time.
  const top = heroes.slice(0, TOP_HEROES);
  const leader = Math.max(...top.map((row) => row.playtime));

  return (
    <Column>
      <ColumnHead title={t("stats.topHeroes")} sub={t("stats.topHeroesSub")} />
      <ol className="mt-4 grid gap-2.5">
        {top.map((row) => {
          const role = row.hero.type ?? row.hero.role;
          const color =
            ROLES.find((entry) => entry.key === role)?.color ?? "var(--aqt-fg-muted)";
          const share = format.number(row.playtime, {
            style: "percent",
            minimumFractionDigits: 1,
            maximumFractionDigits: 1
          });
          return (
            <li
              key={row.hero.id}
              className="grid min-h-8 grid-cols-[28px_84px_minmax(0,1fr)_52px] items-center gap-2.5 text-caption"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- hero portraits live on the asset host next/image is not configured for */}
              <img
                src={row.hero.image_path}
                alt=""
                loading="lazy"
                decoding="async"
                className="size-7 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] object-cover"
              />
              <span className="truncate text-[color:var(--aqt-fg)]">{row.hero.name}</span>
              <span
                role="img"
                aria-label={t("stats.heroAlt", {
                  name: row.hero.name,
                  share,
                  role: role ? t(`roles.${role as "Tank" | "Damage" | "Support"}`).toLowerCase() : ""
                })}
                className="h-2 overflow-hidden rounded-[4px] bg-[color:var(--aqt-overlay-3)]"
              >
                <i
                  className="block h-full rounded-[inherit] bg-[color:var(--hero-c)]"
                  style={
                    { width: `${(row.playtime / leader) * 100}%`, "--hero-c": color } as CSSProperties
                  }
                />
              </span>
              <span className="text-right tabular-nums text-[color:var(--aqt-fg-dim)]">{share}</span>
            </li>
          );
        })}
      </ol>
    </Column>
  );
}
