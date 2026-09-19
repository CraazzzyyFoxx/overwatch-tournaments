"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { SaveBar } from "@/components/kit/SaveBar";
import type { Tournament } from "@/types/tournament.types";
import { TournamentPreviewAllowlist } from "../../components/TournamentPreviewAllowlist";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";
import { EmptyNote } from "@/components/kit/EmptyNote";

export default function PreviewSettingsPage() {
  return (
    <SettingsSectionPage
      section="preview"
      description="Whether the public site shows this tournament, and who may see it while it does not."
    >
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
  const { form, patch, dirty, summary, saving, save, discard } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "preview"
  );

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-4 pt-6">
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/20 p-3.5">
            <Checkbox
              id="settings-is-hidden"
              checked={form.is_hidden}
              disabled={disabled}
              onCheckedChange={(checked) => patch({ is_hidden: checked === true })}
            />
            <Label htmlFor="settings-is-hidden" className="cursor-pointer">
              Hidden (preview) — not visible to the public
            </Label>
          </div>

          <div className="flex flex-col gap-2">
            <h2 className={EYEBROW_CLASS}>Preview allowlist</h2>
            {/* Add and remove mutate immediately — the allowlist is its own
                resource, not a field of the tournament, so it is not part of
                the save below. */}
            {form.is_hidden ? (
              <TournamentPreviewAllowlist
                tournamentId={tournamentId}
                workspaceId={workspaceId}
              />
            ) : (
              <EmptyNote size="sm">
                Tick “Hidden (preview)” above to choose who may view this tournament while it is
                still private.
              </EmptyNote>
            )}
          </div>
        </CardContent>
      </Card>

      <SaveBar dirty={dirty} summary={summary} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
