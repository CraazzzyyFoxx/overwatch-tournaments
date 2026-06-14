"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BarChart3,
  CalendarDays,
  CheckCircle,
  CheckCircle2,
  Layers3,
  Pencil,
  ShieldAlert,
  Trash2,
  Users,
  XCircle
} from "lucide-react";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { TournamentFormFields } from "@/components/admin/tournaments/TournamentFormFields";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { hasUnsavedChanges } from "@/lib/form-change";
import { normalizeChallongeSlug } from "@/lib/challonge";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { TournamentUpdateInput } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import {
  formatDate,
  getTournamentForm,
  type TournamentFormState
} from "./tournamentWorkspace.helpers";
import { TournamentStatusControl } from "./TournamentStatusControl";
import { invalidateTournamentWorkspace } from "./tournamentWorkspace.queryKeys";

type MetricCount = number | null;

interface TournamentWorkspaceHeaderProps {
  tournament: Tournament;
  tournamentId: number;
  teamsCount: MetricCount;
  teamsCountLoading: boolean;
  encountersCount: MetricCount;
  encountersCountLoading: boolean;
  standingsCount: MetricCount;
  standingsCountLoading: boolean;
  canReadAnalytics: boolean;
  canUpdateTournament: boolean;
  canDeleteTournament: boolean;
  canToggleFinished: boolean;
  divisionGridVersions: DivisionGridVersion[];
  divisionGridLoading: boolean;
  onEditClick: () => void;
}

function formatMetricCount(value: MetricCount, isLoading: boolean) {
  if (typeof value === "number") {
    return value.toString();
  }

  return isLoading ? "..." : "-";
}

export function TournamentWorkspaceHeader({
  tournament,
  tournamentId,
  teamsCount,
  teamsCountLoading,
  encountersCount,
  encountersCountLoading,
  standingsCount,
  standingsCountLoading,
  canReadAnalytics,
  canUpdateTournament,
  canDeleteTournament,
  canToggleFinished,
  divisionGridVersions,
  divisionGridLoading,
  onEditClick
}: TournamentWorkspaceHeaderProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const toggleFinishedMutation = useMutation({
    mutationFn: () => adminService.toggleTournamentFinished(tournamentId),
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      notify.success("Tournament status updated");
    }
  });

  return (
    <>
      <Card className="border-border/40">
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <CardTitle className="truncate text-lg font-semibold tracking-tight">
                  {tournament.name}
                </CardTitle>
                {tournament.is_finished ? (
                  <StatusIcon icon={CheckCircle} label="Finished" variant="muted" />
                ) : (
                  <StatusIcon icon={XCircle} label="Live ops" variant="success" />
                )}
              </div>
              <CardDescription className="mt-1">
                Manage tournament settings, stages, teams, encounters, and standings in one
                workspace.
              </CardDescription>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <Button asChild variant="outline">
                <Link href="/admin/tournaments">
                  <ArrowLeft className="mr-2 h-4 w-4" />
                  Back to Tournaments
                </Link>
              </Button>
              {canReadAnalytics ? (
                <Button asChild variant="outline">
                  <Link href={`/tournaments/analytics?tournamentId=${tournament.id}`}>
                    <BarChart3 className="mr-2 h-4 w-4" />
                    Open Analytics
                  </Link>
                </Button>
              ) : null}
              {canUpdateTournament ? (
                <Button variant="outline" onClick={onEditClick}>
                  <Pencil className="mr-2 h-4 w-4" />
                  Edit Tournament
                </Button>
              ) : null}
              {canToggleFinished ? (
                <Button
                  onClick={() => toggleFinishedMutation.mutate()}
                  disabled={toggleFinishedMutation.isPending}
                >
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  {tournament.is_finished ? "Reopen Tournament" : "Mark as Finished"}
                </Button>
              ) : null}
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="border-t border-border/40 pt-3">
            {canUpdateTournament ? (
              <div className="mb-3">
                <TournamentStatusControl tournament={tournament} />
              </div>
            ) : null}
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px] text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <ShieldAlert className="size-3.5" />
                {tournament.is_finished ? "Finished" : "Active"} ·{" "}
                {tournament.is_league ? "League" : "Tournament"}
              </span>
              <span className="flex items-center gap-1.5">
                <CalendarDays className="size-3.5" />
                {formatDate(tournament.start_date)} — {formatDate(tournament.end_date)}
              </span>
              <span className="flex items-center gap-1.5">
                <Users className="size-3.5" />
                {formatMetricCount(teamsCount, teamsCountLoading)} teams /{" "}
                {formatMetricCount(tournament.participants_count ?? teamsCount, teamsCountLoading)}{" "}
                participants
              </span>
              <span className="flex items-center gap-1.5">
                <Layers3 className="size-3.5" />
                {tournament.stages.length} stages /{" "}
                {formatMetricCount(encountersCount, encountersCountLoading)} encounters /{" "}
                {formatMetricCount(standingsCount, standingsCountLoading)} standings
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
