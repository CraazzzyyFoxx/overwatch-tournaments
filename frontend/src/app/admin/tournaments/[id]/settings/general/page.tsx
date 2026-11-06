"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { AuditTrailButton } from "@/components/kit/AuditTrailSheet";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
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
    <SettingsSectionPage section="general">
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
  const t = useTranslations("adminTournament.general");
  const { form, patch, dirty, summary, saving, save, discard, error } = useTournamentSettingsForm(
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
          target={t("auditTarget", { name: tournament.name })}
          showCount
        />
      </div>

      <SettingGroup id="details" title={t("groups.details.title")}>
        <SettingRow htmlFor="settings-name" label={t("name")} stacked>
          <Input
            id="settings-name"
            value={form.name}
            disabled={disabled}
            onChange={(event) => patch({ name: event.target.value })}
          />
        </SettingRow>
        <SettingRow htmlFor="settings-slug" label={t("slug")} hint={t("slugHint")} stacked>
          <Input
            id="settings-slug"
            value={form.slug}
            disabled={disabled}
            onChange={(event) => patch({ slug: event.target.value })}
          />
        </SettingRow>
        <SettingRow htmlFor="settings-description" label={t("descriptionLabel")} stacked>
          <Textarea
            id="settings-description"
            rows={4}
            value={form.description}
            disabled={disabled}
            placeholder={t("descriptionPlaceholder")}
            onChange={(event) => patch({ description: event.target.value })}
          />
        </SettingRow>
      </SettingGroup>

      <SettingGroup id="format" title={t("groups.format.title")}>
        <SettingRow htmlFor="settings-division-grid-version" label={t("divisionGrid")}>
          {gridsQuery.isLoading ? (
            <div role="status" className="w-full">
              <span className="sr-only">{t("loadingDivisionGrids")}</span>
              <Skeleton aria-hidden className="h-9 w-full" />
            </div>
          ) : (
            <Select
              value={form.division_grid_version_id?.toString() ?? "none"}
              disabled={disabled}
              onValueChange={(value) =>
                patch({ division_grid_version_id: value === "none" ? null : Number(value) })
              }
            >
              <SelectTrigger id="settings-division-grid-version">
                <SelectValue placeholder={t("selectVersion")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("workspaceDefault")}</SelectItem>
                {versions.map((version) => (
                  <SelectItem key={version.id} value={version.id.toString()}>
                    {t("gridVersionOption", { label: version.label, version: version.version, status: version.status })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </SettingRow>
      </SettingGroup>

      <BrandingGroup tournament={tournament} tournamentId={tournamentId} disabled={disabled} />

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
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
function BrandingGroup({
  tournament,
  tournamentId,
  disabled
}: Readonly<{ tournament: Tournament; tournamentId: number; disabled: boolean }>) {
  const t = useTranslations("adminTournament.general");
  const queryClient = useQueryClient();

  // Same invalidation the settings form uses: the cover also renders on the
  // public tournament page, so refreshing only the admin query would leave the
  // previous banner up until a reload.
  const upload = useMutation({
    mutationFn: ({ slot, file }: { slot: TournamentImageSlot; file: File }) =>
      adminService.uploadTournamentImage(tournamentId, slot, file),
    onSuccess: () => invalidateTournamentWorkspace(queryClient, tournamentId),
    onError: (error) => notify.apiError(error, { title: t("uploadError") })
  });

  const remove = useMutation({
    mutationFn: (slot: TournamentImageSlot) =>
      adminService.deleteTournamentImage(tournamentId, slot),
    onSuccess: () => invalidateTournamentWorkspace(queryClient, tournamentId),
    onError: (error) => notify.apiError(error, { title: t("removeImageError") })
  });

  const busy = upload.isPending || remove.isPending;

  return (
    <SettingGroup id="images" title={t("branding")} description={t("brandingHint")} immediate>
      {/* Stacked: the 288px banner does not fit half of a narrow group. */}
      <SettingRow label={t("cover")} hint={t("coverHint")} stacked>
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
      </SettingRow>
      <SettingRow label={t("logo")} hint={t("logoHint")}>
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
      </SettingRow>
    </SettingGroup>
  );
}
