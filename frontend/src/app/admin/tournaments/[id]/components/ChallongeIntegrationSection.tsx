"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowDownToLine, ArrowUpFromLine, ExternalLink, Loader2, Users } from "lucide-react";
import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS, TONE_TEXT, type Tone } from "@/components/kit/tone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { ChallongeSyncLogEntry } from "@/types/admin.types";
import { invalidateTournamentWorkspace } from "@/lib/tournament-workspace-query-keys";
import { EmptyNote } from "@/components/kit/EmptyNote";

interface ChallongeIntegrationSectionProps {
  tournamentId: number;
  hasChallongeSource: boolean;
  /** Owned by the settings form: saved with the rest of the tournament. */
  slug: string;
  onSlugChange: (value: string) => void;
}

function formatSyncTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function getLogTone(status: ChallongeSyncLogEntry["status"]): Tone {
  if (status === "success") return "success";
  if (status === "conflict") return "warning";
  return "danger";
}

/**
 * The distinct Challonge participants that blocked an import, newest run first.
 *
 * An import refuses to create an encounter whose participants have no local team
 * mapped, and logs that per MATCH — so eight unmapped participants fill the whole
 * log with rows that all say the same thing. The ids come from the row's
 * `payload_json`, not from `error_message`: the message is prose written for a
 * human, and grouping on a parse of it would break the moment its wording moves.
 */
function getUnmappedParticipantIds(logs: ChallongeSyncLogEntry[]): number[] {
  const ids = new Set<number>();
  for (const log of logs) {
    if (log.status === "success") continue;
    const raw = log.payload_json?.["missing_participant_ids"];
    if (!Array.isArray(raw)) continue;
    for (const value of raw) {
      if (typeof value === "number") ids.add(value);
    }
  }
  return [...ids];
}

/**
 * Challonge link, sync triggers and sync log as one section.
 *
 * The link field used to sit in the settings form's "General information" card
 * while the sync buttons and log lived in a separate card further down the
 * page, so enabling sync meant editing one card to unlock another. They are one
 * connection, so they read as one block.
 *
 * Rendered inside the settings form, hence the explicit `type="button"`: an
 * unlabelled button in a form submits it.
 */
export function ChallongeIntegrationSection({
  tournamentId,
  hasChallongeSource,
  slug,
  onSlugChange
}: Readonly<ChallongeIntegrationSectionProps>) {
  const queryClient = useQueryClient();

  const { data: logs = [], isLoading } = useQuery({
    queryKey: ["admin", "challonge-sync-log", tournamentId],
    queryFn: () => adminService.challongeSyncLog(tournamentId, 20),
    enabled: hasChallongeSource
  });

  const invalidateSyncLog = () => {
    void queryClient.invalidateQueries({
      queryKey: ["admin", "challonge-sync-log", tournamentId]
    });
  };

  const importMutation = useMutation({
    mutationFn: () => adminService.challongeImport(tournamentId),
    onSuccess: () => {
      invalidateSyncLog();
      void queryClient.invalidateQueries({
        queryKey: ["admin", "tournament", tournamentId]
      });
      invalidateTournamentWorkspace(queryClient, tournamentId);
      notify.success("Challonge import started", { description: "Sync log will update shortly." });
    }
  });

  const exportMutation = useMutation({
    mutationFn: () => adminService.challongeExport(tournamentId),
    onSuccess: () => {
      invalidateSyncLog();
      notify.success("Challonge export started", { description: "Sync log will update shortly." });
    }
  });

  const lastLog = logs[0];
  const failedLogCount = logs.filter((log) => log.status !== "success").length;
  const syncPending = importMutation.isPending || exportMutation.isPending;
  const unmappedParticipantIds = getUnmappedParticipantIds(logs);
  // The slug is the settings form's live value, so this tracks an unsaved edit
  // too — which is the honest thing to link: it is the bracket about to be used.
  const bracketUrl = slug.trim() ? `https://challonge.com/${slug.trim()}` : null;
  const teamMappingHref = `/admin/tournaments/${tournamentId}/teams/roster?challongeSync=1`;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className={EYEBROW_CLASS}>Challonge</h3>
        <div className="flex shrink-0 items-center gap-2">
          {/* The only genuinely linkable Challonge target on this card. Sync-log
              rows carry match/participant ids, which have no public URL — they
              used to render this same icon beside them and go nowhere. */}
          {hasChallongeSource && bracketUrl ? (
            <a
              href={bracketUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
            >
              <ExternalLink className="size-3" aria-hidden />
              Open bracket
            </a>
          ) : null}
          <StatusPill tone={hasChallongeSource ? "accent" : "neutral"}>
            {hasChallongeSource ? "Connected" : "Not linked"}
          </StatusPill>
        </div>
      </div>

      <div>
        <Label htmlFor="settings-challonge" className="text-xs">
          Challonge URL or slug
        </Label>
        <Input
          id="settings-challonge"
          placeholder="e.g. my-tournament or https://challonge.com/my-tournament"
          value={slug}
          onChange={(event) => onSlugChange(event.target.value)}
          className="mt-1.5 bg-background/50"
        />
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!hasChallongeSource || importMutation.isPending}
          onClick={() => importMutation.mutate()}
        >
          {importMutation.isPending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <ArrowDownToLine className="size-4" aria-hidden />
          )}
          {importMutation.isPending ? "Importing…" : "Import"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!hasChallongeSource || exportMutation.isPending}
          onClick={() => exportMutation.mutate()}
        >
          {exportMutation.isPending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <ArrowUpFromLine className="size-4" aria-hidden />
          )}
          {exportMutation.isPending ? "Exporting…" : "Export"}
        </Button>
      </div>

      {!hasChallongeSource ? (
        <EmptyNote size="sm">
          Save a Challonge URL or a stage slug above to enable bracket sync.
        </EmptyNote>
      ) : syncPending || isLoading || lastLog ? (
        <div
          aria-live="polite"
          className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"
        >
          <span className={EYEBROW_CLASS}>Last sync</span>
          {syncPending ? (
            <span className="inline-flex items-center gap-1.5 text-foreground">
              <Loader2 className="size-3 animate-spin" aria-hidden />
              Sync running — the log updates when it finishes.
            </span>
          ) : isLoading ? (
            <span>Loading sync state…</span>
          ) : lastLog ? (
            <>
              <StatusPill tone={getLogTone(lastLog.status)} className="h-5">
                {lastLog.status}
              </StatusPill>
              <span className="text-foreground">
                {lastLog.direction} {lastLog.entity_type}
                {lastLog.entity_id ? ` #${lastLog.entity_id}` : ""}
              </span>
              <span aria-hidden>·</span>
              <span className="tabular-nums">{formatSyncTime(lastLog.created_at)}</span>
            </>
          ) : null}
          {failedLogCount > 0 ? (
            <>
              <span aria-hidden>·</span>
              <span className={TONE_TEXT.warning}>
                <span className="tabular-nums">{failedLogCount}</span> recent sync event
                {failedLogCount === 1 ? "" : "s"} need review.
              </span>
            </>
          ) : null}
        </div>
      ) : null}

      {/* The one failure an admin can actually clear from here, lifted out of the
          log: an unmapped participant fails every match it appears in, so the log
          shows the same problem N times with no hint that the fix is a mapping on
          another tab. */}
      {hasChallongeSource && unmappedParticipantIds.length > 0 ? (
        <EmptyNote
          size="sm"
          tone="warning"
          action={
            <Button asChild type="button" size="sm" variant="outline" className="shrink-0">
              <Link href={teamMappingHref}>
                <Users className="size-4" aria-hidden />
                Map teams
              </Link>
            </Button>
          }
        >
          <span className={cn("font-medium", TONE_TEXT.warning)}>
            <span className="tabular-nums">{unmappedParticipantIds.length}</span> Challonge
            participant{unmappedParticipantIds.length === 1 ? "" : "s"} not mapped to a team.
          </span>{" "}
          Import cannot create their matches until each one points at an internal team.
        </EmptyNote>
      ) : null}

      {hasChallongeSource ? (
        <div>
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className={EYEBROW_CLASS}>Sync log</p>
            <Badge variant="secondary" className="tabular-nums">
              {logs.length} recent
            </Badge>
          </div>

          {isLoading ? (
            <div className="text-sm text-muted-foreground">Loading sync log…</div>
          ) : logs.length === 0 ? (
            <EmptyNote>
              No sync history yet. Run an import or export to record the first event.
            </EmptyNote>
          ) : (
            <div className="max-h-[260px] overflow-y-auto rounded-lg border border-border/60">
              {logs.map((log) => (
                <div
                  key={log.id}
                  className="flex items-center gap-2 border-b border-border/50 px-3 py-2 text-xs last:border-b-0"
                >
                  <Badge tone="neutral" className="w-14 justify-center text-xs capitalize">
                    {log.direction}
                  </Badge>
                  <StatusPill tone={getLogTone(log.status)} className="w-16 justify-center text-xs capitalize">
                    {log.status}
                  </StatusPill>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">
                    {log.entity_type}
                    {log.entity_id ? ` #${log.entity_id}` : ""}
                    {log.error_message ? ` · ${log.error_message}` : ""}
                  </span>
                  {/* Plain text, not a link: this is a Challonge match/participant
                      id, and neither has a public URL. It used to carry an
                      ExternalLink icon inside a span — a link affordance that led
                      nowhere. The bracket link lives in the header instead. */}
                  {log.challonge_id ? (
                    <span className="hidden shrink-0 text-muted-foreground lg:inline">
                      Challonge <span className="tabular-nums">#{log.challonge_id}</span>
                    </span>
                  ) : null}
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {formatSyncTime(log.created_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
