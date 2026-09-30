"use client";

import { useTranslations } from "next-intl";

import { SaveBar } from "@/components/kit/SaveBar";
import { TONE_CLASS } from "@/components/kit/tone";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/types/tournament.types";

import { DraftFormatFields } from "../../components/draft/DraftFormatFields";
import { resolveDraftFormat } from "../../components/draft/setup-model";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

export default function DraftSettingsPage() {
  return (
    <SettingsSectionPage
      section="draft"
      description="The pick order every draft of this tournament follows. Timers and autopick are set per draft."
    >
      {({ tournament, tournamentId, canUpdateTournament }) => (
        <DraftFormatForm
          tournament={tournament}
          tournamentId={tournamentId}
          disabled={!canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

function DraftFormatForm({
  tournament,
  tournamentId,
  disabled
}: Readonly<{ tournament: Tournament; tournamentId: number; disabled: boolean }>) {
  const t = useTranslations("draftAdmin");
  const { form, patch, dirty, summary, saving, save, discard } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "draft"
  );
  // The server refuses the change while a draft is in flight, the same guard
  // the roster shape has: a session already copied the rule it drafts with.
  const locked = tournament.roster_locked_by_draft === true;
  const rounds = tournament.roster_shape?.draft_rounds ?? 0;
  const value = resolveDraftFormat(form.draft_format_json, rounds);

  return (
    <>
      <Card>
        <CardContent className="space-y-4 pt-6">
          {locked && (
            <div className={cn("rounded-xl border px-4 py-3 text-sm", TONE_CLASS.warning)}>
              {t("formatLockedByDraft")}
            </div>
          )}
          <DraftFormatFields
            value={value}
            rounds={rounds}
            disabled={disabled || locked}
            onChange={(next) => patch({ draft_format_json: next })}
          />
        </CardContent>
      </Card>

      <SaveBar dirty={dirty} summary={summary} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
