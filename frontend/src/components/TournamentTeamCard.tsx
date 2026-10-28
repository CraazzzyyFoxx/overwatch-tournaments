"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { Crown, Shuffle, Sprout } from "lucide-react";
import { sortTeamPlayers, splitHandle, type SortableRosterPlayer, type TeamRosterPlayer } from "@/lib/player";
import PlayerName from "@/components/PlayerName";
import { Team } from "@/types/team.types";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import DivisionIcon from "@/components/DivisionIcon";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import TeamName from "@/components/TeamName";
import { Badge } from "@/components/ui/badge";
import { Card, CardTitle } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { PlaceBadge } from "@/components/ui/place-badge";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";
import { roleOf, type RoleRef } from "@/lib/roster/role-ref";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import { groupDisplayName, groupHue } from "@/lib/tournament/group";
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
export function rosterSlots<P extends SortableRosterPlayer>(players: P[], ontology: RoleOntology | null): P[][] {
  const slots: P[][] = [];
  for (const player of sortTeamPlayers(players, ontology)) {
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
  inline,
  ontology = null
}: Readonly<{
  role: RoleRef | null;
  position?: RosterSlotPosition<SortableRosterPlayer & { name: string }>;
  inline?: boolean;
  /** The roster's own game's scoped ontology. Absent, the role renders neutral — never another game's glyph. */
  ontology?: RoleOntology | null;
}>) {
  const t = useTranslations();
  const slotLabel = useSlotLabel(ontology);
  const index = position?.index ?? 0;
  const slotSize = position?.slot.length ?? 1;
  const lineBelow = index < slotSize - 1;

  if (position && index > 0) {
    const player = position.slot[index];
    const related = relatedPlayerId(player);
    const original = position.slot.find((member) => member.id === related);
    return (
      <>
        {lineBelow ? (
          <span className={cn(BRANCH_LINE, "-bottom-px left-[21px] top-0 border-l-[1.5px]")} />
        ) : null}
        <IconTooltip
          label={t("teams.roster.substitution")}
          hint={
            original
              ? t("teams.roster.substituteFor", { name: splitHandle(original.name).name })
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

  return (
    <>
      {lineBelow ? (
        <span
          className={cn(
            BRANCH_LINE,
            "-bottom-px left-[21px] top-[calc(50%+14px)] border-l-[1.5px]"
          )}
        />
      ) : null}
      <IconTooltip
        label={slotLabel(role ? roleOf(role) : OPEN_SLOT_CODE)}
        className={cn("shrink-0", position && isReplaced(position) && "opacity-50")}
      >
        <PlayerRoleIcon role={role} ontology={ontology} decorative />
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
  player: Pick<TeamRosterPlayer, "name" | "role" | "user_id" | "is_newcomer" | "is_newcomer_role">;
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
      {player.is_newcomer_role && player.role != null ? (
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
          <Badge tone="accent" voice="label">
            {t("users.tournaments.you")}
          </Badge>
        </span>
      ) : null}
    </div>
  );
}

/** Rank crest (tier name in its tooltip) and the player's SR; "—" when the tournament recorded no rank. */
export function RosterRank({
  division,
  rank,
  tournamentGrid,
  discipline,
  dimmed,
  className
}: Readonly<{
  division: number | null;
  rank: number | null;
  tournamentGrid?: DivisionGridVersion | null;
  discipline?: string;
  dimmed?: boolean;
  className?: string;
}>) {
  const workspaceGrid = useDivisionGrid(discipline);
  const format = useFormatter();
  if (rank == null) {
    return (
      <span className={cn("text-[color:var(--aqt-fg-dim)]", dimmed && "opacity-50", className)}>—</span>
    );
  }
  return (
    <div className={cn("flex items-center gap-2", dimmed && "opacity-50", className)}>
      {division != null ? (
        <IconTooltip
          label={getDivisionLabel(tournamentGrid ?? workspaceGrid, division) ?? `Division ${division}`}
          className="shrink-0"
        >
          <DivisionIcon
            division={division}
            width={26}
            height={26}
            tournamentGrid={tournamentGrid}
            discipline={discipline}
          />
        </IconTooltip>
      ) : null}
      <span className="aqt-tnum text-caption font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]">
        {format.number(rank, { maximumFractionDigits: 0 })}
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

/** Head and cell padding: 10px left is load-bearing, `RosterRole` draws the branch at 22px. */
const ROSTER_HEAD = "h-6.5 px-2.5 py-1.5";
/** One slot (a `group/slot` tbody) lights up together: a player with their subs. */
const ROSTER_CELL =
  "border-t border-[color:var(--aqt-overlay-border)] px-2.5 py-1.25 group-hover/slot:bg-[color:var(--aqt-overlay-2)]";
const ROSTER_ROW = "border-0 hover:bg-transparent";

export const TournamentTeamTable = ({
  players,
  tournamentGrid,
  discipline,
  ontology,
  highlightUserId,
  captainUserId
}: {
  players: TeamRosterPlayer[];
  tournamentGrid?: DivisionGridVersion | null;
  discipline?: string;
  /** The roster's own game's scoped ontology, for the role column. */
  ontology?: RoleOntology | null;
  /** When a roster row belongs to this user id, it gets a "you" tag. */
  highlightUserId?: number;
  /** When a roster row belongs to this user id, it gets a captain crown. */
  captainUserId?: number | null;
}) => {
  const t = useTranslations();

  // Each dossier column renders only when at least one row carries its data;
  // other callers (team cards) pass rosters without these fields.
  const showMvp = players.some((p) => p.avg_mvp != null);
  const showHeroes = players.some((p) => (p.characters?.length ?? 0) > 0);
  const signatureTitle = t("users.tournaments.roster.signatureHeroes");

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead scope="col" className={ROSTER_HEAD} style={{ width: 48 }}>
            {t("teams.roster.role")}
          </TableHead>
          <TableHead scope="col" className={ROSTER_HEAD}>
            {t("teams.roster.battleTag")}
          </TableHead>
          <TableHead scope="col" className={ROSTER_HEAD} style={{ width: 96 }}>
            {t("teams.roster.rank")}
          </TableHead>
          {showMvp ? (
            <TableHead scope="col" className={ROSTER_HEAD} style={{ width: 64, textAlign: "right" }}>
              {t("users.tournaments.roster.avgMvp")}
            </TableHead>
          ) : null}
          {showHeroes ? (
            <TableHead scope="col" className={ROSTER_HEAD} style={{ width: 100 }}>
              {t("users.tournaments.roster.heroes")}
            </TableHead>
          ) : null}
        </TableRow>
      </TableHeader>
      {/* One <tbody> per slot: hover lights a player together with their
          subs, so the highlight never cuts the branch line in half. */}
      {rosterSlots(players, ontology ?? null).map((slot) => (
        <TableBody key={slot[0].id} className="group/slot">
          {slot.map((player, index) => {
            const position = { slot, index };
            const dimmed = isReplaced(position);
            return (
              <TableRow key={player.id} className={ROSTER_ROW}>
                <TableCell className={cn(ROSTER_CELL, "relative")}>
                  <RosterRole role={player.role} position={position} ontology={ontology} />
                </TableCell>
                <TableCell className={ROSTER_CELL}>
                  <RosterPlayer
                    player={player}
                    captainUserId={captainUserId}
                    highlightUserId={highlightUserId}
                    dimmed={dimmed}
                  />
                </TableCell>
                <TableCell className={ROSTER_CELL}>
                  <RosterRank
                    division={player.division}
                    rank={player.rank}
                    tournamentGrid={tournamentGrid}
                    discipline={discipline}
                    dimmed={dimmed}
                  />
                </TableCell>
                {showMvp ? (
                  <TableCell
                    className={cn(ROSTER_CELL, "aqt-tnum tabular-nums")}
                    style={{
                      textAlign: "right",
                      color: player.avg_mvp != null ? avgMvpColor(player.avg_mvp) : "var(--aqt-fg-dim)"
                    }}
                  >
                    {player.avg_mvp != null ? player.avg_mvp.toFixed(1) : "—"}
                  </TableCell>
                ) : null}
                {showHeroes ? (
                  <TableCell className={ROSTER_CELL}>
                    {player.characters && player.characters.length > 0 ? (
                      <div title={signatureTitle} aria-label={signatureTitle}>
                        <CatalogEntityStrip entities={player.characters} size="sm" limit={3} />
                      </div>
                    ) : (
                      <span className="text-[color:var(--aqt-fg-dim)]">—</span>
                    )}
                  </TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      ))}
    </Table>
  );
};

/**
 * A team's place: the medal for 1–3 of a finished competition (`medal`), `#N`
 * text for any other place — a live leader is not on the podium yet.
 */
export function TeamPlacement({ placement, medal }: { placement: number; medal: boolean }) {
  const t = useTranslations();
  if (medal && placement >= 1 && placement <= 3) {
    return (
      <span className="inline-flex">
        <PlaceBadge place={placement} />
        <span className="sr-only">
          {t(`tournamentDetail.podium.place${placement as 1 | 2 | 3}`)}
        </span>
      </span>
    );
  }
  return (
    <span className="aqt-tnum text-caption font-semibold text-[color:var(--aqt-fg-muted)]">
      #{placement}
    </span>
  );
}

/** The group card's surface over `Card`: overlay fill and rim; under the pointer the rim lifts. */
export const TEAM_CARD_CLASS =
  "overflow-hidden border-[color:var(--aqt-overlay-border)] bg-[color:var(--aqt-overlay-1)] transition-colors hover:border-[color:var(--aqt-border-3)] hover:bg-[color:var(--aqt-overlay-2)]";
/** The header band above the divider. */
export const TEAM_CARD_HEADER = "px-3.5 pb-3 pt-2.5";
/** The card's name: one truncating line. */
export const TEAM_CARD_NAME =
  "min-w-0 truncate text-ui font-semibold leading-[1.3] text-[color:var(--aqt-fg)]";

/** Encounter-bound cards: the seat's colour along the top edge, kept under the pointer. */
const SLOT_EDGE = {
  1: "border-t-3 border-t-[color:var(--aqt-teal)] hover:border-t-[color:var(--aqt-teal)]",
  2: "border-t-3 border-t-[color:var(--aqt-rose)] hover:border-t-[color:var(--aqt-rose)]"
} as const;

/** A header figure on the right: its label over its value ("Avg SR" over 3,760). */
export function TeamCardMetric({
  label,
  value,
  className
}: Readonly<{ label?: React.ReactNode; value?: React.ReactNode; className?: string }>) {
  return (
    <span className={cn("shrink-0 text-right", className)}>
      {label != null && (
        <span className={eyebrowClass("faint", "mb-0.5 block font-normal leading-none")}>{label}</span>
      )}
      {value != null && (
        <span className="block text-body font-semibold tabular-nums text-[color:var(--aqt-fg)]">
          {value}
        </span>
      )}
    </span>
  );
}

/** The hairline between a group card's bands. */
export function TeamCardDivider() {
  return <Separator className="bg-[color:var(--aqt-overlay-border)]" />;
}

interface TournamentTeamCardFrameProps extends Omit<React.HTMLAttributes<HTMLElement>, "slot"> {
  name: React.ReactNode;
  leadingTag?: React.ReactNode;
  positionTag?: React.ReactNode;
  metricLabel?: React.ReactNode;
  metricValue?: React.ReactNode;
  /** Encounter-bound cards: the seat's colour along the top edge (slot 1 teal, slot 2 rose). */
  slot?: 1 | 2;
}

/** Shared team-card chrome: the Teams page, encounter, pre-game and rosters modal. */
export const TournamentTeamCardFrame = ({
  name,
  leadingTag,
  positionTag,
  metricLabel,
  metricValue,
  slot,
  children,
  className,
  ...props
}: TournamentTeamCardFrameProps) => {
  const hasTags = leadingTag != null || positionTag != null;
  const hasMetric = metricLabel != null || metricValue != null;

  return (
    <Card asChild className={cn(TEAM_CARD_CLASS, slot && SLOT_EDGE[slot], className)}>
      <article data-slot={slot} {...props}>
        <header className={TEAM_CARD_HEADER}>
          {hasTags && (
            <div className="mb-2.5 flex items-center justify-between gap-2.5">
              {leadingTag ?? <span />}
              {positionTag}
            </div>
          )}
          <div className="flex items-center justify-between gap-3">
            <CardTitle asChild className={TEAM_CARD_NAME}>
              <h3>{name}</h3>
            </CardTitle>
            {hasMetric && <TeamCardMetric label={metricLabel} value={metricValue} />}
          </div>
        </header>
        <TeamCardDivider />
        {children}
      </article>
    </Card>
  );
};

/**
 * `medal`: the competition is finished, so places 1–3 are medals.
 * `showGroup`: the visible teams span several groups, so the group colour
 * tells them apart; otherwise the chip would repeat one value on every card.
 */
export const TournamentTeamCard = ({
  team,
  medal,
  showGroup,
  discipline,
  ontology
}: {
  team: Team;
  medal: boolean;
  showGroup: boolean;
  discipline: string;
  /** The team's own game's scoped ontology, for the roster's role column. */
  ontology?: RoleOntology | null;
}) => {
  const t = useTranslations();
  const format = useFormatter();

  return (
    <TournamentTeamCardFrame
      id={team.id.toString()}
      name={<TeamName team={team} size="md" />}
      leadingTag={
        showGroup && team.group?.name ? (
          <Badge hue={groupHue(team.group.name)} voice="label">
            {groupDisplayName(team.group.name, t("common.group"))}
          </Badge>
        ) : undefined
      }
      positionTag={
        team.placement != null ? <TeamPlacement placement={team.placement} medal={medal} /> : null
      }
      metricLabel={t("teams.roster.avgSr")}
      metricValue={
        <span className="tabular-nums">
          {format.number(team.avg_sr, { maximumFractionDigits: 0 })}
        </span>
      }
    >
      <TournamentTeamTable
        players={team.players}
        tournamentGrid={team.tournament?.division_grid_version}
        discipline={discipline}
        ontology={ontology}
        captainUserId={team.captain_id}
      />
    </TournamentTeamCardFrame>
  );
};
