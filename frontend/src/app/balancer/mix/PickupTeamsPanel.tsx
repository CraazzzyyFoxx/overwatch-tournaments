"use client";

import { useState } from "react";

import Image from "next/image";

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent
} from "@dnd-kit/core";
import {
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  Archive,
  ClipboardCopy,
  Copy,
  Dices,
  History,
  Loader2,
  Send,
  Shuffle,
  Undo2
} from "lucide-react";

import { PANEL_CLASS } from "@/app/balancer/components/balancer-page-helpers";
import { rollNextMap, rollableModes } from "@/app/balancer/pickup/pickup-map-roll";
import { PickupResultControls } from "@/app/balancer/pickup/PickupResultControls";
import {
  CAPTION_CLASS,
  EYEBROW_CLASS,
  METRIC_NEUTRAL_CLASS,
  METRIC_PILL_CLASS,
  teamAccent
} from "@/app/balancer/pickup/pickup-chrome";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from "@/components/ui/alert-dialog";
import DivisionIcon from "@/components/DivisionIcon";
import { MapCombobox } from "@/components/MapCombobox";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { InlineEditText } from "@/components/admin/InlineEditText";
import { formatRelative } from "@/components/admin/format-time";
import { Button, buttonVariants } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useNodeCapture } from "@/hooks/useNodeCapture";
import { OW_REFERENCE_GRID, resolveDivisionFromRank } from "@/lib/division-grid";
import { notify } from "@/lib/notify";
import { ROLES, ROLE_LABELS } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { CustomGame, CustomGameMatch } from "@/services/custom-game.service";
import type { MapRead } from "@/types/map.types";

import {
  LOBBY_SIZE,
  parseVariants,
  teamNamesByIndex,
  type PickupRecordOutcomeInput,
  type PickupSeat,
  type PickupTeam,
  type PickupVariant
} from "./pickup-lineup";

/** The demoted share/close tools: quiet glyphs that only light up on hover. */
const TOOL_ICON_CLASS = "size-9 text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]";

type PickupTeamsPanelProps = {
  canWrite: boolean;
  gamesLoading: boolean;
  gamesError: boolean;
  onRetryGames: () => void;
  game: CustomGame | undefined;
  gameLoading: boolean;
  hasMix: boolean;
  balancing: boolean;
  activeCount: number;
  onBalance: () => void;
  /** Which of the solver's options is on screen — owned by the page so the board agrees. */
  variantIndex: number;
  onVariantIndexChange: (index: number) => void;
  recordingOutcome: boolean;
  onRecordOutcome: (input: PickupRecordOutcomeInput) => void;
  /** The permanent record of every match this mix has played, newest first. */
  matches: CustomGameMatch[];
  /** The match whose undo is in flight, so only that row spins. */
  undoingMatchId?: number | null;
  /** Omitted -- the history renders read-only, matching a page that offers no undo. */
  onUndoMatch?: (matchId: number) => void;
  /** The OW map catalogue with its gamemodes -- the roll pool and the manual picker. */
  maps: MapRead[];
  settingNextMap: boolean;
  /** Rolled or hand-picked; `null` clears. Persisted server-side so every viewer sees the same map. */
  onNextMapChange: (mapId: number | null) => void;
  closingMix: boolean;
  onCloseMix: () => void;
  /** Omitted -- team headers render read-only, matching a `canWrite=false` viewer. */
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  /** Omitted -- seats render without drag handles, matching a `canWrite=false` viewer. */
  onSwapSeats?: (
    variantIndex: number,
    firstUuid: string,
    secondUuid: string
  ) => void | Promise<unknown>;
  onCopyBattleTags: () => void;
  postingToDiscord?: boolean;
  /** Omitted -- no Post to Discord button, matching a page that offers no post. */
  onPostToDiscord?: (variantIndex: number, image: Blob | null) => void;
};

/**
 * The result side: the teams the solver produced, and the writes that act on
 * them — re-balance, record who won (repeatable), and close the mix.
 *
 * Teams are read from the stored `balance_result` document, because only it
 * knows which *seat* each player got and
 * at what rating — the difference between "these five are together" and a
 * lineup a host can actually call out. The solver returns many equally-scored
 * options, so the variant pager walks them without re-running the balance.
 */
export function PickupTeamsPanel({
  canWrite,
  gamesLoading,
  gamesError,
  onRetryGames,
  game,
  gameLoading,
  hasMix,
  balancing,
  activeCount,
  onBalance,
  variantIndex,
  onVariantIndexChange,
  recordingOutcome,
  onRecordOutcome,
  matches,
  undoingMatchId = null,
  onUndoMatch,
  maps,
  settingNextMap,
  onNextMapChange,
  closingMix,
  onCloseMix,
  onRenameTeam,
  onSwapSeats,
  onCopyBattleTags,
  postingToDiscord = false,
  onPostToDiscord
}: Readonly<PickupTeamsPanelProps>) {
  const variants = parseVariants(game?.balance_result, teamNamesByIndex(game?.settings));
  // Clamped rather than reset in an effect: a shorter result must not leave the
  // pager pointing past the end.
  const index = Math.min(variantIndex, Math.max(0, variants.length - 1));
  const variant = variants[index];
  const pointsPerWin = game?.settings.points_per_win ?? null;
  // The matchup card is a self-contained graphic, so "share the teams" here needs
  // no detour through the fullscreen board.
  const { ref: captureRef, capturing, capture, rasterize } = useNodeCapture();

  return (
    // Width-capped by the caller now, alongside the mix header that sits
    // above this block: the matchup stops gaining anything past ~1180px -- a
    // seat row is a glyph, a crest, a name and a number -- and on a
    // 1440p-and-wider screen an uncapped column stretched two five-man
    // rosters across an arm's length of desk, so reading "who is on my team"
    // became a head turn.
    <div className="flex w-full min-w-0 flex-col gap-3.5">
      <div className="flex flex-col gap-3.5">
        {gamesError ? (
          <PageStateCard
            state="error"
            title="Unable to load mixes"
            description="Check your connection and try again."
            actionLabel="Retry"
            onAction={onRetryGames}
            className={cn(PANEL_CLASS, "px-4 py-16")}
          />
        ) : gamesLoading || gameLoading ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : !hasMix ? (
          <PageStateCard
            state="empty"
            title="No mixes yet"
            description={
              canWrite
                ? "Create a mix from the mixes list, then add players from the workspace pool."
                : "A host has not created a mix in this workspace yet."
            }
            className={cn(PANEL_CLASS, "px-4 py-16")}
          />
        ) : (
          // The next map sits inside the captured block on purpose: the shared
          // screenshot answers "who is on my team" and "what are we playing"
          // together, which is exactly what a lobby asks in one breath.
          <div ref={captureRef} data-testid="teams-capture" className="flex flex-col gap-3.5">
            {game ? (
              <NextMapStrip
                game={game}
                maps={maps}
                matches={matches}
                canWrite={canWrite}
                saving={settingNextMap}
                capturing={capturing}
                onNextMapChange={onNextMapChange}
              />
            ) : null}
            {variant == null ? (
              <PageStateCard
                state="empty"
                title="No teams yet"
                description={
                  canWrite
                    ? "Fill the lineup, then press Balance teams to see the matchup."
                    : "This mix has not been balanced yet."
                }
                className={cn(PANEL_CLASS, "px-4 py-16")}
              />
            ) : (
              <VariantView
                variant={variant}
                canWrite={canWrite}
                capturing={capturing}
                onRenameTeam={onRenameTeam}
                onSwapSeats={
                  onSwapSeats &&
                  ((firstUuid, secondUuid) => onSwapSeats(index, firstUuid, secondUuid))
                }
              />
            )}
          </div>
        )}
      </div>

      {/* One card under the matchup, in the order a host uses it: the result
          row first, aligned under the two team columns like their footer (it
          cannot live inside the captured card without leaving a hole in the
          screenshot), then the tools -- balance and paging on the left, the
          rare share/close actions demoted to icons on the right -- and the
          history the results write into. */}
      <div className={cn(PANEL_CLASS, "flex flex-col gap-3 px-4 py-3")}>
        {variant && canWrite ? (
          <PickupResultControls
            teamCount={variant.teams.length}
            teamNames={variant.teams.map((team) => team.name)}
            saving={recordingOutcome}
            pointsPerWin={pointsPerWin}
            onRecord={(recordedOutcome) =>
              onRecordOutcome({ outcome: recordedOutcome, variantIndex: index })
            }
          />
        ) : null}

        <div
          className={cn(
            "flex flex-wrap items-center gap-2",
            variant && canWrite && "border-t border-[color:var(--aqt-border)] pt-3"
          )}
        >
          {canWrite ? (
            <Button
              type="button"
              className="h-9"
              disabled={balancing || activeCount === 0}
              onClick={onBalance}
              title={
                activeCount > LOBBY_SIZE
                  ? `${activeCount - LOBBY_SIZE} extra player${activeCount - LOBBY_SIZE === 1 ? "" : "s"} will be benched automatically -- rotation fairness picks who`
                  : undefined
              }
            >
              {balancing ? (
                <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Shuffle className="mr-1.5 size-3.5" aria-hidden="true" />
              )}
              Balance teams
            </Button>
          ) : null}

          {variants.length > 1 ? (
            <div className="flex h-9 items-center gap-0.5 rounded-lg border border-[color:var(--aqt-border)] bg-white/[0.015] px-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                disabled={index === 0}
                onClick={() => onVariantIndexChange(index - 1)}
              >
                <ChevronLeft className="size-4" aria-hidden="true" />
                <span className="sr-only">Previous balance option</span>
              </Button>
              <span
                role="status"
                aria-live="polite"
                className="min-w-14 px-1 text-center text-caption font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]"
              >
                {`${index + 1} / ${variants.length}`}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7"
                disabled={index >= variants.length - 1}
                onClick={() => onVariantIndexChange(index + 1)}
              >
                <ChevronRight className="size-4" aria-hidden="true" />
                <span className="sr-only">Next balance option</span>
              </Button>
            </div>
          ) : null}

          {activeCount === 0 && canWrite ? (
            <p className="text-xs text-[color:var(--aqt-fg-dim)]">
              Check at least one player in the lobby.
            </p>
          ) : null}

          {variant ? (
            // Icon-only: these are recognisable glyphs and each is used once a
            // night at most, so their labels were spending a third of the row
            // on words nobody reads twice. The name lives in `aria-label`/`title`.
            <div className="ml-auto flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className={TOOL_ICON_CLASS}
                disabled={capturing}
                aria-label="Copy image"
                title="Copy image"
                onClick={() => void capture()}
              >
                {capturing ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Copy className="size-4" aria-hidden="true" />
                )}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className={TOOL_ICON_CLASS}
                aria-label="Copy battletags"
                title="Copy battletags"
                onClick={onCopyBattleTags}
              >
                <ClipboardCopy className="size-4" aria-hidden="true" />
              </Button>
              {/* The workspace channel is the default every mix posts to, so a
                  mix with no override of its own still has somewhere to send. */}
              {canWrite &&
              onPostToDiscord &&
              (game?.settings.discord_channel_id ?? game?.settings.workspace_discord_channel_id) ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className={TOOL_ICON_CLASS}
                  disabled={postingToDiscord || capturing}
                  aria-label="Post to Discord"
                  title="Post to Discord"
                  onClick={() => {
                    // The same rasterised card "Copy image" produces, sent as
                    // the attachment: the bot has no renderer, and a host who
                    // shares the matchup means the card, not a transcript of
                    // it. A failed capture posts without one -- the server
                    // falls back to the text embed rather than to nothing.
                    void rasterize()
                      .catch(() => null)
                      .then((image) => onPostToDiscord(index, image));
                  }}
                >
                  {postingToDiscord ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Send className="size-4" aria-hidden="true" />
                  )}
                </Button>
              ) : null}
              {canWrite ? (
                <>
                  <span aria-hidden="true" className="mx-1 h-5 w-px bg-[color:var(--aqt-border)]" />
                  {/* Once a night, irreversible from here: an icon that only
                      turns red on hover, behind the same confirm as before,
                      instead of the loudest pill in the row. */}
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className={cn(TOOL_ICON_CLASS, "hover:text-[color:var(--aqt-rose)]")}
                        disabled={closingMix}
                        aria-label="Close mix"
                        title="Close mix"
                      >
                        {closingMix ? (
                          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                        ) : (
                          <Archive className="size-4" aria-hidden="true" />
                        )}
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Close this mix?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Stops further balancing, roster edits, and outcome recording. Matches
                          already recorded stay recorded -- this cannot be undone from here.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Keep it open</AlertDialogCancel>
                        <AlertDialogAction
                          className={buttonVariants({ variant: "destructive" })}
                          onClick={onCloseMix}
                        >
                          Yes, close mix
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </>
              ) : null}
            </div>
          ) : null}
        </div>

        {matches.length > 0 ? (
          <MatchHistoryList
            matches={matches}
            canWrite={canWrite}
            undoingMatchId={undoingMatchId}
            onUndoMatch={onUndoMatch}
          />
        ) : null}
      </div>
    </div>
  );
}

/**
 * The map the next match is on, and how a host gets one: roll it (inside one
 * mode, or mode-first across all of them -- see `rollNextMap`), or pick it by
 * hand. The verdict is the mix's `next_map_id`, so every viewer reads the same
 * map and the next recorded result carries it. Only the mode filter is local:
 * it is a preference of whoever is rolling, not a fact about the mix.
 *
 * Hidden from the screenshot when nothing is rolled: "Not rolled yet" beside
 * two teams is noise in the channel the image is pasted into.
 */
function NextMapStrip({
  game,
  maps,
  matches,
  canWrite,
  saving,
  capturing,
  onNextMapChange
}: Readonly<{
  game: CustomGame;
  maps: MapRead[];
  matches: CustomGameMatch[];
  canWrite: boolean;
  saving: boolean;
  capturing: boolean;
  onNextMapChange: (mapId: number | null) => void;
}>) {
  const [modeId, setModeId] = useState<number | null>(null);
  const modes = rollableModes(maps);
  const nextMap =
    game.next_map_id == null ? null : (maps.find((map) => map.id === game.next_map_id) ?? null);

  if (!canWrite && nextMap == null) return null;

  const roll = () => {
    const rolled = rollNextMap(maps, {
      gamemodeId: modeId,
      playedMapIds: matches.flatMap((match) => (match.map_id == null ? [] : [match.map_id]))
    });
    if (rolled == null) {
      notify.error("No competitive maps to roll from");
      return;
    }
    onNextMapChange(rolled.id);
  };

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-xl border border-[color:var(--aqt-border-2)] bg-white/[0.012] px-3 py-2.5",
        capturing && nextMap == null && "hidden"
      )}
    >
      <div className="relative h-10 w-[72px] shrink-0 overflow-hidden rounded-md border border-[color:var(--aqt-border-2)] bg-[linear-gradient(135deg,var(--aqt-card-2),var(--aqt-bg-2))]">
        {nextMap?.image_path ? (
          <Image src={nextMap.image_path} alt="" fill sizes="72px" className="object-cover" />
        ) : (
          <Dices
            className="absolute inset-0 m-auto size-4 text-[color:var(--aqt-fg-faint)]"
            aria-hidden="true"
          />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <span className={EYEBROW_CLASS}>Next map</span>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span
            className={cn(
              "truncate font-display text-base font-bold tracking-[-0.01em]",
              nextMap ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {nextMap?.name ?? "Not rolled yet"}
          </span>
          {nextMap?.gamemode ? (
            <span className={CAPTION_CLASS}>{nextMap.gamemode.name}</span>
          ) : null}
        </div>
      </div>

      {canWrite ? (
        <div
          data-export-hide
          className={cn("flex flex-wrap items-center gap-1.5", capturing && "invisible")}
        >
          <div
            role="group"
            aria-label="Roll within mode"
            className="flex flex-wrap items-center gap-1"
          >
            <ModeChip label="Any" active={modeId == null} onClick={() => setModeId(null)} />
            {modes.map((mode) => (
              <ModeChip
                key={mode.id}
                label={mode.name}
                active={modeId === mode.id}
                onClick={() => setModeId(mode.id)}
              />
            ))}
          </div>
          <Button
            type="button"
            variant="outline"
            className="h-8"
            disabled={saving || maps.length === 0}
            onClick={roll}
          >
            {saving ? (
              <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Dices className="mr-1.5 size-3.5" aria-hidden="true" />
            )}
            Roll
          </Button>
          <MapCombobox maps={maps} mapId={game.next_map_id} onMapIdChange={onNextMapChange} />
        </div>
      ) : null}
    </div>
  );
}

/** One mode the roll can stay inside; the same pressed-pill the add-players filters use. */
function ModeChip({
  label,
  active,
  onClick
}: Readonly<{ label: string; active: boolean; onClick: () => void }>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 shrink-0 items-center rounded-full border px-2.5 text-label transition-colors",
        active
          ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_38%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)]"
          : "border-[color:var(--aqt-border)] bg-white/[0.02] text-[color:var(--aqt-fg-muted)] hover:bg-white/[0.05] hover:text-[color:var(--aqt-fg)]"
      )}
    >
      {label}
    </button>
  );
}

/** Every match this mix has recorded, newest first — the permanent record `Record result` writes into. */
function MatchHistoryList({
  matches,
  canWrite,
  undoingMatchId,
  onUndoMatch
}: Readonly<{
  matches: CustomGameMatch[];
  canWrite: boolean;
  undoingMatchId: number | null;
  onUndoMatch?: (matchId: number) => void;
}>) {
  return (
    <div className="flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3">
      <span className={cn(EYEBROW_CLASS, "flex items-center gap-1.5 tracking-label")}>
        <History className="size-3.5" aria-hidden="true" />
        Match history
      </span>
      <ul className="flex flex-col gap-1.5">
        {matches.map((match, position) => (
          <MatchHistoryRow
            key={match.id}
            match={match}
            // Newest first, and only the newest can be rolled back -- an older
            // undo would have to reason about every match stacked on top of it.
            canUndo={position === 0 && canWrite && onUndoMatch != null}
            undoing={undoingMatchId === match.id}
            onUndoMatch={onUndoMatch}
          />
        ))}
      </ul>
    </div>
  );
}

/** Two-letter fallback for a map with no thumbnail yet, same rule `MapRow` uses. */
function mapInitials(name: string): string {
  return name
    .split(/\s+/)
    .map((word) => word[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function MatchHistoryRow({
  match,
  canUndo,
  undoing,
  onUndoMatch
}: Readonly<{
  match: CustomGameMatch;
  canUndo: boolean;
  undoing: boolean;
  onUndoMatch?: (matchId: number) => void;
}>) {
  const homeAccent = teamAccent(0);
  const awayAccent = teamAccent(1);

  return (
    <li className="flex items-center gap-3 rounded-lg border border-[color:var(--aqt-border-2)] bg-white/[0.012] px-2.5 py-2">
      <div className="relative h-8 w-14 shrink-0 overflow-hidden rounded-md border border-[color:var(--aqt-border-2)] bg-[linear-gradient(135deg,var(--aqt-card-2),var(--aqt-bg-2))]">
        {match.map_image_path ? (
          <Image src={match.map_image_path} alt="" fill sizes="56px" className="object-cover" />
        ) : (
          <span className="flex h-full w-full items-center justify-center font-display text-label font-extrabold text-[color:var(--aqt-fg-faint)]">
            {match.map_name ? mapInitials(match.map_name) : "?"}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-1.5 text-caption font-semibold leading-tight">
          <span
            aria-hidden="true"
            className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", homeAccent.bar)}
          />
          <span
            className={cn(
              "truncate",
              match.winner === 1 ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {match.home_team_name}
          </span>
          <span className="tabular-nums text-[color:var(--aqt-fg-muted)]">
            {match.home_score} : {match.away_score}
          </span>
          <span
            className={cn(
              "truncate",
              match.winner === 2 ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {match.away_team_name}
          </span>
          <span
            aria-hidden="true"
            className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", awayAccent.bar)}
          />
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 truncate text-label text-[color:var(--aqt-fg-dim)]">
          <span className="truncate">{match.map_name ?? "No map"}</span>
          <span aria-hidden="true">&middot;</span>
          <span className="shrink-0">{formatRelative(match.recorded_at)}</span>
        </div>
      </div>
      {canUndo ? (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Undo this match"
              disabled={undoing}
            >
              {undoing ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <Undo2 className="size-4" aria-hidden="true" />
              )}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Undo this match?</AlertDialogTitle>
              <AlertDialogDescription>
                {match.points_per_win_applied != null
                  ? `Removes it from the history and moves every player's rank back by ${match.points_per_win_applied} points. Players pinned as must-play before it were already released to the pool and stay there.`
                  : "Removes it from the history. No rank points were applied."}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep it</AlertDialogCancel>
              <AlertDialogAction
                className={buttonVariants({ variant: "destructive" })}
                onClick={() => onUndoMatch?.(match.id)}
              >
                Undo match
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      ) : null}
    </li>
  );
}

/**
 * The solver's own verdict on this option, as four read-only pills.
 *
 * Off-role is the one that changes colour, because it is the only number a host
 * can act on: it names players who will be unhappy, where quality and spread
 * only rank the option against its siblings.
 */
function VariantMetrics({ variant }: Readonly<{ variant: PickupVariant }>) {
  const { stats } = variant;
  const offRole = stats.offRoleCount ?? 0;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {stats.compositeScore == null ? null : (
        <span
          title="Composite solver score across balance and role comfort \u2014 lower is better."
          className={cn(
            METRIC_PILL_CLASS,
            "border-[color:color-mix(in_srgb,var(--aqt-emerald)_25%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] text-[color:var(--aqt-emerald)]"
          )}
        >
          {`QUALITY ${stats.compositeScore.toFixed(2)}`}
        </span>
      )}
      {stats.mmrStdDev == null ? null : (
        <span
          title="Standard deviation of team rank \u2014 lower means the teams are closer together."
          className={cn(
            METRIC_PILL_CLASS,
            "border-[color:color-mix(in_srgb,var(--aqt-blue)_22%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-blue)_10%,transparent)] text-[color:var(--aqt-blue)]"
          )}
        >
          {`STDDEV ${stats.mmrStdDev.toFixed(1)}`}
        </span>
      )}
      {stats.ratingGap == null ? null : (
        <span
          title="Rank gap between the strongest and weakest team."
          className={cn(METRIC_PILL_CLASS, METRIC_NEUTRAL_CLASS)}
        >
          {`SPREAD ${Math.round(stats.ratingGap)}`}
        </span>
      )}
      <span
        title="Players the solver had to seat outside their first-choice role."
        className={cn(
          METRIC_PILL_CLASS,
          offRole > 0
            ? "border-[color:color-mix(in_srgb,var(--aqt-amber)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)] text-[color:var(--aqt-amber)]"
            : METRIC_NEUTRAL_CLASS
        )}
      >
        {`OFF-ROLE ${offRole}`}
      </span>
    </div>
  );
}

function VariantView({
  variant,
  canWrite,
  capturing,
  onRenameTeam,
  onSwapSeats
}: Readonly<{
  variant: PickupVariant;
  canWrite: boolean;
  /** A screenshot is being taken: the rename pencils drop out so the card exports as a plain matchup. */
  capturing: boolean;
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  /** Omitted -- seats render without drag handles, matching a `canWrite=false` viewer. */
  onSwapSeats?: (firstUuid: string, secondUuid: string) => void | Promise<unknown>;
}>) {
  const twoTeams = variant.teams.length === 2;
  const canDrag = canWrite && onSwapSeats != null;
  const [activeDrag, setActiveDrag] = useState<ActiveSeatDrag | null>(null);
  // 6px before a drag starts: without it, a plain click on a seat (there is
  // nothing to click yet, but there will be) reads as a zero-distance drag
  // and dnd-kit swallows the event.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  const handleDragStart = (event: DragStartEvent) => {
    const data = event.active.data.current as ActiveSeatDrag | undefined;
    if (data) setActiveDrag(data);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveDrag(null);
    const firstUuid = String(event.active.id);
    const secondUuid = event.over ? String(event.over.id) : null;
    if (!secondUuid || secondUuid === firstUuid || !onSwapSeats) return;
    void onSwapSeats(firstUuid, secondUuid);
  };

  return (
    // One card with a divider column, not two cards: the matchup is a single
    // object, and a gap between two boxes read as two unrelated rosters. The
    // verdict pills live inside it too, centred over the seam between the
    // teams and above their rosters -- inside the same border, not a strip
    // floating above the card on its own. Who the option left out is not
    // repeated here: the lineup column already marks them benched.
    <div className={cn(PANEL_CLASS, "overflow-hidden rounded-2xl")}>
      <div className="flex flex-wrap items-center justify-center gap-1.5 border-b border-[color:var(--aqt-border)] px-4 py-2.5">
        <VariantMetrics variant={variant} />
      </div>
      <DndContext
        sensors={sensors}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={() => setActiveDrag(null)}
      >
        <div className={cn("flex items-stretch", twoTeams ? "flex-col lg:flex-row" : "flex-col")}>
          {variant.teams.map((team, teamIndex) => (
            <TeamColumnAndDivider
              key={team.id}
              team={team}
              teamIndex={teamIndex}
              showDivider={twoTeams && teamIndex === 0}
              canWrite={canWrite}
              // The pencil is a 28px square on the 28px title line, so
              // withholding it during capture leaves no hole in the image.
              onRenameTeam={capturing ? undefined : onRenameTeam}
              canDrag={canDrag}
              activeDrag={activeDrag}
            />
          ))}
        </div>
        {/* Follows the pointer instead of the seat teleporting under it --
              without this dnd-kit still swaps correctly, it just looks broken
              mid-drag (the dragged row snaps back until drop). */}
        <DragOverlay>{activeDrag ? <SeatDragPreview seat={activeDrag.seat} /> : null}</DragOverlay>
      </DndContext>
    </div>
  );
}

function TeamColumnAndDivider({
  team,
  teamIndex,
  showDivider,
  canWrite,
  onRenameTeam,
  canDrag,
  activeDrag
}: Readonly<{
  team: PickupTeam;
  teamIndex: number;
  showDivider: boolean;
  canWrite: boolean;
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  canDrag: boolean;
  activeDrag: ActiveSeatDrag | null;
}>) {
  return (
    <>
      <TeamColumn
        team={team}
        teamIndex={teamIndex}
        canWrite={canWrite}
        onRenameTeam={onRenameTeam}
        canDrag={canDrag}
        activeDrag={activeDrag}
      />
      {showDivider ? (
        <div
          aria-hidden="true"
          className="flex shrink-0 items-center justify-center border-y border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] py-2 lg:w-16 lg:border-x lg:border-y-0 lg:py-0"
        >
          <span className="font-display text-ui font-bold tracking-label text-[color:var(--aqt-fg-faint)]">
            VS
          </span>
        </div>
      ) : null}
    </>
  );
}

function TeamColumn({
  team,
  teamIndex,
  canWrite,
  onRenameTeam,
  canDrag,
  activeDrag
}: Readonly<{
  team: PickupTeam;
  teamIndex: number;
  canWrite: boolean;
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  canDrag: boolean;
  activeDrag: ActiveSeatDrag | null;
}>) {
  const accent = teamAccent(teamIndex);

  return (
    <section className="min-w-0 flex-1 px-4 pb-4 pt-4">
      <header className="flex items-baseline gap-2.5 border-b border-[color:var(--aqt-border)] pb-3">
        <span aria-hidden="true" className={cn("h-4 w-[3px] shrink-0 rounded-sm", accent.bar)} />
        <InlineEditText
          value={team.name}
          label="team name"
          canEdit={canWrite && onRenameTeam != null}
          onSave={(next) => onRenameTeam?.(teamIndex, next)}
          textClassName="truncate font-display text-xl font-bold tracking-[0.01em] text-[color:var(--aqt-fg)]"
        />
        <span
          className={cn(
            "ml-auto shrink-0 text-label uppercase tracking-label",
            "text-[color:var(--aqt-fg-faint)]"
          )}
        >
          avg
        </span>
        <span className="shrink-0 text-xl font-bold tabular-nums text-[color:var(--aqt-fg)]">
          {team.averageRank == null ? "\u2014" : Math.round(team.averageRank)}
        </span>
      </header>
      <ul className="mt-2.5 space-y-1">
        {team.seats.map((seat) => (
          <SeatRow
            key={`${seat.uuid}:${seat.role}`}
            seat={seat}
            teamIndex={teamIndex}
            canDrag={canDrag}
            activeDrag={activeDrag}
          />
        ))}
      </ul>
    </section>
  );
}

type ActiveSeatDrag = { uuid: string; role: string; teamIndex: number; seat: PickupSeat };

/**
 * One seat, wired as both drag source and drop target under the same id
 * (dnd-kit tracks the two registries independently, so this is safe): drag it
 * onto another team's seat of the same role to swap them. Cross-role or
 * same-team drops are still accepted here and left to the server's 422 --
 * this only dims a target that obviously cannot work, it does not duplicate
 * that validation.
 */
function SeatRow({
  seat,
  teamIndex,
  canDrag,
  activeDrag
}: Readonly<{
  seat: PickupSeat;
  teamIndex: number;
  canDrag: boolean;
  activeDrag: ActiveSeatDrag | null;
}>) {
  const dragData: ActiveSeatDrag = { uuid: seat.uuid, role: seat.role, teamIndex, seat };
  const draggable = useDraggable({ id: seat.uuid, data: dragData, disabled: !canDrag });
  const droppable = useDroppable({ id: seat.uuid, data: dragData, disabled: !canDrag });
  const grid = OW_REFERENCE_GRID;
  const division = resolveDivisionFromRank(grid, seat.rating);
  const icon = ROLES.find((item) => item.code === seat.role)?.icon ?? "Support";
  const isValidTarget =
    activeDrag != null &&
    activeDrag.uuid !== seat.uuid &&
    activeDrag.role === seat.role &&
    activeDrag.teamIndex !== teamIndex;
  const isDropReady = droppable.isOver && isValidTarget;

  return (
    <li
      ref={(node) => {
        draggable.setNodeRef(node);
        droppable.setNodeRef(node);
      }}
      {...draggable.attributes}
      {...draggable.listeners}
      className={cn(
        "flex items-center gap-3 rounded-lg border px-3.5 py-3 transition-colors",
        canDrag && "touch-none active:cursor-grabbing",
        draggable.isDragging
          ? "opacity-40"
          : isDropReady
            ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)]"
            : "border-[color:var(--aqt-border)] bg-white/[0.015] hover:bg-white/[0.045]"
      )}
    >
      <span
        className="flex size-6 shrink-0 items-center justify-center opacity-90"
        title={`${ROLE_LABELS[seat.role]}${seat.subRole ? ` \u00B7 ${seat.subRole}` : ""}`}
      >
        <PlayerRoleIcon role={icon} size={24} label={ROLE_LABELS[seat.role]} />
      </span>
      {division == null ? null : (
        <DivisionIcon
          division={division}
          tournamentGrid={grid}
          width={32}
          height={32}
          className="shrink-0"
        />
      )}
      <span
        className="min-w-0 flex-1 truncate text-base font-semibold text-[color:var(--aqt-fg)]"
        title={seat.name}
      >
        {seat.name}
      </span>
      {seat.offRole ? (
        <span
          title="Assigned off their first-preference role"
          className="flex size-4 shrink-0 items-center justify-center text-[color:var(--aqt-amber)]"
        >
          <AlertCircle className="size-3.5" aria-hidden="true" />
          <span className="sr-only">Off-role</span>
        </span>
      ) : null}
      <span className="shrink-0 text-lg font-bold tabular-nums text-[color:var(--aqt-fg)]">
        {seat.rating == null ? "\u2014" : Math.round(seat.rating)}
      </span>
    </li>
  );
}

/** The dragged seat's own row, detached from the list, following the pointer. */
function SeatDragPreview({ seat }: Readonly<{ seat: PickupSeat }>) {
  const icon = ROLES.find((item) => item.code === seat.role)?.icon ?? "Support";
  return (
    <div
      className={cn(
        PANEL_CLASS,
        "flex cursor-grabbing items-center gap-3 rounded-lg border-[color:var(--aqt-teal)] px-3.5 py-3 shadow-lg"
      )}
    >
      <span className="flex size-6 shrink-0 items-center justify-center opacity-90">
        <PlayerRoleIcon role={icon} size={24} label={ROLE_LABELS[seat.role]} decorative />
      </span>
      <span className="min-w-0 flex-1 truncate text-base font-semibold text-[color:var(--aqt-fg)]">
        {seat.name}
      </span>
      <span className="shrink-0 text-lg font-bold tabular-nums text-[color:var(--aqt-fg)]">
        {seat.rating == null ? "\u2014" : Math.round(seat.rating)}
      </span>
    </div>
  );
}
