import type { CSSProperties } from "react";
import { getTranslations } from "next-intl/server";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Column, ColumnHead, OpenLoadError, Section, SectionHead } from "@/components/site/open-layout";
import Image from "@/components/ui/image";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { orderedRoleCodes, roleName, roleTint, slotLabel } from "@/lib/roster/ontology";
import disciplineService from "@/services/discipline.service";
import statisticsService from "@/services/statistics.service";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { CharacterPlaytime } from "@/types/user.types";
import type { TournamentDivisionStatistics, TournamentStatistics } from "@/types/statistics.types";
import type { Workspace } from "@/types/workspace.types";

import { ScopedMoreLink } from "./WorkspaceScopeLink";

const TITLE_ID = "cs-title";
/** How many tournaments fit the activity chart before the bars get unreadable. */
const ACTIVITY_SPAN = 24;
const TOP_CHARACTERS = 5;
/** Placeholder rows while the game's roles are unknown. */
const SKELETON_ROLES = 3;

const BAR_CLASS = "flex-1 min-w-[3px] max-w-9 rounded-t-[3px]";

/** The section frame; `tabs` (the block's game tabs) stays above the body in every state, failed reads included. */
async function Shell({
  workspace,
  tabs = null,
  children
}: Readonly<{ workspace: Workspace; tabs?: React.ReactNode; children: React.ReactNode }>) {
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
      {tabs ? <div className="mb-4">{tabs}</div> : null}
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

export async function CommunityStatsSkeleton({ workspace }: Readonly<{ workspace: Workspace }>) {
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
            {Array.from({ length: SKELETON_ROLES }, (_, row) => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        </Column>
        <Column>
          <ColumnHead title={<Skeleton className="h-3 w-36" />} />
          <div className="mt-4 grid gap-2.5">
            {Array.from({ length: TOP_CHARACTERS }, (_, row) => (
              <Skeleton key={row} className="h-8 w-full" />
            ))}
          </div>
        </Column>
      </StatsGrid>
    </Shell>
  );
}

/**
 * Three readings of the community's whole history: turnout, and (of the block's game) skill and characters. Under
 * "all games" the two game-bound columns carry their own game tabs (`tabs`, spec §6.4).
 */
export async function CommunityStats({
  workspace,
  discipline,
  tabs = null
}: Readonly<{ workspace: Workspace; discipline: string | null; tabs?: React.ReactNode }>) {
  const workspaceId = workspace.id;
  const t = await getTranslations("workspace");

  const [history, division, ontology, characters] = await Promise.all([
    statisticsService.getTournaments({ workspaceId }).catch(() => null),
    discipline ? statisticsService.getTournamentsDivision(discipline, { workspaceId }).catch(() => null) : null,
    discipline ? disciplineService.metadata("all", discipline).catch(() => null) : null,
    discipline
      ? statisticsService
          .getCharacterPlaytime(discipline, { axis: workspaceId, perPage: TOP_CHARACTERS })
          .catch(() => null)
      : null
  ]);

  if (history === null && division === null && characters === null) {
    return (
      <Shell workspace={workspace} tabs={tabs}>
        <OpenLoadError what={t("stats.what")} dashed />
      </Shell>
    );
  }

  return (
    <Shell workspace={workspace} tabs={tabs}>
      <StatsGrid>
        <ActivityColumn history={history} />
        {discipline ? (
          <DivisionColumn workspace={workspace} discipline={discipline} division={division} ontology={ontology} />
        ) : null}
        {discipline ? <CharactersColumn characters={characters?.results ?? null} /> : null}
      </StatsGrid>
    </Shell>
  );
}

/** Turnout per tournament, newest on the right and highlighted. */
async function ActivityColumn({ history }: Readonly<{ history: TournamentStatistics[] | null }>) {
  const [t, format] = await Promise.all([getTranslations("workspace"), getFormatter()]);
  const rows = (history ?? []).slice(-ACTIVITY_SPAN);

  if (history === null || rows.length === 0) {
    return (
      <Column>
        <ColumnHead title={t("stats.perTournament")} />
        {history === null ? <OpenLoadError /> : null}
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

/** The community's average division in the browsed game, per role of that game's rated dimension. */
async function DivisionColumn({
  workspace,
  discipline,
  division,
  ontology
}: Readonly<{
  workspace: Workspace;
  discipline: string;
  division: TournamentDivisionStatistics[] | null;
  ontology: DisciplineMetadata | null;
}>) {
  const [t, tRoles, format] = await Promise.all([
    getTranslations("workspace"),
    getTranslations("common.roles"),
    getFormatter()
  ]);

  if (division === null) {
    return (
      <Column>
        <ColumnHead title={t("stats.divisions")} />
        <OpenLoadError />
      </Column>
    );
  }

  // A tournament reports only the roles somebody played; the column averages each over the tournaments that did.
  const codes = orderedRoleCodes(ontology, division.flatMap((row) => Object.keys(row.role_avg_divs)));
  const averages = codes.map((code) => {
    const values = division
      .map((row) => row.role_avg_divs[code])
      .filter((value): value is number => value !== undefined && value > 0);
    return {
      code,
      label: slotLabel(ontology, code, code, (role) =>
        roleName(role, (key) => (tRoles.has(key as never) ? tRoles(key as never) : null))
      ),
      color: roleTint(ontology, code),
      value: values.length === 0 ? null : values.reduce((sum, v) => sum + v, 0) / values.length
    };
  });

  return (
    <Column>
      <ColumnHead title={t("stats.divisions")} />
      <ul className="mt-4 grid gap-2.5">
        {averages.map((role) => (
          <li
            key={role.code}
            className="grid min-h-10 grid-cols-[22px_minmax(0,1fr)_36px_48px] items-center gap-2.5"
          >
            <PlayerRoleIcon role={role.code} ontology={ontology} size={20} decorative />
            <span className="text-[color:var(--aqt-fg-muted)]">{role.label}</span>
            {role.value === null ? (
              <span />
            ) : (
              <DivisionIcon
                division={Math.round(role.value)}
                tournamentGrid={workspace.effective_division_grid_versions[discipline]}
                discipline={discipline}
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

/** Which characters the community's matches are actually spent on. */
async function CharactersColumn({ characters }: Readonly<{ characters: CharacterPlaytime[] | null }>) {
  const [t, format] = await Promise.all([getTranslations("workspace"), getFormatter()]);

  if (characters === null || characters.length === 0) {
    return (
      <Column>
        <ColumnHead title={t("stats.topHeroes")} sub={t("stats.topHeroesSub")} />
        {characters === null ? <OpenLoadError /> : null}
      </Column>
    );
  }

  // `playtime` is already a share of the community's total play time.
  const top = characters.slice(0, TOP_CHARACTERS);
  const leader = Math.max(...top.map((row) => row.playtime));

  return (
    <Column>
      <ColumnHead title={t("stats.topHeroes")} sub={t("stats.topHeroesSub")} />
      <ol className="mt-4 grid gap-2.5">
        {top.map((row) => {
          // The character's own catalog colour, else the neutral ink — never a hue borrowed from a role.
          const color = typeof row.entity.attrs.color === "string" ? row.entity.attrs.color : "var(--aqt-fg-muted)";
          const share = format.number(row.playtime, {
            style: "percent",
            minimumFractionDigits: 1,
            maximumFractionDigits: 1
          });
          return (
            <li
              key={row.entity.id}
              className="grid min-h-8 grid-cols-[28px_84px_minmax(0,1fr)_52px] items-center gap-2.5 text-caption"
            >
              {row.entity.image_path ? (
                <Image
                  src={row.entity.image_path}
                  alt=""
                  width={28}
                  height={28}
                  className="size-7 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] object-cover"
                />
              ) : (
                <span
                  aria-hidden
                  className="size-7 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)]"
                />
              )}
              <span className="truncate text-[color:var(--aqt-fg)]">{row.entity.name}</span>
              <span
                role="img"
                aria-label={t("stats.heroAlt", { name: row.entity.name, share })}
                className="h-2 overflow-hidden rounded-[4px] bg-[color:var(--aqt-overlay-3)]"
              >
                <i
                  className="block h-full rounded-[inherit] bg-[color:var(--hero-c)]"
                  style={
                    {
                      width: `${(row.playtime / leader) * 100}%`,
                      "--hero-c": color
                    } as CSSProperties
                  }
                />
              </span>
              <span className="text-right tabular-nums text-[color:var(--aqt-fg-dim)]">
                {share}
              </span>
            </li>
          );
        })}
      </ol>
    </Column>
  );
}
