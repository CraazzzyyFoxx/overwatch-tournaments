"use client";

import { ArrowRight, X } from "lucide-react";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { PlayerRankHistoryPreviewEntry } from "@/components/balancer/workspace-helpers";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { BalancerPlayerRoleEntry } from "@/types/balancer-admin.types";

import { ROLE_DISPLAY, buildHistoryChangeText } from "./playerEditSheet.model";
import { ROLE_RANK_ACCENTS } from "./RoleRankControls";
import type { PlayerRankHistoryState } from "./usePlayerEditForm";

type HistoryPreviewCardProps = {
  entry: PlayerRankHistoryPreviewEntry;
  currentEntry: BalancerPlayerRoleEntry | undefined;
  getDivisionName: (divisionNumber: number | null) => string | null;
  getOriginalDivisionName: (
    divisionNumber: number | null,
    entry: PlayerRankHistoryPreviewEntry
  ) => string | null;
};

function HistoryPreviewCard({
  entry,
  currentEntry,
  getDivisionName,
  getOriginalDivisionName
}: Readonly<HistoryPreviewCardProps>) {
  const accent = ROLE_RANK_ACCENTS[entry.role];
  // Normalised name (target/workspace grid)
  const divisionName =
    getDivisionName(entry.division_number) ??
    (entry.division_number != null ? `Division ${entry.division_number}` : null);
  // Original name (source tournament grid)
  const originalDivisionName =
    getOriginalDivisionName(entry.original_division_number, entry) ??
    (entry.original_division_number != null ? `Division ${entry.original_division_number}` : null);
  // Show the arrow only when the two differ (cross-version normalisation changed the number)
  const showNormalisedArrow =
    entry.original_division_number !== entry.division_number && entry.division_number != null;
  const changeText = buildHistoryChangeText(currentEntry, entry);

  return (
    <div
      className={cn(
        "grid gap-2.5 rounded-xl border p-3 sm:grid-cols-[minmax(0,1fr)_auto]",
        "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]",
        accent.row
      )}
    >
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2">
            <PlayerRoleIcon role={ROLE_DISPLAY[entry.role]} size={18} decorative />
            <span className={cn("text-sm font-semibold", accent.text)}>
              {ROLE_DISPLAY[entry.role]}
            </span>
          </div>
          <Badge className={cn("h-5 border px-2 text-label", accent.chip)}>
            {entry.rank_value} SR
          </Badge>
          {/* Original division (source tournament grid) */}
          {originalDivisionName ? (
            <div className="flex items-center gap-1.5 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 py-1 text-[color:var(--aqt-fg)]">
              {entry.original_division_number != null ? (
                <DivisionIcon
                  division={entry.original_division_number}
                  width={16}
                  height={16}
                  tournamentGrid={entry.tournament_grid_version}
                />
              ) : null}
              <span className="text-label font-medium">{originalDivisionName}</span>
            </div>
          ) : null}
          {/* Normalised division (workspace target grid) — only when different */}
          {showNormalisedArrow && divisionName ? (
            <>
              <ArrowRight className="size-4 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden />
              <div className="flex items-center gap-1.5 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-2 py-1 text-[color:var(--aqt-fg)]">
                {entry.division_number != null ? (
                  <DivisionIcon division={entry.division_number} width={16} height={16} />
                ) : null}
                <span className="text-label font-medium">{divisionName}</span>
              </div>
            </>
          ) : null}
        </div>
        <p className="text-xs leading-relaxed text-[color:var(--aqt-fg-muted)]">{changeText}</p>
      </div>
      <div className="space-y-1 text-xs text-[color:var(--aqt-fg-muted)] sm:text-right">
        <div className="flex items-center justify-end gap-1.5">
          <span
            className={cn(
              "rounded border px-1.5 py-0.5 text-label font-semibold uppercase tracking-label",
              entry.source === "balancer"
                ? "border-indigo-400/25 bg-indigo-500/10 text-indigo-200"
                : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-muted)]"
            )}
          >
            {entry.source === "balancer" ? "Balancer" : "Analytics"}
          </span>
        </div>
        {entry.tournament_name ? (
          <div className="font-medium text-[color:var(--aqt-fg)]">{entry.tournament_name}</div>
        ) : null}
        {entry.source_role ? <div>Source role: {entry.source_role}</div> : null}
      </div>
    </div>
  );
}

interface PlayerEditHistoryPanelProps {
  history: PlayerRankHistoryState;
  /** The roles being edited, so each preview card can say what it would change. */
  roleEntries: BalancerPlayerRoleEntry[];
  getDivisionName: (divisionNumber: number | null) => string | null;
  getOriginalDivisionName: (
    divisionNumber: number | null,
    entry: PlayerRankHistoryPreviewEntry
  ) => string | null;
}

/** The "Load from history" result: what applying it would change, and which
 *  workspaces it was read from. */
export function PlayerEditHistoryPanel({
  history,
  roleEntries,
  getDivisionName,
  getOriginalDivisionName
}: Readonly<PlayerEditHistoryPanelProps>) {
  const { workspaces } = useWorkspaceStore();
  const entries = history.preview?.entries ?? [];
  const average = history.preview?.average_rank_value ?? null;

  return (
    <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[color:var(--aqt-fg)]">History preview</span>
          {average != null ? (
            <Badge className="h-5 border-primary/20 bg-primary/10 px-2 text-label text-[color:var(--aqt-fg)] hover:bg-primary/10">
              Avg {average}
            </Badge>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {entries.length > 0 ? (
            <Button
              type="button"
              size="sm"
              className="h-7 bg-primary px-2.5 text-label text-primary-foreground hover:bg-primary/90"
              onClick={history.apply}
            >
              Apply history values
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
            onClick={history.dismiss}
            aria-label="Close history preview"
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="mt-2 space-y-1.5">
        {history.error ? (
          <div className="rounded-lg border border-rose-400/20 bg-rose-500/[0.08] px-2.5 py-2 text-xs text-rose-100">
            {history.error}
          </div>
        ) : null}

        {!history.error && !history.loading && entries.length === 0 ? (
          <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 py-2 text-xs text-[color:var(--aqt-fg-muted)]">
            No ranked tournament history was found for this BattleTag.
          </div>
        ) : null}

        {entries.map((entry) => (
          <HistoryPreviewCard
            key={`${entry.role}-${entry.tournament_id}`}
            entry={entry}
            currentEntry={roleEntries.find((roleEntry) => roleEntry.role === entry.role)}
            getDivisionName={getDivisionName}
            getOriginalDivisionName={getOriginalDivisionName}
          />
        ))}
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 border-t border-[color:var(--aqt-border)] pt-2.5">
        <Label className="text-label text-[color:var(--aqt-fg-muted)] select-none">
          Load history from:
        </Label>
        <Select value={history.workspaceValue} onValueChange={history.changeWorkspace}>
          <SelectTrigger className="h-6 w-[180px] border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-label text-[color:var(--aqt-fg)] px-2">
            <SelectValue placeholder="Select workspace" />
          </SelectTrigger>
          <SelectContent className="border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)] text-[color:var(--aqt-fg)] text-label">
            <SelectItem value="current" className="text-label">
              Current Workspace
            </SelectItem>
            <SelectItem value="all" className="text-label">
              All Workspaces
            </SelectItem>
            {workspaces.map((ws) => (
              <SelectItem key={ws.id} value={String(ws.id)} className="text-label">
                {ws.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
