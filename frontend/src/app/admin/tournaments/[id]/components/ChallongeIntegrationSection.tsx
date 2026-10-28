"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { eyebrowClass } from "@/components/ui/eyebrow";
import type { DateFormatter } from "@/components/kit/format-time";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { ChallongeSyncLogEntry } from "@/types/admin.types";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Spinner } from "@/components/ui/spinner";
import { adminQueryKeys } from "@/lib/admin/query-keys";

interface ChallongeIntegrationSectionProps {
  tournamentId: number;
  hasChallongeSource: boolean;
  /** Owned by the settings form: saved with the rest of the tournament. */
  slug: string;
  onSlugChange: (value: string) => void;
}

function formatSyncTime(format: DateFormatter, value: string) {
  return format.dateTime(new Date(value), {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

/** Entity types the sync writes (`challonge.py`); anything else shows raw. */
const ENTITY_TYPES = ["tournament", "participant", "match"] as const;

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
 * connection, so they read as one block. The newest log row is the last sync;
 * a row carries a pill only when it failed or conflicted.
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
  const t = useTranslations("adminTournament.challonge");
  const tx = useTranslations("adminTournament.challongeExtra");
  const format = useFormatter();
  const queryClient = useQueryClient();

  const { data: logs = [], isLoading } = useQuery({
    queryKey: adminQueryKeys.challongeSyncLog(tournamentId),
    queryFn: () => adminService.challongeSyncLog(tournamentId, 20),
    enabled: hasChallongeSource
  });

  const invalidateSyncLog = () => {
    void queryClient.invalidateQueries({
      queryKey: adminQueryKeys.challongeSyncLog(tournamentId)
    });
  };

  const importMutation = useMutation({
    mutationFn: () => adminService.challongeImport(tournamentId),
    onSuccess: () => {
      invalidateSyncLog();
      void queryClient.invalidateQueries({
        queryKey: adminQueryKeys.tournament(tournamentId)
      });
      invalidateTournamentWorkspace(queryClient, tournamentId);
      notify.success(tx("importStarted"), { description: t("syncSoon") });
    }
  });

  const exportMutation = useMutation({
    mutationFn: () => adminService.challongeExport(tournamentId),
    onSuccess: () => {
      invalidateSyncLog();
      notify.success(tx("exportStarted"), { description: t("syncSoon") });
    }
  });

  const unmappedParticipantIds = getUnmappedParticipantIds(logs);
  // The slug is the settings form's live value, so this tracks an unsaved edit
  // too — which is the honest thing to link: it is the bracket about to be used.
  const bracketUrl = slug.trim() ? `https://challonge.com/${slug.trim()}` : null;
  const teamMappingHref = `/admin/tournaments/${tournamentId}/teams/roster?challongeSync=1`;

  return (
    // A `div`, untitled: the settings page and its group already name this
    // block, and a "Challonge" heading inside them said it a third time.
    <div className="flex flex-col gap-4">
      {/* The only genuinely linkable Challonge target on this card. Sync-log
          rows carry match/participant ids, which have no public URL. */}
      {hasChallongeSource && bracketUrl ? (
        <a
          href={bracketUrl}
          target="_blank"
          rel="noreferrer"
          className="self-end text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          {t("openBracket")}
        </a>
      ) : null}

      <div>
        <Label htmlFor="settings-challonge" className="text-xs">
          {t("urlOrSlug")}
        </Label>
        <Input
          id="settings-challonge"
          placeholder={t("placeholder")}
          value={slug}
          onChange={(event) => onSlugChange(event.target.value)}
          className="mt-1.5"
        />
      </div>

      {/* Absent, not disabled, until there is a source to sync with. */}
      {hasChallongeSource ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={importMutation.isPending}
            onClick={() => importMutation.mutate()}
          >
            {importMutation.isPending ? <Spinner /> : null}
            {importMutation.isPending ? tx("importing") : tx("import")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={exportMutation.isPending}
            onClick={() => exportMutation.mutate()}
          >
            {exportMutation.isPending ? <Spinner /> : null}
            {exportMutation.isPending ? tx("exporting") : tx("export")}
          </Button>
        </div>
      ) : (
        <EmptyNote size="sm">{t("enableSync")}</EmptyNote>
      )}

      {/* The one failure an admin can actually clear from here, lifted out of the
          log: an unmapped participant fails every match it appears in, so the log
          shows the same problem N times with no hint that the fix is a mapping on
          another tab. It blocks the import, hence the one alert. */}
      {hasChallongeSource && unmappedParticipantIds.length > 0 ? (
        <Alert tone="warning">
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>
              {tx.rich("unmappedParticipants", {
                count: unmappedParticipantIds.length,
                num: (chunks) => <span className="tabular-nums">{chunks}</span>
              })}{" "}
              {t("importBlocked")}
            </span>
            <Button asChild type="button" size="sm" variant="outline" className="shrink-0">
              <Link href={teamMappingHref}>{t("mapTeams")}</Link>
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {hasChallongeSource ? (
        <div>
          <p className={`${eyebrowClass("muted")} mb-2`}>{t("syncLog")}</p>

          {isLoading ? (
            <div className="space-y-2" aria-busy>
              {[0, 1, 2].map((index) => (
                <Skeleton key={index} className="h-5 w-full" />
              ))}
            </div>
          ) : logs.length === 0 ? (
            <EmptyNote>{t("emptyLog")}</EmptyNote>
          ) : (
            <ul className="max-h-[260px] divide-y divide-border/50 overflow-y-auto text-xs">
              {logs.map((log) => {
                const entity = ENTITY_TYPES.find((known) => known === log.entity_type);
                return (
                  <li key={log.id} className="flex items-center gap-2 py-2">
                    {/* A word, not a pill: a log of twenty failures would be
                        twenty chips. Success, the norm, says nothing. */}
                    {log.status !== "success" ? (
                      <span
                        className={log.status === "conflict" ? "shrink-0 text-warning" : "shrink-0 text-danger"}
                      >
                        {t(`status.${log.status}`)}
                      </span>
                    ) : null}
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">
                      {[
                        t(`direction.${log.direction}`),
                        `${entity ? t(`entity.${entity}`) : log.entity_type}${log.entity_id ? ` #${log.entity_id}` : ""}`,
                        // Plain text, not a link: a Challonge match/participant id
                        // has no public URL.
                        log.challonge_id ? t("challongeId", { id: String(log.challonge_id) }) : null,
                        log.error_message
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {formatSyncTime(format, log.created_at)}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
