"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  ChevronLeft,
  ChevronRight,
  Archive,
  ClipboardCopy,
  Copy,
  DoorOpen,
  Send,
  CircleX,
  MoreHorizontal,
  Shuffle,
  Users
} from "lucide-react";

import { RoomLink } from "@/app/balancer/mix/_room/room-navigation";
import { CAPTION_CLASS, CARD_TITLE_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { PickupResultControls } from "@/app/balancer/mix/PickupResultControls";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useNodeCapture } from "@/hooks/useNodeCapture";
import { cn } from "@/lib/utils";
import type { CustomGame, CustomGameLobby, CustomGameMatch } from "@/services/custom-game.service";
import type { CatalogEntityRead } from "@/types/catalog.types";
import { Spinner } from "@/components/ui/spinner";

import { MatchHistoryList } from "./_components/MatchHistoryList";
import { NextMapStrip } from "./_components/NextMapStrip";
import { LobbyCodeStrip } from "./_components/LobbyCodeStrip";
import { StartMatchButton } from "./_components/StartMatchButton";
import { VariantView } from "./_components/VariantView";
import { slotCodeOrder } from "@/lib/roster/ontology";
import {
  parseVariants,
  teamNamesByIndex,
  type MixOwner,
  type PickupRecordOutcomeInput
} from "./pickup-lineup";

/** The demoted share/close tools: quiet glyphs that only light up on hover. */
const TOOL_ICON_CLASS = "text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]";

type PickupTeamsPanelProps = {
  canWrite: boolean;
  gamesLoading: boolean;
  gamesError: boolean;
  onRetryGames: () => void;
  game: CustomGame | undefined;
  /** The one lobby this panel is showing. `undefined` before the mix loads. */
  lobby: CustomGameLobby | undefined;
  /** Its index, which is also the offset of its team names (`lobbyIndex * 2 + team`). */
  lobbyIndex: number;
  /** The mix owner's game: seat names and glyphs, the full-lobby size and the grid the seats' ranks are on. */
  owner: MixOwner;
  gameLoading: boolean;
  hasMix: boolean;
  balancing: boolean;
  activeCount: number;
  /** Re-runs the solver for THIS lobby. The confirm for an unrecorded lineup is this panel's. */
  onBalance: () => void;
  /** Re-forms THIS lobby as a captain draft (draft mode). The confirm for an unrecorded lineup is this panel's. */
  drafting: boolean;
  onDraft: () => void;
  /** This lobby's room, where its draft and its bans and picks play out. */
  roomHref: string;
  /**
   * Which of the solver's options is on screen — the lobby's own
   * `selected_variant_index`, so the host's pager moves every viewer with it.
   * Viewers get no pager at all: the matchup is read out to a lobby, and a
   * player quietly paging their own copy is looking at teams nobody is playing.
   */
  variantIndex: number;
  onVariantIndexChange: (index: number) => void;
  recordingOutcome: boolean;
  onRecordOutcome: (input: PickupRecordOutcomeInput) => void;
  startingMatch: boolean;
  /**
   * Opens the lobby's match on the lineup on screen (the voices follow server-side); `flipOpener` swaps who bans
   * first.
   */
  onStartMatch: (flipOpener: boolean) => void;
  cancellingMatch: boolean;
  /** Throws the live match away; nothing is recorded. */
  onCancelMatch: () => void;
  /** Omitted -- no "Make captain" on a seat. */
  onMakeCaptain?: (workspaceMemberId: number) => void;
  /** The history this panel lists, newest first: the room's own lobby, or every lobby on a one-lobby overview. */
  matches: CustomGameMatch[];
  /** Every match this mix has played, every lobby: the map roll skips their maps, whichever lobby played them. */
  mixMatches: CustomGameMatch[];
  /** The match whose undo is in flight, so only that row spins. */
  undoingMatchId?: number | null;
  /** Omitted -- the history renders read-only, matching a page that offers no undo. */
  onUndoMatch?: (matchId: number) => void;
  /** The mix game's map catalogue, each map with its mode as `parent` -- the roll pool and the manual picker. */
  maps: CatalogEntityRead[];
  settingNextMap: boolean;
  /** Rolled or hand-picked; `null` clears. Persisted per lobby server-side. */
  onNextMapChange: (mapId: number | null) => void;
  settingLobbyCode: boolean;
  /** Trimmed; `null` clears. Persisted per lobby server-side, writable while the match is live. */
  onLobbyCodeChange: (lobbyCode: string | null) => void;
  closingMix: boolean;
  onCloseMix: () => void;
  /** Takes the GLOBAL team index (`lobbyIndex * 2 + team`). Omitted -- team headers render read-only. */
  onRenameTeam?: (teamIndex: number, name: string) => void | Promise<unknown>;
  /** Omitted -- seats render without drag handles, matching a `canWrite=false` viewer. */
  onSwapSeats?: (
    variantIndex: number,
    firstUuid: string,
    secondUuid: string
  ) => void | Promise<unknown>;
  onCopyHandles: () => void;
  postingToDiscord?: boolean;
  /** Omitted -- no Post to Discord button, matching a page that offers no post. */
  onPostToDiscord?: (variantIndex: number) => void;
  /**
   * The host's checklist in place of the "No teams yet" state while this lobby has no balance. It is handed this
   * lobby's Balance (or Draft) control, with its confirms -- `null` while the lineup cannot be re-formed -- and places
   * it in its own step; the footer then leaves it out, so the control exists once.
   */
  emptyState?: (balanceAction: ReactNode) => ReactNode;
};

/**
 * The host's desk for one lobby: its teams and the writes that act on them -- re-balance (or Draft, in draft mode)
 * and Start match while Ready, the result or Cancel match while Live (the lineup is frozen from Start to the result),
 * and close the mix. What plays out in the lobby's room (spec §7.5) -- the captains' draft, the hero bans and picks --
 * is a link to that room here, not a board.
 *
 * One lobby at a time: the page hands down which one, and every write this
 * panel makes addresses it. Teams are read from that lobby's stored
 * `balance_result` document, because only it knows which *seat* each player got
 * and at what rating — the difference between "these five are together" and a
 * lineup a host can actually call out. The solver returns many equally-scored
 * options, so the variant pager walks them without re-running the balance.
 */
export function PickupTeamsPanel({
  canWrite,
  gamesLoading,
  gamesError,
  onRetryGames,
  game,
  lobby,
  lobbyIndex,
  owner,
  gameLoading,
  hasMix,
  balancing,
  activeCount,
  onBalance,
  drafting,
  onDraft,
  roomHref,
  variantIndex,
  onVariantIndexChange,
  recordingOutcome,
  onRecordOutcome,
  startingMatch,
  onStartMatch,
  cancellingMatch,
  onCancelMatch,
  onMakeCaptain,
  matches,
  mixMatches,
  undoingMatchId = null,
  onUndoMatch,
  maps,
  settingNextMap,
  onNextMapChange,
  settingLobbyCode,
  onLobbyCodeChange,
  closingMix,
  onCloseMix,
  onRenameTeam,
  onSwapSeats,
  onCopyHandles,
  postingToDiscord = false,
  onPostToDiscord,
  emptyState
}: Readonly<PickupTeamsPanelProps>) {
  const t = useTranslations("mixes.lobbies");
  const tTeams = useTranslations("mixes.teams");
  const tMixes = useTranslations("mixes");
  const tCommon = useTranslations("common");
  const teamNames = teamNamesByIndex(game?.settings, lobbyIndex);
  const variants = parseVariants(lobby?.balance_result, teamNames, slotCodeOrder(owner.ontology), (team) =>
    tMixes("voice.team", { n: team + 1 })
  );
  // Clamped rather than reset in an effect: a shorter result must not leave the
  // pager pointing past the end.
  const index = Math.min(variantIndex, Math.max(0, variants.length - 1));
  const variant = variants[index];
  const pointsPerWin = game?.settings.points_per_win ?? null;
  const lobbyCount = game?.lobby_count ?? 1;
  // The matchup card is a self-contained graphic, so "share the teams" here needs
  // no detour through the fullscreen board.
  const { ref: captureRef, capturing, capture } = useNodeCapture();
  const [closeOpen, setCloseOpen] = useState(false);
  // A balance replaces this lobby's lineup. If the lineup on screen was never
  // played into the log, that is a result about to be lost, so it is the one
  // case the button asks first.
  const [balanceOpen, setBalanceOpen] = useState(false);
  const [draftOpen, setDraftOpen] = useState(false);
  const lineupAtRisk = lobby?.lineup_recorded === false;
  const tRoom = useTranslations("mixes.room");
  const state = lobby?.state ?? "idle";
  const live = state === "live";
  const pregame = state === "pregame";
  // The lineup is frozen from Start to the result, bans included (spec §5.1).
  const onFloor = live || pregame;
  // While the lobby drafts, its room is where the teams form; the desk only points there.
  const drafts = state === "draft_setup" || state === "draft_live";
  // Every write that re-forms, re-seats or re-maps the lineup waits for the match (409 `match_live`).
  const reshape = canWrite && !onFloor && !drafts;
  const [cancelOpen, setCancelOpen] = useState(false);
  const awayUuids = new Set(
    (game?.players ?? []).filter((row) => row.away).map((row) => String(row.workspace_member_id)),
  );
  const awayNames = (variant?.teams ?? [])
    .flatMap((team) => team.seats)
    .filter((seat) => awayUuids.has(seat.uuid))
    .map((seat) => seat.name);

  // A lobby with no teams yet: Balance (or Draft) is the host's next step, so it is the solid button. Once teams
  // exist it is a re-balance and Start match takes the solid slot.
  const balanceVariant = variant == null ? "default" : "outline";
  // The one Balance (or Draft) control, with its confirms: the footer's, or the checklist's last step while that shows.
  const balanceControl = reshape ? (
    <>
      {game?.team_formation === "draft" ? (
        <>
          <Button
            type="button"
            variant={balanceVariant}
            size="sm"
            disabled={drafting || activeCount === 0}
            onClick={() => (lineupAtRisk ? setDraftOpen(true) : onDraft())}
          >
            {drafting ? (
              <Spinner className="mr-1.5 size-3.5" />
            ) : (
              <Users className="mr-1.5 size-3.5" aria-hidden="true" />
            )}
            {tRoom("draft")}
          </Button>
          <ConfirmDialog
            open={draftOpen}
            onOpenChange={setDraftOpen}
            intent={{
              title: tRoom("draftReformTitle"),
              description: tRoom("draftReformDescription"),
              confirmLabel: tRoom("draftReformConfirm"),
              tone: "danger"
            }}
            pending={drafting}
            onConfirm={() => {
              setDraftOpen(false);
              onDraft();
            }}
          />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="ghost" size="icon" aria-label={tRoom("moreActions")}>
                <MoreHorizontal className="size-4" aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem
                disabled={balancing || activeCount === 0}
                onSelect={() => (lineupAtRisk ? setBalanceOpen(true) : onBalance())}
              >
                {tRoom("buildWithBalancer")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      ) : (
        <Button
          type="button"
          variant={balanceVariant}
          size="sm"
          disabled={balancing || activeCount === 0}
          onClick={() => (lineupAtRisk ? setBalanceOpen(true) : onBalance())}
          title={
            owner.lobbySize != null && activeCount > owner.lobbySize
              ? tTeams("extraBenched", { count: activeCount - owner.lobbySize })
              : undefined
          }
        >
          {balancing ? (
            <Spinner className="mr-1.5 size-3.5" />
          ) : (
            <Shuffle className="mr-1.5 size-3.5" aria-hidden="true" />
          )}
          {tTeams("balance")}
        </Button>
      )}
      <ConfirmDialog
        open={balanceOpen}
        onOpenChange={setBalanceOpen}
        intent={{
          title: t("rebalanceTitle"),
          description: t("rebalanceDescription"),
          confirmLabel: t("rebalanceConfirm"),
          tone: "danger"
        }}
        pending={balancing}
        onConfirm={() => {
          setBalanceOpen(false);
          onBalance();
        }}
      />
      {activeCount === 0 ? <p className={CAPTION_CLASS}>{tTeams("needPlayer")}</p> : null}
    </>
  ) : null;
  const checklist = variant == null ? (emptyState?.(balanceControl) ?? null) : null;
  const showStart = !onFloor && variant != null && canWrite && state === "ready";
  const balanceInFooter = balanceControl != null && checklist == null;
  const showPager = reshape && variants.length > 1;
  const toolsRow = balanceInFooter || showPager || variant != null;
  const hasFooter = onFloor || showStart || toolsRow || matches.length > 0;

  return (
    // Width-capped by the caller now, alongside the mix header that sits
    // above this block: the matchup stops gaining anything past ~1180px -- a
    // seat row is a glyph, a crest, a name and a number -- and on a
    // 1440p-and-wider screen an uncapped column stretched two five-man
    // rosters across an arm's length of desk, so reading "who is on my team"
    // became a head turn.
    <div data-mix-lobby={lobbyIndex} className="flex w-full min-w-0 flex-col gap-3.5">
      {drafts ? (
        <Card className="flex flex-col items-start gap-3 px-4 py-3.5">
          <h2 className={CARD_TITLE_CLASS}>{tRoom("draftInRoom")}</h2>
          <p className={CAPTION_CLASS}>{tRoom("draftInRoomHint")}</p>
          <Button asChild variant="accent" size="sm">
            <RoomLink href={roomHref}>
              <DoorOpen className="size-3.5" aria-hidden="true" />
              {tRoom("openRoom")}
            </RoomLink>
          </Button>
        </Card>
      ) : gamesError ? (
        <Card asChild>
          <PageStateCard
            state="error"
            title={tMixes("list.errorTitle")}
            description={tMixes("list.errorDescription")}
            actionLabel={tCommon("retry")}
            onAction={onRetryGames}
            className="px-4 py-16"
          />
        </Card>
      ) : gamesLoading || gameLoading ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : !hasMix ? (
        <Card asChild>
          <PageStateCard
            state="empty"
            title={tMixes("history.emptyTitle")}
            description={canWrite ? tTeams("noMixesHost") : tTeams("noMixesViewer")}
            className="px-4 py-16"
          />
        </Card>
      ) : (
        // The lobby card: the next map and the teams on top, the writes that act
        // on them in a footer under one hairline, in the order a host uses them --
        // the result row first, aligned under the two team columns, then the
        // tools (balance and paging on the left, the rare share/close actions
        // demoted to icons on the right) and the history the results write into.
        <Card className="overflow-hidden">
          {/* The next map sits inside the captured block on purpose: the shared
              screenshot answers "who is on my team" and "what are we playing"
              together, which is exactly what a lobby asks in one breath. The
              footer stays outside it -- a screenshot of its own share button is
              noise -- and the fill keeps the copied image opaque. */}
          <div ref={captureRef} data-testid="teams-capture" className="bg-[color:var(--aqt-card)]">
            {game ? (
              <>
                <NextMapStrip
                  nextMapId={lobby?.next_map_id ?? null}
                  maps={maps}
                  matches={mixMatches}
                  canWrite={reshape}
                  saving={settingNextMap}
                  capturing={capturing}
                  onNextMapChange={onNextMapChange}
                />
                <LobbyCodeStrip
                  lobbyCode={lobby?.lobby_code ?? null}
                  canWrite={canWrite}
                  saving={settingLobbyCode}
                  capturing={capturing}
                  onLobbyCodeChange={onLobbyCodeChange}
                />
              </>
            ) : null}
            {variant == null ? (
              (checklist ?? (
                <PageStateCard
                  state="empty"
                  title={tTeams("noTeamsTitle")}
                  description={canWrite ? tTeams("noTeamsHost") : tTeams("noTeamsViewer")}
                  className="rounded-none border-0 px-4 py-16"
                />
              ))
            ) : (
              <VariantView
                variant={variant}
                owner={owner}
                canWrite={canWrite}
                capturing={capturing}
                onRenameTeam={
                  onRenameTeam &&
                  ((teamIndex, name) => onRenameTeam(lobbyIndex * 2 + teamIndex, name))
                }
                onSwapSeats={
                  reshape && onSwapSeats
                    ? (firstUuid, secondUuid) => onSwapSeats(index, firstUuid, secondUuid)
                    : undefined
                }
                onMakeCaptain={
                  reshape && onMakeCaptain ? (uuid) => onMakeCaptain(Number(uuid)) : undefined
                }
                awayUuids={awayUuids}
              />
            )}
          </div>

          {hasFooter ? (
            <div className="flex flex-col gap-3 border-t border-[color:var(--aqt-border)] px-4 py-3">
              {onFloor ? (
                <>
                  {live && variant && canWrite ? (
                    <PickupResultControls
                      teamCount={variant.teams.length}
                      teamNames={variant.teams.map((team) => team.name)}
                      saving={recordingOutcome}
                      pointsPerWin={pointsPerWin}
                      onRecord={(recordedOutcome) =>
                        onRecordOutcome({ outcome: recordedOutcome, lobbyIndex })
                      }
                    />
                  ) : null}
                  {/* Every viewer hears why the teams stopped moving and where the match plays out; only a host can
                      end it. */}
                  <div className="flex flex-wrap items-center gap-2">
                    <p className={CAPTION_CLASS}>{tRoom("frozen")}</p>
                    {pregame ? <p className={CAPTION_CLASS}>{tRoom("bansInRoom")}</p> : null}
                    <Button asChild variant={pregame ? "accent" : "outline"} size="sm" className="ml-auto">
                      <RoomLink href={roomHref}>
                        <DoorOpen className="size-3.5" aria-hidden="true" />
                        {tRoom("openRoom")}
                      </RoomLink>
                    </Button>
                    {canWrite ? (
                      <>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={cancellingMatch}
                          onClick={() => setCancelOpen(true)}
                        >
                          {cancellingMatch ? (
                            <Spinner className="mr-1.5 size-3.5" />
                          ) : (
                            <CircleX className="mr-1.5 size-3.5" aria-hidden="true" />
                          )}
                          {tRoom("cancelMatch")}
                        </Button>
                        <ConfirmDialog
                          open={cancelOpen}
                          onOpenChange={setCancelOpen}
                          intent={{
                            title: tRoom("cancelTitle"),
                            description: tRoom("cancelDescription"),
                            confirmLabel: tRoom("cancelConfirm"),
                            tone: "danger"
                          }}
                          pending={cancellingMatch}
                          onConfirm={() => {
                            setCancelOpen(false);
                            onCancelMatch();
                          }}
                        />
                      </>
                    ) : null}
                  </div>
                </>
              ) : showStart ? (
                <StartMatchButton
                  awayNames={awayNames}
                  opener={
                    lobby?.opener_index != null
                      ? {
                          names: [
                            variant?.teams[0]?.name ?? "Team 1",
                            variant?.teams[1]?.name ?? "Team 2"
                          ],
                          index: lobby.opener_index
                        }
                      : null
                  }
                  starting={startingMatch}
                  onStart={onStartMatch}
                />
              ) : null}

              {toolsRow ? (
                <div
                  className={cn(
                    "flex flex-wrap items-center gap-2",
                    (onFloor || showStart) && "border-t border-[color:var(--aqt-border)] pt-3"
                  )}
                >
                  {balanceInFooter ? balanceControl : null}

                  {showPager ? (
                    <div className="flex items-center gap-0.5">
                      <IconTooltip control label={tTeams("previousOption")}>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          disabled={index === 0}
                          onClick={() => onVariantIndexChange(index - 1)}
                        >
                          <ChevronLeft aria-hidden="true" />
                          <span className="sr-only">{tTeams("previousOption")}</span>
                        </Button>
                      </IconTooltip>
                      <span
                        role="status"
                        aria-live="polite"
                        className="min-w-14 px-1 text-center text-caption font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]"
                      >
                        {`${index + 1} / ${variants.length}`}
                      </span>
                      <IconTooltip control label={tTeams("nextOption")}>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          disabled={index >= variants.length - 1}
                          onClick={() => onVariantIndexChange(index + 1)}
                        >
                          <ChevronRight aria-hidden="true" />
                          <span className="sr-only">{tTeams("nextOption")}</span>
                        </Button>
                      </IconTooltip>
                    </div>
                  ) : null}

                  {variant ? (
                    // Icon-only: these are recognisable glyphs and each is used once a
                    // night at most, so their labels were spending a third of the row
                    // on words nobody reads twice. The name lives in `aria-label` and
                    // the tooltip.
                    <div className="ml-auto flex items-center gap-1">
                      <IconTooltip control label={tTeams("copyImage")} hint={tTeams("copyImageHint")}>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className={TOOL_ICON_CLASS}
                          disabled={capturing}
                          aria-label={tTeams("copyImage")}
                          onClick={() => void capture()}
                        >
                          {capturing ? <Spinner /> : <Copy className="size-4" aria-hidden="true" />}
                        </Button>
                      </IconTooltip>
                      <IconTooltip control label={tTeams("copyHandles")} hint={tTeams("copyHandlesHint")}>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className={TOOL_ICON_CLASS}
                          aria-label={tTeams("copyHandles")}
                          onClick={onCopyHandles}
                        >
                          <ClipboardCopy className="size-4" aria-hidden="true" />
                        </Button>
                      </IconTooltip>
                      {/* The workspace's channel is the only target a mix has; without
                        one there is nowhere to post, so the button stays off. */}
                      {canWrite && onPostToDiscord && game?.settings.workspace_discord_channel_id ? (
                        <IconTooltip control label={tTeams("post")} hint={tTeams("postHint")}>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className={TOOL_ICON_CLASS}
                            disabled={postingToDiscord}
                            aria-label={tTeams("post")}
                            onClick={() => onPostToDiscord(index)}
                          >
                            {postingToDiscord ? (
                              <Spinner />
                            ) : (
                              <Send className="size-4" aria-hidden="true" />
                            )}
                          </Button>
                        </IconTooltip>
                      ) : null}
                      {canWrite ? (
                        <>
                          <span
                            aria-hidden="true"
                            className="mx-1 h-5 w-px bg-[color:var(--aqt-border)]"
                          />
                          {/* Once a night, irreversible from here: an icon that only
                            turns red on hover, behind the same confirm as before,
                            instead of the loudest pill in the row. */}
                          <IconTooltip control label={tTeams("close")} hint={tTeams("closeHint")}>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className={cn(TOOL_ICON_CLASS, "hover:text-[color:var(--aqt-rose-text)]")}
                              disabled={closingMix}
                              aria-label={tTeams("close")}
                              onClick={() => setCloseOpen(true)}
                            >
                              {closingMix ? (
                                <Spinner />
                              ) : (
                                <Archive className="size-4" aria-hidden="true" />
                              )}
                            </Button>
                          </IconTooltip>
                          <ConfirmDialog
                            open={closeOpen}
                            onOpenChange={setCloseOpen}
                            intent={{
                              title: tTeams("closeTitle"),
                              description: tTeams("closeDescription"),
                              confirmLabel: tTeams("closeConfirm"),
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
              ) : null}

              {matches.length > 0 ? (
                <MatchHistoryList
                  matches={matches}
                  lobbyCount={lobbyCount}
                  canWrite={canWrite}
                  undoingMatchId={undoingMatchId}
                  onUndoMatch={onUndoMatch}
                  discipline={game?.discipline ?? null}
                  className={cn(
                    (onFloor || showStart || toolsRow) && "border-t border-[color:var(--aqt-border)] pt-3"
                  )}
                />
              ) : null}
            </div>
          ) : null}
        </Card>
      )}
    </div>
  );
}
