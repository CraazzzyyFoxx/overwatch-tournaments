"use client";

import { useState } from "react";

import {
  ChevronLeft,
  ChevronRight,
  Archive,
  ClipboardCopy,
  Copy,
  Send,
  Shuffle
} from "lucide-react";

import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { PickupResultControls } from "@/app/balancer/mix/PickupResultControls";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useNodeCapture } from "@/hooks/useNodeCapture";
import { cn } from "@/lib/utils";
import type { CustomGame, CustomGameMatch } from "@/services/custom-game.service";
import type { MapRead } from "@/types/map.types";
import { Spinner } from "@/components/ui/spinner";

import { MatchHistoryList } from "./_components/MatchHistoryList";
import { NextMapStrip } from "./_components/NextMapStrip";
import { VariantView } from "./_components/VariantView";
import {
  LOBBY_SIZE,
  parseVariants,
  teamNamesByIndex,
  type PickupRecordOutcomeInput
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
  /**
   * Which of the solver's options is on screen — the mix's own
   * `selected_variant_index`, so the host's pager moves every viewer with it.
   * Viewers get no pager at all: the matchup is read out to a lobby, and a
   * player quietly paging their own copy is looking at teams nobody is playing.
   */
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
  const [closeOpen, setCloseOpen] = useState(false);

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
                <Spinner className="mr-1.5 size-3.5" />
              ) : (
                <Shuffle className="mr-1.5 size-3.5" aria-hidden="true" />
              )}
              Balance teams
            </Button>
          ) : null}

          {canWrite && variants.length > 1 ? (
            <div className="flex h-9 items-center gap-0.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-1">
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
                  <Spinner />
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
              {/* The workspace's channel is the only target a mix has; without
                  one there is nowhere to post, so the button stays off. */}
              {canWrite && onPostToDiscord && game?.settings.workspace_discord_channel_id ? (
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
                    <Spinner />
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
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className={cn(TOOL_ICON_CLASS, "hover:text-[color:var(--aqt-rose)]")}
                    disabled={closingMix}
                    aria-label="Close mix"
                    title="Close mix"
                    onClick={() => setCloseOpen(true)}
                  >
                    {closingMix ? (
                      <Spinner />
                    ) : (
                      <Archive className="size-4" aria-hidden="true" />
                    )}
                  </Button>
                  <ConfirmDialog
                    open={closeOpen}
                    onOpenChange={setCloseOpen}
                    intent={{
                      title: "Close this mix?",
                      description:
                        "Stops further balancing, roster edits, and outcome recording. Matches already recorded stay recorded -- this cannot be undone from here.",
                      confirmLabel: "Yes, close mix",
                      tone: "danger"
                    }}
                    pending={closingMix}
                    onConfirm={() => {
                      setCloseOpen(false);
                      onCloseMix();
                    }}
                  />
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
