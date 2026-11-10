"use client";

import { useTranslations } from "next-intl";

import { Switch } from "@/components/ui/switch";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import type { Tournament } from "@/types/tournament.types";
import { TournamentPreviewAllowlist } from "../../components/TournamentPreviewAllowlist";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";
import { EmptyNote } from "@/components/kit/EmptyNote";

export default function PreviewSettingsPage() {
  return (
    <SettingsSectionPage section="preview">
      {({ tournament, tournamentId, workspaceId, canUpdateTournament }) => (
        <PreviewForm
          tournament={tournament}
          tournamentId={tournamentId}
          workspaceId={workspaceId}
          disabled={!canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

/**
 * Visibility and the allowlist are one section, not two: the allowlist only
 * means anything while the tournament is hidden, and the flag that hides it is
 * the first thing an admin has to reach to use it.
 */
function PreviewForm({
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
  const t = useTranslations("adminTournament.previewExtra");
  const { form, patch, dirty, summary, saving, save, discard, error } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "preview"
  );

  return (
    <>
      <SettingsGrid>
      <SettingGroup id="visibility" title={t("groups.visibility.title")}>
        <SettingRow htmlFor="settings-is-hidden" label={t("hidden")}>
          <Switch
            id="settings-is-hidden"
            checked={form.is_hidden}
            disabled={disabled}
            onCheckedChange={(checked) => patch({ is_hidden: checked })}
          />
        </SettingRow>
      </SettingGroup>

      {/* The allowlist is its own resource, not a field of the tournament:
          add and remove apply at once, outside the save bar. */}
      <SettingGroup id="allowlist" title={t("title")} immediate={form.is_hidden}>
        {form.is_hidden ? (
          <TournamentPreviewAllowlist tournamentId={tournamentId} workspaceId={workspaceId} />
        ) : (
          <EmptyNote size="sm">{t("hint")}</EmptyNote>
        )}
      </SettingGroup>
      </SettingsGrid>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
