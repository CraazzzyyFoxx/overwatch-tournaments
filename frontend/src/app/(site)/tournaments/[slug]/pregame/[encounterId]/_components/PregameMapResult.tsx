"use client";

import { useState } from "react";
import Image from "@/components/ui/image";
import { AlertTriangle, Check, Equal, Hourglass, Lock, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { TeamLogo, type TeamNameInput } from "@/components/TeamName";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Card, CardContent } from "@craazzzyyfoxx/admin-kit/ui/card";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { MapReportDialog } from "@/components/pick-ban/MapReportDialog";
import { acceptedScore, pickBanSeats } from "@/components/pick-ban/pick-ban-model";
import type { PregameCharacterBoard } from "@/disciplines/types";
import { duelSeats, seatTeam, type Duel } from "@/lib/encounter/seats";
import { cn } from "@/lib/utils";
import type { EncounterTeam } from "@/types/encounter.types";
import type { PickBanGame, PickBanGameClaim } from "@/types/tournament.types";

import { PregameCharacterBans } from "./PregameCharacterBans";
import type { RoomMetadata } from "./usePregameRoomData";

interface PregameMapResultProps {
  encounterId: number;
  /** The map's name, already resolved against the catalog by the room. */
  mapName: string;
  /** The map's still, for the phase's banner. Empty when the catalog has none. */
  mapImagePath: string | null;
  /** Which map of the series this is, 1-based. */
  round: number;
  /** The participation the viewer captains; null for a spectator: they watch the step, they never file a report. */
  viewerTeamId: number | null;
  /** The encounter's live seats: names, logos and the slot order of the two claim tiles. */
  teams: EncounterTeam[];
  /**
   * This position's game — the result authority for it. Null only while the
   * server has not opened one (an older payload); the screen then shows the
   * map and no claims.
   */
  game: PickBanGame | null;
  /**
   * This map's hero board — who banned or protected what, what is unavailable
   * here and what is left. Its `actions` are empty when the encounter runs no
   * hero phase, and the section then renders nothing at all.
   */
  heroBoard: PregameCharacterBoard;
  /**
   * The room's game's metadata, as the bans' module slot needs it: loading, failed (with a retry) or ready.
   */
  metadata: RoomMetadata;
  /**
   * Who starts on which side of this map, when the room picked sides — read
   * before the lobby is set up, like the bans.
   */
  sides?: React.ReactNode;
  /**
   * The hero session's undo affordance, rendered under the bans (or the sides)
   * it would take back. Supplied as a node because the consent flow needs the
   * room's query keys and catalog, neither of which this screen otherwise knows about.
   */
  heroUndo?: React.ReactNode;
  header: React.ReactNode;
  /** Query keys to invalidate once a report lands. */
  invalidateKeys: unknown[][];
  /** Catalog for naming the played map when there was no veto pick. */
  mapChoices?: ReadonlyArray<{ id: number; name: string }>;
  /** The report dialog also files the game's match by its id (a tournament game of a game with a match fetcher). */
  matchImport?: boolean;
}

/** What a side's claim tile may show, in the order the phase moves through. */
type ClaimState = "waiting" | "sealed" | "filed";

/**
 * The loop's third phase: the map is picked, its heroes are banned, so the map
 * is played — and BOTH captains confirming its score is what opens the next
 * map's bans (backend: `map_report.submit_map_report` ->
 * `pick_ban_session.advance_to_next_round`).
 *
 * Rendered as the reconciliation it is: the map's still as the banner (the map
 * is the subject of this screen, so its art carries the identity instead of its
 * name in bold), then the two claims side by side with a verdict glyph between
 * them — equals once they agree, a cross once they do not. That diagram is the
 * mechanic; the prose under it is a caption, not the explanation.
 *
 * The opponent's numbers stay hidden until both reports are in: the two are
 * meant to be independent claims that reconcile, and showing one first would
 * turn the second into a copy of it — hence `sealed`, a filed-but-withheld
 * tile rather than a blank one. The viewer's OWN numbers are never withheld
 * from them (they typed them). Once both are in and they disagree, both are
 * shown — there is nothing left to bias, and an admin resolves it.
 */
export function PregameMapResult({
  encounterId,
  mapName,
  mapImagePath,
  round,
  viewerTeamId,
  teams,
  game,
  heroBoard,
  metadata,
  sides,
  heroUndo,
  header,
  invalidateKeys,
  mapChoices,
  matchImport
}: Readonly<PregameMapResultProps>) {
  const t = useTranslations("pickBan.room");
  const [dialogOpen, setDialogOpen] = useState(false);

  const [seatOne, seatTwo] = duelSeats(teams);
  const seats = pickBanSeats(teams);
  const claims = game?.claims ?? [];
  const claimOf = (seat: EncounterTeam | null) =>
    claims.find((claim) => claim.claimant_team_id === seat?.id) ?? null;
  const claimOne = claimOf(seatOne);
  const claimTwo = claimOf(seatTwo);
  const ownClaim =
    viewerTeamId != null && viewerTeamId === seatOne?.id
      ? claimOne
      : viewerTeamId != null && viewerTeamId === seatTwo?.id
        ? claimTwo
        : null;
  const bothFiled = claimOne != null && claimTwo != null;
  const disputed = game?.state === "disputed";
  const accepted = acceptedScore(game, teams);
  const hasBoard = heroBoard.actions.length > 0 || heroBoard.banned.length > 0;

  /** A seat's tile shows its numbers when both claims are in, or when they are the viewer's own. */
  const visibleTo = (seat: EncounterTeam | null) =>
    bothFiled || (viewerTeamId != null && viewerTeamId === seat?.id);
  /** One claim as a scoreline in slot order, whoever filed it. */
  const claimScore = (claim: PickBanGameClaim | null): Duel<number> | null =>
    claim == null
      ? null
      : {
          one: claim.results.find((line) => line.encounter_team_id === seatOne?.id)?.score ?? 0,
          two: claim.results.find((line) => line.encounter_team_id === seatTwo?.id)?.score ?? 0
        };

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-5 p-5">
          {header}

          <section className="overflow-hidden rounded-xl border border-[color:var(--aqt-border)]">
            {/* Map banner: the still is the heading, the name sits on top of it.
              With no still in the catalog the block collapses to the caption
              alone rather than reserving 8rem of flat surface for nothing. */}
            <div
              className={cn(
                "relative flex w-full flex-col justify-end bg-[color:var(--aqt-card-2)]",
                mapImagePath ? "h-32 sm:h-40" : null
              )}
            >
              {mapImagePath ? (
                <>
                  <Image
                    src={mapImagePath}
                    alt=""
                    fill
                    sizes="(max-width: 1024px) 100vw, 1024px"
                    className="object-cover object-center"
                    priority
                  />
                  {/* Two scrims: one lifting the base for the caption, one from the
                    left so a bright skybox never sits under the map's name. */}
                  <span
                    aria-hidden
                    className="absolute inset-0"
                    style={{
                      background:
                        "linear-gradient(to top, var(--aqt-card) 0%, color-mix(in srgb, var(--aqt-card) 82%, transparent) 34%, color-mix(in srgb, var(--aqt-card) 20%, transparent) 72%, transparent 100%)"
                    }}
                  />
                  <span
                    aria-hidden
                    className="absolute inset-0"
                    style={{
                      background:
                        "linear-gradient(to right, color-mix(in srgb, var(--aqt-card) 78%, transparent) 0%, transparent 55%)"
                    }}
                  />
                </>
              ) : null}
              <div className="relative flex flex-col gap-0.5 p-4">
                <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-teal)]">
                  {t("round.label", { n: round })} · {t("mapResult.eyebrow")}
                </span>
                <h2 className="font-onest text-2xl font-semibold leading-tight tracking-[-0.015em] sm:text-3xl">
                  {mapName}
                </h2>
              </div>
            </div>

            {/* Between the banner and the claims, because that is the order the
                captains need it in: the bans belong to the map above (they are
                set up in its lobby) and are read before there is any result to
                file below. */}
            {hasBoard || sides != null ? (
              <div className="flex flex-col gap-3 border-y border-[color:var(--aqt-border)] p-4">
                {sides != null ? <div className="mx-auto w-full max-w-2xl">{sides}</div> : null}
                {/* Same width as the claim row below, so the bans and the score
                    they belong to read as one column rather than two widths. */}
                {hasBoard ? (
                  <div className="mx-auto w-full max-w-2xl">
                    <PregameCharacterBans
                      encounterId={encounterId}
                      metadata={metadata}
                      board={heroBoard}
                      teams={teams}
                    />
                  </div>
                ) : null}
                {/* Directly under the list it corrects: a wrong ban is noticed
                    HERE, reading the lobby setup, not back in the closed grid. */}
                {heroUndo != null ? (
                  <div className="mx-auto w-full max-w-2xl">{heroUndo}</div>
                ) : null}
              </div>
            ) : null}

            <div className="flex flex-col gap-4 p-4">
              {/* Stacked below `sm`: side by side there, three columns on a
                  phone clip both team names and wrap every status label. From
                  `sm` up the tracks are `minmax(0,…)`, never plain `1fr` --
                  grid items default to `min-width:auto` and would not shrink. */}
              <div className="mx-auto grid w-full max-w-2xl grid-cols-1 items-stretch gap-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:gap-4">
                <ClaimTile
                  name={seatOne?.name ?? t("tbd")}
                  team={seatTeam(seatOne)}
                  report={claimScore(claimOne)}
                  revealed={visibleTo(seatOne)}
                  accentVar="--aqt-teal"
                />
                <Verdict bothFiled={bothFiled} disputed={disputed} />
                <ClaimTile
                  name={seatTwo?.name ?? t("tbd")}
                  team={seatTeam(seatTwo)}
                  report={claimScore(claimTwo)}
                  revealed={visibleTo(seatTwo)}
                  accentVar="--aqt-rose"
                />
              </div>

              {accepted != null ? (
                <p
                  data-game-state="confirmed"
                  className="flex items-start gap-2 text-sm text-[color:var(--aqt-positive)]"
                >
                  <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  {t("mapResult.accepted", { first: accepted.one, second: accepted.two })}
                </p>
              ) : disputed ? (
                <p
                  data-game-state="disputed"
                  className="flex items-start gap-2 text-sm text-[color:var(--aqt-amber)]"
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  {t("mapReport.disputedHint")}
                </p>
              ) : (
                <p className="text-xs leading-relaxed text-[color:var(--aqt-fg-muted)]">
                  {t("mapResult.hint")}
                </p>
              )}

              {viewerTeamId != null && game != null ? (
                <div>
                  <Button
                    onClick={() => setDialogOpen(true)}
                    variant={ownClaim == null || accepted != null ? "default" : "outline"}
                  >
                    {accepted != null
                      ? t("mapResult.view")
                      : ownClaim == null
                        ? t("mapResult.report")
                        : t("mapResult.amend")}
                  </Button>
                </div>
              ) : null}
            </div>
          </section>
        </CardContent>
      </Card>

      {viewerTeamId != null && dialogOpen && game != null ? (
        <MapReportDialog
          encounterId={encounterId}
          game={game}
          mapName={mapName}
          seats={seats}
          viewerTeamId={viewerTeamId}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          mapChoices={mapChoices}
          invalidateKeys={invalidateKeys}
          matchImport={matchImport}
        />
      ) : null}
    </>
  );
}

/**
 * One seat's claim: logo, team, and either its two digits or the reason they
 * are not on screen. The digit slab stays the same size in every state, so the
 * tile does not resize under the reader as reports land.
 */
function ClaimTile({
  name,
  team,
  report,
  revealed,
  accentVar
}: Readonly<{
  name: string;
  team: TeamNameInput | null | undefined;
  /** The claim as a scoreline in slot order, or null while it is unfiled. */
  report: Duel<number> | null;
  revealed: boolean;
  accentVar: "--aqt-teal" | "--aqt-rose";
}>) {
  const t = useTranslations("pickBan.room");
  const state: ClaimState = report == null ? "waiting" : revealed ? "filed" : "sealed";
  const StateIcon = state === "waiting" ? Hourglass : state === "sealed" ? Lock : Check;
  const announced =
    report == null
      ? t("mapResult.pending", { team: name })
      : revealed
        ? t("mapResult.filedScore", {
            team: name,
            first: report.one,
            second: report.two
          })
        : t("mapResult.filed", { team: name });

  return (
    <div
      data-claim={state}
      className={cn(
        "flex flex-col gap-2 rounded-xl border px-3 py-3 text-center",
        state === "waiting"
          ? "border-dashed border-[color:var(--aqt-border-2)]"
          : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)]/40"
      )}
    >
      <span className="sr-only">{announced}</span>
      {/* Full width + `justify-center` rather than the column's `items-center`:
          a non-stretch cross alignment would size this row to min-content and
          the team name would overflow the tile instead of truncating. */}
      <span className="flex min-w-0 items-center justify-center gap-1.5">
        <TeamLogo team={team} size="sm" />
        <span
          title={name}
          className="min-w-0 truncate text-xs font-semibold"
          style={{ color: `var(${accentVar})` }}
          aria-hidden
        >
          {name}
        </span>
      </span>

      <span
        aria-hidden
        className="font-onest text-[clamp(1.4rem,3vw,1.9rem)] font-semibold leading-none tabular-nums"
      >
        {state === "filed" && report != null ? (
          <>
            {report.one}
            <span className="text-[0.62em] text-[color:var(--aqt-fg-faint)]">:</span>
            {report.two}
          </>
        ) : (
          <span className="text-[color:var(--aqt-fg-faint)]">
            ?<span className="text-[0.62em]">:</span>?
          </span>
        )}
      </span>

      <span
        aria-hidden
        className={cn(
          eyebrowClass(),
          "inline-flex items-center gap-1",
          state !== "waiting" && "text-[color:var(--aqt-positive)]"
        )}
      >
        <StateIcon className="h-3 w-3" />
        {t(`mapResult.claim.${state}`)}
      </span>
    </div>
  );
}

/** The operator between the two claims: `=` once they agree, `≠` once they clash. */
function Verdict({ bothFiled, disputed }: Readonly<{ bothFiled: boolean; disputed: boolean }>) {
  const t = useTranslations("pickBan.room");
  const tone = !bothFiled ? "pending" : disputed ? "bad" : "good";
  const Icon = tone === "pending" ? Hourglass : tone === "bad" ? X : Equal;
  const label = t(
    `mapResult.verdict.${tone === "pending" ? "waiting" : tone === "bad" ? "disagree" : "agree"}`
  );

  return (
    <output className="flex flex-col items-center justify-center gap-1.5 self-center">
      <span
        aria-hidden
        className={cn(
          "grid h-8 w-8 place-items-center rounded-full border",
          tone === "good"
            ? "border-[color:var(--aqt-positive)]/45 bg-[color:var(--aqt-positive)]/12 text-[color:var(--aqt-positive)]"
            : tone === "bad"
              ? "border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-amber)]/12 text-[color:var(--aqt-amber)]"
              : "border-[color:var(--aqt-border-2)] text-[color:var(--aqt-fg-faint)]"
        )}
      >
        <Icon className="h-4 w-4" strokeWidth={2.5} />
      </span>
      <span
        className={cn(
          eyebrowClass(),
          "max-w-[7.5rem] text-center leading-tight",
          tone === "good"
            ? "text-[color:var(--aqt-positive)]"
            : tone === "bad"
              ? "text-[color:var(--aqt-amber)]"
              : null
        )}
      >
        {label}
      </span>
    </output>
  );
}
