"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import type { DraftBoard, DraftJournalAction, DraftJournalEntry } from "@/types/draft.types";

interface DraftJournalProps {
  id: string;
  board: DraftBoard;
  entries: readonly DraftJournalEntry[] | undefined;
  isLoading: boolean;
  isError: boolean;
}

const KNOWN_ACTIONS = new Set([
  "pick_made",
  "pick_autopicked",
  "pick_overridden",
  "pick_extended",
  "paused",
  "resumed",
  "rollback",
  "started",
  "completed",
  "cancelled",
  "player_role_added"
]);

/** Warnings amber, machine actions muted, everything else plain. */
function entryColor(action: string): string {
  if (action === "pick_overridden" || action === "paused" || action === "rollback") return "var(--aqt-amber)";
  if (action === "pick_autopicked") return "var(--aqt-fg-muted)";
  return "var(--aqt-fg)";
}

/** The organizer's log of what happened in the room, newest first. */
export function DraftJournal({ id, board, entries, isLoading, isError }: Readonly<DraftJournalProps>) {
  const t = useTranslations("draftRedesign");
  const format = useFormatter();
  const teamName = (teamId: number | null) =>
    board.teams.find((team) => team.id === teamId)?.name ?? t("shell.journal.unknownTeam");
  const playerTag = (playerId: number | null) => {
    const player = board.players.find((entry) => entry.id === playerId);
    return player ? (player.battle_tag ?? `#${player.id}`) : t("shell.journal.unknownPlayer");
  };

  const describe = (entry: DraftJournalEntry) =>
    KNOWN_ACTIONS.has(entry.action)
      ? t(`shell.journal.action.${entry.action as DraftJournalAction}`, {
          pick: entry.pick_no ?? "—",
          team: teamName(entry.team_id),
          player: playerTag(entry.player_id),
          role: t(`roles.${entry.role ?? "flex"}`),
          reason: entry.reason ?? "",
          seconds: entry.seconds ?? 0
        })
      : t("shell.journal.action.unknown", { action: entry.action });

  return (
    <div id={id} className="mx-auto max-w-[1720px] px-4 pb-2.5 sm:px-6">
      <div
        role="log"
        aria-label={t("shell.journal.label")}
        className="max-h-[220px] overflow-y-auto rounded-[10px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]"
      >
        {isLoading ? (
          <p className="px-3.5 py-2 text-sm text-[color:var(--aqt-fg-muted)]">{t("shell.journal.loading")}</p>
        ) : isError ? (
          <p className="px-3.5 py-2 text-sm text-[color:var(--aqt-rose)]">{t("shell.journal.error")}</p>
        ) : !entries || entries.length === 0 ? (
          <p className="px-3.5 py-2 text-sm text-[color:var(--aqt-fg-muted)]">{t("shell.journal.empty")}</p>
        ) : (
          <ul>
            {entries.map((entry) => (
              <li
                key={entry.id}
                className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-3 border-b border-[color:var(--aqt-border)] px-3.5 py-2 text-sm last:border-b-0 sm:grid-cols-[80px_minmax(0,1fr)_140px]"
              >
                <time dateTime={entry.created_at} className="tabular-nums text-[color:var(--aqt-fg-faint)]">
                  {format.dateTime(new Date(entry.created_at), {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit"
                  })}
                </time>
                <span style={{ color: entryColor(entry.action) }}>{describe(entry)}</span>
                <span className="col-start-2 truncate text-[color:var(--aqt-fg-muted)] sm:col-start-auto sm:text-right">
                  {entry.actor_name ?? t("shell.journal.system")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
