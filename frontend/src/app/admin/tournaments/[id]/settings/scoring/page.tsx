"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { EYEBROW_CLASS } from "@/components/admin/tone";
import { SaveBar } from "@/components/admin/kit/SaveBar";
import type { Tournament } from "@/types/tournament.types";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

/**
 * What a result is worth, and the two flags that decide how the tournament is
 * counted: split out of the old "Rules & scoring" page, which mixed an
 * authored document with a points table nobody edits in the same sitting.
 */
export default function ScoringSettingsPage() {
  return (
    <SettingsSectionPage
      section="scoring"
      description="The points a match outcome is worth in the standings, and how this tournament is counted."
    >
      {({ tournament, tournamentId, canUpdateTournament }) => (
        <ScoringForm
          tournament={tournament}
          tournamentId={tournamentId}
          disabled={!canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

function ScoringForm({
  tournament,
  tournamentId,
  disabled
}: Readonly<{ tournament: Tournament; tournamentId: number; disabled: boolean }>) {
  const { form, patch, dirty, summary, saving, save, discard } = useTournamentSettingsForm(
    tournament,
    tournamentId,
    "scoring"
  );

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-5 pt-6">
          <section className="flex flex-col gap-2">
            <h2 className={EYEBROW_CLASS}>Scoring points</h2>
            <p className="text-xs text-muted-foreground">
              Points awarded in standings logic for match outcomes.
            </p>
            <div className="grid grid-cols-3 gap-3 pt-1">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="settings-win-points">Win</Label>
                <NumberInput
                  id="settings-win-points"
                  value={form.win_points}
                  disabled={disabled}
                  onValueChange={(next) => patch({ win_points: next ?? 0 })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="settings-draw-points">Draw</Label>
                <NumberInput
                  id="settings-draw-points"
                  value={form.draw_points}
                  disabled={disabled}
                  onValueChange={(next) => patch({ draw_points: next ?? 0 })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="settings-loss-points">Loss</Label>
                <NumberInput
                  id="settings-loss-points"
                  value={form.loss_points}
                  disabled={disabled}
                  onValueChange={(next) => patch({ loss_points: next ?? 0 })}
                />
              </div>
            </div>
          </section>

          <div className="flex flex-col gap-4 rounded-lg border border-border bg-muted/20 p-3.5">
            <div className="flex items-center gap-2">
              <Checkbox
                id="settings-is-league"
                checked={form.is_league}
                disabled={disabled}
                onCheckedChange={(checked) => patch({ is_league: checked === true })}
              />
              <Label htmlFor="settings-is-league" className="cursor-pointer">
                Treat as league season
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="settings-is-finished"
                checked={form.is_finished}
                disabled={disabled}
                onCheckedChange={(checked) => patch({ is_finished: checked === true })}
              />
              <Label htmlFor="settings-is-finished" className="cursor-pointer">
                Mark tournament as finished
              </Label>
            </div>
          </div>
        </CardContent>
      </Card>

      <SaveBar dirty={dirty} summary={summary} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
