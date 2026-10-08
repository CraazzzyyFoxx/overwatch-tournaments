"use client";

import { useState } from "react";

import Image from "next/image";

import { useTranslations } from "next-intl";

import { History, Undo2 } from "lucide-react";

import { EYEBROW_CLASS, lobbyLetter, teamAccent } from "@/app/balancer/mix/pickup-chrome";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { formatRelative } from "@/components/kit/format-time";
import { Button } from "@/components/ui/button";
import { IconTooltip } from "@/components/ui/icon-tooltip";
import { Spinner } from "@/components/ui/spinner";
import { StatusDot } from "@/components/ui/status-dot";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { CustomGameMatch } from "@/services/custom-game.service";

/** Every match this mix has recorded, every lobby, newest first — the permanent record `Record result` writes into. */
export function MatchHistoryList({
  matches,
  lobbyCount,
  canWrite,
  undoingMatchId,
  onUndoMatch
}: Readonly<{
  matches: CustomGameMatch[];
  lobbyCount: number;
  canWrite: boolean;
  undoingMatchId: number | null;
  onUndoMatch?: (matchId: number) => void;
}>) {
  // Newest first, so the first row of each lobby IS that lobby's newest -- the
  // only one the server will undo (`newest_id_for_lobby`).
  const newestPerLobby = new Set<number>();
  const seenLobbies = new Set<number>();
  for (const match of matches) {
    if (!seenLobbies.has(match.lobby_index)) {
      seenLobbies.add(match.lobby_index);
      newestPerLobby.add(match.id);
    }
  }
  // A mix that dropped a lobby keeps that lobby's matches in the log, so the
  // chip follows the history as well as the current count.
  const showLobby = lobbyCount > 1 || [...seenLobbies].some((index) => index > 0);

  return (
    <div className="flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3">
      <span className={cn(EYEBROW_CLASS, "flex items-center gap-1.5 tracking-label")}>
        <History className="size-3.5" aria-hidden="true" />
        Match history
      </span>
      <ul className="flex flex-col gap-1.5">
        {matches.map((match) => (
          <MatchHistoryRow
            key={match.id}
            match={match}
            showLobby={showLobby}
            canUndo={newestPerLobby.has(match.id) && canWrite && onUndoMatch != null}
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
  showLobby,
  canUndo,
  undoing,
  onUndoMatch
}: Readonly<{
  match: CustomGameMatch;
  /** More than one lobby now, or one past the first somewhere in the log: say which one played it. */
  showLobby: boolean;
  canUndo: boolean;
  undoing: boolean;
  onUndoMatch?: (matchId: number) => void;
}>) {
  const t = useTranslations("mixes.lobbies");
  const format = useFormatter();
  const homeAccent = teamAccent(0);
  const awayAccent = teamAccent(1);
  const lobbyAccent = teamAccent(match.lobby_index);
  const letter = lobbyLetter(match.lobby_index);
  const [undoOpen, setUndoOpen] = useState(false);

  return (
    <li className="flex items-center gap-3 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] px-2.5 py-2">
      {showLobby ? (
        <IconTooltip label={t("tab", { letter })} className="shrink-0">
          <span
            data-testid="match-lobby"
            aria-hidden="true"
            className={cn(
              "flex size-5 items-center justify-center rounded font-display text-label font-extrabold",
              lobbyAccent.bar,
              "text-[color:var(--aqt-bg)]"
            )}
          >
            {letter}
          </span>
        </IconTooltip>
      ) : null}
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
          <StatusDot className={cn("inline-block", homeAccent.bar)} />
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
          <StatusDot className={cn("inline-block", awayAccent.bar)} />
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 truncate text-label text-[color:var(--aqt-fg-dim)]">
          <span className="truncate">{match.map_name ?? "No map"}</span>
          <span aria-hidden="true">&middot;</span>
          <span className="shrink-0">{formatRelative(format, match.recorded_at)}</span>
        </div>
      </div>
      {canUndo ? (
        <>
          <IconTooltip control label="Undo this match" hint="Removes it from the history">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Undo this match"
              disabled={undoing}
              onClick={() => setUndoOpen(true)}
            >
              {undoing ? <Spinner /> : <Undo2 className="size-4" aria-hidden="true" />}
            </Button>
          </IconTooltip>
          <ConfirmDialog
            open={undoOpen}
            onOpenChange={setUndoOpen}
            intent={{
              title: "Undo this match?",
              description:
                match.points_per_win_applied != null
                  ? `Removes it from the history and moves every player's rank back by ${match.points_per_win_applied} points. Players pinned as must-play before it were already released to the pool and stay there.`
                  : "Removes it from the history. No rank points were applied.",
              confirmLabel: "Undo match",
              tone: "danger"
            }}
            pending={undoing}
            onConfirm={() => {
              setUndoOpen(false);
              onUndoMatch?.(match.id);
            }}
          />
        </>
      ) : null}
    </li>
  );
}
