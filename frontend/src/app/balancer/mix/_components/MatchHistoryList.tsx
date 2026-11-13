"use client";

import { useState } from "react";

import { useTranslations } from "next-intl";

import { BarChart3, FileDown, FileUp, History, Undo2 } from "lucide-react";

import { CARD_TITLE_CLASS, lobbyLetter, teamAccent } from "@/app/balancer/mix/pickup-chrome";
import type { MixLogUpload } from "@/app/balancer/mix/useMixLogUpload";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { formatRelative } from "@/components/kit/format-time";
import { LogUploadDialog } from "@/components/logs/LogUploadDialog";
import MatchStatsDialog from "@/components/match/MatchStatsDialog";
import { MatchImport } from "@/components/pick-ban/MatchImport";
import { Badge } from "@/components/ui/badge";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@craazzzyyfoxx/admin-kit/ui/dialog";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { IconTooltip } from "@craazzzyyfoxx/admin-kit/ui/icon-tooltip";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import { StatusDot } from "@craazzzyyfoxx/admin-kit/ui/status-dot";
import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { CustomGameMatch } from "@/services/custom-game.service";
import type { CatalogEntityRead } from "@/types/catalog.types";

/** Every match this mix has recorded, every lobby, newest first — the permanent record `Record result` writes into. */
export function MatchHistoryList({
  matches,
  lobbyCount,
  canWrite,
  undoingMatchId,
  onUndoMatch,
  discipline,
  standalone = false,
  className,
  logUpload = null
}: Readonly<{
  matches: CustomGameMatch[];
  lobbyCount: number;
  canWrite: boolean;
  undoingMatchId: number | null;
  onUndoMatch?: (matchId: number) => void;
  /** The mix's game, whose heroes name the bans. */
  discipline: string | null;
  /** Its own card (the several-lobby overview): a card title. Default: an eyebrow, a section under the matchup. */
  standalone?: boolean;
  /** The caller separates it from what comes before (a hairline), since only the caller knows whether anything does. */
  className?: string;
  /** Present when the viewer may file a log under a round (host or `log.create`): each row then offers an upload. */
  logUpload?: MixLogUpload | null;
}>) {
  const t = useTranslations("mixes.matchHistory");
  // The heroes are read only once a round has bans or picks to show (spec §8.4, §11.6).
  const heroes = useCatalogEntities(
    matches.some((match) => match.bans.length > 0 || match.picks.length > 0) ? discipline : null,
    "character",
  );
  const heroById = new Map((heroes.data ?? []).map((hero) => [hero.id, hero]));
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
    <div className={cn("flex flex-col gap-2", className)}>
      {standalone ? (
        <h2 className={CARD_TITLE_CLASS}>{t("title")}</h2>
      ) : (
        <Eyebrow className="flex items-center gap-1.5">
          <History className="size-3.5" aria-hidden="true" />
          {t("title")}
        </Eyebrow>
      )}
      <ul className="flex flex-col divide-y divide-[color:var(--aqt-border)]">
        {matches.map((match) => (
          <MatchHistoryRow
            key={match.id}
            match={match}
            showLobby={showLobby}
            canUndo={newestPerLobby.has(match.id) && canWrite && onUndoMatch != null}
            undoing={undoingMatchId === match.id}
            onUndoMatch={onUndoMatch}
            heroById={heroById}
            logUpload={logUpload}
          />
        ))}
      </ul>
    </div>
  );
}

function MatchHistoryRow({
  match,
  showLobby,
  canUndo,
  undoing,
  onUndoMatch,
  heroById,
  logUpload
}: Readonly<{
  match: CustomGameMatch;
  /** More than one lobby now, or one past the first somewhere in the log: say which one played it. */
  showLobby: boolean;
  canUndo: boolean;
  undoing: boolean;
  onUndoMatch?: (matchId: number) => void;
  heroById: Map<number, CatalogEntityRead>;
  logUpload: MixLogUpload | null;
}>) {
  const t = useTranslations("mixes.lobbies");
  const tHistory = useTranslations("mixes.matchHistory");
  const tRoom = useTranslations("mixes.room");
  const format = useFormatter();
  const [first, second] = match.teams;
  const firstAccent = teamAccent(0);
  const secondAccent = teamAccent(1);
  const lobbyAccent = teamAccent(match.lobby_index);
  const letter = lobbyLetter(match.lobby_index);
  const [undoOpen, setUndoOpen] = useState(false);

  return (
    <li className="flex items-center gap-3 py-2">
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
      <CatalogEntityImage
        entity={{ name: match.map_name ?? "", image_path: match.map_image_path ?? null }}
        size={32}
        shape="wide"
        decorative
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-1.5 text-caption font-semibold leading-tight">
          <StatusDot className={cn("inline-block", firstAccent.bar)} />
          <span
            className={cn(
              "truncate",
              match.winner_slot === 1 ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {first?.name}
          </span>
          <span className="tabular-nums text-[color:var(--aqt-fg-muted)]">
            {first?.score} : {second?.score}
          </span>
          <span
            className={cn(
              "truncate",
              match.winner_slot === 2 ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {second?.name}
          </span>
          <StatusDot className={cn("inline-block", secondAccent.bar)} />
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 truncate text-label text-[color:var(--aqt-fg-dim)]">
          <span className="truncate">{match.map_name ?? tRoom("noMap")}</span>
          <span aria-hidden="true">&middot;</span>
          <span className="shrink-0">{formatRelative(format, match.recorded_at)}</span>
        </div>
        {match.bans.length > 0 ? <HeroBanStrip bans={match.bans} heroById={heroById} className="mt-1" /> : null}
        {match.picks.length > 0 ? <HeroPickList picks={match.picks} heroById={heroById} className="mt-1" /> : null}
      </div>
      {match.stats_match_id == null && match.log_state != null ? (
        <Badge shape="pill" tone={match.log_state === "failed" ? "danger" : "info"} className="shrink-0">
          {tHistory(match.log_state === "failed" ? "logFailed" : "logProcessing")}
        </Badge>
      ) : null}
      {match.stats_match_id != null ? (
        // A mix match lives only inside its mix: no `/matches/{id}` page to link to.
        <MatchStatsDialog
          matchId={match.stats_match_id}
          showMatchLink={false}
          trigger={
            <Button type="button" variant="ghost" size="sm" aria-label={tHistory("statistics")}>
              <BarChart3 aria-hidden="true" />
              <span className="hidden md:inline">{tHistory("statistics")}</span>
            </Button>
          }
        />
      ) : null}
      {logUpload?.fileUpload ? (
        <IconTooltip control label={tHistory("uploadLog")}>
          <LogUploadDialog
            scope={{ customGameId: logUpload.customGameId, encounterId: match.id }}
            onUploaded={logUpload.onUploaded}
            trigger={
              <Button type="button" variant="ghost" size="icon-sm" aria-label={tHistory("uploadLog")}>
                <FileUp aria-hidden="true" />
              </Button>
            }
          />
        </IconTooltip>
      ) : null}
      {logUpload?.matchFetch ? (
        // Statistics only: the round's recorded result is never touched.
        <Dialog>
          <IconTooltip control label={tHistory("importMatch")}>
            <DialogTrigger asChild>
              <Button type="button" variant="ghost" size="icon-sm" aria-label={tHistory("importMatch")}>
                <FileDown aria-hidden="true" />
              </Button>
            </DialogTrigger>
          </IconTooltip>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{tHistory("importMatchTitle")}</DialogTitle>
              <DialogDescription>{tHistory("importMatchDescription")}</DialogDescription>
            </DialogHeader>
            <MatchImport
              scope={{
                customGameId: logUpload.customGameId,
                encounterId: match.id,
                onSubmitted: logUpload.onUploaded,
                search: match.match_search,
                searchError: match.match_search_error,
                searchNextAttemptAt: match.match_search_next_attempt_at,
                searchable: logUpload.matchSearch && match.stats_match_id == null,
                ingestClient: logUpload.ingestClient
              }}
            />
          </DialogContent>
        </Dialog>
      ) : null}
      {canUndo ? (
        <>
          <IconTooltip control label={tHistory("undo")} hint={tHistory("undoHint")}>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={tHistory("undo")}
              disabled={undoing}
              onClick={() => setUndoOpen(true)}
            >
              {undoing ? <Spinner /> : <Undo2 aria-hidden="true" />}
            </Button>
          </IconTooltip>
          <ConfirmDialog
            open={undoOpen}
            onOpenChange={setUndoOpen}
            intent={{
              title: tHistory("undoTitle"),
              description:
                match.points_per_win_applied != null
                  ? tHistory("undoPoints", { points: match.points_per_win_applied })
                  : tHistory("undoNoPoints"),
              confirmLabel: tHistory("undoConfirm"),
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

/** Hero bans in the order they were made, each behind its team's dot. */
function HeroBanStrip({
  bans,
  heroById,
  className
}: Readonly<{
  bans: CustomGameMatch["bans"];
  heroById: Map<number, CatalogEntityRead>;
  className?: string;
}>) {
  const t = useTranslations("mixes.lobbies");
  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)} aria-label={t("bans")}>
      {bans.map((ban, index) => {
        const hero = heroById.get(ban.item_id);
        return (
          <span key={`${ban.item_id}-${index}`} className="flex items-center gap-0.5">
            <StatusDot className={cn("inline-block", teamAccent(ban.slot - 1).bar)} />
            <CatalogEntityImage
              entity={{ name: hero?.name ?? `#${ban.item_id}`, image_path: hero?.image_path ?? null }}
              size={20}
            />
          </span>
        );
      })}
    </div>
  );
}

/** Each player's hero, behind their team's dot (spec §11.6 R4-11). */
function HeroPickList({
  picks,
  heroById,
  className
}: Readonly<{
  picks: { slot: number; name: string; item_id: number }[];
  heroById: Map<number, CatalogEntityRead>;
  className?: string;
}>) {
  const t = useTranslations("mixes.lobbies");
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-3 gap-y-1", className)} aria-label={t("picks")}>
      {picks.map((pick) => {
        const hero = heroById.get(pick.item_id);
        return (
          <li key={`${pick.item_id}-${pick.name}`} className="flex items-center gap-1 text-label">
            <StatusDot className={cn("inline-block", teamAccent(pick.slot - 1).bar)} />
            <CatalogEntityImage
              entity={{ name: hero?.name ?? `#${pick.item_id}`, image_path: hero?.image_path ?? null }}
              size={20}
            />
            <span className="text-[color:var(--aqt-fg-muted)]">{pick.name}</span>
          </li>
        );
      })}
    </ul>
  );
}
