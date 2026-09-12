"use client";

import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";

import { EYEBROW_CLASS } from "@/components/admin/tone";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { ALL_TIEBREAKERS } from "@/lib/tiebreakers";
import { BEST_OF_OPTIONS, stageBestOfRoundSections } from "@/lib/best-of";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { StageBestOfConfig } from "@/types/admin.types";
import type { Team } from "@/types/team.types";
import type { Stage, StageItem, StageType } from "@/types/tournament.types";

import {
  BRACKET_STAGE_TYPES,
  GROUP_STAGE_TYPES,
  normalizeMaxRounds,
  RANKING_PRESETS,
  SEED_RANKING_LABELS,
  STAGE_TYPE_LABELS,
  tiebreakOrderForPreset,
  type SeedRanking,
  type StageProjection
} from "../projection";
import type { StageForm } from "../stageForm";
import { BracketPreview } from "./BracketPreview";

/*
 * The five editor sections, one per `?section=`.
 *
 * These are the field groups that used to live inside `StageManager`'s single
 * `Advanced` `Collapsible` — three levels of nesting deep, all mounted at once
 * and all saved by one button labelled "Save override". Promoted to sections
 * they are the same forms with the same payload; only the disclosure is gone.
 */

type SectionProps = Readonly<{
  stage: Stage;
  form: StageForm;
  onChange: (patch: Partial<StageForm>) => void;
}>;

/**
 * The engine appends this metric to every `tiebreak_order` it reads, so it is
 * rendered as a fixed system step rather than a step the editor owns.
 */
const MANUAL_OVERRIDE = "manual_override";

export function GeneralSection({
  stage,
  form,
  onChange,
  isSuperuser,
  projection,
  teams
}: SectionProps & {
  isSuperuser: boolean;
  projection: StageProjection;
  /** Named on the preview's cards, so their logos and full names resolve. */
  teams: Team[];
}) {
  const ids = useId();

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-name`}>Name</Label>
          <Input
            id={`${ids}-name`}
            value={form.name}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-phase`}>Phase</Label>
          <NumberInput
            id={`${ids}-phase`}
            integer
            min={0}
            value={form.order}
            onValueChange={(next) => onChange({ order: next ?? 0 })}
          />
          <p className="text-xs text-muted-foreground">
            Same number = parallel (High and Low both 1). The next number is the next wave.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-type`}>Format</Label>
          <Select
            value={form.stageType}
            onValueChange={(value) => onChange({ stageType: value as StageType })}
            disabled={!isSuperuser}
          >
            <SelectTrigger id={`${ids}-type`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(STAGE_TYPE_LABELS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {isSuperuser ? null : (
            <p className="text-xs text-muted-foreground">
              Only superusers can modify stage type after creation.
            </p>
          )}
        </div>

        {form.stageType === "swiss" ? (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${ids}-rounds`}>Swiss max rounds</Label>
            <NumberInput
              id={`${ids}-rounds`}
              integer
              min={1}
              value={form.maxRounds === "" ? null : Number(form.maxRounds)}
              onValueChange={(next) => onChange({ maxRounds: next == null ? "" : String(next) })}
            />
          </div>
        ) : null}

        {form.stageType === "double_elimination" ? (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${ids}-grand-final`}>Grand final</Label>
            <Select
              value={form.deGrandFinalType}
              onValueChange={(value) =>
                onChange({ deGrandFinalType: value as "no_reset" | "with_reset" })
              }
            >
              <SelectTrigger id={`${ids}-grand-final`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="no_reset">No reset</SelectItem>
                <SelectItem value="with_reset">With reset</SelectItem>
              </SelectContent>
            </Select>
          </div>
        ) : null}

      </div>

      <BracketPreview projection={projection} stage={stage} teams={teams} />
    </div>
  );
}

export function SeedingSection({
  stage,
  form,
  onChange,
  onChanged,
  stages = []
}: SectionProps & { onChanged: () => void; stages?: Stage[] }) {
  const ids = useId();
  const isBracket = BRACKET_STAGE_TYPES.includes(form.stageType);
  const isGroups = !isBracket;
  const groups = stage.items.filter((item) => item.type === "group");
  const sources = stages.filter(
    (candidate) =>
      candidate.id !== stage.id &&
      GROUP_STAGE_TYPES.includes(candidate.stage_type) &&
      candidate.order < form.order
  );
  const [sourceId, setSourceId] = useState(() =>
    sources.length === 1 ? String(sources[0].id) : ""
  );
  const wireMutation = useMutation({
    mutationFn: (sourceStageId: number) => {
      const source = stages.find((candidate) => candidate.id === sourceStageId);
      const advance = source?.advance_count ?? 0;
      const split =
        form.stageType === "double_elimination" &&
        form.splitLowerBracket &&
        stage.items.some((item) => item.type === "bracket_lower");
      const topLb = split ? Math.floor(advance / 2) : 0;
      return adminService.wireFromGroups(stage.id, {
        source_stage_id: sourceStageId,
        top: split ? advance - topLb : advance,
        top_lb: topLb,
        mode: "snake"
      });
    },
    onSuccess: () => {
      onChanged();
      notify.success("Wired playoff seeds from the selected stage");
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not wire this stage from groups" })
  });


  // Per-group overrides are stage_item rows, not stage form fields: they PATCH
  // on blur instead of waiting for "Save changes", which is why they carry
  // their own draft state rather than living in `form`.
  const [advanceDrafts, setAdvanceDrafts] = useState<Record<number, number | null>>({});
  const advanceMutation = useMutation({
    mutationFn: ({ stageItemId, advanceCount }: { stageItemId: number; advanceCount: number | null }) =>
      adminService.updateStageItem(stageItemId, { advance_count: advanceCount }),
    onSuccess: (_item, variables) => {
      setAdvanceDrafts((current) => {
        const next = { ...current };
        delete next[variables.stageItemId];
        return next;
      });
      onChanged();
    },
    onError: (error) =>
      notify.apiError(error, { title: "Could not change how many teams advance" })
  });

  const commitAdvance = (item: StageItem) => {
    if (!(item.id in advanceDrafts)) return;
    const next = advanceDrafts[item.id];
    if (next === (item.advance_count ?? null)) {
      setAdvanceDrafts((current) => {
        const rest = { ...current };
        delete rest[item.id];
        return rest;
      });
      return;
    }
    advanceMutation.mutate({ stageItemId: item.id, advanceCount: next });
  };

  return (
    <div className="flex flex-col gap-4">
      {form.stageType === "double_elimination" ? (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-split`}>Group seeding</Label>
          <Select
            value={form.splitLowerBracket ? "split" : "all_upper"}
            onValueChange={(value) => onChange({ splitLowerBracket: value === "split" })}
          >
            <SelectTrigger id={`${ids}-split`} className="sm:w-[280px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all_upper">All advancing → Upper bracket</SelectItem>
              <SelectItem value="split">Split: half Upper, half Lower</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Uses the group stage&apos;s &quot;Teams advancing to playoff&quot; count; auto-wired on
            Activate &amp; generate.
          </p>
        </div>
      ) : null}

      {isBracket && sources.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-feed`}>Wire seeds from</Label>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={sourceId} onValueChange={setSourceId}>
              <SelectTrigger id={`${ids}-feed`} className="sm:w-[280px]">
                <SelectValue placeholder="Group stage" />
              </SelectTrigger>
              <SelectContent>
                {sources.map((source) => (
                  <SelectItem key={source.id} value={String(source.id)}>
                    {source.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!sourceId || wireMutation.isPending}
              onClick={() => wireMutation.mutate(Number(sourceId))}
            >
              {wireMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : null}
              Wire
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Which group stage feeds this bracket. Required when two divisions run in parallel.
          </p>
        </div>
      ) : null}

      {isBracket ? (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-seed-ranking`}>Bracket seeds</Label>
          <Select
            value={form.seedRanking}
            onValueChange={(value) => onChange({ seedRanking: value as SeedRanking })}
          >
            <SelectTrigger id={`${ids}-seed-ranking`} className="sm:w-[320px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(SEED_RANKING_LABELS) as SeedRanking[]).map((value) => (
                <SelectItem key={value} value={value}>
                  {SEED_RANKING_LABELS[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Who is seed 1 in the generated bracket. Slot order keeps standings wiring.
          </p>
        </div>
      ) : null}

      {isGroups ? (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-advance`}>Teams advancing to playoff (per group)</Label>
          <NumberInput
            id={`${ids}-advance`}
            integer
            min={1}
            placeholder="Auto (derive from bracket)"
            className="sm:w-[280px]"
            value={form.advanceCount === "" ? null : Number(form.advanceCount)}
            onValueChange={(next) => onChange({ advanceCount: next == null ? "" : String(next) })}
          />
          <p className="text-xs text-muted-foreground">
            Top N from each group advance. Leave empty to auto-derive from the bracket wiring.
          </p>
        </div>
      ) : null}

      {isGroups && groups.length > 0 ? (
        <div className="flex flex-col gap-1.5 border-t border-border pt-3">
          <p className={EYEBROW_CLASS}>Advance count per group</p>
          {groups.map((item) => (
            <div key={item.id} className="flex items-center gap-2">
              <Label
                htmlFor={`${ids}-advance-${item.id}`}
                className="w-40 shrink-0 truncate text-xs text-muted-foreground"
              >
                {item.name}
              </Label>
              <NumberInput
                id={`${ids}-advance-${item.id}`}
                integer
                min={1}
                className="h-8 w-40 text-xs tabular-nums"
                placeholder={`Inherit (${stage.advance_count ?? "—"})`}
                value={item.id in advanceDrafts ? advanceDrafts[item.id] : item.advance_count ?? null}
                onValueChange={(next) =>
                  setAdvanceDrafts((current) => ({ ...current, [item.id]: next }))
                }
                onBlur={() => commitAdvance(item)}
              />
            </div>
          ))}
          <p className="text-xs text-muted-foreground">
            Overrides the number above for one group — set it when groups are uneven. Empty
            inherits. Saved on blur, not by &quot;Save changes&quot;.
          </p>
        </div>
      ) : null}

      <p className="border-t border-border pt-3 text-xs text-muted-foreground">
        Filling the slots themselves is «Seed by SR» and «Auto-wire from groups» in the stage
        actions menu, or the Items section one team at a time.
      </p>
    </div>
  );
}

export function TiebreakersSection({
  stage,
  form,
  onChange,
  winPointsDefault,
  drawPointsDefault,
  lossPointsDefault
}: SectionProps & {
  winPointsDefault: number;
  drawPointsDefault: number;
  lossPointsDefault: number;
}) {
  const ids = useId();

  // `points` and `manual_override` are not tiebreakers an organizer chooses:
  // `points` is the ranking metric every other step only separates ties on, and
  // `manual_override` is the hand-placed position. The engine normalizes every
  // saved order the same way — `points` forced first, `manual_override` forced
  // last and always present, unknown or duplicated metrics dropped — so neither
  // is offered here as a movable or removable step. Everything between them is
  // free to reorder, and free to switch off: a metric that is absent from
  // `tiebreak_order` is simply not evaluated.
  const active = form.tiebreakOrder.filter((metricId) => metricId !== MANUAL_OVERRIDE);
  const inactive = ALL_TIEBREAKERS.filter(
    (metric) => metric.id !== MANUAL_OVERRIDE && !form.tiebreakOrder.includes(metric.id)
  );

  /** Write the movable steps back, keeping `manual_override` pinned to the end. */
  const setActive = (metrics: string[]) =>
    onChange({
      tiebreakOrder: form.tiebreakOrder.includes(MANUAL_OVERRIDE)
        ? [...metrics, MANUAL_OVERRIDE]
        : metrics
    });

  const isPinned = (index: number) => active[index] === "points";

  const moveMetric = (index: number, delta: -1 | 1) => {
    const next = [...active];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    if (isPinned(index) || isPinned(target)) return;
    [next[index], next[target]] = [next[target], next[index]];
    setActive(next);
  };

  const toggleMetric = (metricId: string, enabled: boolean) =>
    setActive(enabled ? [...active, metricId] : active.filter((id) => id !== metricId));

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-preset`}>Standings preset</Label>
          <Select
            value={form.rankingPreset}
            onValueChange={(value) =>
              onChange({
                rankingPreset: value,
                tiebreakOrder: tiebreakOrderForPreset(value, stage.stage_type)
              })
            }
          >
            <SelectTrigger id={`${ids}-preset`}>
              <SelectValue placeholder="System default" />
            </SelectTrigger>
            <SelectContent>
              {RANKING_PRESETS.map((preset) => (
                <SelectItem key={preset.value} value={preset.value}>
                  {preset.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {form.stageType === "swiss" ? (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${ids}-bye`}>Swiss bye points</Label>
            <NumberInput
              id={`${ids}-bye`}
              placeholder={String(form.scoringWin || winPointsDefault)}
              value={form.swissByePoints === "" ? null : Number(form.swissByePoints)}
              onValueChange={(next) =>
                onChange({ swissByePoints: next == null ? "" : String(next) })
              }
            />
          </div>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-win`}>Win points override</Label>
          <NumberInput
            id={`${ids}-win`}
            placeholder={String(winPointsDefault)}
            value={form.scoringWin === "" ? null : Number(form.scoringWin)}
            onValueChange={(next) => onChange({ scoringWin: next == null ? "" : String(next) })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-draw`}>Draw points override</Label>
          <NumberInput
            id={`${ids}-draw`}
            placeholder={String(drawPointsDefault)}
            value={form.scoringDraw === "" ? null : Number(form.scoringDraw)}
            onValueChange={(next) => onChange({ scoringDraw: next == null ? "" : String(next) })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-loss`}>Loss points override</Label>
          <NumberInput
            id={`${ids}-loss`}
            placeholder={String(lossPointsDefault)}
            value={form.scoringLoss === "" ? null : Number(form.scoringLoss)}
            onValueChange={(next) => onChange({ scoringLoss: next == null ? "" : String(next) })}
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className={EYEBROW_CLASS}>Tiebreaker evaluation order</h3>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-xs text-primary"
            onClick={() =>
              onChange({
                tiebreakOrder: tiebreakOrderForPreset(form.rankingPreset, stage.stage_type)
              })
            }
          >
            Reset to preset defaults
          </Button>
        </div>
        <ol className="flex flex-col gap-1 rounded-lg border border-border bg-card p-2">
          {active.map((metricId, index) => {
            const metricLabel =
              ALL_TIEBREAKERS.find((metric) => metric.id === metricId)?.label ?? metricId;
            const isRankingMetric = metricId === "points";
            return (
              <li
                key={metricId}
                className="flex items-center justify-between gap-2 rounded-md border border-border bg-background px-3 py-1 text-xs"
              >
                <span className="flex items-center gap-2 font-medium text-muted-foreground">
                  <Checkbox
                    checked
                    disabled={isRankingMetric}
                    aria-label={`Use ${metricLabel}`}
                    onCheckedChange={() => toggleMetric(metricId, false)}
                  />
                  <span className="tabular-nums">{index + 1}.</span>
                  <span className="text-foreground">{metricLabel}</span>
                  {isRankingMetric ? (
                    <span className="text-label uppercase tracking-wide">ranking metric</span>
                  ) : null}
                </span>
                <span className="flex items-center gap-0.5">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-6 text-muted-foreground hover:text-foreground"
                    aria-label={`Move ${metricLabel} up`}
                    disabled={index === 0 || isPinned(index) || isPinned(index - 1)}
                    onClick={() => moveMetric(index, -1)}
                  >
                    <ChevronUp className="size-3.5" aria-hidden />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-6 text-muted-foreground hover:text-foreground"
                    aria-label={`Move ${metricLabel} down`}
                    disabled={
                      index === active.length - 1 || isPinned(index) || isPinned(index + 1)
                    }
                    onClick={() => moveMetric(index, 1)}
                  >
                    <ChevronDown className="size-3.5" aria-hidden />
                  </Button>
                </span>
              </li>
            );
          })}
          {/*
            The system step. It carries no arrows and no switch because the
            engine appends it to every order it reads: a hand-placed position
            is the last word, after every metric above has come out level.
          */}
          <li className="flex items-center justify-between gap-2 rounded-md border border-dashed border-border px-3 py-1 text-xs">
            <span className="flex items-center gap-2 font-medium text-muted-foreground">
              <Checkbox checked disabled aria-label="Use Manual Override" />
              <span className="text-foreground">Manual Override</span>
            </span>
            <span className="text-label uppercase tracking-wide text-muted-foreground">
              system step, always last
            </span>
          </li>
        </ol>
        {inactive.length > 0 ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-dashed border-border px-3 py-2">
            <span className={EYEBROW_CLASS}>Not evaluated</span>
            {inactive.map((metric) => (
              <span key={metric.id} className="flex items-center gap-2 text-xs opacity-70">
                <Checkbox
                  checked={false}
                  aria-label={`Use ${metric.label}`}
                  onCheckedChange={() => toggleMetric(metric.id, true)}
                />
                <span className="text-muted-foreground">{metric.label}</span>
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function BestOfSection({
  stage,
  form,
  onChange,
  bracketTeamCount,
  onApplyToExisting,
  applying
}: SectionProps & {
  bracketTeamCount: number;
  onApplyToExisting: () => void;
  applying: boolean;
}) {
  const ids = useId();
  const isDoubleElimination = form.stageType === "double_elimination";

  const patchBestOf = (patch: Partial<StageBestOfConfig>) =>
    onChange({ bestOf: { ...form.bestOf, ...patch } });

  const setRound = (round: number, value: number | undefined) => {
    const byRound = { ...(form.bestOf.by_round ?? {}) };
    if (value == null) delete byRound[String(round)];
    else byRound[String(round)] = value;
    onChange({ bestOf: { ...form.bestOf, by_round: byRound } });
  };

  const sections = stageBestOfRoundSections({
    stageType: form.stageType,
    maxRounds: normalizeMaxRounds(form.maxRounds, stage.max_rounds ?? 5),
    bracketTeamCount,
    splitLowerBracket: form.stageType === "double_elimination" && form.splitLowerBracket,
    configuredRounds: Object.keys(form.bestOf.by_round ?? {}).map(Number)
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Best-of per round</h3>
        <Button size="sm" variant="ghost" disabled={applying} onClick={onApplyToExisting}>
          {applying ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          Apply to existing matches
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Baked into matches on (re)generation. Use &quot;Apply to existing matches&quot; to backfill
        without regenerating.
        {isDoubleElimination
          ? " Upper and lower bracket rounds are configured separately."
          : ""}
      </p>

      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-default`}>Default</Label>
          <Select
            value={form.bestOf.default != null ? String(form.bestOf.default) : "inherit"}
            onValueChange={(value) =>
              patchBestOf({ default: value === "inherit" ? undefined : Number(value) })
            }
          >
            <SelectTrigger id={`${ids}-default`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="inherit">Default (Bo3)</SelectItem>
              {BEST_OF_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>{`Bo${n}`}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${ids}-final`}>{isDoubleElimination ? "Grand Final" : "Final"}</Label>
          <Select
            value={form.bestOf.final != null ? String(form.bestOf.final) : "none"}
            onValueChange={(value) =>
              patchBestOf({ final: value === "none" ? undefined : Number(value) })
            }
          >
            <SelectTrigger id={`${ids}-final`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">
                {isDoubleElimination ? "Same as upper bracket" : "Same as rounds"}
              </SelectItem>
              {BEST_OF_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>{`Bo${n}`}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {sections.map((section) => (
        <div key={section.key} className="flex flex-col gap-2">
          {section.label ? (
            <h4 className="text-xs font-medium text-muted-foreground">{section.label}</h4>
          ) : null}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {section.rounds.map(({ round, label }) => (
              <div key={round} className="flex flex-col gap-1.5">
                <Label htmlFor={`${ids}-round-${round}`}>{label}</Label>
                <Select
                  value={
                    form.bestOf.by_round?.[String(round)] != null
                      ? String(form.bestOf.by_round[String(round)])
                      : "inherit"
                  }
                  onValueChange={(next) =>
                    setRound(round, next === "inherit" ? undefined : Number(next))
                  }
                >
                  <SelectTrigger id={`${ids}-round-${round}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="inherit">Default</SelectItem>
                    {BEST_OF_OPTIONS.map((n) => (
                      <SelectItem key={n} value={String(n)}>{`Bo${n}`}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
