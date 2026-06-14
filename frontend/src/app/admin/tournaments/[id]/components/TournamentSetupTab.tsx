"use client";

import { useState, type ElementType } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  GitBranch,
  Link2,
  MessageSquare,
  Pencil,
  RefreshCw,
  Trash2,
  Wifi,
  WifiOff,
  XCircle
} from "lucide-react";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { DiscordChannelInput, DiscordChannelRead } from "@/types/admin.types";
import type { Stage, Tournament } from "@/types/tournament.types";
import { ChallongeSyncPanel } from "./ChallongeSyncPanel";
import { StageManager } from "./StageManager";
import { getTournamentWorkspaceQueryKeys } from "./tournamentWorkspace.queryKeys";

interface TournamentSetupTabProps {
  tournamentId: number;
  tournament: Tournament;
  stages: Stage[];
  hasChallongeSource: boolean;
  canUpdateTournament: boolean;
  discordChannel: DiscordChannelRead | null | undefined;
  discordChannelLoading: boolean;
}

type StatusTone = "ready" | "warning" | "muted";

interface SetupStatusTileProps {
  title: string;
  value: string;
  detail: string;
  tone: StatusTone;
  icon: ElementType;
}

function getStatusToneClass(tone: StatusTone) {
  if (tone === "ready") return "border-primary/40 bg-primary/10 text-primary";
  if (tone === "warning") return "border-amber-700/50 bg-amber-950/20 text-amber-200";
  return "border-border/60 bg-muted/10 text-muted-foreground";
}

function SetupStatusTile({ title, value, detail, tone, icon: Icon }: SetupStatusTileProps) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/70 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {title}
          </p>
          <p className="mt-2 truncate text-lg font-semibold">{value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
        </div>
        <span className={cn("rounded-lg border p-2", getStatusToneClass(tone))}>
          <Icon className="size-4" />
        </span>
      </div>
    </div>
  );
}

function HealthRow({ label, value, tone }: { label: string; value: string; tone: StatusTone }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/50 py-2 last:border-b-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <Badge variant="outline" className={cn("shrink-0", getStatusToneClass(tone))}>
        {value}
      </Badge>
    </div>
  );
}

export function TournamentSetupTab({
  tournamentId,
  tournament,
  stages,
  hasChallongeSource,
  canUpdateTournament,
  discordChannel,
  discordChannelLoading
}: TournamentSetupTabProps) {
  const queryClient = useQueryClient();
  const queryKeys = getTournamentWorkspaceQueryKeys(tournamentId);

  const [discordChannelDialogOpen, setDiscordChannelDialogOpen] = useState(false);
  const [discordChannelDeleteOpen, setDiscordChannelDeleteOpen] = useState(false);
  const [discordChannelForm, setDiscordChannelForm] = useState<DiscordChannelInput>({
    guild_id: "",
    channel_id: "",
    channel_name: "",
    is_active: true
  });

  const saveDiscordChannelMutation = useMutation({
    mutationFn: (data: DiscordChannelInput) => adminService.setDiscordChannel(tournamentId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.discordChannel });
      setDiscordChannelDialogOpen(false);
      notify.success("Discord channel configured");
    }
  });

  const deleteDiscordChannelMutation = useMutation({
    mutationFn: () => adminService.deleteDiscordChannel(tournamentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.discordChannel });
      setDiscordChannelDeleteOpen(false);
      notify.success("Discord channel removed");
    }
  });

  const openDiscordDialog = () => {
    setDiscordChannelForm({
      guild_id: discordChannel?.guild_id ?? "",
      channel_id: discordChannel?.channel_id ?? "",
      channel_name: discordChannel?.channel_name ?? "",
      is_active: discordChannel?.is_active ?? true
    });
    saveDiscordChannelMutation.reset();
    setDiscordChannelDialogOpen(true);
  };

  const linkedStagesCount = stages.filter((stage) => Boolean(stage.challonge_slug)).length;
  const activeStagesCount = stages.filter((stage) => stage.is_active).length;
  const completedStagesCount = stages.filter((stage) => stage.is_completed).length;
  const structuredStagesCount = stages.filter((stage) => stage.items.length > 0).length;
  const setupWarnings = [
    stages.length === 0 ? "No stages configured" : null,
    hasChallongeSource ? null : "No Challonge link",
    discordChannel ? null : "No Discord channel",
    stages.length > 0 && structuredStagesCount < stages.length
      ? "Some stages have no structure"
      : null
  ].filter((warning): warning is string => Boolean(warning));

  return (
    <>
      <div className="flex flex-col gap-4">
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
          <SetupStatusTile
            title="Stages"
            value={stages.length === 0 ? "Not started" : `${stages.length} configured`}
            detail={`${activeStagesCount} active, ${completedStagesCount} completed`}
            tone={stages.length > 0 ? "ready" : "warning"}
            icon={GitBranch}
          />
          <SetupStatusTile
            title="Challonge"
            value={hasChallongeSource ? "Connected" : "Not linked"}
            detail={`${linkedStagesCount} linked stage${linkedStagesCount === 1 ? "" : "s"}`}
            tone={hasChallongeSource ? "ready" : "warning"}
            icon={Link2}
          />
          <SetupStatusTile
            title="Discord"
            value={
              discordChannelLoading
                ? "Checking"
                : discordChannel
                  ? discordChannel.is_active
                    ? "Monitoring"
                    : "Paused"
                  : "Not configured"
            }
            detail={discordChannel?.channel_name ?? "Match log channel"}
            tone={discordChannel?.is_active ? "ready" : discordChannel ? "muted" : "warning"}
            icon={MessageSquare}
          />
          <SetupStatusTile
            title="Setup Health"
            value={setupWarnings.length === 0 ? "Ready" : `${setupWarnings.length} warning(s)`}
            detail={setupWarnings[0] ?? "Core setup is configured"}
            tone={setupWarnings.length === 0 ? "ready" : "warning"}
            icon={setupWarnings.length === 0 ? CheckCircle2 : AlertTriangle}
          />
        </div>

        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
          <StageManager tournamentId={tournamentId} />

          <div className="flex min-w-0 flex-col gap-4">
            <ChallongeSyncPanel
              tournamentId={tournamentId}
              hasChallongeSource={hasChallongeSource}
            />

            <Card className="border-border/40">
              <CardHeader className="gap-3 pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      {discordChannel?.is_active ? (
                        <Wifi className="size-4 text-primary" />
                      ) : discordChannel ? (
                        <WifiOff className="size-4 text-muted-foreground" />
                      ) : (
                        <XCircle className="size-4 text-muted-foreground" />
                      )}
                      <CardTitle className="text-sm font-semibold">Discord Sync</CardTitle>
                    </div>
                    <CardDescription className="mt-1 text-xs">
                      Route Discord match logs into this tournament workspace.
                    </CardDescription>
                  </div>
                  <Badge
                    variant="outline"
                    className={cn(
                      discordChannel?.is_active
                        ? "border-primary/40 bg-primary/10 text-primary"
                        : "border-border/70 text-muted-foreground"
                    )}
                  >
                    {discordChannel?.is_active
                      ? "Active"
                      : discordChannel
                        ? "Inactive"
                        : "Not configured"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {discordChannelLoading ? (
                  <Skeleton className="h-24 w-full" />
                ) : discordChannel ? (
                  <div className="grid gap-3 rounded-lg border border-border/60 bg-muted/10 p-3 text-[13px] sm:grid-cols-2">
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                        Guild
                      </p>
                      <p className="mt-1 truncate font-mono text-[12px]">
                        {discordChannel.guild_id}
                      </p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                        Channel
                      </p>
                      <p className="mt-1 truncate font-mono text-[12px]">
                        {discordChannel.channel_id}
                      </p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                        Name
                      </p>
                      <p className="mt-1 truncate">{discordChannel.channel_name ?? "-"}</p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                        Status
                      </p>
                      <div className="mt-1">
                        {discordChannel.is_active ? (
                          <StatusIcon icon={Wifi} label="Active" variant="success" />
                        ) : (
                          <StatusIcon icon={WifiOff} label="Inactive" variant="muted" />
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-border/70 bg-muted/10 p-3 text-sm text-muted-foreground">
                    No Discord channel configured. Set a guild and channel to enable automatic log
                    intake.
                  </div>
                )}

                {canUpdateTournament ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Button variant="outline" size="sm" onClick={openDiscordDialog}>
                      <Pencil className="size-4" />
                      {discordChannel ? "Edit Channel" : "Configure"}
                    </Button>
                    {discordChannel ? (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setDiscordChannelDeleteOpen(true)}
                      >
                        <Trash2 className="size-4" />
                        Remove
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <Card className="border-border/40">
              <CardHeader className="gap-1 pb-3">
                <div className="flex items-center gap-2">
                  <RefreshCw className="size-4 text-primary" />
                  <CardTitle className="text-sm font-semibold">Setup Health</CardTitle>
                </div>
                <CardDescription className="text-xs">
                  Fast scan of what still needs attention before match operations.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="rounded-lg border border-border/60 bg-muted/10 px-3">
                  <HealthRow
                    label="Stage flow"
                    value={stages.length > 0 ? `${stages.length} total` : "Missing"}
                    tone={stages.length > 0 ? "ready" : "warning"}
                  />
                  <HealthRow
                    label="Stage structure"
                    value={
                      stages.length === 0
                        ? "No stages"
                        : `${structuredStagesCount}/${stages.length} ready`
                    }
                    tone={
                      structuredStagesCount === stages.length && stages.length > 0
                        ? "ready"
                        : "warning"
                    }
                  />
                  <HealthRow
                    label="Challonge source"
                    value={hasChallongeSource ? "Linked" : "Manual only"}
                    tone={hasChallongeSource ? "ready" : "warning"}
                  />
                  <HealthRow
                    label="Discord logs"
                    value={
                      discordChannel?.is_active ? "Monitoring" : discordChannel ? "Paused" : "Off"
                    }
                    tone={
                      discordChannel?.is_active ? "ready" : discordChannel ? "muted" : "warning"
                    }
                  />
                </div>

                {setupWarnings.length > 0 ? (
                  <div className="mt-3 rounded-lg border border-amber-700/40 bg-amber-950/10 p-3">
                    <div className="mb-2 flex items-center gap-2 text-sm font-medium text-amber-200">
                      <AlertTriangle className="size-4" />
                      Needs attention
                    </div>
                    <ul className="flex list-disc flex-col gap-1 pl-5 text-xs text-muted-foreground">
                      {setupWarnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      <EntityFormDialog
        open={discordChannelDialogOpen}
        onOpenChange={(open) => {
          setDiscordChannelDialogOpen(open);
          if (!open) saveDiscordChannelMutation.reset();
        }}
        title="Configure Discord Sync Channel"
        description={`Set the Discord guild and channel for ${tournament.name}.`}
        onSubmit={(event) => {
          event.preventDefault();
          saveDiscordChannelMutation.mutate(discordChannelForm);
        }}
        isSubmitting={saveDiscordChannelMutation.isPending}
        submittingLabel="Saving..."
        errorMessage={
          saveDiscordChannelMutation.isError ? saveDiscordChannelMutation.error.message : undefined
        }
        isDirty
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="discord-guild-id">Guild ID</Label>
            <Input
              id="discord-guild-id"
              type="text"
              inputMode="numeric"
              value={discordChannelForm.guild_id}
              onChange={(event) =>
                setDiscordChannelForm((current) => ({
                  ...current,
                  guild_id: event.target.value.replace(/\D/g, "")
                }))
              }
              placeholder="e.g. 123456789012345678"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="discord-channel-id">Channel ID</Label>
            <Input
              id="discord-channel-id"
              type="text"
              inputMode="numeric"
              value={discordChannelForm.channel_id}
              onChange={(event) =>
                setDiscordChannelForm((current) => ({
                  ...current,
                  channel_id: event.target.value.replace(/\D/g, "")
                }))
              }
              placeholder="e.g. 987654321098765432"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="discord-channel-name">Channel Name (optional)</Label>
            <Input
              id="discord-channel-name"
              value={discordChannelForm.channel_name ?? ""}
              onChange={(event) =>
                setDiscordChannelForm((current) => ({
                  ...current,
                  channel_name: event.target.value || null
                }))
              }
              placeholder="e.g. #match-logs"
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="discord-is-active"
              checked={discordChannelForm.is_active}
              onCheckedChange={(checked) =>
                setDiscordChannelForm((current) => ({ ...current, is_active: Boolean(checked) }))
              }
            />
            <Label htmlFor="discord-is-active">Active (bot will monitor this channel)</Label>
          </div>
        </div>
      </EntityFormDialog>

      <DeleteConfirmDialog
        open={discordChannelDeleteOpen}
        onOpenChange={setDiscordChannelDeleteOpen}
        onConfirm={() => deleteDiscordChannelMutation.mutate()}
        title="Remove Discord Channel"
        description="Remove the Discord sync channel configuration for this tournament? The bot will stop monitoring this channel."
        isDeleting={deleteDiscordChannelMutation.isPending}
      />
    </>
  );
}
