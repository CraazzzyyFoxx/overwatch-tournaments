"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Dices, Headphones, Shuffle, Users } from "lucide-react";

import { MatchHistoryList } from "@/app/balancer/mix/_components/MatchHistoryList";
import { NextMapRoll } from "@/app/balancer/mix/_components/NextMapStrip";
import { StartMatchButton } from "@/app/balancer/mix/_components/StartMatchButton";
import { PickupResultControls } from "@/app/balancer/mix/PickupResultControls";
import { CAPTION_CLASS, CARD_TITLE_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import Image from "@/components/ui/image";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";
import type {
  CustomGame,
  CustomGameLobby,
  CustomGameMatch,
  CustomGameOutcome
} from "@/services/custom-game.service";

/** Everything the match centre writes, handed down by the room (its mutations live in `usePickupMix`). */
export interface RoomMatchActions {
  onBalance: () => void;
  balancing: boolean;
  onDraft: () => void;
  drafting: boolean;
  onStartMatch: (flipOpener: boolean) => void;
  starting: boolean;
  onRecord: (outcome: CustomGameOutcome) => void;
  recording: boolean;
  onNextMapChange: (mapId: number | null) => void;
  settingNextMap: boolean;
}

/**
 * The room's centre outside the draft and the bans (spec §5): an idle lobby waiting for its teams, and -- as one
 * scoreboard under the map -- a formed one waiting for its start (the map, who bans first) and a live one waiting for
 * its result. The scoreboard stretches to the rosters' height; the map's still takes up whatever they leave. A host's
 * action for the phase sits at its foot; everyone else reads what the lobby waits for.
 */
export function RoomMatchStage({
  phase,
  game,
  lobby,
  canWrite,
  teamNames,
  awayNames,
  shortSeats,
  maps,
  mixMatches,
  voiceUrl,
  actions
}: Readonly<{
  phase: "idle" | "ready" | "live";
  game: CustomGame;
  lobby: CustomGameLobby;
  canWrite: boolean;
  /** The two lineup team names, left then right. */
  teamNames: readonly [string, string];
  /** Seated players who stepped away (the start dialog names them). */
  awayNames: readonly string[];
  /** "{count} of {need} players" while the lobby cannot fill its seats; null when it can. */
  shortSeats: string | null;
  maps: CatalogEntityRead[];
  mixMatches: CustomGameMatch[];
  /** The viewer's own team voice channel while they play here. */
  voiceUrl: string | null;
  actions: RoomMatchActions;
}>) {
  const t = useTranslations("mixes.arena.match");
  const tRoom = useTranslations("mixes.room");
  const tTeams = useTranslations("mixes.teams");
  const tLobbies = useTranslations("mixes.lobbies");
  const [reformOpen, setReformOpen] = useState<"draft" | "balance" | null>(null);
  const draftMode = game.team_formation === "draft";
  const map = lobby.next_map_id == null ? null : (maps.find((row) => row.id === lobby.next_map_id) ?? null);
  // Re-forming replaces a lineup nobody recorded: that result would be lost, so the button asks first.
  const atRisk = lobby.lineup_recorded === false;
  const reform = (kind: "draft" | "balance") =>
    atRisk ? setReformOpen(kind) : kind === "draft" ? actions.onDraft() : actions.onBalance();

  const formButtons = canWrite ? (
    <div className="flex flex-wrap items-center gap-2">
      {draftMode ? (
        <Button
          type="button"
          variant={phase === "idle" ? "default" : "outline"}
          size="sm"
          disabled={actions.drafting || shortSeats != null}
          onClick={() => reform("draft")}
        >
          {actions.drafting ? <Spinner className="mr-1.5 size-3.5" /> : <Users className="mr-1.5 size-3.5" aria-hidden />}
          {phase === "idle" ? tRoom("draft") : t("draftAgain")}
        </Button>
      ) : null}
      <Button
        type="button"
        variant={!draftMode && phase === "idle" ? "default" : "outline"}
        size="sm"
        disabled={actions.balancing || shortSeats != null}
        onClick={() => reform("balance")}
      >
        {actions.balancing ? <Spinner className="mr-1.5 size-3.5" /> : <Shuffle className="mr-1.5 size-3.5" aria-hidden />}
        {draftMode ? tRoom("buildWithBalancer") : phase === "idle" ? tTeams("balance") : t("balanceAgain")}
      </Button>
      <ConfirmDialog
        open={reformOpen != null}
        onOpenChange={(open) => !open && setReformOpen(null)}
        intent={
          reformOpen === "balance"
            ? {
                title: tLobbies("rebalanceTitle"),
                description: tLobbies("rebalanceDescription"),
                confirmLabel: tLobbies("rebalanceConfirm"),
                tone: "danger"
              }
            : {
                title: tRoom("draftReformTitle"),
                description: tRoom("draftReformDescription"),
                confirmLabel: tRoom("draftReformConfirm"),
                tone: "danger"
              }
        }
        pending={actions.drafting || actions.balancing}
        onConfirm={() => {
          const kind = reformOpen;
          setReformOpen(null);
          if (kind === "draft") actions.onDraft();
          else if (kind === "balance") actions.onBalance();
        }}
      />
    </div>
  ) : null;

  if (phase === "idle") {
    return (
      <Card className="flex flex-col items-start gap-3 px-5 py-6">
        <h2 className={CARD_TITLE_CLASS}>{t("idleTitle")}</h2>
        <p className="text-body text-[color:var(--aqt-fg-muted)]">{canWrite ? t("idleHost") : t("idleViewer")}</p>
        {shortSeats != null ? <p className={CAPTION_CLASS}>{shortSeats}</p> : null}
        {formButtons}
      </Card>
    );
  }

  const opener = lobby.opener_index != null ? (teamNames[lobby.opener_index] ?? null) : null;
  const history = mixMatches.filter((match) => match.lobby_index === lobby.lobby_index).slice(0, 3);

  return (
    <Card className="flex flex-1 flex-col gap-0 overflow-hidden">
      <MapBanner map={map} label={phase === "ready" ? tRoom("nextMapLabel") : t("map")} emptyName={t("noMap")}>
        {phase === "live" && voiceUrl != null ? (
          <Button asChild variant="outline" size="sm">
            <a href={voiceUrl} target="_blank" rel="noreferrer">
              <Headphones aria-hidden="true" />
              {tRoom("voice")}
            </a>
          </Button>
        ) : null}
      </MapBanner>
      {phase === "ready" && canWrite ? (
        <NextMapRoll
          nextMapId={lobby.next_map_id}
          maps={maps}
          matches={mixMatches}
          saving={actions.settingNextMap}
          onNextMapChange={actions.onNextMapChange}
          className="border-t border-[color:var(--aqt-border)] px-5 py-3"
        />
      ) : null}
      {history.length > 0 ? (
        <MatchHistoryList
          matches={history}
          lobbyCount={game.lobbies.length}
          canWrite={false}
          undoingMatchId={null}
          discipline={game.discipline}
          className="border-t border-[color:var(--aqt-border)] px-5 pb-1 pt-3"
        />
      ) : null}
      <div className="border-t border-[color:var(--aqt-border)] px-5 py-4">
        {phase === "live" ? (
          canWrite ? (
            <PickupResultControls
              teamCount={2}
              teamNames={teamNames}
              saving={actions.recording}
              pointsPerWin={game.settings.points_per_win ?? null}
              onRecord={actions.onRecord}
            />
          ) : (
            <p className={CAPTION_CLASS}>{t("liveViewer")}</p>
          )
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {canWrite ? (
              <>
                <StartMatchButton
                  awayNames={awayNames}
                  opener={lobby.opener_index != null ? { names: teamNames, index: lobby.opener_index } : null}
                  starting={actions.starting}
                  onStart={actions.onStartMatch}
                />
                {formButtons}
              </>
            ) : (
              <p className={CAPTION_CLASS}>{t("readyViewer")}</p>
            )}
            {opener != null ? (
              <p className={cn(CAPTION_CLASS, "ml-auto")}>{tRoom("opener", { team: opener })}</p>
            ) : null}
          </div>
        )}
      </div>
    </Card>
  );
}

/**
 * The map as the scoreboard's backdrop: on a wide screen its still fills whatever height the rosters beside it leave
 * (a phone gets a fixed strip), with the name on top. Without a still, or without a map, a neutral tile keeps the place.
 */
function MapBanner({
  map,
  label,
  emptyName,
  children
}: Readonly<{ map: CatalogEntityRead | null; label: string; emptyName: string; children?: ReactNode }>) {
  const src = map?.image_path || null;
  return (
    <div className="relative flex min-h-32 flex-col justify-end bg-[color:var(--aqt-card-2)] sm:min-h-40 lg:flex-1">
      {src != null ? (
        <>
          <Image src={src} alt="" fill sizes="(min-width: 1024px) 720px, 100vw" className="object-cover object-center" />
          {/* The same two scrims as the tournament pregame's map banner: the base lifted for the caption, and the left
              so a bright skybox never sits under the name. */}
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
      <div className="relative flex flex-wrap items-end gap-x-3 gap-y-2 p-4">
        {map == null ? <Dices aria-hidden className="mb-1 size-6 shrink-0 text-[color:var(--aqt-fg-faint)]" /> : null}
        <div className="min-w-0 flex-1 basis-48">
          <Eyebrow tone="muted">{map?.parent != null ? `${label} · ${map.parent.name}` : label}</Eyebrow>
          <h2
            className={cn(
              "truncate font-display text-2xl font-bold leading-tight",
              map != null ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {map?.name ?? emptyName}
          </h2>
        </div>
        {children}
      </div>
    </div>
  );
}
