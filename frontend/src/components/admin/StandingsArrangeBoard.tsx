"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Lock, LockOpen, RotateCcw } from "lucide-react";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { SortableGrip, SortableRows, useSortableRow } from "@/components/kit/SortableRows";
import { StatusPill } from "@/components/kit/StatusPill";
import TeamName from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
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
  const tables = useMemo(() => tablesOf(rows, stages), [rows, stages]);

  if (tables.length === 0) {
    return <EmptyNote>No standings to arrange yet. Recalculate to build them first.</EmptyNote>;
  }

  return (
    <div className="space-y-3">
      <p className="text-pretty text-sm text-muted-foreground">
        Drag a team to a place to pin it there. Pinned places hold through any later result or
        recalculation; the other teams keep following results.
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
  const [draft, setDraft] = useState<Draft | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

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
        <CardTitle asChild>
          <h3 className="min-w-0 truncate text-sm">{table.title}</h3>
        </CardTitle>
        {canUpdate ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy || !hasPins}
            onClick={() => setConfirmClear(true)}
          >
            <RotateCcw aria-hidden className="size-4" />
            Clear pins
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        <div aria-busy={busy || undefined} className="relative">
          <SortableRows
            className="rounded-md border border-border"
            items={current}
            getId={(row) => String(row.team_id)}
            onReorder={(next, moved) =>
              commit(
                {
                  order: next.map((row) => row.team_id),
                  pinned: [...pinned, moved.team_id]
                },
                "Place pinned — standings recalculated"
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
                    "Place unpinned — standings recalculated"
                  )
                }
              />
            )}
          </SortableRows>
          {busy ? (
            <div className="absolute inset-0 flex items-center justify-center rounded-md bg-background/40">
              <Spinner />
            </div>
          ) : null}
        </div>
      </CardContent>

      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        pending={busy}
        intent={{
          title: "Clear pins?",
          description: `Every pinned place in ${table.title} is released, and the table follows the results again.`,
          confirmLabel: "Clear pins",
          tone: "warning"
        }}
        onConfirm={() => commit({ order, pinned: [] }, "Pins cleared — standings recalculated")}
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
  const name = row.team?.name ?? `team #${row.team_id}`;
  const { ref, style, handleProps } = useSortableRow(String(row.team_id), !canUpdate || disabled);

  return (
    <div
      ref={ref}
      style={style}
      className={cn(
        "flex items-center gap-2 border-b border-border/50 bg-card px-3 py-1.5 last:border-b-0",
        pinned && "bg-muted/40"
      )}
    >
      {canUpdate ? (
        <SortableGrip
          handleProps={handleProps}
          label={`Drag ${name} to a new place`}
          disabled={disabled}
        />
      ) : null}
      <span className="w-6 shrink-0 text-sm font-semibold tabular-nums">{place ?? "—"}</span>
      {row.team ? (
        <TeamName team={row.team} size="xs" className="min-w-0 flex-1" nameClassName="font-medium" />
      ) : (
        <span className="min-w-0 flex-1 truncate text-sm font-medium" title={name}>
          {name}
        </span>
      )}
      {row.tie_group != null && !pinned ? (
        <StatusPill tone="warning" title="Equal on every tiebreaker — pin a place to decide it">
          Tied
        </StatusPill>
      ) : null}
      <span className="shrink-0 text-xs tabular-nums text-muted-foreground" title="Wins · draws · losses">
        {row.win}·{row.draw}·{row.lose}
      </span>
      <span className="w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
        {row.points.toFixed(1)}
        {"\u00a0"}pts
      </span>
      {pinned ? (
        <span className="flex shrink-0 items-center text-foreground" title="Pinned place">
          <Lock aria-hidden className="size-3.5" />
          <span className="sr-only">Pinned place</span>
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
          aria-label={`Unpin ${name}`}
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
