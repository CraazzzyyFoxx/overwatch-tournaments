"use client";

import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, type CSSProperties } from "react";

import { splitBattleTag } from "@/components/balancer/balancer-page-helpers";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useDraftLayerPad } from "@/hooks/useDraftLayerPad";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import {
  teamsNeedingRole,
  turnsUntil,
  type TeamFilter,
  type TeamSlotCell,
  type TeamSort,
  type TeamView
} from "@/lib/draft/room-model";
import { slotRankForPlayer } from "@/lib/draft/workspace-model";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roster/roles";
import { isRoleSlotCode, orderSlotCodes, type RosterSlotCode } from "@/lib/roster/shape";
import { cn } from "@/lib/utils";
import type { DraftBoard, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

interface TeamRostersProps {
  board: DraftBoard;
  teamViews: ReadonlyMap<number, TeamView>;
  /** Already filtered and sorted (`filterSortTeams`). */
  teams: readonly TeamView[];
  filter: TeamFilter;
  onFilterChange: (filter: TeamFilter) => void;
  sort: TeamSort;
  onSortChange: (sort: TeamSort) => void;
  followed: ReadonlySet<number>;
  onToggleFollow: (teamId: number) => void;
  myTeamId: number | null;
  onlineCaptainIds: ReadonlySet<number>;
  onOpenProfile: (playerId: number) => void;
  onSlotFilter?: (role: DraftRole) => void;
  divisionGrid: DivisionGrid;
  /** The on-clock accent (paused / overtime / my turn). */
  clockColor: string;
}

const TEAM_SORTS: readonly TeamSort[] = ["order", "next", "avg"];

const SLOT_COLOR: Record<RosterSlotCode, string> = { ...ROLE_ACCENT, flex: "var(--aqt-flex)" };

const FOCUS_RING = "outline-hidden focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]";

function tint(color: string, percent: number): string {
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`;
}

/** Consecutive runs of one slot code: the header spans one icon over each run. */
function headerGroups(codes: readonly RosterSlotCode[]): { code: RosterSlotCode; span: number }[] {
  const groups: { code: RosterSlotCode; span: number }[] = [];
  for (const code of codes) {
    const last = groups.at(-1);
    if (last?.code === code) last.span += 1;
    else groups.push({ code, span: 1 });
  }
  return groups;
}

export function TeamRosters({
  board,
  teamViews,
  teams,
  filter,
  onFilterChange,
  sort,
  onSortChange,
  followed,
  onToggleFollow,
  myTeamId,
  onlineCaptainIds,
  onOpenProfile,
  onSlotFilter,
  divisionGrid,
  clockColor
}: Readonly<TeamRostersProps>) {
  const t = useTranslations("draftRedesign");
  const shape = board.session.roster_shape;
  const listRef = useRef<HTMLDivElement>(null);
  const hovering = useRef(false);
  useDraftLayerPad(listRef);
  const currentPickId = board.current_pick?.id ?? null;
  const onClockId = board.current_pick?.draft_team_id ?? null;

  // Bring the team on the clock into view whenever the pick changes — unless
  // the viewer is reading the list, where a jump would yank rows from under them.
  useEffect(() => {
    const list = listRef.current;
    if (list == null || onClockId == null || hovering.current) return;
    const row = list.querySelector<HTMLElement>(`[data-team="${onClockId}"]`);
    if (row) list.scrollTop = Math.max(0, row.offsetTop - list.clientHeight / 2 + 24);
  }, [currentPickId, onClockId]);

  // Columns: the shape's slots, widened when the server seated more than it holds.
  const shapeCodes = orderSlotCodes(shape.slots).flatMap((code) =>
    Array.from({ length: shape.slots[code] ?? 0 }, () => code)
  );
  let columns = shapeCodes.length;
  for (const view of teamViews.values()) columns = Math.max(columns, view.cells.length);
  const columnCodes: RosterSlotCode[] = [
    ...shapeCodes,
    ...Array.from({ length: columns - shapeCodes.length }, () => "flex" as const)
  ];
  // Every seat gets the same share of what is left once the name column has had
  // its 140px: a BattleTag's name part is what these cells exist to show. Below
  // the container query's 640px the seats drop to their own row instead of
  // shrinking into 4-character stubs.
  const gridTemplateColumns = `22px minmax(140px,1.2fr) repeat(${Math.max(columns, 1)}, minmax(0,1fr)) 66px`;
  const rowVars = { "--roster-cols": gridTemplateColumns } as CSSProperties;

  const roleCodes = orderSlotCodes(shape.slots).filter(isRoleSlotCode);
  const followCount = board.teams.filter((team) => followed.has(team.id) || team.id === myTeamId).length;
  const chips: { value: TeamFilter; label: string; count: number; aria: string; role: DraftRole | null }[] = [
    { value: "all", label: t("teams.chips.all"), count: teamViews.size, aria: t("teams.chips.allAria", { count: teamViews.size }), role: null },
    { value: "follow", label: t("teams.chips.follow"), count: followCount, aria: t("teams.chips.followAria", { count: followCount }), role: null },
    ...roleCodes.map((role) => {
      const count = teamsNeedingRole(teamViews, role);
      return { value: role, label: t("teams.chips.need"), count, aria: t("teams.chips.needAria", { role, count }), role };
    })
  ];

  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-[color:var(--aqt-border)] px-4 pb-3">
        <div role="group" aria-label={t("teams.chips.label")} className="flex flex-wrap items-center gap-1.5">
          {chips.map((chip) => {
            const on = filter === chip.value;
            const accent = chip.role ? ROLE_ACCENT[chip.role] : "var(--aqt-teal)";
            return (
              <button
                key={chip.value}
                type="button"
                aria-pressed={on}
                aria-label={chip.aria}
                onClick={() => onFilterChange(chip.value)}
                className={cn(
                  "flex min-h-11 max-w-full items-center gap-1.5 whitespace-nowrap rounded-full border bg-[color:var(--chip-bg)] px-[11px] text-caption font-medium hover:bg-[color:var(--aqt-overlay-3)] sm:min-h-8",
                  FOCUS_RING,
                  on ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-muted)]"
                )}
                style={
                  {
                    "--chip-bg": on ? tint(accent, 12) : "transparent",
                    borderColor: on ? accent : "var(--aqt-border-2)"
                  } as CSSProperties
                }
              >
                {chip.role && (
                  <PlayerRoleIcon role={getRoleIconName(chip.role)} size={17} color={ROLE_ACCENT[chip.role]} decorative />
                )}
                <span className="truncate">{chip.label}</span>
                <span className="font-normal tabular-nums text-[color:var(--aqt-fg-faint)]">{chip.count}</span>
              </button>
            );
          })}
        </div>
        <div role="group" aria-label={t("teams.sort.label")} className="ml-auto flex gap-0.5">
          {TEAM_SORTS.map((value) => {
            const on = sort === value;
            return (
              <button
                key={value}
                type="button"
                aria-pressed={on}
                onClick={() => onSortChange(value)}
                className={cn(
                  "flex min-h-11 items-center whitespace-nowrap rounded-[7px] px-[9px] text-caption font-medium sm:min-h-7",
                  FOCUS_RING,
                  on
                    ? "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg)]"
                    : "text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
                )}
              >
                {t(`teams.sort.${value}`)}
              </button>
            );
          })}
        </div>
      </div>

      <div
        className="grid grid-cols-[22px_minmax(0,1fr)_66px] items-center gap-1 overflow-hidden border-b border-[color:var(--aqt-border)] px-4 py-[7px] text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)] [scrollbar-gutter:stable] @[640px]/roster:grid-cols-[var(--roster-cols)]"
        style={rowVars}
      >
        <span>#</span>
        <span>{t("teams.col.team")}</span>
        <span className="hidden @[640px]/roster:contents">
          {headerGroups(columnCodes).map((group, index) => (
            <span
              key={`${group.code}-${index}`}
              title={t(`roles.${group.code}`)}
              className="flex justify-center"
              style={{ gridColumn: `span ${group.span}` }}
            >
              <PlayerRoleIcon
                role={isRoleSlotCode(group.code) ? getRoleIconName(group.code) : "Flex"}
                size={16}
                color={SLOT_COLOR[group.code]}
                label={t(`roles.${group.code}`)}
              />
            </span>
          ))}
        </span>
        <span className="text-right" title={t("teams.col.avgTitle")}>
          {t("teams.col.avg")}
        </span>
      </div>

      <div
        ref={listRef}
        role="list"
        tabIndex={0}
        aria-label={t("teams.listLabel")}
        onPointerEnter={() => {
          hovering.current = true;
        }}
        onPointerLeave={() => {
          hovering.current = false;
        }}
        className="relative min-h-0 flex-1 overflow-y-auto pb-[var(--draft-layer-h,0px)] outline-hidden [scrollbar-gutter:stable] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]"
      >
        {teams.map((view) => {
          const { team } = view;
          const isCur = team.id === onClockId;
          const isMe = team.id === myTeamId;
          const isFollowed = followed.has(team.id);
          const online = team.captain_auth_user_id != null && onlineCaptainIds.has(team.captain_auth_user_id);
          const turns = turnsUntil(board, team.id);
          const status = view.full
            ? t("teams.sub.full")
            : isCur
              ? isMe
                ? t("teams.sub.myTurn")
                : t("teams.sub.picking")
              : turns == null
                ? "—"
                : turns === 0
                  ? t("teams.sub.first")
                  : t("teams.sub.in", { n: turns });
          const sub = isMe && !isCur && !view.full && turns != null ? t("teams.sub.mine", { status }) : status;
          const avgDivision = resolveDivisionFromRank(divisionGrid, view.avgRank);
          const avgLabel = avgDivision == null ? null : getDivisionLabel(divisionGrid, avgDivision);

          return (
            <div
              key={team.id}
              role="listitem"
              data-team={team.id}
              className="grid grid-cols-[22px_minmax(0,1fr)_66px] items-center gap-1 border-b border-[color:var(--aqt-border)] px-4 py-[5px] @[640px]/roster:grid-cols-[var(--roster-cols)]"
              style={{
                ...rowVars,
                // The on-clock wash is the clock's own colour, never a fixed
                // teal: teal means "mine" everywhere else in the room.
                background: isCur ? tint(clockColor, 8) : isMe ? "var(--aqt-overlay-2)" : "transparent",
                boxShadow: isCur ? `inset 3px 0 0 ${clockColor}` : "none"
              }}
            >
              <span className="text-caption tabular-nums text-[color:var(--aqt-fg-faint)]">{team.draft_position}</span>
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-1.5">
                  <button
                    type="button"
                    aria-pressed={isFollowed}
                    aria-label={
                      isFollowed ? t("teams.unfollow", { team: team.name }) : t("teams.follow", { team: team.name })
                    }
                    title={t("teams.followTitle")}
                    onClick={() => onToggleFollow(team.id)}
                    className={cn(
                      "relative flex h-6 w-6 flex-none items-center justify-center rounded-md after:absolute after:-inset-2.5 after:content-[''] hover:bg-[color:var(--aqt-overlay-3)] sm:after:hidden",
                      FOCUS_RING
                    )}
                    style={{ color: isFollowed ? "var(--aqt-follow)" : "var(--aqt-fg-faint)" }}
                  >
                    <Star aria-hidden className="h-[15px] w-[15px]" fill={isFollowed ? "currentColor" : "none"} />
                  </button>
                  <span
                    title={team.name}
                    className="truncate text-body font-semibold"
                    style={{ color: isMe ? "var(--aqt-teal)" : "var(--aqt-fg)" }}
                  >
                    {team.name}
                  </span>
                  {/* Shape, not just hue: filled = the captain is here, hollow = not. */}
                  <span
                    role="img"
                    aria-label={online ? t("teams.captainOnline") : t("teams.captainOffline")}
                    title={online ? t("teams.captainOnline") : t("teams.captainOffline")}
                    className="h-[8px] w-[8px] flex-none rounded-full border"
                    style={{
                      background: online ? "var(--aqt-positive)" : "transparent",
                      borderColor: online ? "var(--aqt-positive)" : "var(--aqt-fg-faint)"
                    }}
                  />
                </div>
                <div
                  className="ml-[30px] truncate text-label"
                  style={{ color: isCur ? clockColor : "var(--aqt-fg-muted)" }}
                >
                  {sub}
                </div>
              </div>
              {/* Wide: `contents` hands the seats straight to the row grid. Narrow:
                  they wrap onto their own row under the team name. */}
              <div className="col-span-full row-start-2 grid grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-1 pb-0.5 pl-[26px] pt-1 @[640px]/roster:contents">
                {view.cells.map((cell, index) => (
                  <RosterCell
                    key={cell.player?.id ?? `open-${index}`}
                    cell={cell}
                    hasRoleSlots={shape.has_role_slots}
                    onClock={isCur}
                    onSlotFilter={isMe ? onSlotFilter : undefined}
                    onOpenProfile={onOpenProfile}
                    divisionGrid={divisionGrid}
                  />
                ))}
                {/* Pad a team the server seated fewer cells for, so the avg column stays aligned. */}
                {view.cells.length < columns && (
                  <span
                    className="hidden @[640px]/roster:block"
                    style={{ gridColumn: `span ${columns - view.cells.length}` }}
                  />
                )}
              </div>
              <span
                title={
                  view.avgRank == null
                    ? t("teams.avgEmpty")
                    : [t("teams.col.avgTitle"), avgLabel].filter(Boolean).join(" · ")
                }
                className="col-start-3 row-start-1 flex items-center justify-end gap-1 whitespace-nowrap text-caption font-medium tabular-nums text-[color:var(--aqt-fg-muted)] @[640px]/roster:col-start-auto @[640px]/roster:row-start-auto"
              >
                {avgDivision != null && (
                  <DivisionIcon
                    division={avgDivision}
                    tournamentGrid={divisionGrid}
                    width={20}
                    height={20}
                    className="h-5 w-5 flex-none object-contain"
                  />
                )}
                {view.avgRank == null ? "—" : Math.round(view.avgRank)}
              </span>
            </div>
          );
        })}
        {teams.length === 0 && (
          <p className="px-[18px] py-12 text-center text-body text-[color:var(--aqt-fg-muted)]">
            {filter === "follow" ? t("teams.empty.follow") : t("teams.empty.role")}
          </p>
        )}
      </div>
    </>
  );
}

function RosterCell({
  cell,
  hasRoleSlots,
  onClock,
  onSlotFilter,
  onOpenProfile,
  divisionGrid
}: Readonly<{
  cell: TeamSlotCell;
  hasRoleSlots: boolean;
  onClock: boolean;
  /** Set only for MY team's row. */
  onSlotFilter?: (role: DraftRole) => void;
  onOpenProfile: (playerId: number) => void;
  divisionGrid: DivisionGrid;
}>) {
  const t = useTranslations("draftRedesign");
  const color = SLOT_COLOR[cell.code];
  const slotLabel = t(`roles.${cell.code}`);

  if (cell.player == null) {
    const { code } = cell;
    const filterRole = onSlotFilter && isRoleSlotCode(code) ? code : null;
    const boxClass = "h-[30px] min-w-0 rounded-[7px] border border-dashed";
    const borderColor = tint(color, onClock ? 75 : 30);
    if (filterRole != null && onSlotFilter) {
      return (
        <button
          type="button"
          aria-label={t("filterBySlot", { role: slotLabel })}
          title={t("teams.cell.openFilter", { role: slotLabel })}
          onClick={() => onSlotFilter(filterRole)}
          className={cn(boxClass, "cursor-pointer hover:bg-[color:var(--aqt-overlay-3)]", FOCUS_RING)}
          style={{ borderColor }}
        />
      );
    }
    const label = t("teams.cell.open", { role: slotLabel });
    return (
      <span title={label} className={boxClass} style={{ borderColor }}>
        <span className="sr-only">{label}</span>
      </span>
    );
  }

  const { player } = cell;
  const tag = player.battle_tag ?? `#${player.id}`;
  const rank = slotRankForPlayer(player, cell.role, { has_role_slots: hasRoleSlots });
  const division = resolveDivisionFromRank(divisionGrid, rank);
  const divisionLabel = division == null ? null : getDivisionLabel(divisionGrid, division);
  // Under a role-less shape nobody holds a role: the slot is all there is to name.
  const roleLabel =
    !hasRoleSlots || cell.role == null
      ? slotLabel
      : cell.code === "flex"
        ? `${slotLabel} · ${t(`roles.${cell.role}`)}`
        : t(`roles.${cell.role}`);
  const title = [
    tag,
    roleLabel,
    rank != null ? `${Math.round(rank)} SR` : null,
    divisionLabel,
    player.is_captain ? t("captain") : null,
    cell.offRole ? t("teams.cell.offRole") : null
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={() => onOpenProfile(player.id)}
      className={cn(
        "flex h-[30px] min-w-0 items-center gap-1 overflow-hidden rounded-[7px] border border-transparent bg-[color:var(--cell-bg)] px-[5px] text-left text-label font-medium text-[color:var(--aqt-fg)] hover:bg-[color:var(--cell-bg-hover)]",
        FOCUS_RING,
        // Off-role is the one thing a cell still draws a border for.
        cell.offRole && "border-dashed border-[color:var(--aqt-amber)]"
      )}
      style={
        {
          "--cell-bg": tint(color, 12),
          "--cell-bg-hover": tint(color, 26)
        } as CSSProperties
      }
    >
      {division != null && (
        <DivisionIcon
          division={division}
          tournamentGrid={divisionGrid}
          width={16}
          height={16}
          className="h-4 w-4 flex-none object-contain"
        />
      )}
      <span className="min-w-0 truncate">{splitBattleTag(tag).name}</span>
    </button>
  );
}
