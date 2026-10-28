"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, DoorOpen, MoreHorizontal, Shuffle, Users } from "lucide-react";

import {
  CAPTION_CLASS,
  CARD_TITLE_CLASS,
  lobbyLetter,
  mixRoomHref,
  playsInRoom,
  teamAccent,
} from "@/app/balancer/mix/pickup-chrome";
import { useLiveMinutes } from "@/app/balancer/mix/_hooks/useLiveMinutes";
import { LineupRow } from "@/app/balancer/mix/_components/LineupRow";
import { LobbyStage } from "@/app/balancer/mix/_components/LobbyStage";
import { StartMatchButton } from "@/app/balancer/mix/_components/StartMatchButton";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Spinner } from "@/components/ui/spinner";
import { slotCodeOrder } from "@/lib/roster/ontology";
import { RoomLink } from "@/app/balancer/mix/_room/room-navigation";
import { cn } from "@/lib/utils";
import type { CustomGame, CustomGameLobby, CustomGamePlayer } from "@/services/custom-game.service";

import {
  lobbyCandidateCount,
  parseVariants,
  sortLineup,
  teamNamesByIndex,
  type MixOwner,
  type PickupRecordOutcomeInput,
} from "./pickup-lineup";

type PickupLobbyCardsProps = {
  game: CustomGame;
  rows: CustomGamePlayer[];
  owner: MixOwner;
  canWrite: boolean;
  /** The lobby whose balance / start / record is in flight, so only its button spins. */
  balancingLobby: number | null;
  startingLobby: number | null;
  recordingLobby: number | null;
  shufflingAll: boolean;
  onBalance: (lobbyIndex: number) => void;
  /** `flipOpener` swaps who bans first, with bans. */
  onStartMatch: (lobbyIndex: number, flipOpener: boolean) => void;
  onRecordOutcome: (input: PickupRecordOutcomeInput) => void;
  onShuffleAll: () => void;
  /** The lobby whose Draft is in flight (`null` while none), so only its button spins. */
  drafting: number | null;
  onDraft: (lobbyIndex: number) => void;
  splitting: boolean;
  onSplitPool: () => void;
  /** The lobby whose desk (its teams panel) shows under the cards, `null` for none. */
  selectedLobby: number | null;
  /** Shows a lobby's desk; `null` hides it. */
  onSelectLobby: (index: number | null) => void;
};

/**
 * The overview of a mix running several lobbies (spec §7.5, A1): one card per lobby with its stage, one line about
 * it and the one action that stage calls for -- Balance (Draft in draft mode, the balancer one menu away), Start match
 * or Record -- plus the way into its room, loud while the room is where the lobby's draft or bans are happening. A
 * card's Teams toggle opens that lobby's desk under the cards. A card's Balance is off, with the reason, while the
 * lobby cannot fill its seats. Shuffle all lobbies (Split pool in draft mode) re-forms every lobby at once, so it waits
 * while any match is live (the server refuses it too). Beside the cards, the players no lobby seats: waiting for a
 * seat, away, or on the bench. A one-lobby mix renders nothing: the overview is its desk.
 */
export function PickupLobbyCards(props: Readonly<PickupLobbyCardsProps>) {
  const { game, rows, owner, canWrite, shufflingAll, onShuffleAll, splitting, onSplitPool } = props;
  const t = useTranslations("mixes.lobbies");
  const [shuffleOpen, setShuffleOpen] = useState(false);
  if (game.lobby_count < 2) return null;
  const drafts = game.team_formation === "draft";
  const pending = drafts ? splitting : shufflingAll;
  const reform = drafts ? onSplitPool : onShuffleAll;
  const anyLive = game.lobbies.some((lobby) => lobby.live_encounter_id != null);
  const anyUnrecorded = game.lobbies.some((lobby) => lobby.lineup_recorded === false);
  return (
    <section className="flex flex-col gap-3">
      {canWrite ? (
        <div className="flex justify-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={pending || anyLive}
            onClick={() => (anyUnrecorded ? setShuffleOpen(true) : reform())}
          >
            {pending ? (
              <Spinner className="size-3.5" />
            ) : drafts ? (
              <Users className="size-3.5" aria-hidden="true" />
            ) : (
              <Shuffle className="size-3.5" aria-hidden="true" />
            )}
            {t(drafts ? "splitPool" : "shuffleAll")}
          </Button>
          <ConfirmDialog
            open={shuffleOpen}
            onOpenChange={setShuffleOpen}
            intent={{
              title: t(drafts ? "splitTitle" : "shuffleTitle"),
              description: t(drafts ? "splitDescription" : "shuffleDescription"),
              confirmLabel: t(drafts ? "splitConfirm" : "shuffleConfirm"),
              tone: "danger",
            }}
            pending={pending}
            onConfirm={() => {
              setShuffleOpen(false);
              reform();
            }}
          />
        </div>
      ) : null}
      <ul aria-label={t("tabsLabel")} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {game.lobbies.map((lobby) => (
          <LobbyCard key={lobby.lobby_index} {...props} lobby={lobby} />
        ))}
      </ul>
      <UnseatedGroups rows={rows} owner={owner} lobbyCount={game.lobby_count} />
    </section>
  );
}

function LobbyCard({
  game,
  rows,
  owner,
  canWrite,
  lobby,
  balancingLobby,
  startingLobby,
  recordingLobby,
  drafting,
  onBalance,
  onStartMatch,
  onRecordOutcome,
  onDraft,
  selectedLobby,
  onSelectLobby,
}: Readonly<PickupLobbyCardsProps & { lobby: CustomGameLobby }>) {
  const t = useTranslations("mixes.room");
  const tLobby = useTranslations("mixes.lobbies");
  const tVoice = useTranslations("mixes.voice");
  const defaultName = (team: number) => tVoice("team", { n: team + 1 });
  const index = lobby.lobby_index;
  const letter = lobbyLetter(index);
  const state = lobby.state ?? "idle";
  const selected = selectedLobby === index;
  const variant =
    parseVariants(
      lobby.balance_result,
      teamNamesByIndex(game.settings, index),
      slotCodeOrder(owner.ontology),
      defaultName,
    )[lobby.selected_variant_index] ?? null;
  const candidates = lobbyCandidateCount(rows, index);
  const need = owner.lobbySize;
  const short = need != null && candidates < need;
  const away = new Set(rows.filter((row) => row.away).map((row) => String(row.workspace_member_id)));
  const awayNames = (variant?.teams ?? [])
    .flatMap((team) => team.seats)
    .filter((seat) => away.has(seat.uuid))
    .map((seat) => seat.name);
  const teamNames: [string, string] = [
    variant?.teams[0]?.name ?? defaultName(0),
    variant?.teams[1]?.name ?? defaultName(1),
  ];
  const minutes = useLiveMinutes(state, lobby.live_started_at);
  const gap = variant?.stats.ratingGap ?? null;
  // A running match, its bans or a running draft: its minutes. A draft in setup reads its stage only, and only an idle
  // lobby can be short of seats.
  const detail =
    minutes != null
      ? t("elapsed", { minutes })
      : state === "ready"
        ? gap == null
          ? null
          : t("gap", { gap: Math.round(gap) })
        : state === "idle" && need != null
          ? t("shortSeats", { count: candidates, need })
          : null;
  const shortTitle = short && need != null ? t("shortSeats", { count: candidates, need }) : undefined;

  return (
    <Card asChild className={cn(selected && "border-[color:var(--aqt-teal)]")}>
      <li data-mix-lobby={selected ? undefined : index} className="flex flex-col gap-3 px-4 py-3.5">
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className={cn("h-4 w-[3px] shrink-0 rounded-sm", teamAccent(index).bar)}
          />
          <h2 className={CARD_TITLE_CLASS}>{tLobby("tab", { letter })}</h2>
          <LobbyStage state={state} className="ml-auto" />
        </div>
        {detail ? <p className={CAPTION_CLASS}>{detail}</p> : null}
        <div className="flex flex-wrap items-center gap-2">
          {canWrite && state === "idle" && game.team_formation === "draft" ? (
            <>
              <Button
                type="button"
                variant="accent"
                size="sm"
                disabled={short || drafting === index}
                title={shortTitle}
                onClick={() => onDraft(index)}
              >
                {drafting === index ? (
                  <Spinner className="size-3.5" />
                ) : (
                  <Users className="size-3.5" aria-hidden="true" />
                )}
                {t("draft")}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={t("moreActions")}>
                    <MoreHorizontal aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem disabled={short || balancingLobby === index} onSelect={() => onBalance(index)}>
                    {t("buildWithBalancer")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          ) : null}
          {canWrite && state === "idle" && game.team_formation !== "draft" ? (
            <Button
              type="button"
              variant="accent"
              size="sm"
              disabled={short || balancingLobby === index}
              title={shortTitle}
              onClick={() => onBalance(index)}
            >
              {balancingLobby === index ? (
                <Spinner className="size-3.5" />
              ) : (
                <Shuffle className="size-3.5" aria-hidden="true" />
              )}
              {t("balance")}
            </Button>
          ) : null}
          {canWrite && state === "ready" ? (
            <StartMatchButton
              awayNames={awayNames}
              opener={lobby.opener_index != null ? { names: teamNames, index: lobby.opener_index } : null}
              starting={startingLobby === index}
              onStart={(flip) => onStartMatch(index, flip)}
              variant="accent"
            />
          ) : null}
          {canWrite && state === "live" ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="accent" size="sm" disabled={recordingLobby === index}>
                  {recordingLobby === index ? <Spinner className="size-3.5" /> : null}
                  {t("record")}
                  <ChevronDown className="size-3.5" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem
                  onSelect={() => onRecordOutcome({ outcome: { winner: 1 }, lobbyIndex: index })}
                >
                  {t("teamWin", { team: teamNames[0] })}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => onRecordOutcome({ outcome: { winner: null }, lobbyIndex: index })}
                >
                  {t("draw")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => onRecordOutcome({ outcome: { winner: 2 }, lobbyIndex: index })}
                >
                  {t("teamWin", { team: teamNames[1] })}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto"
            aria-pressed={selected}
            onClick={() => onSelectLobby(selected ? null : index)}
          >
            {tLobby("desk")}
          </Button>
          <Button asChild variant={playsInRoom(state) ? "accent" : "outline"} size="sm">
            <RoomLink href={mixRoomHref(game.id, index)}>
              <DoorOpen className="size-3.5" aria-hidden="true" />
              {t("openRoom")}
            </RoomLink>
          </Button>
        </div>
      </li>
    </Card>
  );
}

/**
 * The players no lobby seats right now (spec §7.5, A1/F), each in one group: waiting for a seat, away (whatever their
 * participation -- away overrides it), or on the bench. The lineup's own rows, read-only: the host edits them in the
 * lineup beside the cards.
 */
function UnseatedGroups({
  rows,
  owner,
  lobbyCount,
}: Readonly<{ rows: CustomGamePlayer[]; owner: MixOwner; lobbyCount: number }>) {
  const t = useTranslations("mixes.room");
  const lineup = sortLineup(rows);
  const groups = [
    {
      key: "waiting",
      rows: lineup.filter((row) => !row.away && row.participation !== "benched" && row.current_lobby == null),
    },
    { key: "away", rows: lineup.filter((row) => row.away) },
    { key: "bench", rows: lineup.filter((row) => !row.away && row.participation === "benched") },
  ] as const;
  return (
    <div className="grid gap-x-6 gap-y-4 2xl:grid-cols-3">
      {groups.map((group) => (
        <section
          key={group.key}
          aria-label={t(`groups.${group.key}`)}
          className="flex flex-col gap-1.5 border-t border-[color:var(--aqt-border)] pt-3"
        >
          <div className="flex items-baseline gap-1.5">
            <Eyebrow>{t(`groups.${group.key}`)}</Eyebrow>
            <span className="text-label text-[color:var(--aqt-fg-dim)]">{group.rows.length}</span>
          </div>
          {group.rows.length > 0 ? (
            <ul className="flex flex-col gap-0.5">
              {group.rows.map((row) => (
                // `canWrite={false}` leaves none of the row's write controls reachable, so its handlers never fire.
                <LineupRow
                  key={row.workspace_member_id}
                  row={row}
                  rotationHint={undefined}
                  owner={owner}
                  canWrite={false}
                  lobbyCount={lobbyCount}
                  saving={false}
                  dimmed={group.key === "bench"}
                  onPatch={() => {}}
                  onOpen={() => {}}
                  onRemove={() => {}}
                />
              ))}
            </ul>
          ) : null}
        </section>
      ))}
    </div>
  );
}
