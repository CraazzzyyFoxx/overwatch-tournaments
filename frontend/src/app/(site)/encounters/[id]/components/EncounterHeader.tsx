import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { Encounter, EncounterTeam } from "@/types/encounter.types";
import { TeamLogo } from "@/components/TeamName";
import { Card } from "@/components/ui/card";
import { Eyebrow, eyebrowClass } from "@/components/ui/eyebrow";
import { acceptedScore } from "@/components/pick-ban/pick-ban-model";
import {
  BOARD,
  BOARD_CENTER,
  BOARD_SIDE,
  BOARD_SIDE_TWO,
  CARD_SUB,
  HEADER_CARD,
  HEADER_FOOT,
  HEADER_TOP,
  SIDE_TEXT
} from "@/components/match/EncounterAtoms";
import { buildSeriesSlots, getSeriesVerdict, type SeriesSlot } from "@/lib/encounter/detail";
import { duelSeats, seatTeam, type Duel, type DuelSlot } from "@/lib/encounter/seats";

export type EncounterHeaderFact = { label: string; value: string; sub?: string };

/**
 * The match, stated once: where it sits, who played, the result, and the few
 * facts about the series. The hero and the scoreboard under it used to say the
 * same thing three times — "A vs B" as a title, "A took the series 3–2" as a
 * lede, then the 3:2 board — before the page reached any content.
 */
export default function EncounterHeader({
  encounter,
  crumbs,
  actions,
  pills,
  facts
}: Readonly<{
  encounter: Encounter;
  crumbs: ReactNode;
  actions: ReactNode;
  /** Chips for states that want attention; nothing is rendered without one. */
  pills?: ReactNode;
  facts: EncounterHeaderFact[];
}>) {
  const t = useTranslations();
  const slots = buildSeriesSlots(encounter);
  const verdict = getSeriesVerdict(encounter);
  const [seatOne, seatTwo] = duelSeats(encounter.teams);
  const names = {
    one: seatOne?.name ?? t("common.tbd"),
    two: seatTwo?.name ?? t("common.tbd")
  };

  return (
    <Card asChild className={HEADER_CARD}>
      <header>
        <div className={HEADER_TOP}>
          <div
            className={eyebrowClass(
              "faint",
              "flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 font-normal"
            )}
          >
            {crumbs}
          </div>
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        </div>

        {/* The page's one h1: the matchup, read by the outline the way the old
            hero title was, while the board below draws it. */}
        <h1 className="sr-only">
          {t("encounters.detail.heroTitle", { first: names.one, second: names.two })}
        </h1>
        <div className={BOARD}>
          <TeamBlock seat={seatOne} slot={1} />
          <div className={BOARD_CENTER}>
            <p className="flex items-baseline gap-3 font-display text-display font-bold leading-none tabular-nums">
              <span className={SIDE_TEXT[1]}>{seatOne?.score ?? 0}</span>
              <span aria-hidden className="text-title text-[color:var(--aqt-fg-faint)]">
                :
              </span>
              <span className={SIDE_TEXT[2]}>{seatTwo?.score ?? 0}</span>
            </p>
            <p className={eyebrowClass("faint", "text-center")}>
              {verdict.outcome === "win"
                ? t("encounters.detail.verdictWin", {
                    team: verdict.winner === 1 ? names.one : names.two
                  })
                : verdict.outcome === "draw"
                  ? t("encounters.detail.verdictDraw")
                  : t("encounters.detail.verdictPending")}
            </p>
            <MapPips slots={slots} teams={encounter.teams} names={names} />
          </div>
          <TeamBlock seat={seatTwo} slot={2} />
        </div>

        <div className={HEADER_FOOT}>
          {pills ? <div className="flex flex-wrap gap-1.5">{pills}</div> : null}
          {facts.length > 0 ? (
            <dl className="flex flex-wrap gap-x-7 gap-y-2.5">
              {facts.map((fact) => (
                <div key={fact.label} className="flex flex-col gap-0.75">
                  <Eyebrow as="dt">{fact.label}</Eyebrow>
                  <dd className="inline-flex items-baseline gap-2 font-display text-ui font-bold tabular-nums text-[color:var(--aqt-fg)]">
                    {fact.value}
                    {fact.sub ? <span className={cn(CARD_SUB, "font-normal")}>{fact.sub}</span> : null}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      </header>
    </Card>
  );
}

function TeamBlock({
  seat,
  slot
}: Readonly<{ seat: EncounterTeam | null; slot: DuelSlot }>) {
  const t = useTranslations();
  const meta = [
    seat?.team?.placement != null
      ? `${t("encounters.detail.placementShort")} #${seat.team.placement}`
      : null,
    seat?.team?.group?.name ? `${t("common.group")} ${seat.team.group.name}` : null
  ].filter(Boolean);

  return (
    <div className={cn(BOARD_SIDE, slot === 2 && BOARD_SIDE_TWO)}>
      <TeamLogo team={seatTeam(seat)} size="xl" />
      <div className="flex min-w-0 flex-col gap-1.5">
        {/* Not a heading: a scoreboard label. The h1 above names the matchup. */}
        <p className={cn("font-display text-heading font-bold wrap-anywhere md:text-title", SIDE_TEXT[slot])}>
          {seat?.name ?? t("common.tbd")}
        </p>
        {/* Plain text, not chips: the winner is already the verdict and the pips. */}
        {meta.length > 0 ? <p className={CARD_SUB}>{meta.join(" · ")}</p> : null}
      </div>
    </div>
  );
}

/** Played: a parsed log or an accepted result — the page's own rule. */
function isPlayed(slot: SeriesSlot, teams: Encounter["teams"]): boolean {
  return slot.match != null || acceptedScore(slot.game, teams) != null;
}

/**
 * Pip hue, in the same precedence the aria summary below reads out: in-progress
 * first, then never-played, then the winner's side, then a tie.
 */
function pipToneClass(slot: SeriesSlot, teams: Encounter["teams"]): string {
  if (slot.isLive)
    return "border-[color:var(--aqt-status-live)] ring-2 ring-[color:color-mix(in_srgb,var(--aqt-status-live)_18%,transparent)]";
  if (!isPlayed(slot, teams)) return "border-dashed border-[color:var(--aqt-border-2)]";
  if (slot.winner === 1) return "bg-[color:var(--aqt-teal)]";
  if (slot.winner === 2) return "bg-[color:var(--aqt-rose)]";
  return "bg-[color:var(--aqt-amber)]";
}

/**
 * One pip per slot of the format: filled in the winner's hue, hollow for a map
 * the series never needed, ringed for the map in progress. This is what makes a
 * 3–1 in a Bo5 legible as "four maps played, one spare".
 */
function MapPips({
  slots,
  teams,
  names
}: Readonly<{ slots: SeriesSlot[]; teams: Encounter["teams"]; names: Duel<string> }>) {
  const t = useTranslations();
  const summary = slots
    .map((slot) => {
      if (slot.isLive) return t("encounters.state.live");
      if (!isPlayed(slot, teams)) return t("encounters.detail.pipUnplayed");
      if (!slot.winner) return t("encounters.detail.tie");
      return slot.winner === 1 ? names.one : names.two;
    })
    .join(", ");

  return (
    <div
      className="flex items-center gap-1"
      role="img"
      aria-label={t("encounters.detail.pipsAria", { summary })}
    >
      {slots.map((slot) => (
        <span
          key={slot.index}
          aria-hidden
          className={cn("h-4.5 w-2.75 rounded-xs border border-transparent", pipToneClass(slot, teams))}
        />
      ))}
    </div>
  );
}
