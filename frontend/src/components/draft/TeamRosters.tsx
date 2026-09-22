"use client";

import { Ban, Crown, Shuffle } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftPick, DraftPlayer, DraftRole, DraftTeam } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { teamCrest } from "@/lib/draft-crest";
import {
  buildRosterByTeam,
  slotRankForPlayer,
  rosterRoleForPlayer
} from "@/lib/draft-workspace-model";
import {
  isRoleSlotCode,
  orderSlotCodes,
  ROSTER_SLOT_CODES,
  type RosterRoleSlotCode,
  type RosterShape
} from "@/lib/roster-shape";

interface TeamRostersProps {
  teams: DraftTeam[];
  players: DraftPlayer[];
  picks: DraftPick[];
  shape: RosterShape;
  myTeamId?: number | null;
  focusTeamOnly?: boolean;
  onClockTeamId?: number | null;
  divisionGrid: DivisionGrid;
  /** Vertical compact card list (mockup `.teams-col`) vs the default grid of full team cards. */
  variant?: "grid" | "column";
  /** Auth user ids of captains currently connected, for the column card's captain dot. */
  onlineCaptainIds?: ReadonlySet<number>;
  /**
   * Captain only: clicking one of MY team's open role slots filters the pool to
   * that role. Omitted (or an all-flex shape) leaves every open slot inert.
   */
  onSlotFilter?: (role: DraftRole | null) => void;
  /** The pool's current role filter, so the pressed slot reads as pressed. */
  activeSlotRole?: DraftRole | null;
}

/**
 * One slot of the shape next to what the roster currently holds. A flex slot
 * carries no fill count: only the server's slot matching knows which player
 * occupies one, and guessing it here would be the mirror this feature removes.
 */
type SlotCounter =
  | { code: RosterRoleSlotCode; target: number; filled: number }
  | { code: "flex"; target: number };

interface TeamRosterView {
  roster: DraftPlayer[];
  counters: SlotCounter[];
  avgRank: number | null;
  avgDivision: number | null;
  openSlots: number;
  /**
   * One entry per open slot, naming the role the SHAPE still wants there
   * (`null` once the role deficits are exhausted — a flex slot, or a slot held
   * by a player the shape assigned no role).
   */
  openSlotCodes: (RosterRoleSlotCode | null)[];
}

function computeTeamRosterView(
  team: DraftTeam,
  rosters: Map<number, DraftPlayer[]>,
  picks: DraftPick[],
  shape: RosterShape,
  divisionGrid: DivisionGrid
): TeamRosterView {
  // A player with no playable role holds no slot: sort them after every slot
  // code instead of pretending they fill one.
  const slotOrder = (player: DraftPlayer) => {
    const role = rosterRoleForPlayer(player, picks);
    return role == null ? ROSTER_SLOT_CODES.length : ROSTER_SLOT_CODES.indexOf(role);
  };
  const roster = [...(rosters.get(team.id) ?? [])].sort((a, b) => slotOrder(a) - slotOrder(b));
  const rosterRoles = roster.map((player) => rosterRoleForPlayer(player, picks));
  const counters: SlotCounter[] = orderSlotCodes(shape.slots).map((code) =>
    isRoleSlotCode(code)
      ? {
          code,
          target: shape.slots[code] ?? 0,
          filled: rosterRoles.filter((role) => role === code).length
        }
      : { code, target: shape.slots[code] ?? 0 }
  );
  const rankValues = roster
    .map((player, index) => slotRankForPlayer(player, rosterRoles[index], shape))
    .filter((value): value is number => value != null);
  const avgRank =
    rankValues.length > 0 ? rankValues.reduce((sum, value) => sum + value, 0) / rankValues.length : null;
  const avgDivision = avgRank == null ? null : resolveDivisionFromRank(divisionGrid, avgRank);
  const openSlots = Math.max(0, shape.team_size - roster.length);
  const openSlotCodes: (RosterRoleSlotCode | null)[] = [];
  for (const counter of counters) {
    if (counter.code === "flex") continue;
    for (let index = counter.filled; index < counter.target; index += 1) {
      openSlotCodes.push(counter.code);
    }
  }
  while (openSlotCodes.length < openSlots) openSlotCodes.push(null);
  openSlotCodes.length = openSlots;
  return { roster, counters, avgRank, avgDivision, openSlots, openSlotCodes };
}

/**
 * The shape's slot counters. Callers render this only when at least one slot
 * asks for a role: under an all-flex shape a row of `0/0` per role would state
 * a requirement that does not exist, which is the confusion this feature removes.
 */
function SlotCounters({ counters, accented }: Readonly<{ counters: SlotCounter[]; accented: boolean }>) {
  const t = useTranslations("draftRedesign");
  return (
    <>
      {counters.map((counter) => {
        if (counter.code === "flex") {
          return (
            <span key="flex" className="inline-flex items-center gap-1" title={t("roles.flex")}>
              <Shuffle className="h-3.5 w-3.5" aria-hidden />
              <span className="sr-only">{t("roles.flex")}</span>×{counter.target}
            </span>
          );
        }
        const { code, target, filled } = counter;
        const accent = accented ? ROLE_ACCENT[code] : undefined;
        return (
          <span
            key={code}
            className="inline-flex items-center gap-1"
            style={accent ? { color: accent } : undefined}
            title={t(`roles.${code}`)}
          >
            <PlayerRoleIcon role={getRoleIconName(code)} size={14} color={accent} />
            <span className="sr-only">{t(`roles.${code}`)}</span>
            {filled}/{target}
          </span>
        );
      })}
    </>
  );
}

/**
 * The glyph on a roster row. A role-less (all-flex) roster assigns nobody a
 * role, so it gets the flex glyph: a role icon there would state an assignment
 * the shape never made, which is exactly the mirror this feature removes. A
 * `null` role is different — the player has no playable role at all — and gets
 * the ban glyph rather than a stand-in role. The captain's crown outranks all
 * three: it is a position, not a slot.
 */
function RosterRowIcon({
  player,
  role,
  hasRoleSlots
}: Readonly<{
  player: DraftPlayer;
  role: RosterRoleSlotCode | null;
  hasRoleSlots: boolean;
}>) {
  if (player.is_captain) return <Crown className="h-4 w-4 text-[color:var(--aqt-warm)]" />;
  if (!hasRoleSlots) return <Shuffle className="h-4 w-4 text-[color:var(--aqt-fg-muted)]" aria-hidden />;
  if (role == null) return <Ban className="h-4 w-4 text-[color:var(--aqt-fg-faint)]" aria-hidden />;
  return <PlayerRoleIcon role={getRoleIconName(role)} size={16} />;
}

/**
 * The text of one open slot. On MY team it is a real button: an empty support
 * slot is the shortest possible way to say "show me the supports", so pressing
 * it filters the pool instead of making the captain find the role chip.
 */
function OpenSlotLabel({
  ordinal,
  code,
  filterable,
  active,
  onSlotFilter
}: Readonly<{
  ordinal: number;
  code: RosterRoleSlotCode | null;
  filterable: boolean;
  active: boolean;
  onSlotFilter?: (role: DraftRole | null) => void;
}>) {
  const t = useTranslations("draftRedesign");
  const text = `${t("openSlot")} ${ordinal}`;
  if (!filterable || code == null || !onSlotFilter) {
    return <>{text}</>;
  }
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={t("filterBySlot", { role: t(`roles.${code}`) })}
      onClick={() => onSlotFilter(active ? null : code)}
      className={cn(
        "inline-flex min-h-8 items-center gap-1.5 rounded-md border px-1.5 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]",
        active
          ? "border-[color:var(--aqt-teal)] bg-[color:var(--aqt-teal)]/15 text-[color:var(--aqt-fg)]"
          : "border-dashed border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-dim)] hover:border-[color:var(--aqt-teal)]/60"
      )}
    >
      <PlayerRoleIcon role={getRoleIconName(code)} size={14} color={ROLE_ACCENT[code]} decorative />
      <span className="truncate">{text}</span>
    </button>
  );
}

export function TeamRosters({
  teams,
  players,
  picks,
  shape,
  myTeamId = null,
  focusTeamOnly = false,
  onClockTeamId = null,
  divisionGrid,
  variant = "grid",
  onlineCaptainIds,
  onSlotFilter,
  activeSlotRole = null
}: Readonly<TeamRostersProps>) {
  const t = useTranslations("draftRedesign");
  const rosters = buildRosterByTeam(players);

  if (variant === "column") {
    const columnTeams = [...teams].sort((left, right) => left.draft_position - right.draft_position);
    return (
      <section aria-labelledby="team-rosters-column-heading">
        <div className="border-b border-[color:var(--aqt-border)] pb-3">
          <h2 id="team-rosters-column-heading" className="font-onest text-lg font-semibold">
            {t("teamRosters")}
          </h2>
        </div>
        <div className="mt-4 flex flex-col gap-3 overflow-y-auto">
          {columnTeams.map((team) => {
            const view = computeTeamRosterView(team, rosters, picks, shape, divisionGrid);
            const onClock = team.id === onClockTeamId;
            const isMine = team.id === myTeamId;
            const crest = teamCrest(team);
            const captainOnline =
              team.captain_auth_user_id != null && (onlineCaptainIds?.has(team.captain_auth_user_id) ?? false);

            return (
              <div
                key={team.id}
                className={cn(
                  "min-w-0 overflow-hidden rounded-[14px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]",
                  isMine && "border-[color:var(--aqt-teal)]/60",
                  // Border (not ring): the sidebar scroll container clips outer
                  // box-shadows, which left a ring visible only at the corners.
                  onClock &&
                    "border-[color:var(--aqt-teal)] shadow-[0_0_22px_color-mix(in_srgb,var(--aqt-teal)_20%,transparent)]"
                )}
              >
                {onClock && (
                  <p className="px-3 pt-2 text-label font-bold uppercase tracking-label text-[color:var(--aqt-teal)]">
                    {t("onTheClock")}
                  </p>
                )}
                <div className="flex items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-3 py-2.5">
                  <span
                    className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-[9px] text-caption font-extrabold"
                    style={{ background: `hsl(${crest.hue} 55% 22%)`, color: `hsl(${crest.hue} 70% 72%)` }}
                  >
                    {crest.initial}
                  </span>
                  <span className="min-w-0 truncate text-ui font-semibold tracking-tight">{team.name}</span>
                  <span className="inline-flex shrink-0 items-center">
                    <span
                      aria-hidden
                      className="h-[7px] w-[7px] rounded-full"
                      style={
                        captainOnline
                          ? { background: "var(--aqt-support)", boxShadow: "0 0 5px var(--aqt-support)" }
                          : { background: "var(--aqt-fg-faint)" }
                      }
                    />
                    <span className="sr-only">
                      {captainOnline ? t("captainOnline") : t("captainOffline")}
                    </span>
                  </span>
                  <span className="ml-auto flex shrink-0 items-center gap-2">
                    {view.avgDivision != null && (
                      <span
                        title={`${getDivisionLabel(divisionGrid, view.avgDivision)} · ${view.avgRank!.toFixed(0)} SR`}
                      >
                        <DivisionIcon
                          division={view.avgDivision}
                          width={24}
                          height={24}
                          className="h-6 w-6 object-contain"
                          tournamentGrid={divisionGrid}
                        />
                      </span>
                    )}
                    <span className="text-xs text-[color:var(--aqt-fg-faint)]">
                      #{team.draft_position}
                    </span>
                  </span>
                </div>
                {shape.has_role_slots && (
                  <div className="flex gap-4 border-b border-[color:var(--aqt-border)] px-3 py-2 text-xs text-[color:var(--aqt-fg-muted)]">
                    <SlotCounters counters={view.counters} accented />
                  </div>
                )}
                <div className="divide-y divide-[color:var(--aqt-border)]">
                  {view.roster.map((player) => {
                    const role = rosterRoleForPlayer(player, picks);
                    const rank = slotRankForPlayer(player, role, shape);
                    const slotLabel = !shape.has_role_slots
                      ? t("roles.flex")
                      : role == null
                        ? t("noRole")
                        : t(`roles.${role}`);
                    const division = resolveDivisionFromRank(divisionGrid, rank);
                    const divisionLabel = division == null ? null : getDivisionLabel(divisionGrid, division);
                    return (
                      <div
                        key={player.id}
                        className="grid grid-cols-[24px_1fr_auto] items-center gap-2 px-3 py-2 text-sm"
                      >
                        <span className="inline-flex h-6 w-6 items-center justify-center" title={slotLabel}>
                          <RosterRowIcon player={player} role={role} hasRoleSlots={shape.has_role_slots} />
                        </span>
                        <span className="min-w-0 truncate font-medium" title={player.battle_tag ?? undefined}>{player.battle_tag ?? `#${player.id}`}</span>
                        {division != null ? (
                          <span title={[divisionLabel, rank != null ? `${rank} SR` : null].filter(Boolean).join(" · ")}>
                            <DivisionIcon
                              division={division}
                              width={26}
                              height={26}
                              className="h-[26px] w-[26px] object-contain"
                              tournamentGrid={divisionGrid}
                            />
                          </span>
                        ) : (
                          <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                        )}
                      </div>
                    );
                  })}
                  {view.openSlotCodes.map((code, index) => (
                    <div
                      key={`open-${index}`}
                      className="grid grid-cols-[24px_1fr_auto] items-center gap-2 px-3 py-2 text-sm"
                    >
                      {/* --aqt-fg-dim, not faint behind an opacity: an open slot still
                          has to be readable, it is roster information. */}
                      <span className="inline-flex h-6 w-6 items-center justify-center text-[color:var(--aqt-fg-dim)]">
                        ·
                      </span>
                      <span className="min-w-0 truncate italic text-[color:var(--aqt-fg-dim)]">
                        <OpenSlotLabel
                          ordinal={view.roster.length + index + 1}
                          code={code}
                          filterable={isMine && shape.has_role_slots}
                          active={activeSlotRole === code}
                          onSlotFilter={onSlotFilter}
                        />
                      </span>
                      <span className="text-[color:var(--aqt-fg-dim)]">—</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    );
  }

  const visibleTeams =
    focusTeamOnly && myTeamId != null
      ? teams.filter((team) => team.id === myTeamId)
      : [...teams].sort((left, right) => left.draft_position - right.draft_position);

  return (
    <section aria-labelledby="team-rosters-heading">
      <div className="border-b border-[color:var(--aqt-border)] pb-3">
        <h2 id="team-rosters-heading" className="font-onest text-lg font-semibold">
          {focusTeamOnly ? t("myTeam") : t("teamRosters")}
        </h2>
      </div>
      <div
        className={cn(
          "mt-4 grid gap-4",
          focusTeamOnly ? "grid-cols-1" : "md:grid-cols-2 xl:grid-cols-3"
        )}
      >
        {visibleTeams.map((team) => {
          const view = computeTeamRosterView(team, rosters, picks, shape, divisionGrid);
          const { roster, avgRank, avgDivision, openSlots, openSlotCodes } = view;
          const onClock = team.id === onClockTeamId;
          const isMine = team.id === myTeamId;

          return (
            <TournamentTeamCardFrame
              key={team.id}
              name={team.name}
              className={cn(
                "min-w-0",
                onClock && "ring-2 ring-[color:var(--aqt-teal)] ring-offset-2 ring-offset-[color:var(--aqt-bg)]"
              )}
              style={team.id === myTeamId ? { borderColor: "var(--aqt-teal)" } : undefined}
              metricValue={
                avgDivision != null ? (
                  <span title={`${getDivisionLabel(divisionGrid, avgDivision)} · ${avgRank!.toFixed(0)} SR`}>
                    <DivisionIcon
                      division={avgDivision}
                      width={26}
                      height={26}
                      className="h-6 w-6 object-contain"
                      tournamentGrid={divisionGrid}
                    />
                  </span>
                ) : undefined
              }
            >
              {onClock && (
                <p className="px-4 pt-2 text-xs font-semibold uppercase tracking-wide text-[color:var(--aqt-teal)]">
                  {t("onTheClock")}
                </p>
              )}
              {shape.has_role_slots && (
                <div className="flex flex-wrap gap-3 px-4 pt-2 text-xs text-[color:var(--aqt-fg-muted)]">
                  <SlotCounters counters={view.counters} accented={false} />
                </div>
              )}
              {roster.length > 0 || openSlots > 0 ? (
                <div className="roster-scroll">
                  <table className="roster">
                    <thead>
                      <tr>
                        {/* Without role slots nobody holds a role: every row
                            carries the flex glyph, so the column names it. */}
                        <th className="c" style={{ width: 48 }}>
                          {shape.has_role_slots ? t("role") : t("roles.flex")}
                        </th>
                        <th>{t("sortName")}</th>
                        <th className="c" style={{ width: 68 }}>
                          {t("rank")}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {roster.map((player) => {
                        const role = rosterRoleForPlayer(player, picks);
                        const rank = slotRankForPlayer(player, role, shape);
                        const slotLabel = !shape.has_role_slots
                          ? t("roles.flex")
                          : role == null
                            ? t("noRole")
                            : t(`roles.${role}`);
                        const division = resolveDivisionFromRank(divisionGrid, rank);
                        const divisionLabel =
                          division == null ? null : getDivisionLabel(divisionGrid, division);
                        return (
                          <tr key={player.id}>
                            <td className="c">
                              <span
                                className="inline-flex h-8 w-8 items-center justify-center"
                                title={slotLabel}
                              >
                                <RosterRowIcon player={player} role={role} hasRoleSlots={shape.has_role_slots} />
                              </span>
                            </td>
                            <td>
                              <span
                                className="block max-w-[16rem] truncate font-medium"
                                title={player.battle_tag ?? undefined}
                              >
                                {player.battle_tag ?? `#${player.id}`}
                              </span>
                            </td>
                            <td className="c">
                              {division != null ? (
                                <span
                                  className="inline-flex rounded-md px-1 py-0.5"
                                  title={[divisionLabel, rank != null ? `${rank} SR` : null]
                                    .filter(Boolean)
                                    .join(" · ")}
                                >
                                  <DivisionIcon
                                    division={division}
                                    width={32}
                                    height={32}
                                    className="h-8 w-8 object-contain drop-shadow-[0_3px_8px_rgba(0,0,0,0.35)]"
                                    tournamentGrid={divisionGrid}
                                  />
                                </span>
                              ) : (
                                <span className="text-[color:var(--aqt-fg-faint)]">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                      {openSlotCodes.map((code, index) => (
                        <tr key={`open-${index}`}>
                          <td className="c">
                            <span className="inline-flex h-8 w-8 items-center justify-center text-[color:var(--aqt-fg-dim)]">—</span>
                          </td>
                          <td>
                            <span className="block max-w-[16rem] truncate text-[color:var(--aqt-fg-dim)]">
                              <OpenSlotLabel
                                ordinal={roster.length + index + 1}
                                code={code}
                                filterable={isMine && shape.has_role_slots}
                                active={activeSlotRole === code}
                                onSlotFilter={onSlotFilter}
                              />
                            </span>
                          </td>
                          <td className="c">
                            <span className="text-[color:var(--aqt-fg-dim)]">—</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="px-4 py-6 text-sm text-[color:var(--aqt-fg-muted)]">
                  {t("emptyRoster")}
                </p>
              )}
            </TournamentTeamCardFrame>
          );
        })}
      </div>
    </section>
  );
}
