"use client";

import { ChevronDown } from "lucide-react";
import { useMemo } from "react";
import type { CSSProperties } from "react";
import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import DivisionIcon from "@/components/DivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
import { answerFlag } from "@/lib/forms/answers";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { isRoleSlotCode, orderSlotCodes, ROSTER_SLOT_CODES } from "@/lib/roster-shape";
import type { RosterShape } from "@/lib/roster-shape";
import { cn } from "@/lib/utils";
import type { Hero } from "@/types/hero.types";
import type { Registration, RegistrationRole } from "@/types/registration.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { getPlayerSlug } from "@/utils/player";

import { getRoleLabel } from "./participantsColumns";
import { TournamentPageState } from "../../_components/TournamentPageState";

/** The one status that means "was in, took themselves out" (§6 ④). */
const WITHDRAWN_STATUS = "withdrawn";

/**
 * How many players a role column shows before the rest move into a `<details>`.
 * A pool column can hold thirty names; the question the column answers ("how
 * deep is this role, who is at the top") is answered by the first screenful.
 */
const VISIBLE_PER_COLUMN = 10;

/** Icon names `PlayerRoleIcon` knows, keyed by the registration role code. */
const ROLE_TO_ICON: Record<string, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex"
};

/**
 * One colour per column, exposed as `--pool-role` on the card so the accent
 * rail, the icon chip and the leading positions all read from a single value.
 */
const ROLE_COLOR: Record<string, string> = {
  tank: "var(--aqt-tank)",
  damage: "var(--aqt-damage)",
  support: "var(--aqt-support)",
  flex: "var(--aqt-teal)"
};

/** Positions that wear the role colour — the top of a role is the headline. */
const HIGHLIGHTED_POSITIONS = 3;

/**
 * Row track widths, spelled out per case because Tailwind only emits arbitrary
 * values it can see verbatim. A column with no divisions (before the balancer
 * assigns ranks) or no hero data must not reserve the space for it.
 */
const ROW_GRID: Record<string, string> = {
  "division-heroes": "grid-cols-[1.25rem_minmax(0,1fr)_1.25rem_3.25rem]",
  division: "grid-cols-[1.25rem_minmax(0,1fr)_1.25rem]",
  heroes: "grid-cols-[1.25rem_minmax(0,1fr)_3.25rem]",
  bare: "grid-cols-[1.25rem_minmax(0,1fr)]"
};

function rowGridClass(showDivision: boolean, showHeroes: boolean): string {
  if (showDivision && showHeroes) return ROW_GRID["division-heroes"];
  if (showDivision) return ROW_GRID.division;
  if (showHeroes) return ROW_GRID.heroes;
  return ROW_GRID.bare;
}

interface PoolEntry {
  registration: Registration;
  role: RegistrationRole;
  division: number | null;
  /** The player declared more than one role, so they sit in several columns. */
  isFlex: boolean;
}

export interface ParticipantsPoolProps {
  /** Every registration of the tournament, withdrawn ones included. */
  registrations: readonly Registration[];
  /** Drives which role columns exist; `null` falls back to the declared roles. */
  rosterShape: RosterShape | null;
  divisionGrid: DivisionGrid;
  heroesMap: Map<string, Hero>;
  search: string;
  division: number | null;
  /** Clears search + division for the filtered-empty state. */
  onResetFilters: () => void;
}

function isWithdrawn(registration: Registration): boolean {
  return registration.status === WITHDRAWN_STATUS;
}

/** Volunteered to be called in if somebody drops or they cannot make the start.
 *  An availability note, nothing more: they are in the field and in the role
 *  columns like anybody else. Read off the row's own public answer, exactly like
 *  the badge. */
function isReserve(registration: Registration): boolean {
  return answerFlag(registration.answers, "reserve");
}

/**
 * Divisions actually represented in the pool, ascending. Offering the whole
 * ladder would hand the reader twenty options of which three match anybody.
 */
export function poolDivisionOptions(
  registrations: readonly Registration[],
  grid: DivisionGrid
): number[] {
  const present = new Set<number>();
  for (const registration of registrations) {
    if (isWithdrawn(registration)) continue;
    for (const role of registration.roles ?? []) {
      const division = resolveDivisionFromRank(grid, role.rank_value);
      if (division != null) present.add(division);
    }
  }
  return [...present].sort((left, right) => left - right);
}

/** Heroes for one role, resolved through the catalogue with a slug fallback. */
function topHeroes(role: RegistrationRole, heroesMap: Map<string, Hero>, limit: number): Hero[] {
  const heroes: Hero[] = [];
  for (const slug of role.top_heroes ?? []) {
    if (!slug || heroes.length >= limit) continue;
    const hero = heroesMap.get(slug);
    heroes.push(hero ?? ({ name: slug, slug, image_path: "", role: role.role } as Hero));
  }
  return heroes;
}

function PoolRow({
  entry,
  position,
  heroesMap,
  divisionGrid,
  showDivision,
  showHeroes
}: Readonly<{
  entry: PoolEntry;
  position: number;
  heroesMap: Map<string, Hero>;
  divisionGrid: DivisionGrid;
  showDivision: boolean;
  showHeroes: boolean;
}>) {
  const t = useTranslations();
  const { registration, role, division, isFlex } = entry;
  const rank = role.rank_value ?? null;
  const heroes = topHeroes(role, heroesMap, 3);
  const battleTag = registration.battle_tag ?? "\u2014";
  // BattleTags are `Name#1234`; the discriminator is how you tell two Kennys
  // apart and nothing else, so it stays present and stops competing with the
  // name for attention.
  const hash = battleTag.indexOf("#");
  const name = hash > 0 ? battleTag.slice(0, hash) : battleTag;
  const discriminator = hash > 0 ? battleTag.slice(hash) : "";
  // A multi-role player is listed in every role column; in the columns of their
  // secondary roles the name is dimmed. That says "also plays this" without a
  // glyph — in a flex tournament nearly every row would carry the glyph and it
  // would say nothing.
  const secondary = isFlex && !role.is_primary;
  const flexTitle = isFlex
    ? t("tournamentDetail.participantsPool.flexTitle", {
        roles: (registration.roles ?? [])
          .map((declared) => getRoleLabel(declared.role, t))
          .join(" · ")
      })
    : null;

  const label = (
    <>
      <span className="truncate">{name}</span>
      {discriminator ? (
        <span className="shrink-0 text-[color:var(--aqt-fg-faint)]">{discriminator}</span>
      ) : null}
    </>
  );

  return (
    <li
      className={cn(
        "grid items-center gap-x-2 rounded-md px-1.5 py-[5px] transition-colors hover:bg-[color:var(--aqt-overlay-2)]",
        rowGridClass(showDivision, showHeroes)
      )}
      data-flex-mark={isFlex || undefined}
    >
      <span
        aria-hidden
        className={cn(
          "aqt-tnum text-right text-label tabular-nums",
          position <= HIGHLIGHTED_POSITIONS
            ? "text-[color:var(--pool-role)]"
            : "text-[color:var(--aqt-fg-faint)]"
        )}
      >
        {position}
      </span>
      <span className="flex min-w-0 items-baseline text-caption">
        {registration.battle_tag ? (
          <a
            href={`/users/${getPlayerSlug(registration.battle_tag)}`}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "flex min-w-0 items-baseline transition hover:text-[color:var(--aqt-teal)]",
              secondary
                ? "text-[color:var(--aqt-fg-muted)]"
                : "font-medium text-[color:var(--aqt-fg)]"
            )}
            title={flexTitle ?? battleTag}
          >
            {label}
          </a>
        ) : (
          <span className="flex min-w-0 items-baseline text-[color:var(--aqt-fg-dim)]">
            {label}
          </span>
        )}
        {flexTitle ? <span className="sr-only">{flexTitle}</span> : null}
      </span>
      {showDivision ? (
        // The icon is the division; the SR behind it stays available on hover
        // rather than spending a column of its own on five digits per row.
        <span
          className="justify-self-end leading-none"
          title={
            division != null && rank != null
              ? t("tournamentDetail.participantsPool.rank", { division, rank })
              : undefined
          }
        >
          {division != null ? (
            <DivisionIcon
              division={division}
              tournamentGrid={divisionGrid}
              width={20}
              height={20}
            />
          ) : (
            <span className="text-label text-[color:var(--aqt-fg-faint)]">{"\u2014"}</span>
          )}
        </span>
      ) : null}
      {showHeroes ? (
        <HeroStrip heroes={heroes} size={20} limit={3} className="justify-self-end" />
      ) : null}
    </li>
  );
}

function RoleColumn({
  role,
  entries,
  heroesMap,
  divisionGrid,
  showDivision
}: Readonly<{
  role: string;
  entries: PoolEntry[];
  heroesMap: Map<string, Hero>;
  divisionGrid: DivisionGrid;
  showDivision: boolean;
}>) {
  const t = useTranslations();
  const visible = entries.slice(0, VISIBLE_PER_COLUMN);
  const rest = entries.slice(VISIBLE_PER_COLUMN);
  // Reserving the hero track in a column nobody filled in leaves a stripe of
  // nothing next to every name.
  const showHeroes = entries.some((entry) => (entry.role.top_heroes?.length ?? 0) > 0);

  const renderRow = (entry: PoolEntry, index: number) => (
    <PoolRow
      key={entry.registration.id}
      entry={entry}
      position={index + 1}
      heroesMap={heroesMap}
      divisionGrid={divisionGrid}
      showDivision={showDivision}
      showHeroes={showHeroes}
    />
  );

  return (
    <section
      className="relative overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-2 pt-3"
      style={{ "--pool-role": ROLE_COLOR[role] ?? "var(--aqt-fg-muted)" } as CSSProperties}
      aria-label={t("tournamentDetail.participantsPool.columnLabel", {
        role: getRoleLabel(role, t),
        count: entries.length
      })}
      data-pool-column={role}
    >
      {/* The column's identity: a role-tinted edge, readable before the label. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,var(--pool-role),transparent_75%)]"
      />
      <h3 className="mb-2 flex items-center gap-2 px-1.5">
        <span className="inline-flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md border border-[color:color-mix(in_srgb,var(--pool-role)_26%,transparent)] bg-[color:color-mix(in_srgb,var(--pool-role)_12%,transparent)] text-[color:var(--pool-role)]">
          <PlayerRoleIcon role={ROLE_TO_ICON[role] ?? role} size={13} decorative />
        </span>
        <span className="aqt-display text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg)]">
          {getRoleLabel(role, t)}
        </span>
        <span className="aqt-tnum ml-auto rounded-md bg-[color:var(--aqt-overlay-2)] px-1.5 py-px text-label tabular-nums text-[color:var(--aqt-fg-muted)]">
          {entries.length}
        </span>
      </h3>
      {entries.length === 0 ? (
        <p className="px-1.5 py-1 text-xs text-[color:var(--aqt-fg-dim)]">
          {t("tournamentDetail.participantsPool.columnEmpty")}
        </p>
      ) : (
        <ul>{visible.map(renderRow)}</ul>
      )}
      {rest.length > 0 ? (
        <details className="group mt-1 border-t border-[color:var(--aqt-border)] pt-1">
          <summary className="flex cursor-pointer list-none items-center gap-1 rounded-md px-1.5 py-1 text-label text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-2)] hover:text-[color:var(--aqt-fg)]">
            <ChevronDown
              size={12}
              aria-hidden
              className="transition-transform group-open:rotate-180"
            />
            {t("tournamentDetail.participantsPool.more", { count: rest.length })}
          </summary>
          <ul>{rest.map((entry, index) => renderRow(entry, index + VISIBLE_PER_COLUMN))}</ul>
        </details>
      ) : null}
    </section>
  );
}

/**
 * The player pool of a balancer/draft tournament (§6 ②③④): one column per role
 * slot the roster shape asks for, each sorted by rank, a player who declared
 * several roles listed in every one of them, and the withdrawn registrations
 * folded away at the bottom instead of eating a filter chip.
 */
export default function ParticipantsPool({
  registrations,
  rosterShape,
  divisionGrid,
  heroesMap,
  search,
  division,
  onResetFilters
}: Readonly<ParticipantsPoolProps>) {
  const t = useTranslations();

  // The field: everybody who has not withdrawn. The `reserve` answer says
  // nothing about depth at a role, so it does not take a name out of a column.
  const active = useMemo(
    () => registrations.filter((registration) => !isWithdrawn(registration)),
    [registrations]
  );

  // Columns come from the roster shape's role slots, never a hardcoded trio.
  // `flex` is dropped: it is a wildcard slot, not a role anybody registers as,
  // so a FLEX column would be permanently empty. Any role a player declared
  // that the shape does not list is appended, so nobody becomes invisible.
  const roleColumns = useMemo(() => {
    const fromShape = rosterShape ? orderSlotCodes(rosterShape.slots).filter(isRoleSlotCode) : [];
    const declared = new Set<string>();
    for (const registration of active) {
      for (const role of registration.roles ?? []) {
        if (role.role) declared.add(role.role);
      }
    }
    const extra = [...declared]
      .filter((role) => !fromShape.includes(role as (typeof fromShape)[number]) && role !== "flex")
      .sort((left, right) => {
        // Unknown codes sort after every canonical one, then alphabetically.
        const leftIndex = ROSTER_SLOT_CODES.indexOf(left as (typeof ROSTER_SLOT_CODES)[number]);
        const rightIndex = ROSTER_SLOT_CODES.indexOf(right as (typeof ROSTER_SLOT_CODES)[number]);
        const leftRank = leftIndex === -1 ? ROSTER_SLOT_CODES.length : leftIndex;
        const rightRank = rightIndex === -1 ? ROSTER_SLOT_CODES.length : rightIndex;
        return leftRank - rightRank || left.localeCompare(right);
      });
    return [...fromShape, ...extra] as string[];
  }, [active, rosterShape]);

  const normalizedSearch = search.trim().toLowerCase();

  const entriesByRole = useMemo(() => {
    const grouped = new Map<string, PoolEntry[]>();
    for (const role of roleColumns) grouped.set(role, []);

    for (const registration of active) {
      if (
        normalizedSearch.length > 0 &&
        !(registration.battle_tag?.toLowerCase().includes(normalizedSearch) ?? false)
      ) {
        continue;
      }
      const roles = registration.roles ?? [];
      const isFlex = roles.length > 1;
      for (const role of roles) {
        const bucket = grouped.get(role.role);
        if (!bucket) continue;
        const entryDivision = resolveDivisionFromRank(divisionGrid, role.rank_value);
        if (division != null && entryDivision !== division) continue;
        bucket.push({ registration, role, division: entryDivision, isFlex });
      }
    }

    for (const bucket of grouped.values()) {
      bucket.sort((left, right) => {
        const leftRank = left.role.rank_value ?? -1;
        const rightRank = right.role.rank_value ?? -1;
        if (leftRank !== rightRank) return rightRank - leftRank;
        // Players who main this role before those who only also play it.
        if (left.role.is_primary !== right.role.is_primary) return left.role.is_primary ? -1 : 1;
        return (left.registration.battle_tag ?? "").localeCompare(
          right.registration.battle_tag ?? ""
        );
      });
    }
    return grouped;
  }, [active, division, divisionGrid, normalizedSearch, roleColumns]);

  const withdrawn = useMemo(
    () =>
      registrations.filter(
        (registration) =>
          isWithdrawn(registration) &&
          (normalizedSearch.length === 0 ||
            (registration.battle_tag?.toLowerCase().includes(normalizedSearch) ?? false))
      ),
    [normalizedSearch, registrations]
  );

  // A lookup aid, not a bucket: these names are already in the role columns
  // above, and this is just "who did I say I could call". Searchable like every
  // other name, and deliberately not division-filtered — a division filter
  // would empty the list for anybody the balancer has not ranked yet.
  const reserves = useMemo(
    () =>
      registrations.filter(
        (registration) =>
          !isWithdrawn(registration) &&
          isReserve(registration) &&
          (normalizedSearch.length === 0 ||
            (registration.battle_tag?.toLowerCase().includes(normalizedSearch) ?? false))
      ),
    [normalizedSearch, registrations]
  );

  const shownPlayers = useMemo(() => {
    const ids = new Set<number>();
    for (const bucket of entriesByRole.values()) {
      for (const entry of bucket) ids.add(entry.registration.id);
    }
    return ids.size;
  }, [entriesByRole]);

  // Before the organizer assigns ranks (the balancer does, after registration
  // closes) no entry resolves to a division, and a column of em dashes is noise.
  const showDivision = useMemo(() => {
    for (const bucket of entriesByRole.values()) {
      if (bucket.some((entry) => entry.division != null)) return true;
    }
    return false;
  }, [entriesByRole]);

  if (shownPlayers === 0 && reserves.length === 0 && withdrawn.length === 0) {
    const isFiltered = normalizedSearch.length > 0 || division != null;
    return isFiltered ? (
      <TournamentPageState state="filtered-empty" onReset={onResetFilters} />
    ) : (
      <TournamentPageState
        state="empty"
        title={t("tournamentDetail.participants.empty.title")}
        description={t("tournamentDetail.participants.empty.description")}
      />
    );
  }

  return (
    <div className="space-y-4">
      <p aria-atomic="true" aria-live="polite" className="sr-only">
        {t("tournamentDetail.participantsPool.resultCount", { count: shownPlayers })}
      </p>

      {roleColumns.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {roleColumns.map((role) => (
            <RoleColumn
              key={role}
              role={role}
              entries={entriesByRole.get(role) ?? []}
              heroesMap={heroesMap}
              divisionGrid={divisionGrid}
              showDivision={showDivision}
            />
          ))}
        </div>
      ) : null}

      {reserves.length > 0 ? (
        <section
          aria-label={t("tournamentDetail.participantsPool.reserve", {
            count: reserves.length
          })}
          className="rounded-xl border border-[color:color-mix(in_srgb,var(--aqt-blue)_25%,transparent)] bg-[color:var(--aqt-card)] px-3 py-2"
          data-pool-reserve="true"
        >
          <h3 className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-blue)]">
            {t("tournamentDetail.participantsPool.reserve", { count: reserves.length })}
          </h3>
          <p className="mt-0.5 text-xs text-[color:var(--aqt-fg-dim)]">
            {t("tournamentDetail.participantsPool.reserveDesc")}
          </p>
          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {reserves.map((registration) => (
              <li key={registration.id} className="text-xs text-[color:var(--aqt-fg-muted)]">
                {registration.battle_tag ?? "\u2014"}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {withdrawn.length > 0 ? (
        <details className="group rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-3 py-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)]">
            <ChevronDown
              size={12}
              aria-hidden
              className="transition-transform group-open:rotate-180"
            />
            {t("tournamentDetail.participantsPool.withdrawn", { count: withdrawn.length })}
          </summary>
          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {withdrawn.map((registration) => (
              <li
                key={registration.id}
                className="text-xs text-[color:var(--aqt-fg-dim)] line-through"
              >
                {registration.battle_tag ?? "\u2014"}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
