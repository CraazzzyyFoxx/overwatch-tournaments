"use client";

import { useId, useState } from "react";
import { History } from "lucide-react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import adminService from "@/services/admin.service";
import type { PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import type { PickBanSide } from "@/components/pick-ban/pick-ban-model";
import type { PregameRoomHistoryEntry } from "@/types/admin.types";
import type { PickBanKind } from "@/types/tournament.types";

/**
 * Every action this panel has a sentence for, and whether it is one an
 * organizer is scanning FOR (overrides, disputes, clock trouble, cancellations
 * — tinted amber). The wire is open-ended: a backend that learns a new verb
 * must not turn the journal into blanks, so anything missing here is rendered
 * as its raw name.
 */
const ACTIONS = {
  ready_marked: "plain",
  ready_cleared: "warning",
  readiness_reset: "warning",
  session_opened: "plain",
  session_reset: "warning",
  session_completed: "plain",
  round_opened: "plain",
  opener_elected: "plain",
  acted: "plain",
  draft_locked: "plain",
  draft_set: "warning",
  step_revealed: "plain",
  step_auto_resolved: "plain",
  step_timed_out: "warning",
  step_disputed: "warning",
  step_reopened: "warning",
  undo_requested: "plain",
  undo_withdrawn: "plain",
  undo_applied: "plain",
  map_reported: "plain",
  map_disputed: "warning",
  series_reported: "plain",
  paused: "warning",
  resumed: "plain",
  timer_extended: "warning",
  session_cancelled: "warning",
  technical_loss: "warning",
  result_confirm: "plain",
  result_reopen: "warning",
  result_auto_confirm: "plain",
  result_auto_dispute: "warning",
  result_import: "plain",
  result_cascade_reset: "warning",
  result_game_confirm: "plain",
  result_game_correct: "warning",
  result_game_cancel: "warning"
} as const satisfies Record<string, "plain" | "warning">;

/** Only these have a `history.action.*` message; anything else is unknown. */
type RoomHistoryAction = keyof typeof ACTIONS;

const VERBS = { ban: true, pick: true, protect: true } as const;

const asText = (value: unknown) => (typeof value === "string" ? value : null);
const asNumber = (value: unknown) => (typeof value === "number" ? value : null);

/** The item ids an entry talks about, however the recorder packed them. */
function itemIds(data: Record<string, unknown>): number[] {
  const single = asNumber(data.item_id);
  if (single != null) return [single];
  if (Array.isArray(data.item_ids)) {
    return data.item_ids.filter((id): id is number => typeof id === "number");
  }
  if (Array.isArray(data.items)) {
    return data.items
      .map((item) =>
        item != null && typeof item === "object"
          ? asNumber((item as Record<string, unknown>).item_id)
          : null
      )
      .filter((id): id is number => id != null);
  }
  return [];
}

/**
 * The organizer's log of everything that happened in this room — the room's own
 * events merged with the encounter's result audit, newest first.
 *
 * It is the only place a room ever explains itself: a step that resolved on its
 * own, a draft an organizer submitted for an absent captain and a technical
 * loss all leave the same room state behind, and "who did that, and why" was
 * otherwise only answerable from the server logs.
 */
export function PregameRoomHistory({
  encounterId,
  sideNameOf,
  itemsByKind
}: Readonly<{
  encounterId: number;
  sideNameOf: (side: PickBanSide) => string;
  itemsByKind: Record<PickBanKind, Record<number, PickBanItemLike | undefined>>;
}>) {
  const t = useTranslations("pickBan.room");
  const format = useFormatter();
  const listId = useId();
  const [open, setOpen] = useState(false);

  // Only while the panel is open: the room already polls two states and the
  // encounter, and nobody reads a log they have not asked for.
  const history = useQuery({
    queryKey: encounterQueryKeys.roomHistory(encounterId),
    queryFn: () => adminService.getPregameRoomHistory(encounterId),
    enabled: open
  });
  const entries = history.data?.entries;

  // The two origins share no id space and no vocabulary; prefixing keeps a
  // result "reopen" from ever being read as a pick-ban step reopen.
  const actionKey = (entry: PregameRoomHistoryEntry) =>
    (entry.origin === "result" ? `result_${entry.action}` : entry.action) as RoomHistoryAction;

  const describe = (entry: PregameRoomHistoryEntry) => {
    const key = actionKey(entry);
    if (ACTIONS[key] == null) return t("history.action.unknown", { action: entry.action });

    const data = entry.data ?? {};
    const loser = data.loser_side === "home" || data.loser_side === "away" ? data.loser_side : null;
    const first = data.first_side === "home" || data.first_side === "away" ? data.first_side : null;
    const side = entry.side ?? loser;
    const home = asNumber(data.home_score);
    const away = asNumber(data.away_score);
    const verb = asText(data.action);
    const names = itemIds(data).map(
      (id) => itemsByKind[entry.kind === "hero" ? "hero" : "map"][id]?.name ?? `#${id}`
    );
    return t(`history.action.${key}`, {
      team: side != null ? sideNameOf(side) : t("history.unknownTeam"),
      first: first != null ? sideNameOf(first) : t("history.unknownTeam"),
      kind: entry.kind != null ? t(`phase.${entry.kind}`) : t("title"),
      verb:
        verb != null && verb in VERBS
          ? t(`history.verb.${verb as keyof typeof VERBS}`)
          : (verb ?? "—"),
      item: names[0] ?? "—",
      items: names.length > 0 ? names.join(", ") : "—",
      round: asNumber(data.round) ?? "—",
      step: asNumber(data.step_index) ?? "—",
      position: asNumber(data.position) ?? "—",
      score: home != null && away != null ? `${home}–${away}` : "—",
      seconds: asNumber(data.seconds) ?? asNumber(data.paused_seconds) ?? 0,
      attempt: asNumber(data.attempt) ?? "—",
      policy: asText(data.policy) ?? "—"
    });
  };

  return (
    <section className="rounded-xl border border-dashed border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-3">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <History className="mr-2 h-4 w-4" aria-hidden />
        {open
          ? t("history.hide")
          : entries != null
            ? t("history.toggleCount", { count: entries.length })
            : t("history.toggle")}
      </Button>

      {open ? (
        <div
          id={listId}
          role="log"
          aria-label={t("history.label")}
          className="mt-2 max-h-[280px] overflow-y-auto rounded-[10px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]"
        >
          {history.isPending ? (
            <p className="px-3.5 py-2 text-sm text-[color:var(--aqt-fg-muted)]">
              {t("history.loading")}
            </p>
          ) : history.isError ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2">
              <p className="text-sm text-[color:var(--aqt-rose-text)]">{t("history.error")}</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void history.refetch()}
              >
                {t("retry")}
              </Button>
            </div>
          ) : entries == null || entries.length === 0 ? (
            <p className="px-3.5 py-2 text-sm text-[color:var(--aqt-fg-muted)]">
              {t("history.empty")}
            </p>
          ) : (
            <ul>
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 border-b border-[color:var(--aqt-border)] px-3.5 py-2 text-sm last:border-b-0 sm:grid-cols-[110px_minmax(0,1fr)_140px]"
                >
                  <time dateTime={entry.at} className="tabular-nums text-[color:var(--aqt-fg-faint)]">
                    {format.dateTime(new Date(entry.at), {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit"
                    })}
                  </time>
                  <span
                    style={{
                      color:
                        ACTIONS[actionKey(entry)] === "warning"
                          ? "var(--aqt-amber)"
                          : entry.source === "system"
                            ? "var(--aqt-fg-muted)"
                            : "var(--aqt-fg)"
                    }}
                  >
                    {describe(entry)}
                    {entry.reason ? ` — “${entry.reason}”` : ""}
                  </span>
                  <span className="col-start-2 truncate text-[color:var(--aqt-fg-muted)] sm:col-start-auto sm:text-right">
                    {entry.actor_name ?? t("history.system")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
