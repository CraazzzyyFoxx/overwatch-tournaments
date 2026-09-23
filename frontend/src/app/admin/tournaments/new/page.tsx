"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, PenLine } from "lucide-react";

import { getPhaseSchedulePayload } from "@/app/admin/tournaments/[id]/components/tournamentWorkspace.helpers";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import {
  WizardShell,
  type WizardStep as WizardRailStep
} from "@/components/kit/WizardShell";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { normalizeChallongeSlug } from "@/lib/tournament/challonge";
import { notify } from "@/lib/notify";
import { DEFAULT_WORKSPACE_TIMEZONE } from "@/lib/workspace/timezone";
import { SCHEDULABLE_PHASES } from "@/lib/tournament/lifecycle";
import adminService from "@/services/admin.service";
import balancerAdminService from "@/services/balancer-admin.service";
import tournamentService from "@/services/tournament.service";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Tournament } from "@/types/tournament.types";
import type { DivisionGridVersion } from "@/types/workspace.types";

import { BasicsStep } from "./steps/BasicsStep";
import { RegistrationStep } from "./steps/RegistrationStep";
import { ReviewStep } from "./steps/ReviewStep";
import { RulesStep } from "./steps/RulesStep";
import { ScheduleStep } from "./steps/ScheduleStep";
import {
  buildDraftCreateInput,
  buildDraftUpdateInput,
  findResumableDraft,
  nextWizardStep,
  previousWizardStep,
  stepEntryRequiresDraft,
  validateWizardStep,
  visibleWizardSteps,
  wizardStateFromDraft,
  type WizardBasicsState,
  type WizardFormData,
  type WizardRegistrationState,
  type WizardScheduleState,
  type WizardSource,
  type WizardStep
} from "./wizard-model";

const STEP_META: Record<WizardStep, { label: string; description: string }> = {
  basics: {
    label: "Basics",
    description: "Name the tournament and pick its dates."
  },
  schedule: {
    label: "Schedule",
    description: "Optional phase schedule and automatic transitions."
  },
  rules: {
    label: "Rules",
    description: "Team formation, division grid, and scoring points."
  },
  registration: {
    label: "Registration",
    description: "How players sign up. The full form builder opens after creation."
  },
  review: {
    label: "Review & create",
    description: "Check the configuration and create the tournament."
  }
};

/** `validateWizardStep` returns codes; the wizard turns them into a fix. */
const BASICS_ERRORS: Record<string, string> = {
  name_required: "Enter a tournament name.",
  challonge_slug_required: "Enter a Challonge URL or slug.",
  dates_required: "Pick a start and an end date."
};

const emptyForm: WizardFormData = {
  name: "",
  description: "",
  is_league: false,
  start_date: "",
  end_date: "",
  division_grid_version_id: null,
  team_formation: "balancer",
  win_points: 1,
  draw_points: 0.5,
  loss_points: 0
};

const emptySchedule: WizardScheduleState = {
  phase_schedule: Object.fromEntries(
    SCHEDULABLE_PHASES.map((phase) => [phase, { starts_at: "", ends_at: "" }])
  ) as WizardScheduleState["phase_schedule"],
  auto_transitions_enabled: true
};

export default function NewTournamentPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const timezone =
    workspaces.find((ws) => ws.id === currentWorkspaceId)?.timezone ?? DEFAULT_WORKSPACE_TIMEZONE;
  const canCreate = canAccessPermission("tournament.create", currentWorkspaceId);
  const canTeamImport = canAccessPermission("team.create", currentWorkspaceId);
  const steps = useMemo(() => visibleWizardSteps(canTeamImport), [canTeamImport]);

  // Step and source live in the URL: the step so a reload keeps the place, the
  // source so "import from Challonge" is a linkable entry to this same wizard.
  // `push`, not `replace` — the browser Back button should step back a step.
  const { searchParams, setParams } = useQueryParams({ mode: "push" });
  const requestedStep = searchParams?.get("step");
  // The registration step can disappear while active (the permission profile
  // loads in), and `?step=` is user-supplied — both fall back to step 1.
  const activeStep = steps.find((entry) => entry === requestedStep) ?? "basics";
  const activeIndex = steps.indexOf(activeStep);
  const source: WizardSource = searchParams?.get("source") === "challonge" ? "challonge" : "manual";

  const [challongeSlug, setChallongeSlug] = useState("");
  const [form, setForm] = useState<WizardFormData>(emptyForm);
  const [schedule, setSchedule] = useState<WizardScheduleState>(emptySchedule);
  const [registration, setRegistration] = useState<WizardRegistrationState>({
    auto_approve: false,
    require_open_profile: false,
    require_subscription: false
  });

  // Lazy Unpublished draft (D4): created by the first action needing an id.
  // The ref mirrors the state so async closures never see a stale draft, and
  // the promise ref collapses concurrent triggers into one POST.
  const [draft, setDraft] = useState<Tournament | null>(null);
  const draftRef = useRef<Tournament | null>(null);
  const draftPromiseRef = useRef<Promise<Tournament> | null>(null);
  const [resumeDismissed, setResumeDismissed] = useState(false);

  const divisionGridsQuery = useQuery({
    queryKey: ["admin", "tournaments", "create", "division-grids", currentWorkspaceId],
    queryFn: async () => {
      if (!currentWorkspaceId) return [];
      return workspaceService.getDivisionGrids(currentWorkspaceId);
    },
    enabled: Boolean(currentWorkspaceId)
  });
  const divisionGridVersions: DivisionGridVersion[] = (divisionGridsQuery.data ?? [])
    .flatMap((grid) => grid.versions)
    .slice()
    .sort((left, right) => right.version - left.version);

  // The subscription rule is a workspace property now, so the review step reads it
  // from the workspace rather than from the wizard state. Fetched here, next to the
  // division grids, because that is where this wizard loads its server data.
  const subscriptionRequirementQuery = useQuery({
    queryKey: ["subscription-requirement", currentWorkspaceId],
    queryFn: () => balancerAdminService.getSubscriptionRequirement(currentWorkspaceId as number),
    enabled: Boolean(currentWorkspaceId)
  });

  // Resume (D4): the latest Unpublished stage-less tournament of this
  // workspace is an abandoned wizard draft — offer to continue it.
  const resumeQuery = useQuery({
    queryKey: ["admin", "tournaments", "wizard-resume", currentWorkspaceId],
    queryFn: () => tournamentService.getAll(null, currentWorkspaceId),
    enabled: Boolean(currentWorkspaceId),
    staleTime: Infinity
  });
  const resumable = findResumableDraft(resumeQuery.data?.results ?? [], currentWorkspaceId);
  const showResumePrompt = Boolean(resumable) && !resumeDismissed && !draft;

  const adoptDraft = (tournament: Tournament) => {
    draftRef.current = tournament;
    draftPromiseRef.current = Promise.resolve(tournament);
    setDraft(tournament);
  };

  const goToStep = (target: WizardStep) => setParams({ step: target });

  const resumeDraft = (candidate: Tournament) => {
    const prefill = wizardStateFromDraft(candidate, timezone);
    setParams({ step: "basics", source: null });
    setChallongeSlug(candidate.challonge_slug ?? "");
    setForm(prefill.form);
    setSchedule(prefill.schedule);
    adoptDraft(candidate);
    setResumeDismissed(true);
  };

  const basics: WizardBasicsState = {
    source,
    name: form.name,
    challongeSlug,
    startDate: form.start_date,
    endDate: form.end_date
  };

  /** ensureSession pattern (DraftSetupWizard): first caller POSTs the hidden
   * draft, everyone after — including retries of Save as draft / publish —
   * reuses the same tournament and only PATCHes it. */
  const ensureDraft = (): Promise<Tournament> => {
    if (draftRef.current) return Promise.resolve(draftRef.current);
    if (!draftPromiseRef.current) {
      const workspaceId = currentWorkspaceId;
      draftPromiseRef.current = (async () => {
        if (!workspaceId) throw new Error("Select a workspace first");
        let created: Tournament;
        if (source === "challonge") {
          const imported = await adminService.createTournamentWithGroups({
            workspace_id: workspaceId,
            challonge_slug: normalizeChallongeSlug(challongeSlug),
            is_league: form.is_league,
            start_date: form.start_date,
            end_date: form.end_date,
            division_grid_version_id: form.division_grid_version_id ?? null
          });
          // Adopt BEFORE hiding: a failed hide must never re-run the import
          // (duplicate tournaments). with_groups cannot take is_hidden itself.
          adoptDraft(imported);
          try {
            created = await adminService.updateTournament(imported.id, { is_hidden: true });
          } catch {
            try {
              created = await adminService.updateTournament(imported.id, { is_hidden: true });
            } catch {
              notify.warning("Imported from Challonge, but hiding it failed", {
                description:
                  "The tournament is temporarily public — hide it from Settings → Visibility if needed."
              });
              created = imported;
            }
          }
        } else {
          created = await adminService.createTournament(buildDraftCreateInput(workspaceId, form));
        }
        adoptDraft(created);
        void queryClient.invalidateQueries({ queryKey: ["tournaments"] });
        void queryClient.invalidateQueries({
          queryKey: ["admin", "tournaments", "wizard-resume"]
        });
        return created;
      })().catch((error) => {
        // A created-but-unadopted draft only happens before the import resolves;
        // after adoption draftRef short-circuits this initializer entirely.
        draftPromiseRef.current = null;
        throw error;
      });
    }
    return draftPromiseRef.current;
  };

  const finishMutation = useMutation({
    mutationFn: async (publish: boolean) => {
      const active = await ensureDraft();
      await adminService.updateTournament(
        active.id,
        buildDraftUpdateInput(form, schedule, { publish })
      );
      const scheduleEntries = getPhaseSchedulePayload(schedule.phase_schedule, timezone);
      if (scheduleEntries.length > 0) {
        await adminService.setTournamentSchedule(active.id, scheduleEntries);
      }
      return { id: active.id, publish };
    },
    onSuccess: ({ id, publish }) => {
      void queryClient.invalidateQueries({ queryKey: ["tournaments"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "tournaments", "wizard-resume"] });
      notify.success(publish ? "Tournament created" : "Draft created", {
        description: publish
          ? undefined
          : "It stays Unpublished until you publish it from Review or Settings."
      });
      router.push(`/admin/tournaments/${id}/overview`);
    },
    onError: (error) => notify.apiError(error, { title: "Could not create the tournament" })
  });

  /** Validation runs on submit, so every action stays reachable and explains
   * itself. Both writes go through here — the step is in the URL, so review is
   * reachable by a pasted link that never passed a Continue. */
  const createTournament = (publish: boolean) => {
    const problems = validateWizardStep("basics", basics);
    if (problems.length > 0) {
      notify.warning(problems.map((code) => BASICS_ERRORS[code] ?? code).join(" "));
      return;
    }
    finishMutation.mutate(publish);
  };

  const next = () => {
    const problems = validateWizardStep(activeStep, basics);
    if (problems.length > 0) {
      notify.warning(problems.map((code) => BASICS_ERRORS[code] ?? code).join(" "));
      return;
    }
    const target = nextWizardStep(steps, activeStep);
    // Step 4 links the form builder and review publishes via PATCH — both
    // need the draft; create it in the background on entry.
    if (stepEntryRequiresDraft(target)) {
      ensureDraft().catch((error) =>
        notify.apiError(error, { title: "Could not create the draft" })
      );
    }
    goToStep(target);
  };

  const rail: WizardRailStep[] = steps.map((entry, index) => ({
    key: entry,
    label: STEP_META[entry].label,
    state: index === activeIndex ? "current" : index < activeIndex ? "done" : "todo"
  }));

  // Keeps `step` when flipping the source, so the link never resets the wizard.
  const sourceHref = useMemo(() => {
    const query = new URLSearchParams(searchParams?.toString() ?? "");
    if (source === "challonge") query.delete("source");
    else query.set("source", "challonge");
    const search = query.toString();
    return search ? `/admin/tournaments/new?${search}` : "/admin/tournaments/new";
  }, [searchParams, source]);

  if (!canCreate) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Unauthorized</CardTitle>
          <CardDescription>
            You do not have permission to create tournaments in this workspace.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <AdminPageHeader
        title="New tournament"
        description="Set up a tournament step by step. Only the basics are required."
      />

      <AlertDialog open={showResumePrompt}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Resume draft?</AlertDialogTitle>
            <AlertDialogDescription>
              “{resumable?.name}” is an Unpublished draft you started earlier. Resume it where you
              left off, or start a new tournament from scratch.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setResumeDismissed(true)}>
              Start a new tournament
            </AlertDialogCancel>
            <AlertDialogAction onClick={() => resumable && resumeDraft(resumable)}>
              Resume draft
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <WizardShell
        steps={rail}
        aside={
          <Link
            href={sourceHref}
            className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:text-primary"
          >
            {source === "challonge" ? (
              <PenLine aria-hidden className="size-4 shrink-0" />
            ) : (
              <Download aria-hidden className="size-4 shrink-0" />
            )}
            {source === "challonge"
              ? "Enter the details manually instead"
              : "Import from Challonge instead"}
          </Link>
        }
        footer={{
          back: activeIndex > 0 ? () => goToStep(previousWizardStep(steps, activeStep)) : undefined,
          secondary:
            activeStep === "review" ? null : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={finishMutation.isPending}
                onClick={() => createTournament(false)}
              >
                {finishMutation.isPending ? "Saving…" : "Save as draft"}
              </Button>
            ),
          next:
            activeStep === "review"
              ? {
                  label: finishMutation.isPending ? "Creating…" : "Create tournament",
                  onClick: () => createTournament(true),
                  disabled: finishMutation.isPending
                }
              : { label: "Continue", onClick: next }
        }}
      >
        <div className="space-y-1">
          <p className={`${EYEBROW_CLASS} tabular-nums`}>
            Step {activeIndex + 1} of {steps.length}
          </p>
          <h2 className="font-display text-xl font-semibold text-foreground">
            {STEP_META[activeStep].label}
          </h2>
          <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
            {STEP_META[activeStep].description}
          </p>
        </div>

        <Card className="mt-5 p-4 sm:p-6">
          {activeStep === "basics" && (
            <BasicsStep
              source={source}
              value={form}
              onChange={setForm}
              challongeSlug={challongeSlug}
              onChallongeSlugChange={setChallongeSlug}
              divisionGridVersions={divisionGridVersions}
              divisionGridLoading={divisionGridsQuery.isLoading}
            />
          )}
          {activeStep === "schedule" && (
            <ScheduleStep
              value={schedule}
              onChange={setSchedule}
              showDraftPhase={form.team_formation === "draft"}
            />
          )}
          {activeStep === "rules" && (
            <RulesStep
              value={form}
              onChange={setForm}
              divisionGridVersions={divisionGridVersions}
              divisionGridLoading={divisionGridsQuery.isLoading}
            />
          )}
          {activeStep === "registration" && (
            <RegistrationStep
              value={registration}
              onChange={setRegistration}
              draftId={draft?.id ?? null}
            />
          )}
          {activeStep === "review" && (
            <ReviewStep
              source={source}
              challongeSlug={challongeSlug}
              form={form}
              schedule={schedule}
              registration={registration}
              registrationVisible={canTeamImport}
              divisionGridVersions={divisionGridVersions}
              subscriptionRequirement={subscriptionRequirementQuery.data?.requirement}
            />
          )}
        </Card>
      </WizardShell>
    </div>
  );
}
