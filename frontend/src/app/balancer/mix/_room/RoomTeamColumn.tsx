"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Ban, Crown, WifiOff } from "lucide-react";

import { AWAY_CHIP_CLASS, teamAccent } from "@/app/balancer/mix/pickup-chrome";
import type { MixOwner } from "@/app/balancer/mix/pickup-lineup";
import { HandleLabel } from "@/components/HandleLabel";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanItemThumb } from "@/components/pick-ban/PickBanItemThumb";
import { CHARACTER_PICK_BAN_KIND } from "@/components/pick-ban/pick-ban-model";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { RowButton } from "@/components/ui/row-button";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import { cn } from "@/lib/utils";

import { heroTransitionName, playerTransitionName, type RoomSeat, type RoomTeam } from "./room-model";

/** `lg` in `globals.css`: from here the rosters are full columns beside the centre, with art to match. */
const COLUMNS_QUERY = "(min-width: 1024px)";

/**
 * One team of the room: its name and side, its bans, then a slot per seat of the lobby's shape. A slot is a player
 * (the viewer's own marked, the captain crowned, the picked hero beside them) or the role it still waits for. The team
 * on the clock wears the accent; the first empty slot of a drafting team is where its pick will land. On a member pick
 * the player picked for is outlined, and a viewer who may pick for several players chooses one by their row.
 */
export function RoomTeamColumn({
  team,
  index,
  owner,
  active,
  myMemberId,
  awayIds,
  heroesById,
  sideLabel,
  captainOffline = false,
  captainControl,
  pickFor,
  className
}: Readonly<{
  team: RoomTeam;
  /** The team's position: 0 is the left column. */
  index: number;
  owner: MixOwner;
  /** On the clock: a draft pick or a ban/pick step is this team's. */
  active: boolean;
  myMemberId: number | null;
  awayIds: ReadonlySet<number>;
  heroesById: Record<number, PickBanItemLike | undefined>;
  sideLabel: (code: string) => string;
  /** The drafting captain has no browser on the draft right now. */
  captainOffline?: boolean;
  /** A host's captain picker, under the name while a draft is being set up or run. */
  captainControl?: ReactNode;
  /**
   * A member pick (spec §11.6): the players (`RoomSeat.teamMemberId`) the viewer may pick for and the one the pick is
   * for. With more than one to choose from, each of their rows is a button that picks for that player.
   */
  pickFor?: { choosable: readonly number[]; acting: number | null; onChoose: (teamMemberId: number) => void };
  className?: string;
}>) {
  const t = useTranslations("mixes.arena");
  const wide = useMediaQuery(COLUMNS_QUERY, true);
  const accent = teamAccent(index);
  const filled = team.slots.filter((slot) => slot.seat != null).length;
  const nextSlot = active ? team.slots.findIndex((slot) => slot.seat == null) : -1;
  const heroName = (heroId: number) => heroesById[heroId]?.name ?? `#${heroId}`;
  const choosing = pickFor != null && pickFor.choosable.length > 1 ? pickFor : null;
  return (
    <section
      aria-label={team.name}
      className={cn(
        "flex min-w-0 flex-col gap-2.5 rounded-xl border bg-[color:var(--aqt-card)] p-2.5 transition-colors lg:gap-3 lg:p-4",
        active ? "border-[color:var(--aqt-teal)]/60" : "border-[color:var(--aqt-border)]",
        className
      )}
    >
      <header className="flex min-w-0 items-center gap-2">
        <span aria-hidden="true" className={cn("h-4 w-[3px] shrink-0 rounded-sm", accent.bar)} />
        <h2 className="min-w-0 truncate font-display text-ui font-semibold text-[color:var(--aqt-fg)] lg:text-heading">
          {team.name}
        </h2>
        {team.side != null ? (
          <span className="shrink-0 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
            {sideLabel(team.side)}
          </span>
        ) : null}
        <span className="ml-auto shrink-0 text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">
          {team.averageRank != null ? Math.round(team.averageRank) : `${filled}/${team.slots.length}`}
        </span>
      </header>
      {captainControl}
      {team.bans.length > 0 || team.unassignedPicks.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5" aria-label={t("teamHeroes", { team: team.name })}>
          {team.bans.map((heroId) => (
            // The portrait stays readable; a corner badge says it is banned.
            <span
              key={`ban-${heroId}`}
              className="relative grid place-items-center"
              style={{ viewTransitionName: heroTransitionName(heroId) }}
              title={t("banned", { hero: heroName(heroId) })}
            >
              <PickBanItemThumb
                kind={CHARACTER_PICK_BAN_KIND}
                item={heroesById[heroId]}
                name={heroName(heroId)}
                size={wide ? 32 : 28}
                muted
              />
              <span
                aria-hidden
                className="absolute -bottom-1 -right-1 grid size-4 place-items-center rounded-full bg-[color:var(--aqt-card)] ring-1 ring-[color:var(--aqt-rose)]/70"
              >
                <Ban className="size-3 text-[color:var(--aqt-rose)]" />
              </span>
            </span>
          ))}
          {team.unassignedPicks.map((heroId) => (
            <span key={`pick-${heroId}`} style={{ viewTransitionName: heroTransitionName(heroId) }}>
              <PickBanItemThumb
                kind={CHARACTER_PICK_BAN_KIND}
                item={heroesById[heroId]}
                name={heroName(heroId)}
                size={wide ? 30 : 26}
              />
            </span>
          ))}
        </div>
      ) : null}
      <ul className="flex flex-col gap-1.5 lg:gap-2">
        {team.slots.map((slot, position) => {
          if (slot.seat == null) {
            return <EmptySlot key={slot.key} role={slot.role} owner={owner} next={position === nextSlot} />;
          }
          const teamMemberId = slot.seat.teamMemberId;
          return (
            <SeatLine
              key={slot.key}
              seat={slot.seat}
              owner={owner}
              mine={myMemberId != null && slot.seat.memberId === myMemberId}
              away={slot.seat.memberId != null && awayIds.has(slot.seat.memberId)}
              captainOffline={captainOffline && slot.seat.isCaptain}
              hero={slot.seat.heroId != null ? heroesById[slot.seat.heroId] : undefined}
              heroName={slot.seat.heroId != null ? heroName(slot.seat.heroId) : null}
              wide={wide}
              acting={teamMemberId != null && pickFor?.acting === teamMemberId}
              onChoose={
                choosing != null && teamMemberId != null && choosing.choosable.includes(teamMemberId)
                  ? () => choosing.onChoose(teamMemberId)
                  : undefined
              }
            />
          );
        })}
      </ul>
    </section>
  );
}

function SeatLine({
  seat,
  owner,
  mine,
  away,
  captainOffline,
  hero,
  heroName,
  wide,
  acting,
  onChoose
}: Readonly<{
  seat: RoomSeat;
  owner: MixOwner;
  mine: boolean;
  away: boolean;
  captainOffline: boolean;
  hero: PickBanItemLike | undefined;
  heroName: string | null;
  /** The desktop columns: bigger art. */
  wide: boolean;
  /** The member pick in play is this player's. */
  acting: boolean;
  /** Makes the row a button that picks for this player instead. */
  onChoose?: () => void;
}>) {
  const t = useTranslations("mixes.arena");
  const tRoom = useTranslations("mixes.room");
  const slotLabel = useSlotLabel(owner.ontology);
  const showRole = owner.showsRoles && seat.role != null && seat.role !== OPEN_SLOT_CODE;
  const heroSize = wide ? 36 : 26;
  const body = (
    <>
      {showRole ? (
        <IconTooltip label={slotLabel(seat.role as string)} className="hidden size-5 shrink-0 items-center justify-center sm:flex">
          <PlayerRoleIcon role={seat.role} ontology={owner.ontology} size={18} decorative />
        </IconTooltip>
      ) : null}
      <RankCrest rank={seat.rank} grid={owner.grid} size={wide ? 28 : 22} className="shrink-0" />
      <HandleLabel
        handle={seat.name}
        className="min-w-0 flex-1 truncate text-caption font-semibold text-[color:var(--aqt-fg)] lg:text-body"
        tagClassName="text-label"
      />
      {seat.isCaptain ? (
        <IconTooltip label={tRoom("captain")} className="flex shrink-0 items-center">
          <Crown aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
        </IconTooltip>
      ) : null}
      {captainOffline ? (
        <IconTooltip label={t("captainOffline")} className="flex shrink-0 items-center">
          <WifiOff aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
        </IconTooltip>
      ) : null}
      {mine ? (
        <span className="shrink-0 text-label font-semibold text-[color:var(--aqt-teal)]">{tRoom("you")}</span>
      ) : null}
      {away ? <span className={AWAY_CHIP_CLASS}>{tRoom("away")}</span> : null}
      {heroName != null && seat.heroId != null ? (
        <span className="shrink-0" style={{ viewTransitionName: heroTransitionName(seat.heroId) }}>
          <PickBanItemThumb kind={CHARACTER_PICK_BAN_KIND} item={hero} name={heroName} size={heroSize} />
        </span>
      ) : acting || onChoose != null ? (
        // Where the hero will land: in the accent for the player picked for now, faint for the others on offer.
        <span
          aria-hidden
          className={cn(
            "shrink-0 rounded-full border-2 border-dashed",
            acting ? "border-[color:var(--aqt-teal)]" : "border-[color:var(--aqt-border-2)]"
          )}
          style={{ width: heroSize, height: heroSize }}
        />
      ) : null}
    </>
  );
  const frame = cn(
    "flex min-h-10 w-full min-w-0 items-center gap-2 rounded-lg border px-2 py-1.5 lg:min-h-14 lg:gap-2.5 lg:px-3",
    acting
      ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)] ring-1 ring-[color:var(--aqt-teal)]"
      : mine
        ? "border-[color:var(--aqt-teal)]/60 bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)]"
        : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)]"
  );
  return (
    <li style={{ viewTransitionName: playerTransitionName(seat.key) }} className="min-w-0">
      {onChoose != null ? (
        <RowButton
          aria-pressed={acting}
          className={cn(
            frame,
            acting
              ? "hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)]"
              : "hover:border-[color:var(--aqt-teal)]/60"
          )}
          onClick={onChoose}
        >
          {body}
        </RowButton>
      ) : (
        <div className={frame}>{body}</div>
      )}
    </li>
  );
}

function EmptySlot({ role, owner, next }: Readonly<{ role: string | null; owner: MixOwner; next: boolean }>) {
  const t = useTranslations("mixes.arena");
  const slotLabel = useSlotLabel(owner.ontology);
  const named = owner.showsRoles && role != null;
  return (
    <li
      className={cn(
        "flex min-h-10 items-center gap-2 rounded-lg border border-dashed px-2 py-1.5 text-caption lg:min-h-14 lg:px-3",
        next
          ? "border-[color:var(--aqt-teal)]/70 text-[color:var(--aqt-teal)]"
          : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-faint)]"
      )}
    >
      {named ? <PlayerRoleIcon role={role} ontology={owner.ontology} size={18} decorative /> : null}
      <span className="truncate">{named ? slotLabel(role) : t("openSlot")}</span>
    </li>
  );
}
