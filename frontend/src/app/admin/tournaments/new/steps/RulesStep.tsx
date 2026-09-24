"use client";

import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import type { DivisionGridVersion } from "@/types/workspace.types";

import type { WizardFormData } from "../wizard-model";

// Field set mirrors the Rules & Grid + Scoring cards of TournamentSettingsTab;
// those cards are inline JSX in a monolithic form, so they are not reusable as-is.
interface RulesStepProps {
  value: WizardFormData;
  onChange: (next: WizardFormData) => void;
  divisionGridVersions: DivisionGridVersion[];
  divisionGridLoading: boolean;
}

export function RulesStep({
  value,
  onChange,
  divisionGridVersions,
  divisionGridLoading
}: Readonly<RulesStepProps>) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <Label htmlFor="wizard-team-formation">Team formation</Label>
          <Select
            value={value.team_formation ?? "balancer"}
            onValueChange={(nextValue) => onChange({ ...value, team_formation: nextValue })}
          >
            <SelectTrigger id="wizard-team-formation" className="mt-1.5">
              <SelectValue placeholder="Select method" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="balancer">Auto-balance (Balancer)</SelectItem>
              <SelectItem value="draft">Live draft</SelectItem>
              <SelectItem value="registration">Team registration</SelectItem>
              <SelectItem value="solo">Solo registration (FFA)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label htmlFor="wizard-division-grid-version">Division grid version</Label>
          <Select
            value={value.division_grid_version_id?.toString() ?? "none"}
            onValueChange={(nextValue) =>
              onChange({
                ...value,
                division_grid_version_id: nextValue === "none" ? null : Number(nextValue)
              })
            }
          >
            <SelectTrigger id="wizard-division-grid-version" className="mt-1.5">
              <SelectValue
                placeholder={divisionGridLoading ? "Loading division grids…" : "Select version"}
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Workspace default</SelectItem>
              {divisionGridVersions.map((version) => (
                <SelectItem key={version.id} value={version.id.toString()}>
                  {version.label} (v{version.version}, {version.status})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-medium">Scoring points</h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label htmlFor="wizard-win-points">Win</Label>
            <NumberInput
              id="wizard-win-points"
              value={value.win_points ?? 1}
              onValueChange={(next) => onChange({ ...value, win_points: next ?? 0 })}
              className="mt-1.5 tabular-nums"
            />
          </div>
          <div>
            <Label htmlFor="wizard-draw-points">Draw</Label>
            <NumberInput
              id="wizard-draw-points"
              value={value.draw_points ?? 0.5}
              onValueChange={(next) => onChange({ ...value, draw_points: next ?? 0 })}
              className="mt-1.5 tabular-nums"
            />
          </div>
          <div>
            <Label htmlFor="wizard-loss-points">Loss</Label>
            <NumberInput
              id="wizard-loss-points"
              value={value.loss_points ?? 0}
              onValueChange={(next) => onChange({ ...value, loss_points: next ?? 0 })}
              className="mt-1.5 tabular-nums"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
