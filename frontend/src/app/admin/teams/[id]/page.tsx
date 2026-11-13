"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDateRange } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";

import { InlineEditText } from "@/components/kit/InlineEditText";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { EntityHubHeader } from "@/components/kit/EntityHubHeader";
import { SettingGroup } from "@/components/kit/SettingRow";
import { TeamRosterEditor } from "@/components/admin/teams/TeamRosterEditor";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@craazzzyyfoxx/admin-kit/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@craazzzyyfoxx/admin-kit/ui/select";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useEntityWorkspace } from "@/hooks/useEntityWorkspace";
import { MAX_AVATAR_BYTES } from "@/lib/uploads";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Player, Team } from "@/types/team.types";
import type { Tournament } from "@/types/tournament.types";
import type { User } from "@/types/user.types";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

type AdminTeamDetail = Team & {
  captain?: User | null;
  tournament?: Tournament | null;
  players: Player[];
};

/** Roster members eligible to captain the team, deduplicated by linked user. */
function buildCaptainOptions(team: AdminTeamDetail, offRosterLabel: (captain: User | null | undefined, id: number) => string) {
  const options = new Map<number, string>();

  for (const player of team.players ?? []) {
    if (player.user_id > 0 && !options.has(player.user_id)) {
      options.set(player.user_id, player.user?.name ?? player.name);
    }
  }

  // A captain inherited from before this rule existed may sit outside the roster.
  // Keep them selectable so the field shows who it actually is.
  if (team.captain_id > 0 && !options.has(team.captain_id)) {
    options.set(team.captain_id, offRosterLabel(team.captain, team.captain_id));
  }

  return Array.from(options, ([userId, label]) => ({ userId, label }));
}

/**
 * The team page is the team editor.
 *
 * Name, captain and every roster row are edited here and persist on change, so
 * opening a team lands directly on the thing an operator came to change instead
 * of a read-only summary behind an "Edit" dialog.
 */
export default function AdminTeamWorkspacePage() {
  const t = useTranslations("adminPeople.teams");
  const format = useFormatter();
  const params = useParams<{ id: string }>();
  const teamId = Number(params.id);
  const router = useRouter();
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const [deleteOpen, setDeleteOpen] = useState(false);

  const teamQuery = useQuery({
    queryKey: adminQueryKeys.team(teamId),
    queryFn: () => adminService.getTeam(teamId) as Promise<AdminTeamDetail>,
    enabled: Number.isFinite(teamId)
  });

  const team = teamQuery.data;
  const workspaceId = team?.tournament?.workspace_id ?? null;
  useEntityWorkspace(workspaceId);
  const canUpdateTeam = canAccessPermission("team.update", workspaceId);
  const canDeleteTeam = canAccessPermission("team.delete", workspaceId);
  const canCreatePlayer = canAccessPermission("player.create", workspaceId);
  const canUpdatePlayer = canAccessPermission("player.update", workspaceId);
  const canDeletePlayer = canAccessPermission("player.delete", workspaceId);

  const captainOptions = useMemo(
    () =>
      team
        ? buildCaptainOptions(team, (captain, id) =>
            t("captainOffRoster", { name: captain?.name ?? t("userId", { id }) })
          )
        : [],
    [team, t]
  );

  const invalidateTeam = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.team(teamId) }),
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.teamsAll() })
    ]);

  const updateTeam = useMutation({
    mutationFn: (payload: { name?: string; captain_id?: number }) =>
      adminService.updateTeam(teamId, payload),
    onSuccess: invalidateTeam
  });

  const uploadImage = useMutation({
    mutationFn: (file: File) => adminService.uploadTeamImage(teamId, file),
    onSuccess: async () => {
      await invalidateTeam();
      notify.success(t("imageUpdated"));
    },
    onError: (error) => notify.apiError(error)
  });

  const deleteImage = useMutation({
    mutationFn: () => adminService.deleteTeamImage(teamId),
    onSuccess: async () => {
      await invalidateTeam();
      notify.success(t("imageRemoved"));
    },
    onError: (error) => notify.apiError(error)
  });

  const deleteTeam = useMutation({
    mutationFn: () => adminService.deleteTeam(teamId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.teamsAll() });
      router.push(
        team?.tournament_id ? `/admin/teams?tournament=${team.tournament_id}` : "/admin/teams"
      );
    }
  });

  if (teamQuery.isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    );
  }

  if (teamQuery.isError) {
    return <PageStateCard state="error" headingLevel={1} onAction={() => void teamQuery.refetch()} />;
  }

  if (!team) {
    return (
      <Card>
        <CardHeader>
          <CardTitle asChild>
            <h1>{t("notFound")}</h1>
          </CardTitle>
          <CardDescription>
            {t.rich("deletedNotice", {
              link: (chunks) => (
                <Link href="/admin/teams" className="underline">
                  {chunks}
                </Link>
              )
            })}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <EntityHubHeader
        leading={
          <EditableAvatar
            src={team.image_url}
            name={team.name}
            size={40}
            shape="rounded"
            editable={canUpdateTeam}
            busy={uploadImage.isPending || deleteImage.isPending}
            onSelectFile={(file) => uploadImage.mutate(file)}
            onDelete={team.image_url ? () => deleteImage.mutate() : undefined}
            maxSizeBytes={MAX_AVATAR_BYTES}
            onError={(message) => notify.error(message)}
          />
        }
        // The `<h1>` is the editable name itself: the page is the team
        // editor, so a read-only heading beside an edit field would print
        // the same name twice.
        title={
          <InlineEditText
            value={team.name}
            label={t("teamName")}
            canEdit={canUpdateTeam}
            onSave={(name) => updateTeam.mutateAsync({ name })}
          />
        }
        status={team.captain_id > 0 ? undefined : { label: t("noCaptain"), tone: "warning" }}
        meta={[
          team.tournament?.name ?? t("noTournament"),
          team.tournament ? (
            <span className="tabular-nums">
              {formatDateRange(format, team.tournament.start_date, team.tournament.end_date)}
            </span>
          ) : null,
          <span key="avg" className="tabular-nums">{t("avgSrMeta", { value: team.avg_sr.toFixed(0) })}</span>,
          <span key="total" className="tabular-nums">{t("totalSrMeta", { value: team.total_sr })}</span>,
          team.group?.name ?? null,
          team.placement != null ? (
            <span key="placement" className="tabular-nums">{t("placement", { id: team.placement })}</span>
          ) : null
        ]}
        backHref={
          team.tournament_id ? `/admin/teams?tournament=${team.tournament_id}` : "/admin/teams"
        }
        actions={
          <>
            {team.tournament ? (
              <Button asChild variant="outline" size="sm">
                <Link href={`/admin/tournaments/${team.tournament.id}`}>{t("openTournament")}</Link>
              </Button>
            ) : null}
            {canDeleteTeam ? (
              <Button
                variant="outline"
                size="sm"
                className="text-destructive"
                onClick={() => setDeleteOpen(true)}
              >
                {t("delete")}
              </Button>
            ) : null}
          </>
        }
      />

      <SettingGroup
        id="roster"
        title={t("labels.roster")}
        description={t("rosterDescription")}
        actions={
          <div className="flex items-center gap-2">
            <Label htmlFor="team-captain" className="text-sm text-muted-foreground">
              {t("labels.captain")}
            </Label>
            <Select
              value={team.captain_id > 0 ? String(team.captain_id) : ""}
              disabled={!canUpdateTeam || captainOptions.length === 0}
              onValueChange={(value) =>
                updateTeam.mutate({ captain_id: Number.parseInt(value, 10) })
              }
            >
              <SelectTrigger id="team-captain" size="sm" className="w-56">
                <SelectValue placeholder={t("captainPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {captainOptions.map((option) => (
                  <SelectItem key={option.userId} value={String(option.userId)}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        }
        flush
      >
        <TeamRosterEditor
          teamId={team.id}
          tournamentId={team.tournament_id}
          workspaceId={workspaceId}
          discipline={team.tournament?.discipline ?? null}
          players={team.players ?? []}
          divisionGrid={team.tournament?.division_grid_version ?? null}
          canCreatePlayer={canCreatePlayer}
          canUpdatePlayer={canUpdatePlayer}
          canDeletePlayer={canDeletePlayer}
        />
      </SettingGroup>

      {canDeleteTeam ? (
        <ConfirmDialog
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          pending={deleteTeam.isPending}
          intent={{
            title: t("deleteNamed", { name: team.name }),
            description: t("deleteDescription", { name: team.name }),
            confirmLabel: t("delete"),
            tone: "danger",
            cascade: [t("cascadePlayers"), t("cascadeStats")]
          }}
          onConfirm={() => deleteTeam.mutate()}
        />
      ) : null}
    </div>
  );
}
