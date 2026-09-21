"use client";

import { Card, CardContent } from "@/components/ui/card";
import { MarkdownEditor } from "@/components/admin/MarkdownEditor";
import { SaveBar } from "@/components/kit/SaveBar";
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
    <SettingsSectionPage
      section="rules"
      description="The document published on the tournament's public Rules tab."
    >
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
  const { form, patch, dirty, summary, saving, save, discard } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "rules"
  );

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-3 pt-6">
          <p className="text-caption text-muted-foreground">
            Markdown, shown to everyone on the tournament&apos;s Rules tab. The tab appears only
            once this is not empty — clearing it unpublishes the document. Write sections as{" "}
            <code>##</code> headings (<code>###</code> for subsections): two or more of them give
            the public page a table of contents. Bold text on its own line does not.
          </p>
          <MarkdownEditor
            label="Tournament rules, Markdown"
            placeholder={"## Format\n\n- Best of 3, grand final best of 5\n\n## Tiebreakers\n\n1. Head-to-head\n2. Map difference"}
            value={form.rules}
            onChange={(rules) => patch({ rules })}
            readOnly={disabled}
            maxLength={RULES_MAX_LENGTH}
          />
          {/* Unformatted on purpose: this component also renders in the server
              pass, and a locale-grouped number there can disagree with the
              browser's and trip hydration. */}
          <p className="text-caption text-muted-foreground tabular-nums">
            {form.rules.length} / {RULES_MAX_LENGTH} characters
          </p>
        </CardContent>
      </Card>

      <SaveBar dirty={dirty} summary={summary} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
