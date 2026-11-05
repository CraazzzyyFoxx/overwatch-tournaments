"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Crown, Lock } from "lucide-react";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { SettingGroup } from "@/components/kit/SettingRow";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { NumberInput } from "@/components/ui/number-input";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import adminService from "@/services/admin.service";
import type { PlayerStanding } from "@/types/admin.types";
import type { Stage, Tournament } from "@/types/tournament.types";

import { tabError, tabFallback } from "../../hubQueries";
import {
  cutIndex,
  pinOf,
  pinsDirty,
  pinsPayload,
  tablesByRole,
  type PinEdits
} from "./playerStandings.model";

/** Same cadence as the public standings of a live tournament. */
const REFRESH_MS = 15_000;

/**
 * The personal table of an `individual_swiss` stage, one table per role: pin a
 * player's place, and — once the stage is completed — lock the qualification,
 * which excludes everyone below the cut and moves the tournament to its draft.
 */
export function PlayerStandingsSection({
  stage,
  tournament,
  onChanged
}: Readonly<{ stage: Stage; tournament: Tournament | undefined; onChanged: () => void }>) {
  const t = useTranslations("adminBracket.individual");
  const queryClient = useQueryClient();
  const ontology =
    useDisciplineMetadata(tournament?.workspace_id ?? "all", tournament?.discipline ?? null).data ??
    null;
  const slotLabel = useSlotLabel(ontology);
  const [edits, setEdits] = useState<PinEdits>({});
  const [confirmingLock, setConfirmingLock] = useState(false);
  const [lockError, setLockError] = useState<string | null>(null);

  const standingsKey = adminQueryKeys.tournamentPlayerStandings(stage.tournament_id);
  const standingsQuery = useQuery({
    queryKey: standingsKey,
    queryFn: () => adminService.listPlayerStandings(stage.tournament_id),
    refetchInterval: REFRESH_MS
  });

  const stageRows = (standingsQuery.data ?? []).filter((row) => row.stage_id === stage.id);
  const tables = tablesByRole(stageRows, stage.id);
  const dirty = pinsDirty(stageRows, edits);

  const saveMutation = useMutation({
    mutationFn: () =>
      adminService.setPlayerStandingPins(stage.tournament_id, stage.id, pinsPayload(stageRows, edits)),
    onSuccess: (pins) => {
      // The recalculation that applies the pins is a job: show them now, the poll brings the new places.
      const pinned = new Map(pins.map((pin) => [pin.workspace_member_id, pin.position]));
      queryClient.setQueryData<PlayerStanding[]>(standingsKey, (current) =>
        current?.map((row) =>
          row.stage_id === stage.id
            ? {
                ...row,
                is_pinned: pinned.has(row.workspace_member_id),
                position: pinned.get(row.workspace_member_id) ?? row.position
              }
            : row
        )
      );
      setEdits({});
      notify.success(t("pinsSaved"));
    },
    onError: (error) => notify.apiError(error, { title: t("pinsError") })
  });

  const lockMutation = useMutation({
    mutationFn: () => adminService.lockQualification(stage.tournament_id, stage.id),
    onSuccess: (result) => {
      setConfirmingLock(false);
      setLockError(null);
      notify.success(
        t("locked", { qualified: result.qualified.length, captains: result.captains.length })
      );
      invalidateTournamentWorkspace(queryClient, stage.tournament_id);
      void queryClient.invalidateQueries({ queryKey: standingsKey });
      onChanged();
    },
    onError: (error) => {
      setConfirmingLock(false);
      // A 409 explains itself in the server's words (not completed, not live, nobody qualified).
      setLockError(error instanceof Error ? error.message : t("lockError"));
    }
  });

  if (standingsQuery.isPending) return tabFallback;
  if (standingsQuery.isError) return tabError(() => standingsQuery.refetch());

  // The server refuses a lock while rounds are still open and says why; the worker never completes this stage.
  const canLock = stage.status === "live" && tournament?.status === "live";

  return (
    <div className="flex flex-col gap-4">
      <p className="max-w-prose text-caption text-muted-foreground">{t("description")}</p>

      {lockError ? (
        <Alert tone="danger">
          <AlertDescription>{lockError}</AlertDescription>
        </Alert>
      ) : null}

      {tables.length === 0 ? <p className="text-caption text-muted-foreground">{t("empty")}</p> : null}

      {tables.map((table) => {
        const cut = cutIndex(table.rows);
        return (
          <SettingGroup
            key={table.role}
            id={`stage-players-${table.role}`}
            title={slotLabel(table.role)}
            summary={table.rows.length}
            flush
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">{t("place")}</TableHead>
                  <TableHead>{t("player")}</TableHead>
                  <TableHead className="text-right">{t("points")}</TableHead>
                  <TableHead className="text-right">{t("record")}</TableHead>
                  <TableHead className="text-right">{t("mapDiff")}</TableHead>
                  <TableHead className="text-right">{t("buchholz")}</TableHead>
                  <TableHead className="w-28">{t("pin")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {table.rows.map((row, index) => (
                  <TableRow
                    key={row.workspace_member_id}
                    // The cut: everyone up to this row qualifies, the rest does not.
                    className={cn(
                      "aqt-tnum",
                      index === cut && index < table.rows.length - 1 && "border-b-2 border-b-[color:var(--aqt-border-3)]",
                      !row.is_qualified && "text-[color:var(--aqt-fg-dim)]"
                    )}
                  >
                    <TableCell>{row.position ?? "–"}</TableCell>
                    <TableCell>
                      <span className="inline-flex items-center gap-1.5">
                        {row.display_name}
                        {row.is_captain ? (
                          <Crown
                            aria-label={t("captain")}
                            className="size-3.5 text-[color:var(--aqt-warm)]"
                          />
                        ) : null}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">{row.points}</TableCell>
                    <TableCell className="text-right">
                      {row.wins}–{row.draws}–{row.losses}
                    </TableCell>
                    <TableCell className="text-right">
                      {row.map_diff > 0 ? `+${row.map_diff}` : row.map_diff}
                    </TableCell>
                    <TableCell className="text-right">{row.buchholz.toFixed(1)}</TableCell>
                    <TableCell>
                      <NumberInput
                        integer
                        min={1}
                        max={table.rows.length}
                        size="sm"
                        aria-label={t("pinLabel", { name: row.display_name })}
                        placeholder="–"
                        value={pinOf(row, edits)}
                        onValueChange={(next) =>
                          setEdits((current) => ({ ...current, [row.workspace_member_id]: next }))
                        }
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SettingGroup>
        );
      })}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button
          size="sm"
          variant="outline"
          disabled={!dirty || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          {saveMutation.isPending ? <Spinner /> : null}
          {t("savePins")}
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          {canLock ? null : <p className="text-caption text-muted-foreground">{t("lockHint")}</p>}
          <Button
            size="sm"
            disabled={!canLock || lockMutation.isPending}
            onClick={() => setConfirmingLock(true)}
          >
            <Lock className="size-4" aria-hidden />
            {t("lock")}
          </Button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmingLock}
        onOpenChange={setConfirmingLock}
        intent={{
          title: t("lockTitle"),
          description: t("lockDescription"),
          confirmLabel: t("lockConfirm"),
          tone: "warning"
        }}
        onConfirm={() => lockMutation.mutate()}
        pending={lockMutation.isPending}
      />
    </div>
  );
}
