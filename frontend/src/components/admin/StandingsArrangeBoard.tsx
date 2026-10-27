"use client";

import { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation } from "@tanstack/react-query";
import { Lock, LockOpen, RotateCcw } from "lucide-react";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { SortableGrip, SortableRows, useSortableRow } from "@/components/kit/SortableRows";
import TeamName from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { Stage, Standings } from "@/types/tournament.types";

/** One standings table: the rows of one stage, or of one group within it. */
interface StandingsTableScope {
  key: string;
  stageId: number;
  stageItemId: number | null;
  title: string;
  /** Sort key: stage order, then group order. */
  rank: [number, number];
  /** By `position`; unranked playoff placeholders (`position` 0) last. */
  rows: Standings[];
}

function tablesOf(rows: Standings[], stages: Stage[]): StandingsTableScope[] {
  const stageById = new Map(stages.map((stage) => [stage.id, stage]));
  const byKey = new Map<string, StandingsTableScope>();
  for (const row of rows) {
    // Pins live on a stage; a row with none has nowhere to store one.
    if (row.stage_id == null) continue;
    const key = `${row.stage_id}:${row.stage_item_id ?? "-"}`;
    const table = byKey.get(key);
    if (table) {
      table.rows.push(row);
      continue;
    }
    const stage = stageById.get(row.stage_id);
    const item =
      row.stage_item_id == null
        ? undefined
        : stage?.items.find((entry) => entry.id === row.stage_item_id);
    const stageName = row.stage?.name ?? stage?.name ?? `Stage #${row.stage_id}`;
    const itemName = row.stage_item_id == null ? null : (row.stage_item?.name ?? item?.name ?? null);
    byKey.set(key, {
      key,
      stageId: row.stage_id,
      stageItemId: row.stage_item_id,
      title: itemName ? `${stageName} · ${itemName}` : stageName,
      rank: [stage?.order ?? Number.MAX_SAFE_INTEGER, item?.order ?? row.stage_item?.order ?? 0],
      rows: [row]
    });
  }
  const tables = [...byKey.values()];
  for (const table of tables) {
    table.rows.sort(
      (a, b) => (a.position || Number.MAX_SAFE_INTEGER) - (b.position || Number.MAX_SAFE_INTEGER)
    );
  }
  return tables.sort(
    (a, b) => a.rank[0] - b.rank[0] || a.rank[1] - b.rank[1] || a.title.localeCompare(b.title)
  );
}

/**
 * Where an organizer pins places. A pinned place holds no matter what results
 * come later; every other team fills the free places in computed order.
 *
 * The list is what gets saved: after a drop, the dragged team and every team
 * already pinned are pinned at their index in the list — nothing else, so the
 * unpinned teams keep following results.
 */
export function StandingsArrangeBoard({
  rows,
  stages,
  canUpdate,
  onChanged
}: Readonly<{
  rows: Standings[];
  stages: Stage[];
  canUpdate: boolean;
  onChanged: () => void;
}>) {
  const t = useTranslations("adminTournaments.arrange");
  const tables = useMemo(() => tablesOf(rows, stages), [rows, stages]);

  if (tables.length === 0) {
    return <EmptyNote>{t("empty")}</EmptyNote>;
  }

  return (
    <div className="space-y-3">
      <p className="text-pretty text-sm text-muted-foreground">
        {t("description")}
      </p>
      {tables.map((table) => (
        <ArrangeCard key={table.key} table={table} canUpdate={canUpdate} onChanged={onChanged} />
      ))}
    </div>
  );
}

/** The table as the organizer is arranging it: a team order and who is pinned. */
interface Draft {
  order: number[];
  pinned: number[];
}

function ArrangeCard({
  table,
  canUpdate,
  onChanged
}: Readonly<{ table: StandingsTableScope; canUpdate: boolean; onChanged: () => void }>) {
  const t = useTranslations("adminTournaments.arrange");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const noPinsId = useId();

  // The dropped order is shown while the recalculation runs and until the
  // refetched rows carry it. Keyed on the rows themselves, not the array
  // identity, and reset during render rather than in an effect, so the rows and
  // the draft indexed by them never commit out of step.
  const signature = table.rows
    .map((row) => `${row.team_id}:${row.position}:${row.is_pinned ? 1 : 0}`)
    .join(",");
  const [seenSignature, setSeenSignature] = useState(signature);
  if (seenSignature !== signature) {
    setSeenSignature(signature);
    setDraft(null);
  }

  const rowById = new Map(table.rows.map((row) => [row.team_id, row]));
  const order = draft?.order ?? table.rows.map((row) => row.team_id);
  const pinned = new Set(
    draft?.pinned ?? table.rows.filter((row) => row.is_pinned).map((row) => row.team_id)
  );
  const current = order.flatMap((teamId) => rowById.get(teamId) ?? []);

  const mutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: (next: Draft & { message: string }) => {
      const pinnedIds = new Set(next.pinned);
      return adminService.setStandingPins(table.stageId, {
        stage_item_id: table.stageItemId,
        pins: next.order.flatMap((teamId, index) =>
          pinnedIds.has(teamId) ? [{ team_id: teamId, position: index + 1 }] : []
        )
      });
    },
    onSuccess: (_result, variables) => {
      setConfirmClear(false);
      onChanged();
      notify.success(variables.message);
    },
    onError: (error) => {
      setDraft(null);
      notify.apiError(error);
    }
  });

  const commit = (next: Draft, message: string) => {
    setDraft(next);
    mutation.mutate({ ...next, message });
  };

  const busy = mutation.isPending;
  const hasPins = pinned.size > 0;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2 space-y-0 pb-3">
        <CardTitle asChild className="min-w-0 truncate text-sm">
          <h3>{table.title}</h3>
        </CardTitle>
        {canUpdate ? (
          <div className="flex shrink-0 items-center gap-2">
            {hasPins ? null : (
              <span id={noPinsId} className="text-caption text-muted-foreground">
                {t("noPins")}
              </span>
            )}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy || !hasPins}
              aria-describedby={hasPins ? undefined : noPinsId}
              onClick={() => setConfirmClear(true)}
            >
              <RotateCcw aria-hidden className="size-4" />
              {t("clearPins")}
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardContent>
        {/* While the pins save, the list dims rather than hiding under a spinner. */}
        <div aria-busy={busy || undefined} className={cn(busy && "opacity-60")}>
          <SortableRows
            className="flex flex-col divide-y divide-border"
            items={current}
            getId={(row) => String(row.team_id)}
            onReorder={(next, moved) =>
              commit(
                {
                  order: next.map((row) => row.team_id),
                  pinned: [...pinned, moved.team_id]
                },
                t("placePinned")
              )
            }
          >
            {(row, index) => (
              <ArrangeRow
                key={row.team_id}
                row={row}
                // The saved place, which a playoff may share (3rd-4th); the
                // list index only while a drop waits for its recalculation.
                place={row.position > 0 ? (draft ? index + 1 : row.position) : null}
                pinned={pinned.has(row.team_id)}
                canUpdate={canUpdate}
                disabled={busy}
                onUnpin={() =>
                  commit(
                    { order, pinned: [...pinned].filter((teamId) => teamId !== row.team_id) },
                    t("placeUnpinned")
                  )
                }
              />
            )}
          </SortableRows>
        </div>
      </CardContent>

      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        pending={busy}
        intent={{
          title: t("clearPinsTitle"),
          description: t("clearPinsDescription", { table: table.title }),
          confirmLabel: t("clearPins"),
          tone: "warning"
        }}
        onConfirm={() => commit({ order, pinned: [] }, t("pinsCleared"))}
      />
    </Card>
  );
}

function ArrangeRow({
  row,
  place,
  pinned,
  canUpdate,
  disabled,
  onUnpin
}: Readonly<{
  row: Standings;
  /** `null` for an unranked playoff placeholder. */
  place: number | null;
  pinned: boolean;
  canUpdate: boolean;
  disabled: boolean;
  onUnpin: () => void;
}>) {
  const t = useTranslations("adminTournaments.arrange");
  const name = row.team?.name ?? t("teamFallback", { id: row.team_id });
  const { ref, style, handleProps } = useSortableRow(String(row.team_id), !canUpdate || disabled);

  return (
    <div
      ref={ref}
      style={style}
      className={cn("flex items-center gap-2 bg-card py-1.5", pinned && "bg-muted/40")}
    >
      {canUpdate ? (
        <SortableGrip
          handleProps={handleProps}
          label={t("drag", { name })}
          disabled={disabled}
        />
      ) : null}
      <span className="w-6 shrink-0 text-sm font-semibold tabular-nums">{place}</span>
      {row.team ? (
        <TeamName team={row.team} size="xs" className="min-w-0 flex-1" nameClassName="font-medium" />
      ) : (
        <span className="min-w-0 flex-1 truncate text-sm font-medium" title={name}>
          {name}
        </span>
      )}
      {row.tie_group != null && !pinned ? (
        <span className="shrink-0 text-sm text-muted-foreground" title={t("tiedTitle")}>
          <span aria-hidden>=</span>
          <span className="sr-only">{t("tied")}</span>
        </span>
      ) : null}
      <span className="shrink-0 text-xs tabular-nums text-muted-foreground" title={t("recordTitle")}>
        {row.win}·{row.draw}·{row.lose}
      </span>
      <span className="w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {t("pointsValue", { points: row.points.toFixed(1) })}
      </span>
      {pinned ? (
        <span className="flex shrink-0 items-center" title={t("pinnedPlace")}>
          <Lock aria-hidden className="size-3.5" />
          <span className="sr-only">{t("pinnedPlace")}</span>
        </span>
      ) : (
        <span aria-hidden className="size-3.5 shrink-0" />
      )}
      {canUpdate && pinned ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 shrink-0"
          aria-label={t("unpin", { name })}
          title={t("unpin", { name })}
          disabled={disabled}
          onClick={onUnpin}
        >
          <LockOpen aria-hidden />
        </Button>
      ) : canUpdate ? (
        <span aria-hidden className="size-7 shrink-0" />
      ) : null}
    </div>
  );
}
