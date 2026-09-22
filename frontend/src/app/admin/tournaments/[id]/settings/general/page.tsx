"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Card, CardContent } from "@/components/ui/card";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AuditTrailButton } from "@/components/kit/AuditTrailSheet";
import { SaveBar } from "@/components/kit/SaveBar";
import { MAX_AVATAR_BYTES } from "@/lib/uploads";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Tournament, TournamentImageSlot } from "@/types/tournament.types";
import { flattenDivisionGridVersions, useHubDivisionGridsQuery } from "../../hubQueries";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";

export default function GeneralSettingsPage() {
  return (
    <SettingsSectionPage
      section="general"
      description="How this tournament is named and described, how teams form, and which division grid seeds them."
    >
      {({ tournament, tournamentId, workspaceId, canUpdateTournament }) => (
        <GeneralForm
          tournament={tournament}
          tournamentId={tournamentId}
          workspaceId={workspaceId}
          disabled={!canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

function GeneralForm({
  tournament,
  tournamentId,
  workspaceId,
  disabled
}: Readonly<{
  tournament: Tournament;
  tournamentId: number;
  workspaceId: number;
  disabled: boolean;
}>) {
  const { form, patch, dirty, summary, saving, save, discard } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "general"
  );
  // Only this section reads the grid list, which is why the hub shell does not
  // fetch it on every tab load.
  const gridsQuery = useHubDivisionGridsQuery(tournamentId, workspaceId);
  const versions = flattenDivisionGridVersions(gridsQuery.data);

  return (
    <>
      {/* The audit trail is a drawer the whole admin shares, not a settings
          section of its own: it answers "who changed this" about every entity
          of the tournament, and General is the page the rail lands on. */}
      <div className="flex justify-end">
        <AuditTrailButton
          scope={{
            entityType: "tournament",
            entityId: tournamentId,
            workspaceId: tournament.workspace_id
          }}
          target={`tournament “${tournament.name}”`}
          showCount
        />
      </div>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-6">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="settings-name">Tournament name</Label>
            <Input
              id="settings-name"
              value={form.name}
              disabled={disabled}
              onChange={(event) => patch({ name: event.target.value })}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="settings-slug">Public URL slug</Label>
            <Input
              id="settings-slug"
              value={form.slug}
              disabled={disabled}
              onChange={(event) => patch({ slug: event.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              Used in the public tournament URL. Changing it keeps the previous link working via a
              redirect.
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="settings-description">Description</Label>
            <Textarea
              id="settings-description"
              rows={4}
              value={form.description}
              disabled={disabled}
              placeholder="Optional tournament description…"
              onChange={(event) => patch({ description: event.target.value })}
            />
          </div>

          <div className="grid gap-4 border-t border-border pt-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="settings-team-formation">Team formation</Label>
              <Select
                value={form.team_formation}
                disabled={disabled}
                onValueChange={(value) => patch({ team_formation: value })}
              >
                <SelectTrigger id="settings-team-formation">
                  <SelectValue placeholder="Select method" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="balancer">Auto-balance (Balancer)</SelectItem>
                  <SelectItem value="draft">Live draft</SelectItem>
                  <SelectItem value="registration">Team registration</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">How teams are formed for this tournament.</p>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="settings-division-grid-version">Division grid version</Label>
              <Select
                value={form.division_grid_version_id?.toString() ?? "none"}
                disabled={disabled}
                onValueChange={(value) =>
                  patch({ division_grid_version_id: value === "none" ? null : Number(value) })
                }
              >
                <SelectTrigger id="settings-division-grid-version">
                  <SelectValue
                    placeholder={gridsQuery.isLoading ? "Loading division grids…" : "Select version"}
                  />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Workspace default</SelectItem>
                  {versions.map((version) => (
                    <SelectItem key={version.id} value={version.id.toString()}>
                      {version.label} (v{version.version}, {version.status})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <BrandingCard tournament={tournament} tournamentId={tournamentId} disabled={disabled} />

      <SaveBar dirty={dirty} summary={summary} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}

/**
 * The cover banner and the logo.
 *
 * Deliberately outside the `SaveBar` flow: images are not part of
 * `TournamentUpdate`, they travel as multipart to their own endpoint. Holding a
 * `File` in dirty-tracked form state would mean reconciling a failed upload
 * with a succeeded PATCH on every save, so the picker uploads immediately.
 */
function BrandingCard({
  tournament,
  tournamentId,
  disabled
}: Readonly<{ tournament: Tournament; tournamentId: number; disabled: boolean }>) {
  const queryClient = useQueryClient();

  // Same invalidation the settings form uses: the cover also renders on the
  // public tournament page, so refreshing only the admin query would leave the
  // previous banner up until a reload.
  const upload = useMutation({
    mutationFn: ({ slot, file }: { slot: TournamentImageSlot; file: File }) =>
      adminService.uploadTournamentImage(tournamentId, slot, file),
    onSuccess: () => invalidateTournamentWorkspace(queryClient, tournamentId),
    onError: (error) => notify.apiError(error, { title: "Could not upload this image" })
  });

  const remove = useMutation({
    mutationFn: (slot: TournamentImageSlot) =>
      adminService.deleteTournamentImage(tournamentId, slot),
    onSuccess: () => invalidateTournamentWorkspace(queryClient, tournamentId),
    onError: (error) => notify.apiError(error, { title: "Could not remove this image" })
  });

  const busy = upload.isPending || remove.isPending;

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 pt-6">
        <div className="flex flex-col gap-1.5">
          <Label>Branding</Label>
          <p className="text-xs text-muted-foreground">
            Shown on the public tournament page. Uploads apply immediately — they are not part of
            the save bar below.
          </p>
        </div>

        <div className="flex flex-wrap items-start gap-8">
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted-foreground">Cover banner</span>
            <EditableAvatar
              src={tournament.cover_image_url}
              name={tournament.name}
              size={96}
              width={288}
              shape="rounded"
              editable={!disabled}
              busy={busy}
              onSelectFile={(file) => upload.mutate({ slot: "cover", file })}
              onDelete={tournament.cover_image_url ? () => remove.mutate("cover") : undefined}
              maxSizeBytes={MAX_AVATAR_BYTES}
              onError={(message) => notify.error(message)}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">
              16:9. Shown in full: large on the tournaments list, and as a 284×160 poster in the
              tournament page&apos;s header, whose background also takes its colours. Another
              ratio is not cropped — it just fits inside that box with margins.
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted-foreground">Logo</span>
            <EditableAvatar
              src={tournament.logo_url}
              name={tournament.name}
              size={80}
              shape="rounded"
              editable={!disabled}
              busy={busy}
              onSelectFile={(file) => upload.mutate({ slot: "logo", file })}
              onDelete={tournament.logo_url ? () => remove.mutate("logo") : undefined}
              maxSizeBytes={MAX_AVATAR_BYTES}
              onError={(message) => notify.error(message)}
              disabled={disabled}
            />
            <p className="text-xs text-muted-foreground">Square image, shown beside the name.</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
