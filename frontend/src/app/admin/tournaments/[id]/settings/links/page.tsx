"use client";

import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { NumberInput } from "@/components/ui/number-input";
import { usePermissions } from "@/hooks/usePermissions";
import type { Tournament } from "@/types/tournament.types";
import { tabFallback } from "../../hubQueries";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

const TournamentLinksTab = dynamic(
  () =>
    import("../../components/TournamentLinksTab").then((module) => ({
      default: module.TournamentLinksTab
    })),
  { loading: () => tabFallback }
);

/** Twitch's own maximum stream delay; the backend CHECK holds the same bound. */
const MAX_POV_STREAM_DELAY_S = 900;

export default function LinksSettingsPage() {
  const { canAccessPermission } = usePermissions();

  return (
    <SettingsSectionPage section="links">
      {({ tournament, tournamentId, workspaceId, canUpdateTournament }) => (
        <>
          <PovStreamDelayForm
            tournament={tournament}
            tournamentId={tournamentId}
            disabled={!canUpdateTournament}
          />
          <TournamentLinksTab
            tournamentId={tournamentId}
            canCreate={canAccessPermission("tournament_link.create", workspaceId)}
            canUpdate={canAccessPermission("tournament_link.update", workspaceId)}
            canDelete={canAccessPermission("tournament_link.delete", workspaceId)}
            canRepollStreams={canAccessPermission("stream.update", workspaceId)}
          />
        </>
      )}
    </SettingsSectionPage>
  );
}

function PovStreamDelayForm({
  tournament,
  tournamentId,
  disabled
}: Readonly<{ tournament: Tournament; tournamentId: number; disabled: boolean }>) {
  const t = useTranslations("adminTournament.povStreams");
  const { form, patch, dirty, summary, saving, save, discard, error } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "links"
  );

  return (
    <>
      <SettingGroup id="pov-streams" title={t("title")}>
        <SettingRow htmlFor="settings-pov-stream-delay" label={t("delay")} hint={t("delayHint")}>
          <NumberInput
            id="settings-pov-stream-delay"
            value={form.pov_stream_delay_s}
            min={0}
            max={MAX_POV_STREAM_DELAY_S}
            integer
            disabled={disabled}
            onValueChange={(next) => patch({ pov_stream_delay_s: next ?? 0 })}
            size="sm"
            className="w-24"
          />
        </SettingRow>
      </SettingGroup>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
