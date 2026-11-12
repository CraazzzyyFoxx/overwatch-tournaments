"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { InspectorField } from "@/components/kit/InspectorField";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@craazzzyyfoxx/admin-kit/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { Skeleton } from "@/components/ui/skeleton";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { DiscordChannelInput, DiscordChannelRead } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";

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
  const t = useTranslations("adminTournament.discord");
  const tx = useTranslations("adminTournament.discordExtra");
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
      notify.success(tx("saved"));
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteDiscordChannel(tournamentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.discordChannel });
      setDeleteOpen(false);
      notify.success(tx("removed"));
    }
  });

  const backfillMutation = useMutation({
    mutationFn: () => adminService.backfillDiscordChannel(tournamentId),
    onSuccess: () => {
      notify.success(tx("backfillStarted"));
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

  return (
    <>
      <div className="flex flex-col gap-3">
        {/* Monitoring is the norm and "not configured" is the empty note
            below; only a paused channel wants attention. */}
        {discordChannel && !discordChannel.is_active ? (
          <StatusPill tone="warning" className="self-start">
            {tx("paused")}
          </StatusPill>
        ) : null}

        {discordChannelLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : discordChannel ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <InspectorField label={t("channel")}>
              {discordChannel.channel_name ? `#${discordChannel.channel_name}` : tx("unnamed")}
            </InspectorField>
            <InspectorField label={t("channelId")}>
              <span className="font-mono text-xs">{discordChannel.channel_id}</span>
            </InspectorField>
          </div>
        ) : (
          <EmptyNote size="sm">
            {t("empty")}
          </EmptyNote>
        )}

        {canUpdateTournament ? (
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={openDialog}>
              {discordChannel ? tx("editChannel") : tx("addChannel")}
            </Button>
            {discordChannel ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                title={tx("backfillTitle")}
                disabled={backfillMutation.isPending}
                onClick={() => backfillMutation.mutate()}
              >
                {backfillMutation.isPending ? tx("importing") : tx("importHistory")}
              </Button>
            ) : null}
            {discordChannel ? (
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => setDeleteOpen(true)}
              >
                {t("remove")}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      <EntityFormDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) saveMutation.reset();
        }}
        title={t("title")}
        description={t("setDescription", { name: tournament.name })}
        onSubmit={(event) => {
          event.preventDefault();
          if (!form.channel_id) {
            setChannelMissing(true);
            return;
          }
          saveMutation.mutate(form);
        }}
        isSubmitting={saveMutation.isPending}
        errorMessage={saveMutation.isError ? saveMutation.error.message : undefined}
        isDirty={hasUnsavedChanges(form, openedWith)}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="discord-channel-id">{t("channel")}</Label>
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
                {t("pickChannel")}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                {t("channelHint")}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="discord-channel-name">{t("displayName")}</Label>
            <Input
              id="discord-channel-name"
              value={form.channel_name ?? ""}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  channel_name: event.target.value || null
                }))
              }
              placeholder={tx("displayNamePlaceholder")}
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
            <Label htmlFor="discord-is-active">{t("monitor")}</Label>
          </div>
        </div>
      </EntityFormDialog>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onConfirm={() => deleteMutation.mutate()}
        pending={deleteMutation.isPending}
        intent={{
          title: t("removeTitle"),
          description: t("removeDescription"),
          confirmLabel: deleteMutation.isPending ? tx("deleting") : tx("delete"),
          tone: "danger"
        }}
      />
    </>
  );
}
