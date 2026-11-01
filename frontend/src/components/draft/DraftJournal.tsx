"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { useFormatter } from "@/lib/datetime/client";
import { showsRoles, type RoleOntology } from "@/lib/roster/ontology";
import { roleOf } from "@/lib/roster/role-ref";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import type { DraftBoard, DraftJournalAction, DraftJournalEntry } from "@/types/draft.types";

interface DraftJournalProps {
  id: string;
  board: DraftBoard;
  entries: readonly DraftJournalEntry[] | undefined;
  ontology: RoleOntology | null;
  isLoading: boolean;
  isError: boolean;
  /** Refetch the journal after a failed load. */
  onRetry: () => void;
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

/** The sentences that name a role; a one-role game words them without it (every seat is that role). */
const ROLE_ACTIONS = ["pick_made", "pick_autopicked", "pick_overridden", "player_role_added"] as const;

/** Warnings amber, machine actions muted, everything else plain. */
function entryColor(action: string): string {
  if (action === "pick_overridden" || action === "paused" || action === "rollback") return "var(--aqt-amber)";
  if (action === "pick_autopicked") return "var(--aqt-fg-muted)";
  return "var(--aqt-fg)";
}

/** The organizer's log of what happened in the room, newest first. */
export function DraftJournal({ id, board, entries, ontology, isLoading, isError, onRetry }: Readonly<DraftJournalProps>) {
  const t = useTranslations("draftRedesign");
  const slotLabel = useSlotLabel(ontology);
  const named = showsRoles(ontology);
  const format = useFormatter();
  const teamName = (teamId: number | null) =>
    board.teams.find((team) => team.id === teamId)?.name ?? t("shell.journal.unknownTeam");
  const playerTag = (playerId: number | null) => {
    const player = board.players.find((entry) => entry.id === playerId);
    return player ? player.display.name : t("shell.journal.unknownPlayer");
  };

  const describe = (entry: DraftJournalEntry) => {
    if (!KNOWN_ACTIONS.has(entry.action)) return t("shell.journal.action.unknown", { action: entry.action });
    const values = {
      pick: entry.pick_no ?? "—",
      team: teamName(entry.team_id),
      player: playerTag(entry.player_id),
      reason: entry.reason ?? "",
      seconds: entry.seconds ?? 0
    };
    if (!named && (ROLE_ACTIONS as readonly string[]).includes(entry.action)) {
      return t(`shell.journal.actionNoRole.${entry.action as (typeof ROLE_ACTIONS)[number]}`, values);
    }
    return t(`shell.journal.action.${entry.action as DraftJournalAction}`, {
      ...values,
      role: slotLabel(entry.role ? roleOf(entry.role) : OPEN_SLOT_CODE)
    });
  };

  return (
    <div id={id} className="mx-auto max-w-[1720px] px-4 pb-2.5 sm:px-6">
      <div
        role="log"
        aria-label={t("shell.journal.label")}
        className="max-h-[220px] overflow-y-auto rounded-[10px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]"
      >
        {isLoading ? (
          <div role="status">
            <span className="sr-only">{t("shell.journal.loading")}</span>
            {[0, 1, 2].map((row) => (
              <div
                key={row}
                aria-hidden
                className="flex items-center gap-3 border-b border-[color:var(--aqt-border)] px-3.5 py-2.5 last:border-b-0"
              >
                <Skeleton className="h-4 w-14" />
                <Skeleton className="h-4 flex-1" />
              </div>
            ))}
          </div>
        ) : isError ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2">
            <p className="text-body text-[color:var(--aqt-rose-text)]">{t("shell.journal.error")}</p>
            <Button type="button" variant="outline" size="sm" className="min-h-11 sm:min-h-8" onClick={onRetry}>
              {t("retry")}
            </Button>
          </div>
        ) : !entries || entries.length === 0 ? (
          <p className="px-3.5 py-2 text-body text-[color:var(--aqt-fg-muted)]">{t("shell.journal.empty")}</p>
        ) : (
          <ul>
            {entries.map((entry) => (
              <li
                key={entry.id}
                className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-3 border-b border-[color:var(--aqt-border)] px-3.5 py-2 text-body last:border-b-0 sm:grid-cols-[80px_minmax(0,1fr)_140px]"
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
