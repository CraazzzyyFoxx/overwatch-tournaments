"use client";

import { useState, type FormEvent, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Save,
  RotateCcw,
  Trash2,
  AlertTriangle,
  Info,
  CalendarDays,
  Wrench,
  Award,
  Network
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Field, FieldLabel } from "@/components/ui/field";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { normalizeChallongeSlug } from "@/lib/challonge";
import { hasUnsavedChanges } from "@/lib/form-change";
import type { Tournament } from "@/types/tournament.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import type { TournamentUpdateInput } from "@/types/admin.types";
import { getTournamentForm, type TournamentFormState } from "./tournamentWorkspace.helpers";
import { invalidateTournamentWorkspace } from "./tournamentWorkspace.queryKeys";
import { cn } from "@/lib/utils";

interface TournamentSettingsTabProps {
  tournament: Tournament;
  tournamentId: number;
  divisionGridVersions: DivisionGridVersion[];
  divisionGridLoading: boolean;
  canDeleteTournament: boolean;
}

export function TournamentSettingsTab({
  tournament,
  tournamentId,
  divisionGridVersions,
  divisionGridLoading,
  canDeleteTournament
}: TournamentSettingsTabProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [formData, setFormData] = useState<TournamentFormState>(getTournamentForm(tournament));
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const initialFormData = getTournamentForm(tournament);
  const isDirty = hasUnsavedChanges(formData, initialFormData);

  // Sync state if tournament updates in background
  useEffect(() => {
    setFormData(getTournamentForm(tournament));
  }, [tournament]);

  const updateMutation = useMutation({
    mutationFn: (data: TournamentUpdateInput) => adminService.updateTournament(tournamentId, data),
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      notify.success("Tournament settings updated successfully");
    }
  });

  const deleteMutation = useMutation({
    mutationFn: () => adminService.deleteTournament(tournamentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["tournaments"] });
      notify.success("Tournament deleted successfully");
      router.push("/admin/tournaments");
    }
  });

  const handleReset = () => {
    setFormData(initialFormData);
    notify.info("Changes discarded", { description: "Form reset to current tournament settings." });
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();

    const payload: TournamentUpdateInput = {
      number: formData.number,
      name: formData.name.trim(),
      description: formData.description.trim() || null,
      challonge_slug: formData.challonge_slug
        ? normalizeChallongeSlug(formData.challonge_slug)
        : null,
      is_league: formData.is_league,
      is_finished: formData.is_finished,
      start_date: formData.start_date,
      end_date: formData.end_date,
      win_points: formData.win_points,
      draw_points: formData.draw_points,
      loss_points: formData.loss_points,
      registration_opens_at: formData.registration_opens_at || null,
      registration_closes_at: formData.registration_closes_at || null,
      check_in_opens_at: formData.check_in_opens_at || null,
      check_in_closes_at: formData.check_in_closes_at || null,
      division_grid_version_id: formData.division_grid_version_id,
      team_formation: formData.team_formation
    };

    updateMutation.mutate(payload);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 pb-20">
      {/* Dirty state notification bar */}
      {isDirty && (
        <div className="sticky top-4 z-40 flex items-center justify-between gap-4 rounded-xl border border-primary/30 bg-primary/10 px-4 py-3.5 shadow-lg backdrop-blur-md animate-in fade-in slide-in-from-top-4 duration-300">
          <div className="flex items-center gap-2 text-sm text-primary">
            <Info className="size-4 shrink-0" />
            <span className="font-medium">You have unsaved changes in settings.</span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleReset}
              className="h-8 border-primary/30 text-primary hover:bg-primary/20"
              disabled={updateMutation.isPending}
            >
              <RotateCcw className="mr-1.5 size-3.5" />
              Discard
            </Button>
            <Button type="submit" size="sm" className="h-8" disabled={updateMutation.isPending}>
              <Save className="mr-1.5 size-3.5" />
              {updateMutation.isPending ? "Saving..." : "Save changes"}
            </Button>
          </div>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <div className="flex flex-col gap-6 min-w-0">
          {/* Card 1: General Info */}
          <Card className="border-border/40 bg-card/50">
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2">
                <Info className="size-4 text-primary" />
                <CardTitle className="text-sm font-semibold">General Information</CardTitle>
              </div>
              <CardDescription className="text-xs">
                Update core tournament identity metadata.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-[3fr_1fr] gap-4">
                <div>
                  <Label htmlFor="settings-name" className="text-xs">
                    Tournament Name
                  </Label>
                  <Input
                    id="settings-name"
                    value={formData.name}
                    onChange={(event) => setFormData({ ...formData, name: event.target.value })}
                    required
                    className="mt-1.5 bg-background/50"
                  />
                </div>
                <div>
                  <Label htmlFor="settings-number" className="text-xs">
                    Number
                  </Label>
                  <Input
                    id="settings-number"
                    type="number"
                    value={formData.number ?? ""}
                    onChange={(event) =>
                      setFormData({
                        ...formData,
                        number: event.target.value ? Number(event.target.value) : null
                      })
                    }
                    className="mt-1.5 bg-background/50"
                  />
                </div>
              </div>
              <div>
                <Label htmlFor="settings-description" className="text-xs">
                  Description
                </Label>
                <Textarea
                  id="settings-description"
                  value={formData.description}
                  onChange={(event) =>
                    setFormData({ ...formData, description: event.target.value })
                  }
                  className="mt-1.5 bg-background/50 min-h-[90px]"
                  placeholder="Optional tournament description..."
                />
              </div>
            </CardContent>
          </Card>

          {/* Card 2: Schedule & Periods */}
          <Card className="border-border/40 bg-card/50">
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2">
                <CalendarDays className="size-4 text-primary" />
                <CardTitle className="text-sm font-semibold">Schedule & Timeline</CardTitle>
              </div>
              <CardDescription className="text-xs">
                Manage operational dates, registration periods, and player check-in.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div>
                <Field>
                  <FieldLabel
                    htmlFor="settings-date-range"
                    className="text-xs font-normal text-foreground"
                  >
                    Tournament Duration Range
                  </FieldLabel>
                  <div className="mt-1.5">
                    <DateRangePicker
                      id="settings-date-range"
                      startDate={formData.start_date}
                      endDate={formData.end_date}
                      onChange={(start, end) =>
                        setFormData({ ...formData, start_date: start, end_date: end })
                      }
                    />
                  </div>
                </Field>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 border-t border-border/30 pt-4">
                <div className="space-y-3">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Registration Period
                  </p>
                  <div className="grid gap-3">
                    <DateTimePicker
                      id="settings-registration-opens"
                      timeId="settings-registration-opens-time"
                      dateLabel="Opens at"
                      timeLabel="Time"
                      value={formData.registration_opens_at}
                      onChange={(nextValue) =>
                        setFormData({ ...formData, registration_opens_at: nextValue })
                      }
                    />
                    <DateTimePicker
                      id="settings-registration-closes"
                      timeId="settings-registration-closes-time"
                      dateLabel="Closes at"
                      timeLabel="Time"
                      value={formData.registration_closes_at}
                      onChange={(nextValue) =>
                        setFormData({ ...formData, registration_closes_at: nextValue })
                      }
                    />
                  </div>
                </div>

                <div className="space-y-3">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Check-in Period
                  </p>
                  <div className="grid gap-3">
                    <DateTimePicker
                      id="settings-check-in-opens"
                      timeId="settings-check-in-opens-time"
                      dateLabel="Opens at"
                      timeLabel="Time"
                      value={formData.check_in_opens_at}
                      onChange={(nextValue) =>
                        setFormData({ ...formData, check_in_opens_at: nextValue })
                      }
                    />
                    <DateTimePicker
                      id="settings-check-in-closes"
                      timeId="settings-check-in-closes-time"
                      dateLabel="Closes at"
                      timeLabel="Time"
                      value={formData.check_in_closes_at}
                      onChange={(nextValue) =>
                        setFormData({ ...formData, check_in_closes_at: nextValue })
                      }
                    />
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-col gap-6 min-w-0">
          {/* Card 3: Rules & Format */}
          <Card className="border-border/40 bg-card/50">
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2">
                <Wrench className="size-4 text-primary" />
                <CardTitle className="text-sm font-semibold">Rules & Grid Configuration</CardTitle>
              </div>
              <CardDescription className="text-xs">
                Adjust grid versions, team formation mechanism, and toggle league status.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="settings-team-formation" className="text-xs">
                    Team formation
                  </Label>
                  <Select
                    value={formData.team_formation}
                    onValueChange={(nextValue) =>
                      setFormData({ ...formData, team_formation: nextValue })
                    }
                  >
                    <SelectTrigger id="settings-team-formation" className="mt-1.5 bg-background/50">
                      <SelectValue placeholder="Select method" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="balancer">Auto-balance (Balancer)</SelectItem>
                      <SelectItem value="draft">Live draft</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="settings-division-grid-version" className="text-xs">
                    Division Grid Version
                  </Label>
                  <Select
                    value={formData.division_grid_version_id?.toString() ?? "none"}
                    onValueChange={(nextValue) =>
                      setFormData({
                        ...formData,
                        division_grid_version_id: nextValue === "none" ? null : Number(nextValue)
                      })
                    }
                  >
                    <SelectTrigger
                      id="settings-division-grid-version"
                      className="mt-1.5 bg-background/50"
                    >
                      <SelectValue
                        placeholder={
                          divisionGridLoading ? "Loading division grids..." : "Select version"
                        }
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

              {/* Checkboxes panel */}
              <div className="flex flex-col gap-4 bg-muted/20 border border-border/50 rounded-lg p-3.5 mt-2">
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="settings-is-league"
                    checked={formData.is_league}
                    onCheckedChange={(checked) =>
                      setFormData({ ...formData, is_league: checked === true })
                    }
                  />
                  <Label
                    htmlFor="settings-is-league"
                    className="cursor-pointer text-sm font-medium"
                  >
                    Treat as league season
                  </Label>
                </div>

                <div className="flex items-center gap-2">
                  <Checkbox
                    id="settings-is-finished"
                    checked={formData.is_finished}
                    onCheckedChange={(checked) =>
                      setFormData({ ...formData, is_finished: checked === true })
                    }
                  />
                  <Label
                    htmlFor="settings-is-finished"
                    className="cursor-pointer text-sm font-medium"
                  >
                    Mark tournament as finished
                  </Label>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Scoring and Integrations side-by-side */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Card 4: Scoring */}
            <Card className="border-border/40 bg-card/50">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-2">
                  <Award className="size-4 text-primary" />
                  <CardTitle className="text-sm font-semibold">Scoring Points</CardTitle>
                </div>
                <CardDescription className="text-xs">
                  Points awarded in standings logic for match outcomes.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <Label htmlFor="settings-win-points" className="text-xs">
                      Win
                    </Label>
                    <Input
                      id="settings-win-points"
                      type="number"
                      step="0.5"
                      value={formData.win_points}
                      onChange={(event) =>
                        setFormData({ ...formData, win_points: Number(event.target.value) })
                      }
                      className="mt-1.5 bg-background/50"
                    />
                  </div>
                  <div>
                    <Label htmlFor="settings-draw-points" className="text-xs">
                      Draw
                    </Label>
                    <Input
                      id="settings-draw-points"
                      type="number"
                      step="0.5"
                      value={formData.draw_points}
                      onChange={(event) =>
                        setFormData({ ...formData, draw_points: Number(event.target.value) })
                      }
                      className="mt-1.5 bg-background/50"
                    />
                  </div>
                  <div>
                    <Label htmlFor="settings-loss-points" className="text-xs">
                      Loss
                    </Label>
                    <Input
                      id="settings-loss-points"
                      type="number"
                      step="0.5"
                      value={formData.loss_points}
                      onChange={(event) =>
                        setFormData({ ...formData, loss_points: Number(event.target.value) })
                      }
                      className="mt-1.5 bg-background/50"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Card 5: Integrations */}
            <Card className="border-border/40 bg-card/50">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-2">
                  <Network className="size-4 text-primary" />
                  <CardTitle className="text-sm font-semibold">Integrations</CardTitle>
                </div>
                <CardDescription className="text-xs">
                  Link this tournament to external provider accounts.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div>
                  <Label htmlFor="settings-challonge" className="text-xs">
                    Challonge URL or Slug
                  </Label>
                  <Input
                    id="settings-challonge"
                    placeholder="e.g. my-tournament or https://challonge.com/my-tournament"
                    value={formData.challonge_slug}
                    onChange={(event) =>
                      setFormData({ ...formData, challonge_slug: event.target.value })
                    }
                    className="mt-1.5 bg-background/50"
                  />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Card 6: Danger Zone */}
          {canDeleteTournament && (
            <Card className="border-destructive/30 bg-destructive/5">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="size-4 text-destructive" />
                  <CardTitle className="text-sm font-semibold text-destructive">
                    Danger Zone
                  </CardTitle>
                </div>
                <CardDescription className="text-xs text-destructive/70">
                  Irreversible actions. Deleting a tournament will remove all historical logs and
                  participant rosters.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  type="button"
                  variant="destructive"
                  className="w-full"
                  onClick={() => setDeleteDialogOpen(true)}
                  disabled={deleteMutation.isPending}
                >
                  <Trash2 className="mr-2 size-4" />
                  {deleteMutation.isPending ? "Deleting..." : "Delete Tournament"}
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Non-sticky Save/Discard actions at bottom of screen if no changes, or regular placement */}
      {!isDirty && (
        <div className="flex items-center justify-end gap-3 border-t border-border/40 pt-4 mt-6">
          <Button type="submit" disabled={true} className="opacity-50 cursor-not-allowed">
            <Save className="mr-1.5 size-3.5" />
            Save changes
          </Button>
        </div>
      )}

      {canDeleteTournament && (
        <DeleteConfirmDialog
          open={deleteDialogOpen}
          onOpenChange={setDeleteDialogOpen}
          onConfirm={() => deleteMutation.mutate()}
          title="Delete Tournament"
          description={`Delete "${tournament.name}"? This removes the tournament and all linked workspace data.`}
          cascadeInfo={[
            "Tournament stages",
            "Teams and players",
            "Encounters and matches",
            "Standings rows"
          ]}
          isDeleting={deleteMutation.isPending}
        />
      )}
    </form>
  );
}
