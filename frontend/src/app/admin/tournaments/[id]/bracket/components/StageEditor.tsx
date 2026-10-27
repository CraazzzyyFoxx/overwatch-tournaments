"use client";

import { Fragment, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { usePathname, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import {
  GitMerge,
  MoreHorizontal,
  PlayCircle,
  Shuffle,
  Trash2,
  Undo2,
  Wand2,
  Workflow,
  Link2,
  Zap
} from "lucide-react";

import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { EntityHubHeader } from "@/components/kit/EntityHubHeader";
import { SaveBar } from "@/components/kit/SaveBar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Stage, Tournament } from "@/types/tournament.types";
import type { Team } from "@/types/team.types";

import {
  BRACKET_STAGE_TYPES,
  FFA_STAGE_TYPES,
  getDefaultMergedStageName,
  getStageStatus,
  getStageStatusTone,
  GROUP_STAGE_TYPES,
  isMergeableGroupStage,
  normalizeMaxRounds,
  projectStage,
  type StageProgress
} from "@/lib/bracket/projection";
import { Spinner } from "@/components/ui/spinner";
import {
  buildStageUpdatePayload,
  stageFormChanges,
  stageFormFromStage,
  type StageForm
} from "../stageForm";
import { BracketLayoutSection } from "./BracketLayoutSection";
import { BracketPreview } from "./BracketPreview";
import { FfaScoringSection } from "./FfaScoringSection";
import { RoundScheduleSection, useRoundSchedule } from "./RoundScheduleSection";
import { StageItemsSection } from "./StageItemsSection";
import { BestOfSection } from "./stage-settings/BestOfSection";
import { GeneralSection } from "./stage-settings/GeneralSection";
import { SeedingSection } from "./stage-settings/SeedingSection";
import { SwissSection } from "./stage-settings/SwissSection";
import { TiebreakersSection } from "./stage-settings/TiebreakersSection";
import { tabFallback } from "../../hubQueries";
import { useStageOperations } from "./stage-editor/useStageOperations";
import { MatchesView } from "../../matches/MatchesView";

// The standings table is the heaviest thing the editor can show and only one
// tab of four needs it, so it is split out of the Bracket tab's bundle.
const StandingsBrowser = dynamic(
  () =>
    import("@/components/admin/StandingsBrowser").then((module) => ({
      default: module.StandingsBrowser
    })),
  { loading: () => tabFallback }
);

/** The tabs, each named by its own key in `adminBracket.editor`. */
const BRACKET_SECTIONS = ["settings", "layout", "standings", "items"] as const;
type BracketSection = (typeof BRACKET_SECTIONS)[number];

interface StageEditorProps {
  stage: Stage;
  stages: Stage[];
  tournament: Tournament | undefined;
  teams: Team[];
  isTeamsLoading: boolean;
  progress: StageProgress | undefined;
  isSuperuser: boolean;
  /** `Matches › Encounters` scoped to this stage. */
  encountersHref: string;
  onChanged: () => void;
  /** After a delete or a merge the selected stage is gone. */
  onSelect: (stageId: number | null) => void;
}

/**
 * The detail column of the Bracket tab: one stage, four tabs, one save.
 *
 * The pre-redesign screen put all of this behind an `Advanced` disclosure and
 * spread seven separate delete-confirmation dialogs around it. Here every
 * setting of the stage, round times included, sits on one Settings page under
 * the bracket preview and is saved by one `SaveBar`; the bracket layout, the
 * standings and the items are tabs of their own (`?section=`). Every
 * destructive operation goes through the single `ConfirmDialog` below with a
 * swapped `intent`.
 *
 * Mount with `key={stage.id}`: the drafts are per-stage, and remounting is how
 * they reset when the selection changes.
 */
export function StageEditor({
  stage,
  stages,
  tournament,
  teams,
  isTeamsLoading,
  progress,
  isSuperuser,
  encountersHref,
  onChanged,
  onSelect
}: Readonly<StageEditorProps>) {
  const t = useTranslations("adminBracket.editor");
  const tRoot = useTranslations("adminBracket");
  const formatRound = useBracketRoundLabel();
  const tr = (key: string, values?: Record<string, unknown>) => tRoot(key as never, values as never);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [form, setForm] = useState<StageForm>(() => stageFormFromStage(stage));
  // The last refusal of a save. The FFA rules are the one part of this form the
  // server rejects by position inside a field, and a toast cannot point at one.
  const [saveError, setSaveError] = useState<unknown>(null);

  const hasEncounters = (progress?.total ?? 0) > 0;
  const stageStatus = getStageStatus(stage, hasEncounters);
  const changes = stageFormChanges(stage, form);
  // The engine's own round list: the shape the bracket will actually be
  // generated in, including an uneven upper/lower split (and, later, a custom
  // bracket template) that no team-count formula can derive. Keyed on the whole
  // `stage` the way the bracket preview is, so a save refetches it.
  const plannedRoundsQuery = useQuery({
    queryKey: adminQueryKeys.stagePlannedRounds(stage.id, stage),
    queryFn: () => adminService.getStagePlannedRounds(stage.id),
    enabled: BRACKET_STAGE_TYPES.includes(stage.stage_type)
  });
  // The engine answered for the SAVED format. With another one picked and not
  // yet saved, its rounds describe a stage that is about to stop existing, so
  // the projection falls back to the team-count formula until the save lands.
  const plannedRounds =
    form.stageType === stage.stage_type ? plannedRoundsQuery.data : undefined;

  const projection = useMemo(
    () =>
      projectStage({
        stage,
        stages,
        stageType: form.stageType,
        maxRounds: normalizeMaxRounds(form.maxRounds, stage.max_rounds ?? 5),
        bestOf: form.bestOf,
        plannedRounds,
        formatRound
      }),
    [stage, stages, form.stageType, form.maxRounds, form.bestOf, plannedRounds, formatRound]
  );

  const mergeCandidates = isMergeableGroupStage(stage)
    ? stages.filter(
        (candidate) =>
          candidate.id !== stage.id &&
          candidate.stage_type === stage.stage_type &&
          isMergeableGroupStage(candidate)
      )
    : [];
  const mergedName = getDefaultMergedStageName(stage);
  const {
    pendingOp,
    setPendingOp,
    intent,
    opPending,
    runPendingOp,
    activateMutation,
    generateMutation,
    applyBestOfMutation,
    autoWireMutation,
    activateAndGenerateMutation
  } = useStageOperations({ stage, teams, mergeCandidates, mergedName, onChanged, onSelect });

  const isFfaForm = FFA_STAGE_TYPES.includes(form.stageType);
  // Standings presets and tiebreakers rank the stages that produce a table:
  // a group, and an FFA league (whose lobby IS its table).
  const ranksTable = GROUP_STAGE_TYPES.includes(form.stageType) || isFfaForm;
  // Only an elimination bracket HAS a layout to draw.
  const hasLayout = BRACKET_STAGE_TYPES.includes(form.stageType);
  const requested = searchParams?.get("section") ?? "";
  const activeSection: BracketSection =
    (BRACKET_SECTIONS as readonly string[]).includes(requested) &&
    (requested !== "layout" || hasLayout)
      ? (requested as BracketSection)
      : "settings";

  const sectionHref = (key: BracketSection) => {
    const next = new URLSearchParams(searchParams?.toString() ?? "");
    next.set("stage", String(stage.id));
    next.set("section", key);
    return `${pathname}?${next.toString()}`;
  };

  const patchForm = (patch: Partial<StageForm>) => setForm((current) => ({ ...current, ...patch }));

  const updateMutation = useMutation({
    mutationFn: () => adminService.updateStage(stage.id, buildStageUpdatePayload(stage, form)),
    onMutate: () => setSaveError(null),
    onSuccess: (saved) => {
      setForm(stageFormFromStage(saved));
      onChanged();
    },
    onError: (error) => {
      setSaveError(error);
      notify.apiError(error, { title: t("saveError") });
    }
  });

  // Round times are matches, not stage fields, but they are drafts of the same
  // `SaveBar`: the editor owns them so a save sees them from any tab.
  const schedule = useRoundSchedule({
    stage,
    bracketTeamCount: projection.bracketTeams.count,
    lowerBracketTeamCount: projection.lowerBracketTeamCount,
    plannedRounds,
    onChanged
  });
  const tSchedule = useTranslations("adminBracket.roundSchedule");
  const [confirmingSchedule, setConfirmingSchedule] = useState(false);
  const movedRounds = [...new Set(schedule.moved.map((write) => write.round))].join(", ");
  const scheduleIntent: ConfirmIntent = {
    title: tSchedule("confirmTitle", { count: schedule.moved.length }),
    description: tSchedule("confirmDescription", {
      count: schedule.moved.length,
      round: movedRounds
    }),
    confirmLabel: tSchedule("confirmLabel"),
    tone: "warning"
  };

  /**
   * The stage first, then its round times: a refused stage sends no match
   * write. A save that would overwrite individually moved matches asks first;
   * the answer comes back here as `overwriteMoved`.
   */
  const save = async (overwriteMoved?: boolean) => {
    if (overwriteMoved === undefined && schedule.moved.length > 0) {
      setConfirmingSchedule(true);
      return;
    }
    setConfirmingSchedule(false);
    if (changes.length > 0) {
      try {
        await updateMutation.mutateAsync();
      } catch {
        return; // `onError` already said why.
      }
    }
    // `onError` reports a refused match write; the round drafts stay to retry.
    if (schedule.dirty) await schedule.save(overwriteMoved ?? false).catch(() => undefined);
  };

  const isBracket = BRACKET_STAGE_TYPES.includes(stage.stage_type);
  // A lobby is seated the same way a group is filled: teams into the stage's
  // items. Only a bracket takes its slots from a preceding stage instead.
  const canSeed = !isBracket && teams.length > 0 && stage.items.length > 0;
  const canDeactivate = (stage.is_active || stage.is_published) && !stage.is_completed;

  const tabs: LinkTabItem[] = BRACKET_SECTIONS.map((key) => ({
    key,
    label: t(key),
    href: sectionHref(key),
    badge: key === "items" ? stage.items.length || undefined : undefined,
    hidden: key === "layout" && !hasLayout
  }));

  return (
    <div className="min-w-0">
      <div className="border-b border-border pb-3">
        <EntityHubHeader
          level={2}
          title={stage.name}
          // A pill only while captains play (or are about to): draft and
          // completed are the default ends of every stage.
          status={
            stageStatus === "Active" || stageStatus === "Preview"
              ? {
                  label: tr(`extra.statuses.${stageStatus.toLowerCase()}`),
                  tone: getStageStatusTone(stage, hasEncounters)
                }
              : undefined
          }
          meta={[
            tRoot(`labels.types.${stage.stage_type}`),
            <span key="slots" className="tabular-nums">
              {tRoot("extra.slotsSummary", { assigned: projection.assigned, total: projection.slots })}
            </span>,
            hasEncounters ? (
              <span key="matches" className="tabular-nums">
                {tRoot("extra.matchesSummary", { completed: progress?.completed ?? 0, total: progress?.total ?? 0 })}
              </span>
            ) : null,
            // Captain visibility used to sit in the General form under a second
            // "Status" label, beside a second status badge. It is a fact about
            // the stage, so it lives with the other facts up here.
            stage.is_published ? t("published") : t("notVisible"),
            stage.challonge_slug ? (
              <a
                key="challonge"
                className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
                href={`https://challonge.com/${stage.challonge_slug}`}
                target="_blank"
                rel="noreferrer"
              >
                <Link2 className="size-3" aria-hidden />
                {tRoot("extra.challonge")}
              </a>
            ) : null
          ]}
          actions={
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={generateMutation.isPending}
                onClick={() => {
                  if (hasEncounters) setPendingOp({ kind: "regenerate" });
                  else generateMutation.mutate();
                }}
                title={t("generateTitle")}
              >
                {generateMutation.isPending ? (
                  <Spinner />
                ) : (
                  <Wand2 className="size-4" aria-hidden />
                )}
                {hasEncounters ? t("regenerate") : t("generate")}
              </Button>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="icon" variant="ghost" aria-label={t("actions", { name: stage.name })}>
                    <MoreHorizontal className="size-4" aria-hidden />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {stage.is_active ? null : (
                    <DropdownMenuItem
                      disabled={activateMutation.isPending}
                      onSelect={() => activateMutation.mutate()}
                    >
                      <PlayCircle className="size-4" aria-hidden />
                      {t("activate")}
                    </DropdownMenuItem>
                  )}
                  {isBracket ? (
                    <DropdownMenuItem
                      disabled={activateAndGenerateMutation.isPending}
                      onSelect={() => activateAndGenerateMutation.mutate(undefined)}
                    >
                      <Zap className="size-4" aria-hidden />
                      {t("activateGenerate")}
                    </DropdownMenuItem>
                  ) : null}
                  {isBracket ? (
                    <DropdownMenuItem
                      disabled={autoWireMutation.isPending}
                      onSelect={() => autoWireMutation.mutate()}
                    >
                      <Workflow className="size-4" aria-hidden />
                      {t("autoWire")}
                    </DropdownMenuItem>
                  ) : null}
                  {canSeed ? (
                    <DropdownMenuItem onSelect={() => setPendingOp({ kind: "seed" })}>
                      <Shuffle className="size-4" aria-hidden />
                      {t("seed")}
                    </DropdownMenuItem>
                  ) : null}
                  {mergeCandidates.length > 0 ? (
                    <DropdownMenuItem onSelect={() => setPendingOp({ kind: "merge" })}>
                      <GitMerge className="size-4" aria-hidden />
                      {t("merge")}
                    </DropdownMenuItem>
                  ) : null}
                  {canDeactivate ? (
                    <DropdownMenuItem onSelect={() => setPendingOp({ kind: "deactivate" })}>
                      <Undo2 className="size-4" aria-hidden />
                      {t("revert")}
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuItem
                    variant="destructive"
                    onSelect={() => setPendingOp({ kind: "delete-stage" })}
                  >
                    <Trash2 className="size-4" aria-hidden />
                    {t("delete")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          }
        />
      </div>

      <div className="border-b border-border py-2">
        <LinkTabs
          items={tabs}
          activeKey={activeSection}
          level={2}
          ariaLabel={t("sections", { name: stage.name })}
        />
      </div>

      <div className="pt-4">
        {activeSection === "settings" ? (
          // The settings rail's rhythm: a stack of `SettingGroup` cards, each
          // section building its own. The preview stays unframed between them:
          // the bracket draws its own panel, and a card around it would be a
          // second frame.
          <div className="flex flex-col gap-4">
            <GeneralSection stage={stage} form={form} onChange={patchForm} isSuperuser={isSuperuser} />

            {/* Right under the fields that shape it: format and grand final. */}
            <BracketPreview projection={projection} stage={stage} teams={teams} className="px-1 py-2" />

            <SeedingSection
              stage={stage}
              stages={stages}
              form={form}
              onChange={patchForm}
              onChanged={onChanged}
            />

            {isFfaForm ? (
              <FfaScoringSection form={form} onChange={patchForm} saveError={saveError} />
            ) : null}

            {/* Under the advance count it checks, over the Points group's bye. */}
            {form.stageType === "swiss" ? (
              <SwissSection stage={stage} form={form} onChange={patchForm} />
            ) : null}

            {ranksTable ? (
              <TiebreakersSection
                stage={stage}
                form={form}
                onChange={patchForm}
                winPointsDefault={tournament?.win_points ?? 1}
                drawPointsDefault={tournament?.draw_points ?? 0.5}
                lossPointsDefault={tournament?.loss_points ?? 0}
              />
            ) : null}

            <BestOfSection
              stage={stage}
              form={form}
              onChange={patchForm}
              bracketTeamCount={projection.bracketTeams.count}
              lowerBracketTeamCount={projection.lowerBracketTeamCount}
              plannedRounds={plannedRounds}
              onApplyToExisting={() => applyBestOfMutation.mutate()}
              applying={applyBestOfMutation.isPending}
            />

            <RoundScheduleSection schedule={schedule} />
          </div>
        ) : null}

        {activeSection === "layout" ? <BracketLayoutSection stage={stage} /> : null}

        {activeSection === "standings" ? (
          <MatchesView tournamentId={stage.tournament_id}>
            {({ workspaceId }) => (
              <StandingsBrowser
                tournamentId={stage.tournament_id}
                workspaceId={workspaceId}
                stageId={stage.id}
              />
            )}
          </MatchesView>
        ) : null}

        {activeSection === "items" ? (
          <StageItemsSection
            stage={stage}
            stages={stages}
            teams={teams}
            isTeamsLoading={isTeamsLoading}
            progress={progress}
            encountersHref={encountersHref}
            onChanged={onChanged}
            onRequestDeleteItem={(item) => setPendingOp({ kind: "delete-item", item })}
            onRequestRemoveInput={(input, label) =>
              setPendingOp({ kind: "remove-input", inputId: input.id, label })
            }
          />
        ) : null}

        <SaveBar
          dirty={changes.length > 0 || schedule.dirty}
          summary={
            <Fragment>
              {t("unsaved")}{" "}
              <span className="text-foreground">
                {[
                  ...changes.map((key) => tr(`changes.${key}`)),
                  ...(schedule.dirty ? [tr("changes.roundSchedule")] : [])
                ].join(", ")}
              </span>
            </Fragment>
          }
          onDiscard={() => {
            setForm(stageFormFromStage(stage));
            schedule.discard();
          }}
          onSave={() => void save()}
          saving={updateMutation.isPending || schedule.saving}
          // The tabs above are `?section=` links of THIS form, so the anchor
          // guard would demand a discard just to look at another one. The
          // stage list beside it is buttons, which the guard never saw.
          guardNavigation={false}
        />
      </div>

      <ConfirmDialog
        open={pendingOp !== null}
        onOpenChange={(open) => {
          if (!open) setPendingOp(null);
        }}
        intent={intent}
        onConfirm={runPendingOp}
        pending={opPending}
      />

      {/* The save's own question, so it is not one of `PendingOp`'s: declining
          is not "do nothing" — it keeps the moved matches and still saves the
          rest, which the description says. */}
      <ConfirmDialog
        open={confirmingSchedule}
        onOpenChange={(open) => {
          if (!open && confirmingSchedule) void save(false);
        }}
        intent={scheduleIntent}
        onConfirm={() => save(true)}
      />
    </div>
  );
}
