"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { History, Pencil, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { Skeleton } from "@/components/ui/skeleton";
import { EYEBROW_CLASS, type Tone } from "@/components/kit/tone";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { DiscordChannelInput, DiscordChannelRead } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament-workspace-query-keys";
import { EmptyNote } from "@/components/kit/EmptyNote";

const EMPTY_CHANNEL_FORM: DiscordChannelInput = {
  channel_id: "",
  channel_name: "",
  is_active: true
};

interface TournamentDiscordSectionProps {
  tournamentId: number;
  tournament: Tournament;
  canUpdateTournament: boolean;
  discordChannel: DiscordChannelRead | null | undefined;
  discordChannelLoading: boolean;
}

function DetailField({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <p className="mt-1 truncate font-mono text-xs">{value}</p>
    </div>
  );
}

/**
 * The tournament's Discord match-log channel.
 *
 * Was the lower half of one "Integrations" card that also held Challonge; the
 * two are separate settings sections now, because they answer different
 * questions and each one's failure mode is its own. Discord state used to be
 * rendered five times on Overview alone (tile, header icon, header badge, a
 * "Status" detail field and a health row) — Overview shows read-only state,
 * configuration lives here.
 *
 * Every button carries `type="button"`: the section sits next to a settings
 * form, and an unlabelled button submits whatever form it lands in.
 */
export function TournamentDiscordSection({
  tournamentId,
  tournament,
  canUpdateTournament,
  discordChannel,
  discordChannelLoading
}: Readonly<TournamentDiscordSectionProps>) {
  const queryClient = useQueryClient();
  const queryKeys = getTournamentWorkspaceQueryKeys(tournamentId);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [form, setForm] = useState<DiscordChannelInput>(EMPTY_CHANNEL_FORM);
  // Baseline the dialog opened with. Without it the discard prompt fired on
  // every close, including one where nothing had been typed.
  const [openedWith, setOpenedWith] = useState<DiscordChannelInput>(EMPTY_CHANNEL_FORM);
  const [channelMissing, setChannelMissing] = useState(false);

  const saveMutation = useMutation({
    mutationFn: (data: DiscordChannelInput) => adminService.setDiscordChannel(tournamentId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.discordChannel });
      setDialogOpen(false);
      notify.success("Discord channel saved");
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteDiscordChannel(tournamentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.discordChannel });
      setDeleteOpen(false);
      notify.success("Discord channel removed");
    }
  });

  const backfillMutation = useMutation({
    mutationFn: () => adminService.backfillDiscordChannel(tournamentId),
    onSuccess: () => {
      notify.success("Backfill started — scanning channel history for match logs");
    }
  });

  const openDialog = () => {
    const next: DiscordChannelInput = {
      channel_id: discordChannel?.channel_id ?? "",
      channel_name: discordChannel?.channel_name ?? "",
      is_active: discordChannel?.is_active ?? true
    };
    setForm(next);
    setOpenedWith(next);
    setChannelMissing(false);
    saveMutation.reset();
    setDialogOpen(true);
  };

  const tone: Tone = discordChannel?.is_active ? "success" : discordChannel ? "neutral" : "warning";
  const label = discordChannel?.is_active
    ? "Monitoring"
    : discordChannel
      ? "Paused"
      : "Not configured";

  return (
    <>
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className={EYEBROW_CLASS}>Discord match logs</h3>
          <StatusPill tone={tone} className="shrink-0">
            {label}
          </StatusPill>
        </div>
        <p className="text-xs text-muted-foreground">
          Route Discord match logs into this tournament workspace.
        </p>

        {discordChannelLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : discordChannel ? (
          <div className="grid gap-3 rounded-lg border border-border bg-muted/10 p-3 sm:grid-cols-2">
            <DetailField
              label="Channel"
              value={discordChannel.channel_name ? `#${discordChannel.channel_name}` : "Unnamed"}
            />
            <DetailField label="Channel ID" value={discordChannel.channel_id} />
          </div>
        ) : (
          <EmptyNote size="sm">
            No channel yet. Add a channel to start pulling match logs in automatically.
          </EmptyNote>
        )}

        {canUpdateTournament ? (
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={openDialog}>
              <Pencil className="mr-2 size-4" aria-hidden />
              {discordChannel ? "Edit channel" : "Add channel"}
            </Button>
            {discordChannel ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                title="Scans the last 500 messages in the channel for match-log attachments and queues them for parsing. Useful right after connecting a channel that already has logs in it."
                disabled={backfillMutation.isPending}
                onClick={() => backfillMutation.mutate()}
              >
                <History className="mr-2 size-4" aria-hidden />
                {backfillMutation.isPending ? "Importing…" : "Import channel history"}
              </Button>
            ) : null}
            {discordChannel ? (
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => setDeleteOpen(true)}
              >
                <Trash2 className="mr-2 size-4" aria-hidden />
                Remove channel
              </Button>
            ) : null}
          </div>
        ) : null}
      </section>

      <EntityFormDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) saveMutation.reset();
        }}
        title="Discord match logs"
        description={`Set the Discord channel for ${tournament.name}.`}
        onSubmit={(event) => {
          event.preventDefault();
          if (!form.channel_id) {
            setChannelMissing(true);
            return;
          }
          saveMutation.mutate(form);
        }}
        isSubmitting={saveMutation.isPending}
        submittingLabel="Saving…"
        errorMessage={saveMutation.isError ? saveMutation.error.message : undefined}
        isDirty={hasUnsavedChanges(form, openedWith)}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="discord-channel-id">Channel</Label>
            <DiscordChannelSelect
              id="discord-channel-id"
              workspaceId={tournament.workspace_id}
              value={form.channel_id}
              onChange={(channelId) => {
                setChannelMissing(false);
                setForm((current) => ({ ...current, channel_id: channelId }));
              }}
              onChannelNameSelected={(channelName) =>
                setForm((current) => ({ ...current, channel_name: channelName }))
              }
            />
            {channelMissing ? (
              <p className="text-xs font-medium text-destructive" role="alert">
                Pick the channel the bot should read match logs from.
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Channels come from the workspace&apos;s Discord server. Not listed? Switch to
                manual entry and paste the channel ID.
              </p>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="discord-channel-name">Display name (optional)</Label>
            <Input
              id="discord-channel-name"
              value={form.channel_name ?? ""}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  channel_name: event.target.value || null
                }))
              }
              placeholder="#match-logs"
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="discord-is-active"
              checked={form.is_active}
              onCheckedChange={(checked) =>
                setForm((current) => ({ ...current, is_active: Boolean(checked) }))
              }
            />
            <Label htmlFor="discord-is-active">Monitor this channel</Label>
          </div>
        </div>
      </EntityFormDialog>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onConfirm={() => deleteMutation.mutate()}
        pending={deleteMutation.isPending}
        intent={{
          title: "Remove Discord channel",
          description:
            "The bot stops monitoring this channel and match logs will no longer arrive automatically. The tournament and its existing logs are untouched.",
          confirmLabel: deleteMutation.isPending ? "Deleting…" : "Delete",
          tone: "danger"
        }}
      />
    </>
  );
}
