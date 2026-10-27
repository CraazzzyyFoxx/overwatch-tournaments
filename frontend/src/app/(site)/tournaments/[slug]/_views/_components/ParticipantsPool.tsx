"use client";

import { roleOf } from "@/lib/roster/role-ref";
import { ChevronDown } from "lucide-react";
import { useMemo } from "react";
import type { CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { HandleLabel } from "@/components/HandleLabel";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import DivisionIcon from "@/components/DivisionIcon";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { Card } from "@/components/ui/card";
import { answerFlag } from "@/lib/forms/answers";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import {
  ratedDimension,
  roleColor,
  showsRoles,
  slotCodeOrder,
  slotRank,
  type RoleOntology
} from "@/lib/roster/ontology";
import { isRoleSlot, OPEN_SLOT_CODE, slotCodesOf } from "@/lib/roster/shape";
import type { RosterShape } from "@/lib/roster/shape";
import { cn } from "@/lib/utils";
import type { CatalogEntityChip } from "@/types/catalog.types";
import type { Registration, RegistrationRole } from "@/types/registration.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { getPlayerSlug } from "@/lib/player";

import { TournamentPageState } from "../../_components/TournamentPageState";

/** The one status that means "was in, took themselves out" (§6 ④). */
const WITHDRAWN_STATUS = "withdrawn";

/**
 * How many players a role column shows before the rest move into a `<details>`.
 * A pool column can hold thirty names; the question the column answers ("how
 * deep is this role, who is at the top") is answered by the first screenful.
 */
const VISIBLE_PER_COLUMN = 10;

/**
 * A column whose role declares no colour reads as this neutral. One colour per column is exposed as
 * `--pool-role` on the card, so the accent rail, the icon chip and the leading positions all read from
 * a single value — the role's own presentation color from the owner game's ontology.
 */
const NEUTRAL_ROLE_COLOR = "var(--aqt-fg-muted)";

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
  heroesMap: Map<string, CatalogEntityChip>;
  /** The owner game's scoped ontology (role names, glyphs, colors); `null` while it loads. */
  ontology: RoleOntology | null;
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

/** Characters for one role, resolved through the catalogue with a slug fallback. */
function topHeroes(role: RegistrationRole, heroesMap: Map<string, CatalogEntityChip>, limit: number): CatalogEntityChip[] {
  const heroes: CatalogEntityChip[] = [];
  for (const slug of role.top_characters ?? []) {
    if (!slug || heroes.length >= limit) continue;
    const hero = heroesMap.get(slug);
    heroes.push(hero ?? { name: slug, slug, image_path: null, attrs: {} });
  }
  return heroes;
}

function PoolRow({
  entry,
  position,
  heroesMap,
  divisionGrid,
  ontology,
  showDivision,
  showHeroes
}: Readonly<{
  entry: PoolEntry;
  position: number;
  heroesMap: Map<string, CatalogEntityChip>;
  divisionGrid: DivisionGrid;
  ontology: RoleOntology | null;
  showDivision: boolean;
  showHeroes: boolean;
}>) {
  const t = useTranslations();
  const roleLabel = useSlotLabel(ontology);
  const { registration, role, division, isFlex } = entry;
  const rank = role.rank_value ?? null;
  const heroes = topHeroes(role, heroesMap, 3);
  const battleTag = registration.primary_handle ?? "\u2014";
  // A multi-role player is listed in every role column; in the columns of their
  // secondary roles the name is dimmed. That says "also plays this" without a
  // glyph — in a flex tournament nearly every row would carry the glyph and it
  // would say nothing.
  const secondary = isFlex && !role.is_primary;
  const flexTitle = isFlex
    ? t("tournamentDetail.participantsPool.flexTitle", {
        roles: (registration.roles ?? [])
          .map((declared) => roleLabel(roleOf(declared.role)))
          .join(" · ")
      })
    : null;

  // BattleTags are `Name#1234`; the discriminator is how you tell two Kennys
  // apart and nothing else, so it stays present and stops competing with the
  // name for attention.
  const label = <HandleLabel handle={battleTag} />;

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
        {registration.primary_handle ? (
          <a
            href={`/users/${getPlayerSlug(registration.primary_handle)}`}
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
        <CatalogEntityStrip entities={heroes} size={20} limit={3} className="justify-self-end" />
      ) : null}
    </li>
  );
}

function RoleColumn({
  role,
  entries,
  heroesMap,
  divisionGrid,
  ontology,
  showDivision
}: Readonly<{
  role: string;
  entries: PoolEntry[];
  heroesMap: Map<string, CatalogEntityChip>;
  divisionGrid: DivisionGrid;
  ontology: RoleOntology | null;
  showDivision: boolean;
}>) {
  const t = useTranslations();
  const roleLabel = useSlotLabel(ontology);
  const rated = ontology ? ratedDimension(ontology) : null;
  // A one-role game has one column, and it is everybody: named by no role.
  const named = showsRoles(ontology);
  const title = named ? roleLabel(role) : t("tournamentDetail.participantsPool.players");
  const visible = entries.slice(0, VISIBLE_PER_COLUMN);
  const rest = entries.slice(VISIBLE_PER_COLUMN);
  // Reserving the hero track in a column nobody filled in leaves a stripe of
  // nothing next to every name.
  const showHeroes = entries.some((entry) => (entry.role.top_characters?.length ?? 0) > 0);

  const renderRow = (entry: PoolEntry, index: number) => (
    <PoolRow
      key={entry.registration.id}
      entry={entry}
      position={index + 1}
      heroesMap={heroesMap}
      divisionGrid={divisionGrid}
      ontology={ontology}
      showDivision={showDivision}
      showHeroes={showHeroes}
    />
  );

  return (
    <Card asChild>
      <section
        className="relative overflow-hidden p-2 pt-3"
        style={{ "--pool-role": roleColor(ontology, role) ?? NEUTRAL_ROLE_COLOR } as CSSProperties}
        aria-label={
          named
            ? t("tournamentDetail.participantsPool.columnLabel", { role: title, count: entries.length })
            : title
        }
        data-pool-column={role}
      >
        {/* The column's identity: a role-tinted edge, readable before the label. */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,var(--pool-role),transparent_75%)]"
        />
        <h3 className="mb-2 flex items-center gap-2 px-1.5">
          {named ? (
            <span className="inline-flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md border border-[color:color-mix(in_srgb,var(--pool-role)_26%,transparent)] bg-[color:color-mix(in_srgb,var(--pool-role)_12%,transparent)] text-[color:var(--pool-role)]">
              <PlayerRoleIcon
                role={rated ? { dimension: rated.code, role } : null}
                ontology={ontology}
                size={13}
                decorative
              />
            </span>
          ) : null}
          <span className="aqt-display text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg)]">
            {title}
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
    </Card>
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
  ontology,
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

  // Columns come from the roster shape's role slots, never a fixed list of roles.
  // `flex` is dropped: it is a wildcard slot, not a role anybody registers as,
  // so a FLEX column would be permanently empty. Any role a player declared
  // that the shape does not list is appended, so nobody becomes invisible.
  const roleColumns = useMemo(() => {
    const fromShape = rosterShape ? slotCodesOf(rosterShape.slots).filter(isRoleSlot) : [];
    const order = slotCodeOrder(ontology);
    const declared = new Set<string>();
    for (const registration of active) {
      for (const role of registration.roles ?? []) {
        if (roleOf(role.role)) declared.add(roleOf(role.role));
      }
    }
    const extra = [...declared]
      .filter((role) => !fromShape.includes(role) && role !== OPEN_SLOT_CODE)
      // Roles the game does not declare sort after every declared one, then alphabetically.
      .sort((left, right) => slotRank(order, left) - slotRank(order, right) || left.localeCompare(right));
    return [...fromShape, ...extra];
  }, [active, ontology, rosterShape]);

  const normalizedSearch = search.trim().toLowerCase();

  const entriesByRole = useMemo(() => {
    const grouped = new Map<string, PoolEntry[]>();
    for (const role of roleColumns) grouped.set(role, []);

    for (const registration of active) {
      if (
        normalizedSearch.length > 0 &&
        !(registration.primary_handle?.toLowerCase().includes(normalizedSearch) ?? false)
      ) {
        continue;
      }
      const roles = registration.roles ?? [];
      const isFlex = roles.length > 1;
      for (const role of roles) {
        const bucket = grouped.get(roleOf(role.role));
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
        return (left.registration.primary_handle ?? "").localeCompare(
          right.registration.primary_handle ?? ""
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
            (registration.primary_handle?.toLowerCase().includes(normalizedSearch) ?? false))
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
            (registration.primary_handle?.toLowerCase().includes(normalizedSearch) ?? false))
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
              ontology={ontology}
              showDivision={showDivision}
            />
          ))}
        </div>
      ) : null}

      {reserves.length > 0 ? (
        <Card asChild>
          <section
            aria-label={t("tournamentDetail.participantsPool.reserve", {
              count: reserves.length
            })}
            className="border-[color:color-mix(in_srgb,var(--aqt-blue)_25%,transparent)] px-3 py-2"
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
                  {registration.primary_handle ?? "\u2014"}
                </li>
              ))}
            </ul>
          </section>
        </Card>
      ) : null}

      {withdrawn.length > 0 ? (
        <Card asChild>
          <details className="group px-3 py-2">
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
                  {registration.primary_handle ?? "\u2014"}
                </li>
              ))}
            </ul>
          </details>
        </Card>
      ) : null}
    </div>
  );
}
