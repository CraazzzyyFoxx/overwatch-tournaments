"use client";

import { useTranslations } from "next-intl";

import { MarkdownEditor } from "@/components/admin/MarkdownEditor";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

/**
 * Mirrors `RULES_MAX_LENGTH` in
 * `backend/tournament-service/src/schemas/admin/tournament.py`: the backend
 * rejects a longer document with a 422, so the counter below has to name the
 * same number the save is judged against.
 */
const RULES_MAX_LENGTH = 32_000;

/**
 * The published regulations, and nothing else.
 *
 * Authoring a document and setting the points a win is worth are different
 * jobs at different times — the scoring lives in its own section now, so this
 * page is the editor at full height instead of a text box above two selects.
 */
export default function RulesSettingsPage() {
  return (
    <SettingsSectionPage section="rules">
      {({ tournament, tournamentId, canUpdateTournament }) => (
        <RulesForm
          tournament={tournament}
          tournamentId={tournamentId}
          disabled={!canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

function RulesForm({
  tournament,
  tournamentId,
  disabled
}: Readonly<{ tournament: Tournament; tournamentId: number; disabled: boolean }>) {
  const t = useTranslations("adminTournament.rules");
  const { form, patch, dirty, summary, saving, save, discard, error } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "rules"
  );

  return (
    <>
      <SettingsGrid>
      <SettingGroup id="document" title={t("groups.document.title")} wide>
        <SettingRow
          label={t("label")}
          hint={t.rich("hint", { code: (chunks) => <code>{chunks}</code> })}
          count={{ value: form.rules.length, max: RULES_MAX_LENGTH }}
          stacked
        >
          <MarkdownEditor
            label={t("label")}
            placeholder={"## Format\n\n- Best of 3, grand final best of 5\n\n## Tiebreakers\n\n1. Head-to-head\n2. Map difference"}
            value={form.rules}
            onChange={(rules) => patch({ rules })}
            readOnly={disabled}
            maxLength={RULES_MAX_LENGTH}
            className="w-full"
          />
        </SettingRow>
      </SettingGroup>
      </SettingsGrid>

      <SaveBar dirty={dirty} summary={summary} error={error} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
