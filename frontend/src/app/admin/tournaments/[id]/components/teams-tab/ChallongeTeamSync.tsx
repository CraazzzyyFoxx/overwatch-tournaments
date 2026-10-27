"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";

import type { TableCommand } from "@/components/data-table";
import { adminDetailTableStyles as tableStyles } from "@/components/admin/AdminDetailTable";
import { WizardShell } from "@/components/kit/WizardShell";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type {
  ChallongeTeamMapping,
  ChallongeTeamPreviewParticipant
} from "@/types/admin.types";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { ChallongeTeamPicker } from "./ChallongeTeamPicker";
import { UNMAPPED_TEAM_VALUE, getChallongeParticipantKey } from "./model";

/**
 * The Teams tab's "Sync teams" command and the Challonge mapping dialog it
 * opens. The dialog is returned even when the command is hidden:
 * `?challongeSync=1` opens it regardless of `canImportTeams`.
 */
export function useChallongeTeamSync({
  tournamentId,
  hasChallongeSource,
  canImportTeams
}: Readonly<{
  tournamentId: number;
  hasChallongeSource: boolean;
  canImportTeams: boolean;
}>): { command: TableCommand; dialog: ReactNode } {
  const t = useTranslations("adminTournament.teams");
  const tx = useTranslations("adminTournament.teamsExtra");
  const queryClient = useQueryClient();

  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // `?challongeSync=1` exists so the Integrations card can send an admin straight
  // to the mapping table that clears its "N participants not mapped" failure —
  // otherwise the error is on one tab and its only fix on another. Read once for
  // the initial value and stripped on mount: with the param left in place a
  // refresh (or a Back into this page) would reopen a dialog nobody asked for.
  const [challongeSyncDialogOpen, setChallongeSyncDialogOpen] = useState(
    () => searchParams.get("challongeSync") === "1"
  );
  const [challongeMappingDraft, setChallongeMappingDraft] = useState<Record<string, string>>({});
  const [challongeSyncStep, setChallongeSyncStep] = useState<"map" | "confirm">("map");

  useEffect(() => {
    if (searchParams.get("challongeSync") !== "1") {
      return;
    }
    const next = new URLSearchParams(searchParams);
    next.delete("challongeSync");
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  const { data: challongePreview, isLoading: isChallongePreviewLoading } = useQuery({
    queryKey: adminQueryKeys.challongeTeamSyncPreview(tournamentId),
    queryFn: () => adminService.getChallongeTeamSyncPreview(tournamentId),
    enabled: challongeSyncDialogOpen && hasChallongeSource
  });

  const syncTeamsMutation = useMutation({
    mutationFn: (mappings: ChallongeTeamMapping[]) =>
      adminService.syncTeamsFromChallonge(tournamentId, { mappings }),
    onSuccess: ({ created, updated, unchanged, skipped }) => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      setChallongeSyncDialogOpen(false);
      notify.success(tx("syncSuccess"), {
        description: (
          <span className="tabular-nums">
            {t("syncSummary", { created, updated, unchanged, skipped })}
          </span>
        )
      });
    }
  });

  const challongeParticipants = useMemo(
    () => challongePreview?.participants ?? [],
    [challongePreview?.participants]
  );
  const challongeTeamOptions = useMemo(
    () => challongePreview?.teams ?? [],
    [challongePreview?.teams]
  );
  const challongeTeamsById = useMemo(
    () => new Map(challongeTeamOptions.map((team) => [team.id, team])),
    [challongeTeamOptions]
  );
  const getChallongeMappingValue = (participant: ChallongeTeamPreviewParticipant) =>
    challongeMappingDraft[getChallongeParticipantKey(participant)] ??
    (participant.mapped_team_id != null ? String(participant.mapped_team_id) : UNMAPPED_TEAM_VALUE);
  const activeUnmappedParticipants = challongeParticipants.filter(
    (participant) =>
      participant.active && getChallongeMappingValue(participant) === UNMAPPED_TEAM_VALUE
  );
  const selectedChallongeMappings = challongeParticipants.flatMap((participant) => {
    const value = getChallongeMappingValue(participant);
    if (!value || value === UNMAPPED_TEAM_VALUE) {
      return [];
    }

    const teamId = Number.parseInt(value, 10);
    if (Number.isNaN(teamId)) {
      return [];
    }

    return [
      {
        participant_id: participant.participant_id,
        group_id: participant.group_id,
        team_id: teamId
      }
    ];
  });
  const canSubmitChallongeMappings =
    !isChallongePreviewLoading &&
    challongeParticipants.length > 0 &&
    selectedChallongeMappings.length > 0 &&
    activeUnmappedParticipants.length === 0;

  // The confirm step reads back what will be written, so it needs the names
  // behind the ids the request carries.
  const onConfirmStep = challongeSyncStep === "confirm";
  const confirmedChallongeRows = challongeParticipants.flatMap((participant) => {
    const value = getChallongeMappingValue(participant);
    const team = value === UNMAPPED_TEAM_VALUE ? undefined : challongeTeamsById.get(Number(value));
    return team
      ? [
          {
            key: getChallongeParticipantKey(participant),
            participant: participant.name,
            team: team.name,
            group: participant.group_name ?? tx("mainGroup")
          }
        ]
      : [];
  });

  const openChallongeSyncDialog = () => {
    syncTeamsMutation.reset();
    setChallongeMappingDraft({});
    setChallongeSyncStep("map");
    setChallongeSyncDialogOpen(true);
  };

  const closeChallongeSyncDialog = () => {
    if (syncTeamsMutation.isPending) {
      return;
    }

    setChallongeSyncDialogOpen(false);
    setChallongeMappingDraft({});
    setChallongeSyncStep("map");
  };

  const applyChallongeSuggestions = () => {
    setChallongeMappingDraft((current) => {
      const next = { ...current };
      for (const participant of challongeParticipants) {
        if (participant.suggested_team_id != null) {
          next[getChallongeParticipantKey(participant)] = String(participant.suggested_team_id);
        }
      }
      return next;
    });
  };

  const submitChallongeMappings = () => {
    if (!canSubmitChallongeMappings) {
      notify.error(tx("mappingsIncomplete"), {
        description: tx("mappingsIncompleteDescription", { count: activeUnmappedParticipants.length })
      });
      return;
    }

    syncTeamsMutation.mutate(selectedChallongeMappings);
  };

  const command: TableCommand = {
    id: "challonge-sync",
    label: t("sync"),
    onSelect: openChallongeSyncDialog,
    hidden: !(canImportTeams && hasChallongeSource),
    disabled: syncTeamsMutation.isPending
  };

  const dialog = (
    <Dialog
      open={challongeSyncDialogOpen}
      onOpenChange={(open) => {
        if (open) {
          setChallongeSyncDialogOpen(true);
        } else {
          closeChallongeSyncDialog();
        }
      }}
    >
      <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto" aria-describedby={undefined}>
        <DialogHeader className="border-b border-border/60 pb-4">
          <DialogTitle>{t("syncChallonge")}</DialogTitle>
        </DialogHeader>

        {/* Two steps rather than one long table with a Sync button at the
            bottom: the mapping is destructive on the internal teams, and the
            confirm step is where the admin reads back what will be written
            instead of re-scanning the picker column they just filled in. */}
        <WizardShell
          steps={[
            { key: "map", label: t("mapParticipants"), state: onConfirmStep ? "done" : "current" },
            { key: "confirm", label: t("confirm"), state: onConfirmStep ? "current" : "todo" }
          ]}
          footer={{
            back: onConfirmStep ? () => setChallongeSyncStep("map") : undefined,
            next: onConfirmStep
              ? {
                  label: syncTeamsMutation.isPending ? tx("syncing") : tx("syncMappings"),
                  onClick: submitChallongeMappings,
                  disabled: !canSubmitChallongeMappings || syncTeamsMutation.isPending
                }
              : {
                  label: t("continue"),
                  onClick: () => setChallongeSyncStep("confirm"),
                  disabled: !canSubmitChallongeMappings
                },
            secondary: (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={closeChallongeSyncDialog}
                disabled={syncTeamsMutation.isPending}
              >
                {t("cancel")}
              </Button>
            )
          }}
        >
          {onConfirmStep ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {tx("mappingSummary", { selected: selectedChallongeMappings.length, total: challongeParticipants.length })}
              </p>
              <ul className="divide-y divide-border/60">
                {confirmedChallongeRows.map((row) => (
                  <li
                    key={row.key}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 flex-1 truncate" title={row.participant}>
                      {row.participant}
                    </span>
                    <ArrowRight
                      className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate font-medium" title={row.team}>
                      {row.team}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {row.group}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs tabular-nums text-muted-foreground">
                  {t.rich("participantsSummary", {
                    participants: challongeParticipants.length,
                    unmapped: activeUnmappedParticipants.length,
                    warn: (chunks) => (
                      <span className={activeUnmappedParticipants.length > 0 ? "text-warning" : undefined}>
                        {chunks}
                      </span>
                    )
                  })}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={applyChallongeSuggestions}
                  disabled={
                    isChallongePreviewLoading ||
                    !challongeParticipants.some(
                      (participant) => participant.suggested_team_id != null
                    )
                  }
                >
                  {t("apply")}
                </Button>
              </div>

              <div className="max-h-[52vh] overflow-auto rounded-md border border-border/60">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className={tableStyles.head}>{tx("participant")}</TableHead>
                      <TableHead className={tableStyles.head}>{t("group")}</TableHead>
                      <TableHead className={tableStyles.head}>{t("current")}</TableHead>
                      <TableHead className={tableStyles.head}>{t("suggestion")}</TableHead>
                      <TableHead className={tableStyles.head}>{t("internalTeam")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {isChallongePreviewLoading ? (
                      [0, 1, 2].map((index) => (
                        <TableRow key={index} className={tableStyles.row}>
                          <TableCell className={tableStyles.cell} colSpan={5}>
                            <Skeleton className="h-8 w-full" />
                          </TableCell>
                        </TableRow>
                      ))
                    ) : challongeParticipants.length ? (
                      challongeParticipants.map((participant) => {
                        const participantKey = getChallongeParticipantKey(participant);
                        const currentTeam =
                          participant.mapped_team_id != null
                            ? challongeTeamsById.get(participant.mapped_team_id)
                            : undefined;
                        const suggestedTeam =
                          participant.suggested_team_id != null
                            ? challongeTeamsById.get(participant.suggested_team_id)
                            : undefined;

                        return (
                          <TableRow key={participantKey} className={tableStyles.row}>
                            <TableCell className={tableStyles.cell}>
                              <div className="min-w-0">
                                <div className="truncate font-medium" title={participant.name}>
                                  {participant.name}
                                </div>
                                <div className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                                  {tx("participantNumber", {
                                    id: participant.participant_id,
                                    challongeId: participant.challonge_id
                                  })}
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className={tableStyles.cell}>
                              {participant.group_name ?? tx("mainGroup")}
                            </TableCell>
                            <TableCell className={tableStyles.cell}>
                              {currentTeam ? (
                                <span className="truncate" title={currentTeam.name}>
                                  {currentTeam.name}
                                </span>
                              ) : (
                                <span className="text-muted-foreground">{t("unmapped")}</span>
                              )}
                            </TableCell>
                            <TableCell className={tableStyles.cell}>
                              {suggestedTeam ? (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 max-w-[180px] justify-start px-2"
                                  aria-label={t("mapAria", { participant: participant.name, team: suggestedTeam.name })}
                                  onClick={() =>
                                    setChallongeMappingDraft((current) => ({
                                      ...current,
                                      [participantKey]: String(suggestedTeam.id)
                                    }))
                                  }
                                >
                                  <span className="truncate">{suggestedTeam.name}</span>
                                </Button>
                              ) : null}
                            </TableCell>
                            <TableCell className={tableStyles.cell}>
                              <ChallongeTeamPicker
                                participant={participant}
                                teams={challongeTeamOptions}
                                value={getChallongeMappingValue(participant)}
                                onChange={(next) =>
                                  setChallongeMappingDraft((current) => ({
                                    ...current,
                                    [participantKey]: next
                                  }))
                                }
                              />
                            </TableCell>
                          </TableRow>
                        );
                      })
                    ) : (
                      <TableRow className={tableStyles.row}>
                        <TableCell className={tableStyles.cell} colSpan={5}>
                          <div className="py-4 text-sm text-muted-foreground">
                            {t("noParticipants")}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </WizardShell>
      </DialogContent>
    </Dialog>
  );

  return { command, dialog };
}
