"use client";

// The card's own global CSS (`.team-card`, `.roster`, `.group-chip`,
// `.placement`), moved out of globals.css and next to its only consumer.
import "./TournamentTeamCard.css";

import React from "react";
import { useTranslations } from "next-intl";
import { Crown, Shuffle, Sprout } from "lucide-react";
import {
  sortTeamPlayers,
  type SortableRosterPlayer,
  type TeamRosterPlayer
} from "@/lib/player";
import PlayerName from "@/components/PlayerName";
import { Team } from "@/types/team.types";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import DivisionIcon from "@/components/DivisionIcon";
import { HeroStrip } from "@/components/hero/HeroImage";
import TeamName from "@/components/TeamName";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { normalizePlayerRole, PLAYER_ROLE_LABEL_KEY } from "@/lib/roster/player-role";
import { cn } from "@/lib/utils";
import type { DivisionGridVersion } from "@/types/workspace.types";

/** One nick line tall, so crown/flag icons sit on the nick, not mid-block. */
const ICON_SLOT = "flex h-6 shrink-0 items-center";

const relatedPlayerId = (player: SortableRosterPlayer) =>
  player.related_player_id ?? player.relative_player ?? null;

/**
 * The roster split into slots: a player, then everyone who came in for them
 * (the substitution chain `sortTeamPlayers` already orders that way). A sub
 * whose original is not in the list starts a slot of its own.
 */
export function rosterSlots<P extends SortableRosterPlayer>(players: P[]): P[][] {
  const slots: P[][] = [];
  for (const player of sortTeamPlayers(players)) {
    const slot = slots.at(-1);
    const related = relatedPlayerId(player);
    if (player.is_substitution && slot?.some((member) => member.id === related)) {
      slot.push(player);
    } else {
      slots.push([player]);
    }
  }
  return slots;
}

/** Where a row sits in its slot — what `RosterRole` needs to draw the branch. */
export interface RosterSlotPosition<P extends SortableRosterPlayer = TeamRosterPlayer> {
  slot: P[];
  index: number;
}

/** Someone in the slot came in for this player: they left the roster. */
export function isReplaced<P extends SortableRosterPlayer>({ slot, index }: RosterSlotPosition<P>) {
  const id = slot[index].id;
  return slot.some((member) => member.is_substitution && relatedPlayerId(member) === id);
}

const BRANCH_LINE = "pointer-events-none absolute border-[color:var(--aqt-fg-faint)]";

/**
 * Role icon, or — for a sub — the branch linking them to whoever they replaced.
 *
 * The lines are laid out against the enclosing cell, which must be positioned
 * (`relative` or `sticky`) with a 10px left padding: the 24px role icon's centre
 * is then at 22px, where the branch runs. `inline` is for a cell that holds the
 * nick too: the elbow stops at the icon's edge and an empty slot keeps the nick
 * aligned with the rows above.
 */
export function RosterRole({
  role,
  position,
  inline
}: Readonly<{
  role: string | null;
  position?: RosterSlotPosition<SortableRosterPlayer & { name: string }>;
  inline?: boolean;
}>) {
  const t = useTranslations();
  const index = position?.index ?? 0;
  const slotSize = position?.slot.length ?? 1;
  const lineBelow = index < slotSize - 1;

  if (position && index > 0) {
    const player = position.slot[index];
    const related = relatedPlayerId(player);
    const original = position.slot.find((member) => member.id === related);
    return (
      <>
        {lineBelow ? <span className={cn(BRANCH_LINE, "-bottom-px left-[21px] top-0 border-l-[1.5px]")} /> : null}
        <IconTooltip
          label={t("teams.roster.substitution")}
          hint={
            original
              ? t("teams.roster.substituteFor", { name: original.name.split("#")[0] })
              : undefined
          }
          className={cn(
            BRANCH_LINE,
            "pointer-events-auto -top-px left-[21px] h-[calc(50%+1px)] rounded-bl-lg border-b-[1.5px] border-l-[1.5px]",
            inline ? "w-[13px]" : "right-1"
          )}
        />
        {inline ? <span aria-hidden className="block w-6 shrink-0" /> : null}
      </>
    );
  }

  const roleKey = PLAYER_ROLE_LABEL_KEY[normalizePlayerRole(role)];
  return (
    <>
      {lineBelow ? (
        <span className={cn(BRANCH_LINE, "-bottom-px left-[21px] top-[calc(50%+14px)] border-l-[1.5px]")} />
      ) : null}
      <IconTooltip
        label={t(roleKey)}
        className={cn("shrink-0", position && isReplaced(position) && "opacity-50")}
      >
        <PlayerRoleIcon role={role} decorative />
      </IconTooltip>
    </>
  );
}

/** Nick (with specialization under it), then captain, newcomer and "you" marks. */
export function RosterPlayer({
  player,
  captainUserId,
  highlightUserId,
  dimmed
}: Readonly<{
  player: Pick<TeamRosterPlayer, "name" | "role" | "sub_role" | "user_id" | "is_newcomer" | "is_newcomer_role">;
  captainUserId?: number | null;
  /** When the row belongs to this user id, it gets a "you" tag. */
  highlightUserId?: number;
  dimmed?: boolean;
}>) {
  const t = useTranslations();
  return (
    <div className={cn("flex min-w-0 items-start gap-2", dimmed && "opacity-50")}>
      <PlayerName player={player} includeSpecialization={true} />
      {captainUserId != null && player.user_id === captainUserId ? (
        <IconTooltip label={t("teams.roster.captain")} className={ICON_SLOT}>
          <Crown aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
        </IconTooltip>
      ) : null}
      {player.is_newcomer ? (
        <IconTooltip
          label={t("teams.roster.newcomer")}
          hint={t("teams.roster.newcomerHint")}
          className={ICON_SLOT}
        >
          <Sprout aria-hidden className="size-4 text-[color:var(--aqt-rose)]" />
        </IconTooltip>
      ) : null}
      {/* Same rule as the Teams list view: a flex player has no role to be new
          to, and a flex tournament sets the flag on everyone. */}
      {player.is_newcomer_role && normalizePlayerRole(player.role) !== "Flex" ? (
        <IconTooltip
          label={t("teams.roster.newcomerRole")}
          hint={t("teams.roster.newcomerRoleHint")}
          className={ICON_SLOT}
        >
          <Shuffle aria-hidden className="size-4 text-[color:var(--aqt-amber)]" />
        </IconTooltip>
      ) : null}
      {highlightUserId != null && player.user_id === highlightUserId ? (
        <span className={ICON_SLOT}>
          <span
            className="aqt-tnum rounded-[4px] px-1.5 py-0.5 text-label font-bold uppercase tracking-label"
            style={{
              background: "color-mix(in srgb, var(--aqt-teal) 12%, transparent)",
              border: "1px solid color-mix(in srgb, var(--aqt-teal) 30%, transparent)",
              color: "var(--aqt-teal)"
            }}
          >
            {t("users.tournaments.you")}
          </span>
        </span>
      ) : null}
    </div>
  );
}

/** Rank crest (tier name in its tooltip) and the player's SR. */
export function RosterRank({
  division,
  rank,
  tournamentGrid,
  dimmed,
  className
}: Readonly<{
  division: number;
  rank: number;
  tournamentGrid?: DivisionGridVersion | null;
  dimmed?: boolean;
  className?: string;
}>) {
  const workspaceGrid = useDivisionGrid();
  const label = getDivisionLabel(tournamentGrid ?? workspaceGrid, division) ?? `Division ${division}`;
  return (
    <div className={cn("flex items-center gap-2", dimmed && "opacity-50", className)}>
      <IconTooltip label={label} className="shrink-0">
        <DivisionIcon division={division} width={26} height={26} tournamentGrid={tournamentGrid} />
      </IconTooltip>
      <span className="aqt-tnum text-caption font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]">
        {rank}
      </span>
    </div>
  );
}

/** Threshold color for the average MVP placement (1 = best). */
function avgMvpColor(value: number): string {
  if (value <= 2.5) return "var(--aqt-emerald)";
  if (value >= 4.5) return "var(--aqt-fg-dim)";
  return "var(--aqt-fg)";
}

export const TournamentTeamTable = ({
  players,
  tournamentGrid,
  highlightUserId,
  captainUserId
}: {
  players: TeamRosterPlayer[];
  tournamentGrid?: DivisionGridVersion | null;
  /** When a roster row belongs to this user id, it gets a "you" tag. */
  highlightUserId?: number;
  /** When a roster row belongs to this user id, it gets a captain crown. */
  captainUserId?: number | null;
}) => {
  const t = useTranslations();

  // Only render the dossier columns when at least one row carries the data;
  // other callers (team cards) pass rosters without these fields.
  const showExtra = players.some((p) => p.avg_mvp != null || (p.heroes?.length ?? 0) > 0);
  const signatureTitle = t("users.tournaments.roster.signatureHeroes");

  return (
    <div className="roster-scroll">
      <table className="roster">
        <thead>
          <tr>
            <th scope="col" style={{ width: 48 }}>
              {t("teams.roster.role")}
            </th>
            <th scope="col">{t("teams.roster.battleTag")}</th>
            <th scope="col" style={{ width: 96 }}>
              {t("teams.roster.rank")}
            </th>
            {showExtra ? (
              <>
                <th scope="col" style={{ width: 64, textAlign: "right" }}>
                  {t("users.tournaments.roster.avgMvp")}
                </th>
                <th scope="col" style={{ width: 100 }}>
                  {t("users.tournaments.roster.heroes")}
                </th>
              </>
            ) : null}
          </tr>
        </thead>
        {/* One <tbody> per slot: hover lights a player together with their
            subs, so the highlight never cuts the branch line in half. */}
        {rosterSlots(players).map((slot) => (
          <tbody key={slot[0].id}>
            {slot.map((player, index) => {
              const position = { slot, index };
              const dimmed = isReplaced(position);
              return (
                <tr key={player.id}>
                  <td className="relative">
                    <RosterRole role={player.role} position={position} />
                  </td>
                  <td>
                    <RosterPlayer
                      player={player}
                      captainUserId={captainUserId}
                      highlightUserId={highlightUserId}
                      dimmed={dimmed}
                    />
                  </td>
                  <td>
                    <RosterRank
                      division={player.division}
                      rank={player.rank}
                      tournamentGrid={tournamentGrid}
                      dimmed={dimmed}
                    />
                  </td>
                  {showExtra ? (
                    <>
                      <td
                        className="aqt-tnum tabular-nums"
                        style={{
                          textAlign: "right",
                          color:
                            player.avg_mvp != null
                              ? avgMvpColor(player.avg_mvp)
                              : "var(--aqt-fg-dim)"
                        }}
                      >
                        {player.avg_mvp != null ? player.avg_mvp.toFixed(1) : "—"}
                      </td>
                      <td>
                        {player.heroes && player.heroes.length > 0 ? (
                          <div title={signatureTitle} aria-label={signatureTitle}>
                            <HeroStrip heroes={player.heroes} size="sm" limit={3} />
                          </div>
                        ) : (
                          <span className="text-[color:var(--aqt-fg-dim)]">—</span>
                        )}
                      </td>
                    </>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        ))}
      </table>
    </div>
  );
};

function groupChipClass(name?: string | null): string {
  switch (name?.trim().toUpperCase()) {
    case "B":
      return "b";
    case "C":
      return "c";
    case "D":
      return "d";
    default:
      return "a";
  }
}

function placementClass(placement: number): string {
  if (placement === 1) return "gold";
  if (placement === 2) return "silver";
  if (placement === 3) return "bronze";
  return "def";
}

interface TournamentTeamCardFrameProps extends React.HTMLAttributes<HTMLElement> {
  name: React.ReactNode;
  leadingTag?: React.ReactNode;
  positionTag?: React.ReactNode;
  metricLabel?: React.ReactNode;
  metricValue?: React.ReactNode;
  /** Encounter-bound cards: the side's colour along the top edge. */
  side?: "home" | "away";
}

/** Shared team-card chrome: the Teams page, encounter, pre-game and rosters modal. */
export const TournamentTeamCardFrame = ({
  name,
  leadingTag,
  positionTag,
  metricLabel,
  metricValue,
  side,
  children,
  className,
  ...props
}: TournamentTeamCardFrameProps) => {
  const hasTags = leadingTag != null || positionTag != null;
  const hasMetric = metricLabel != null || metricValue != null;

  return (
    <article className={cn("team-card", className)} data-side={side} {...props}>
      <header className="tc-header">
        {hasTags && (
          <div className="tc-tags">
            {leadingTag ?? <span />}
            {positionTag}
          </div>
        )}
        <div className="tc-name-row">
          <h3 className="tc-name">{name}</h3>
          {hasMetric && (
            <div className="tc-sr">
              {metricLabel != null && <div className="l">{metricLabel}</div>}
              {metricValue != null && <div className="v">{metricValue}</div>}
            </div>
          )}
        </div>
      </header>
      <div className="tc-divider" />
      {children}
    </article>
  );
};

export const TournamentTeamCard = ({ team }: { team: Team }) => {
  const t = useTranslations();

  return (
    <TournamentTeamCardFrame
      id={team.id.toString()}
      name={<TeamName team={team} size="md" />}
      leadingTag={
        team.group?.name ? (
          <span className={cn("group-chip", groupChipClass(team.group.name))}>
            {t("teams.groupLabel", { name: team.group.name })}
          </span>
        ) : (
          <span />
        )
      }
      positionTag={
        team.placement != null ? (
          <span className={cn("placement tabular-nums", placementClass(team.placement))}>
            #{team.placement}
          </span>
        ) : null
      }
      metricLabel={t("teams.roster.avgSr")}
      metricValue={<span className="tabular-nums">{team.avg_sr.toFixed(0)}</span>}
    >
      <TournamentTeamTable
        players={team.players}
        tournamentGrid={team.tournament?.division_grid_version}
        captainUserId={team.captain_id}
      />
    </TournamentTeamCardFrame>
  );
};
