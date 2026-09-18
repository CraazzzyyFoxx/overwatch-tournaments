"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { EYEBROW_CLASS } from "@/components/admin/tone";
import { SaveBar } from "@/components/admin/kit/SaveBar";
import { MarkdownEditor } from "@/components/admin/MarkdownEditor";
import type { Tournament } from "@/types/tournament.types";
import { flattenDivisionGridVersions, useHubDivisionGridsQuery } from "../../hubQueries";
import { SettingsSectionPage } from "../SettingsSection";
import { useTournamentSettingsForm } from "../useTournamentSettingsForm";

/**
 * Mirrors `RULES_MAX_LENGTH` in
 * `backend/tournament-service/src/schemas/admin/tournament.py`: the backend
 * rejects a longer document with a 422, so the counter below has to name the
 * same number the save is judged against.
 */
const RULES_MAX_LENGTH = 32_000;

export default function RulesSettingsPage() {
  return (
    <SettingsSectionPage
      section="rules"
      description="The published regulations, plus team formation, the division grid and the points a result is worth."
    >
      {({ tournament, tournamentId, workspaceId, canUpdateTournament }) => (
        <RulesForm
          tournament={tournament}
          tournamentId={tournamentId}
          workspaceId={workspaceId}
          disabled={!canUpdateTournament}
        />
      )}
    </SettingsSectionPage>
  );
}

function RulesForm({
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
    "rules"
  );
  // Only this section reads the grid list, which is why the hub shell stopped
  // fetching it on every tab load.
  const gridsQuery = useHubDivisionGridsQuery(tournamentId, workspaceId);
  const versions = flattenDivisionGridVersions(gridsQuery.data);

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-3 pt-6">
          <div className="flex flex-col gap-1">
            <h2 className={EYEBROW_CLASS}>Published rules</h2>
            <p className="text-caption text-muted-foreground">
              Markdown, shown to everyone on the tournament&apos;s Rules tab. The tab appears only
              once this is not empty — clearing it unpublishes the document.
            </p>
          </div>
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

      <Card>
        <CardContent className="flex flex-col gap-5 pt-6">
          <div className="grid gap-4 sm:grid-cols-2">
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

          <section className="flex flex-col gap-2 border-t border-border pt-4">
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
        </CardContent>
      </Card>

      <SaveBar dirty={dirty} summary={summary} saving={saving} onDiscard={discard} onSave={save} />
    </>
  );
}
