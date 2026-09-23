"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { XCircle } from "lucide-react";
import { useTranslations } from "next-intl";

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
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { WizardShell, type WizardStep } from "@/components/kit/WizardShell";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { notify } from "@/lib/notify";
import type { RosterShape } from "@/lib/roster/shape";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import balancerAdminService from "@/services/balancer-admin.service";
import draftService from "@/services/draft.service";
import type {
  DraftBoard,
  DraftSeedRequest,
  DraftSeedResponse,
  DraftSession
} from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { useHubTournamentQuery } from "../../hubQueries";

import { DraftCaptainsStep } from "./DraftCaptainsStep";
import { DraftConfigStep } from "./DraftConfigStep";
import { DraftOrderStep } from "./DraftOrderStep";
import { DraftPoolStep } from "./DraftPoolStep";
import { DraftReadyStep } from "./DraftReadyStep";
import { DraftReviewStep } from "./DraftReviewStep";
import {
  canCancelDraftSetup,
  derivePoolReadiness,
  MAX_DRAFT_TEAM_COUNT,
  MIN_DRAFT_TEAM_COUNT,
  orderCaptainIds,
  previousSetupStep,
  SETUP_STEPS,
  type DraftSetupStep,
  validateSetupStep
} from "./setup-model";
import type { DraftCaptainSetup, DraftSetupConfig } from "./setup-types";
import { captainRankSummary, isInDraftPool, poolRegistrationSummary } from "./setup-types";

interface DraftSetupWizardProps {
  tournamentId: number;
  board: DraftBoard | null;
  /** Resolved tournament roster shape; a live session's own shape wins over it. */
  rosterShape: RosterShape;
  /** Rail slot (F5 ·4): past sessions, secondary to the session being set up. */
  aside?: ReactNode;
}

function configFromSession(session: DraftSession | null, shape: RosterShape): DraftSetupConfig {
  const roundRules = session?.settings_json?.round_rules;
  const teamCount = session?.settings_json?.team_count;
  return {
    teamCount: typeof teamCount === "number" ? teamCount : 2,
    pickTimeSeconds: session?.pick_time_seconds ?? 45,
    overtimeSeconds: session?.overtime_seconds ?? 0,
    format: session?.format ?? "snake",
    autopickStrategy: session?.autopick_strategy ?? "best_fit",
    allowAdminOverride: session?.allow_admin_override ?? true,
    roundRules: Array.isArray(roundRules)
      ? roundRules.map(String)
      : Array.from({ length: shape.draft_rounds }, () => "linear")
  };
}

function createEmptyCaptainSetup(): DraftCaptainSetup {
  return {
    ids: [],
    teamNames: {},
    order: "weakest_first",
    randomSeed: Math.floor(Math.random() * 2_147_483_647)
  };
}

export function DraftSetupWizard({
  tournamentId,
  board,
  rosterShape,
  aside
}: Readonly<DraftSetupWizardProps>) {
  const t = useTranslations("draftAdmin");
  const queryClient = useQueryClient();
  const boardKey = tournamentQueryKeys.draftBoard(tournamentId);
  const initialSession = board?.session ?? null;
  const [localSession, setLocalSession] = useState<DraftSession | null>(initialSession);
  const session =
    localSession == null
      ? initialSession
      : initialSession == null || localSession.version >= initialSession.version
        ? localSession
        : initialSession;
  const [step, setStep] = useState<DraftSetupStep>(
    initialSession?.status === "ready" ? "ready" : initialSession ? "pool" : "config"
  );
  const [config, setConfig] = useState<DraftSetupConfig>(() =>
    configFromSession(initialSession, initialSession?.roster_shape ?? rosterShape)
  );
  const [captains, setCaptains] = useState<DraftCaptainSetup>(createEmptyCaptainSetup);
  const [preview, setPreview] = useState<DraftSeedResponse | null>(null);
  const [committedFeasibility, setCommittedFeasibility] = useState<
    DraftSeedResponse["feasibility"] | null
  >(null);
  const [reseedDialogOpen, setReseedDialogOpen] = useState(false);
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);

  // Tournament grid first, workspace default second — the captains list ranks
  // players on the same grid the draft is seeded and balanced on. The hub shell
  // already mounts this query under the same key, so this is a cache read.
  const tournamentGridVersion =
    useHubTournamentQuery(tournamentId).data?.division_grid_version ?? null;
  const workspaceGrid = useDivisionGrid();
  const divisionGrid: DivisionGrid = useMemo(
    () => (tournamentGridVersion?.tiers ? { tiers: tournamentGridVersion.tiers } : workspaceGrid),
    [tournamentGridVersion, workspaceGrid]
  );

  const resetSetupState = () => {
    setLocalSession(null);
    setConfig(configFromSession(null, rosterShape));
    setCaptains(createEmptyCaptainSetup());
    setPreview(null);
    setCommittedFeasibility(null);
    setReseedDialogOpen(false);
    setCancelDialogOpen(false);
    setStep("config");
  };

  const poolQuery = useQuery({
    queryKey: ["balancer", "draft-setup-pool", tournamentId],
    queryFn: () => balancerAdminService.listRegistrations(tournamentId, { include_deleted: true })
  });
  const allRegistrations = poolQuery.data ?? [];
  const pool = useMemo(() => allRegistrations.filter(isInDraftPool), [allRegistrations]);

  const hydrateCaptainsFromBoard = () => {
    if (!board || pool.length === 0 || board.teams.length === 0) return;
    const orderedTeams = [...board.teams].sort(
      (left, right) => left.draft_position - right.draft_position
    );
    const ids = orderedTeams
      .map((team) => pool.find((registration) => registration.user_id === team.captain_user_id)?.id)
      .filter((id): id is number => id != null);
    if (ids.length > 0) {
      setCaptains((current) => ({
        ...current,
        ids,
        order: "manual",
        teamNames: Object.fromEntries(
          orderedTeams.flatMap((team, index) => (ids[index] ? [[ids[index], team.name]] : []))
        )
      }));
      setConfig((current) => ({ ...current, teamCount: ids.length }));
    }
  };

  const candidates = useMemo(
    () =>
      allRegistrations.map((registration) => {
        const summary = poolRegistrationSummary(registration);
        return {
          id: registration.id,
          roles: summary.roles,
          rank: summary.rank,
          hasAccount: registration.user_id != null,
          excluded: !isInDraftPool(registration)
        };
      }),
    [allRegistrations]
  );
  // A created session froze its own shape; before that the tournament's applies.
  const shape = session?.roster_shape ?? rosterShape;
  const readiness = useMemo(
    () => derivePoolReadiness(candidates, config.teamCount, shape),
    [candidates, config.teamCount, shape]
  );
  const ranks = useMemo(
    () =>
      new Map(pool.map((registration) => [registration.id, captainRankSummary(registration).rank])),
    [pool]
  );
  const orderedCaptainIds = useMemo(
    () => orderCaptainIds(captains.ids, captains.order, ranks, captains.randomSeed),
    [captains.ids, captains.order, captains.randomSeed, ranks]
  );

  const feasibilityQuery = useQuery({
    queryKey: session
      ? tournamentQueryKeys.draftFeasibility(session.id)
      : ["draft", "feasibility", "none"],
    queryFn: () => draftService.getFeasibility(session!.id),
    enabled: session?.status === "ready"
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: boardKey });
  };

  const createMutation = useMutation({
    mutationFn: () =>
      draftService.createSession(tournamentId, {
        pool_source: "balancer_balance",
        format: config.format,
        pick_time_seconds: config.pickTimeSeconds,
        overtime_seconds: config.overtimeSeconds,
        autopick_strategy: config.autopickStrategy,
        allow_admin_override: config.allowAdminOverride,
        settings: {
          team_count: config.teamCount,
          ...(config.format === "custom" ? { round_rules: config.roundRules } : {})
        }
      })
  });

  const ensureSession = async (): Promise<DraftSession> => {
    if (session) return session;
    const created = await createMutation.mutateAsync();
    setLocalSession(created);
    await invalidate();
    return created;
  };

  const seedBody = (activeSession: DraftSession, previewOnly: boolean): DraftSeedRequest => ({
    captain_order: captains.order,
    seed: captains.order === "random" ? captains.randomSeed : null,
    pool_captains: captains.ids.map((id) => ({
      registration_id: id,
      name: captains.teamNames[id]?.trim() || null
    })),
    preview_only: previewOnly,
    expected_version: activeSession.version
  });

  const previewMutation = useMutation({
    mutationFn: async () => {
      const activeSession = await ensureSession();
      return draftService.seed(tournamentId, activeSession.id, seedBody(activeSession, true));
    },
    onSuccess: (result) => {
      setPreview(result);
      setStep("review");
    },
    onError: (error) => notify.apiError(error, { title: t("previewFailed") })
  });

  const commitMutation = useMutation({
    mutationFn: async () => {
      if (!session) throw new Error("Draft session is missing");
      return draftService.seed(tournamentId, session.id, seedBody(session, false));
    },
    onSuccess: async (result) => {
      setLocalSession(result.session);
      setCommittedFeasibility(result.feasibility);
      setPreview(null);
      setReseedDialogOpen(false);
      setStep("ready");
      notify.success(t("draftSeeded"));
      await invalidate();
    },
    onError: (error) => notify.apiError(error, { title: t("seedFailed") })
  });

  const startMutation = useMutation({
    mutationFn: () => draftService.lifecycle(tournamentId, session!.id, "start"),
    onSuccess: async (result) => {
      setLocalSession(result);
      notify.success(t("draftStarted"));
      await invalidate();
    },
    onError: (error) => notify.apiError(error, { title: t("startFailed") })
  });

  const cancelMutation = useMutation({
    mutationFn: () => {
      if (!session) throw new Error("Draft session is missing");
      return draftService.lifecycle(tournamentId, session.id, "cancel");
    },
    onSuccess: async (result) => {
      queryClient.setQueryData<DraftBoard | null>(boardKey, (current) =>
        current ? { ...current, session: result } : null
      );
      resetSetupState();
      notify.success(t("controlRoom.actionSuccess.cancel"));
      await invalidate();
    },
    onError: (error) => notify.apiError(error, { title: t("controlRoom.confirm.cancel.title") })
  });

  const isReseed =
    session?.status === "ready" ||
    (preview?.diff.teams_before ?? board?.teams.length ?? 0) > 0 ||
    (preview?.diff.picks_before ?? board?.picks.length ?? 0) > 0;
  const captainsHaveAccounts = captains.ids.every(
    (id) => pool.find((registration) => registration.id === id)?.user_id != null
  );
  const reviewReady =
    readiness.blockers.length === 0 &&
    captains.ids.length === config.teamCount &&
    captainsHaveAccounts &&
    preview?.feasibility.is_feasible === true;
  const currentIndex = SETUP_STEPS.indexOf(step);
  const pending =
    createMutation.isPending ||
    previewMutation.isPending ||
    commitMutation.isPending ||
    startMutation.isPending ||
    cancelMutation.isPending;
  const canCancelSetup = canCancelDraftSetup(step, session?.status ?? null);

  const validationState = {
    pickTimeSeconds: config.pickTimeSeconds,
    captainIds: captains.ids,
    poolReady: readiness.blockers.length === 0,
    previewFeasible: preview?.feasibility.is_feasible === true
  };

  const next = async () => {
    if (step === "config") {
      if (
        validateSetupStep(step, validationState).length > 0 ||
        config.teamCount < MIN_DRAFT_TEAM_COUNT ||
        config.teamCount > MAX_DRAFT_TEAM_COUNT
      ) {
        notify.warning(t("fixStepErrors"));
        return;
      }
      // Keep the early setup steps reversible. The server session is only
      // required when generating the seed preview, so creating it here would
      // unnecessarily lock the configuration as soon as the admin continues.
      setStep("pool");
      return;
    }
    if (step === "pool") {
      if (validateSetupStep(step, validationState).length > 0) {
        notify.warning(t("poolBlocked"));
        return;
      }
      setStep("captains");
      return;
    }
    if (step === "captains") {
      if (captains.ids.length !== config.teamCount) {
        notify.warning(t("captainCountError", { count: config.teamCount }));
        return;
      }
      setStep("order");
      return;
    }
    if (step === "order") {
      await previewMutation.mutateAsync();
      return;
    }
    if (step === "review") {
      if (!reviewReady) {
        notify.warning(t("previewInfeasible"));
        return;
      }
      if (isReseed) setReseedDialogOpen(true);
      else commitMutation.mutate();
    }
  };

  const back = () => {
    // The rail is an indicator in T6, so this is the only way back and must
    // not race a mutation that is about to move the step itself.
    if (pending) return;
    if (step === "review") setPreview(null);
    setStep(previousSetupStep(step));
  };

  const setCaptainsAndReset = (nextValue: DraftCaptainSetup) => {
    setCaptains(nextValue);
    setPreview(null);
  };

  const wizardSteps: WizardStep[] = SETUP_STEPS.map((entry, index) => ({
    key: entry,
    label: t(`steps.${entry}`),
    state: index < currentIndex ? "done" : index === currentIndex ? "current" : "todo"
  }));

  const cancelButton = canCancelSetup ? (
    <Button
      type="button"
      size="sm"
      variant="outline"
      disabled={pending}
      className="border-[color:var(--aqt-live)]/40 text-[color:var(--aqt-live)] hover:border-[color:var(--aqt-live)] hover:bg-[color:var(--aqt-live)]/10"
      onClick={() => setCancelDialogOpen(true)}
    >
      <XCircle className="mr-2 h-4 w-4" aria-hidden />
      {session ? t("actions.cancel") : t("discardSetup")}
    </Button>
  ) : null;

  return (
    <div className="space-y-5 text-[color:var(--aqt-fg)]">
      <WizardShell
        steps={wizardSteps}
        aside={aside}
        footer={
          // The Ready step carries its own confirmed "Start draft"; a generic
          // Continue beside it would be a second, unlabelled way to go live.
          step === "ready"
            ? { secondary: cancelButton }
            : {
                back: step === "config" ? undefined : back,
                next: {
                  label: step === "review" ? t("seedDraft") : t("continue"),
                  onClick: () => void next(),
                  disabled: pending || (step === "review" && !reviewReady)
                },
                secondary: cancelButton
              }
        }
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className={EYEBROW_CLASS}>
              {t("stepOf", { current: currentIndex + 1, total: SETUP_STEPS.length })}
            </p>
            <h2 className="mt-2 font-onest text-xl font-semibold">{t(`stepTitles.${step}`)}</h2>
            <p className="mt-1 max-w-3xl text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
              {t(`stepDescriptions.${step}`)}
            </p>
          </div>
          {session && (
            <Badge variant="outline" className="tabular-nums">
              {t("sessionNumber", { id: session.id })} · v{session.version}
            </Badge>
          )}
        </div>
        <div className="mt-6">
          {step === "config" && (
            <DraftConfigStep
              value={config}
              onChange={setConfig}
              rosterShape={shape}
              tournamentId={tournamentId}
              locked={!!session}
            />
          )}
          {step === "pool" && (
            <DraftPoolStep
              readiness={readiness}
              feasibility={preview?.feasibility ?? feasibilityQuery.data ?? null}
              loading={poolQuery.isLoading}
              failed={poolQuery.isError}
            />
          )}
          {step === "captains" && (
            <DraftCaptainsStep
              pool={pool}
              teamCount={config.teamCount}
              value={captains}
              onChange={setCaptainsAndReset}
              divisionGrid={divisionGrid}
            />
          )}
          {step === "order" && (
            <DraftOrderStep
              value={captains}
              onChange={setCaptainsAndReset}
              pool={pool}
              rounds={shape.draft_rounds}
              format={config.format}
              roundRules={config.roundRules}
            />
          )}
          {step === "review" && (
            <DraftReviewStep
              config={config}
              rounds={shape.draft_rounds}
              captains={captains}
              orderedCaptainIds={orderedCaptainIds}
              pool={pool}
              readiness={readiness}
              preview={preview}
              previewPending={previewMutation.isPending}
              previewError={previewMutation.isError}
              isReseed={isReseed}
            />
          )}
          {step === "ready" && session && (
            <DraftReadyStep
              tournamentId={tournamentId}
              session={session}
              feasibility={committedFeasibility ?? feasibilityQuery.data ?? null}
              pending={pending}
              onStart={() => startMutation.mutate()}
              onReseed={() => {
                hydrateCaptainsFromBoard();
                setPreview(null);
                setStep("captains");
              }}
            />
          )}
        </div>
      </WizardShell>

      <AlertDialog open={reseedDialogOpen} onOpenChange={setReseedDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("reseedConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("reseedConfirmDescription")}</AlertDialogDescription>
          </AlertDialogHeader>
          {preview && (
            <div className="grid grid-cols-3 gap-2 rounded-xl bg-muted/50 p-3 text-center text-sm tabular-nums">
              <div>
                {t("teams")}: {preview.diff.teams_before} → {preview.diff.teams_after}
              </div>
              <div>
                {t("players")}: {preview.diff.players_before} → {preview.diff.players_after}
              </div>
              <div>
                {t("picks")}: {preview.diff.picks_before} → {preview.diff.picks_after}
              </div>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>{t("keepEditing")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={commitMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                commitMutation.mutate();
              }}
            >
              {t("seedDraft")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={cancelDialogOpen} onOpenChange={setCancelDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {session ? t("controlRoom.confirm.cancel.title") : t("cancelSetupTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {session
                ? t("controlRoom.confirm.cancel.description")
                : t("cancelSetupDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={cancelMutation.isPending}>
              {t("keepEditing")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={cancelMutation.isPending}
              className={buttonVariants({ variant: "destructive" })}
              onClick={(event) => {
                event.preventDefault();
                if (session) cancelMutation.mutate();
                else resetSetupState();
              }}
            >
              {session ? t("actions.cancel") : t("discardSetup")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
