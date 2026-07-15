"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  ListChecks,
  Settings2,
  ShieldCheck,
  Sparkles,
  UsersRound
} from "lucide-react";
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
import { Button } from "@/components/ui/button";
import { HeroFrame } from "@/components/site/PageHero";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import balancerAdminService from "@/services/balancer-admin.service";
import draftService from "@/services/draft.service";
import type {
  DraftBoard,
  DraftSeedRequest,
  DraftSeedResponse,
  DraftSession
} from "@/types/draft.types";

import { DraftCaptainsStep } from "./DraftCaptainsStep";
import { DraftConfigStep } from "./DraftConfigStep";
import { DraftOrderStep } from "./DraftOrderStep";
import { DraftPoolStep } from "./DraftPoolStep";
import { DraftReadyStep } from "./DraftReadyStep";
import { DraftReviewStep } from "./DraftReviewStep";
import {
  derivePoolReadiness,
  orderCaptainIds,
  roundsForTeamSize,
  SETUP_STEPS,
  type DraftSetupStep,
  validateSetupStep
} from "./setup-model";
import type { DraftCaptainSetup, DraftSetupConfig } from "./setup-types";
import { isInDraftPool, summarizeRegistration } from "./setup-types";

interface DraftSetupWizardProps {
  tournamentId: number;
  board: DraftBoard | null;
}

const STEP_ICONS = [Settings2, ListChecks, UsersRound, Sparkles, ClipboardCheck, ShieldCheck];

function configFromSession(session: DraftSession | null): DraftSetupConfig {
  const teamSize = session?.team_size ?? 5;
  const roundRules = session?.settings_json?.round_rules;
  const teamCount = session?.settings_json?.team_count;
  return {
    teamSize,
    teamCount: typeof teamCount === "number" ? teamCount : 2,
    pickTimeSeconds: session?.pick_time_seconds ?? 45,
    format: session?.format ?? "snake",
    autopickStrategy: session?.autopick_strategy ?? "best_fit",
    allowAdminOverride: session?.allow_admin_override ?? true,
    roundRules: Array.isArray(roundRules)
      ? roundRules.map(String)
      : Array.from({ length: roundsForTeamSize(teamSize) }, () => "linear")
  };
}

export function DraftSetupWizard({ tournamentId, board }: DraftSetupWizardProps) {
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
  const [config, setConfig] = useState<DraftSetupConfig>(() => configFromSession(initialSession));
  const [captains, setCaptains] = useState<DraftCaptainSetup>(() => ({
    ids: [],
    teamNames: {},
    order: "weakest_first",
    randomSeed: Math.floor(Math.random() * 2_147_483_647)
  }));
  const [preview, setPreview] = useState<DraftSeedResponse | null>(null);
  const [committedFeasibility, setCommittedFeasibility] = useState<DraftSeedResponse["feasibility"] | null>(
    null
  );
  const [reseedDialogOpen, setReseedDialogOpen] = useState(false);

  const poolQuery = useQuery({
    queryKey: ["balancer", "draft-setup-pool", tournamentId],
    queryFn: () => balancerAdminService.listRegistrations(tournamentId, { include_deleted: true })
  });
  const allRegistrations = poolQuery.data ?? [];
  const pool = useMemo(() => allRegistrations.filter(isInDraftPool), [allRegistrations]);

  const hydrateCaptainsFromBoard = () => {
    if (!board || pool.length === 0 || board.teams.length === 0) return;
    const orderedTeams = [...board.teams].sort((left, right) => left.draft_position - right.draft_position);
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
        const summary = summarizeRegistration(registration);
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
  const readiness = useMemo(
    () => derivePoolReadiness(candidates, config.teamCount, config.teamSize),
    [candidates, config.teamCount, config.teamSize]
  );
  const ranks = useMemo(
    () => new Map(pool.map((registration) => [registration.id, summarizeRegistration(registration).rank])),
    [pool]
  );
  const orderedCaptainIds = useMemo(
    () => orderCaptainIds(captains.ids, captains.order, ranks, captains.randomSeed),
    [captains.ids, captains.order, captains.randomSeed, ranks]
  );

  const feasibilityQuery = useQuery({
    queryKey: session ? tournamentQueryKeys.draftFeasibility(session.id) : ["draft", "feasibility", "none"],
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
        rounds: roundsForTeamSize(config.teamSize),
        pick_time_seconds: config.pickTimeSeconds,
        team_size: config.teamSize,
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
  const minimumIndex = session ? 1 : 0;
  const pending =
    createMutation.isPending || previewMutation.isPending || commitMutation.isPending || startMutation.isPending;

  const validationState = {
    teamSize: config.teamSize,
    pickTimeSeconds: config.pickTimeSeconds,
    captainIds: captains.ids,
    poolReady: readiness.blockers.length === 0,
    previewFeasible: preview?.feasibility.is_feasible === true
  };

  const next = async () => {
    if (step === "config") {
      if (validateSetupStep(step, validationState).length > 0 || config.teamCount < 2 || config.teamCount > 12) {
        notify.warning(t("fixStepErrors"));
        return;
      }
      try {
        await ensureSession();
        setStep("pool");
      } catch (error) {
        notify.apiError(error, { title: t("createFailed") });
      }
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
    const nextIndex = Math.max(minimumIndex, currentIndex - 1);
    if (step === "review") setPreview(null);
    setStep(SETUP_STEPS[nextIndex]);
  };

  const setCaptainsAndReset = (nextValue: DraftCaptainSetup) => {
    setCaptains(nextValue);
    setPreview(null);
  };

  return (
    <div className="space-y-5 text-[color:var(--aqt-fg)]">
      <div className="overflow-x-auto pb-1">
        <ol className="flex min-w-[720px] items-center gap-2" aria-label={t("setupSteps")}>
          {SETUP_STEPS.map((entry, index) => {
            const Icon = STEP_ICONS[index];
            const complete = index < currentIndex;
            const active = entry === step;
            const reachable = index <= currentIndex && index >= minimumIndex && entry !== "ready";
            return (
              <li key={entry} className="flex min-w-0 flex-1 items-center gap-2">
                <button
                  type="button"
                  disabled={!reachable || pending}
                  onClick={() => setStep(entry)}
                  aria-current={active ? "step" : undefined}
                  className={cn(
                    "flex min-w-0 flex-1 items-center gap-2 border-y border-[color:var(--aqt-border)] px-3 py-2.5 text-left transition-colors",
                    active && "border-[color:var(--aqt-teal)] bg-[color:var(--aqt-teal)]/8 text-[color:var(--aqt-teal)]",
                    complete && !active && "text-[color:var(--aqt-support)]",
                    !active && !complete && "text-[color:var(--aqt-fg-muted)]",
                    reachable && "hover:border-[color:var(--aqt-teal)]/50",
                    !reachable && "cursor-default"
                  )}
                >
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-[color:var(--aqt-card-2)]">
                    {complete ? <Check className="h-4 w-4 text-[color:var(--aqt-support)]" /> : <Icon className="h-4 w-4" />}
                  </span>
                  <span className="truncate text-xs font-medium">
                    {index + 1}. {t(`steps.${entry}`)}
                  </span>
                </button>
                {index < SETUP_STEPS.length - 1 && <ChevronRight className="h-4 w-4 shrink-0 text-[color:var(--aqt-fg-faint)]" />}
              </li>
            );
          })}
        </ol>
      </div>

      <HeroFrame>
        <div className="border-b border-[color:var(--aqt-border)] px-5 py-5 sm:px-7">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-[color:var(--aqt-teal)]">
                {t("stepOf", { current: currentIndex + 1, total: SETUP_STEPS.length })}
              </p>
              <h2 className="mt-2 font-onest text-2xl font-semibold">{t(`stepTitles.${step}`)}</h2>
              <p className="mt-1 max-w-3xl text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">{t(`stepDescriptions.${step}`)}</p>
            </div>
            {session && (
              <Badge variant="outline">
                {t("sessionNumber", { id: session.id })} · v{session.version}
              </Badge>
            )}
          </div>
        </div>
        <div className="p-4 sm:p-7">
          {step === "config" && (
            <DraftConfigStep value={config} onChange={setConfig} locked={!!session} />
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
            />
          )}
          {step === "order" && (
            <DraftOrderStep
              value={captains}
              onChange={setCaptainsAndReset}
              pool={pool}
              rounds={roundsForTeamSize(config.teamSize)}
              format={config.format}
              roundRules={config.roundRules}
            />
          )}
          {step === "review" && (
            <DraftReviewStep
              config={config}
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

        {step !== "ready" && (
          <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]/95 px-4 py-3 backdrop-blur supports-[padding:max(0px)]:pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-7">
            <Button
              type="button"
              variant="ghost"
              disabled={pending || currentIndex <= minimumIndex}
              onClick={back}
            >
              <ChevronLeft className="mr-2 h-4 w-4" />
              {t("back")}
            </Button>
            <Button
              type="button"
              disabled={pending || (step === "review" && !reviewReady)}
              onClick={() => void next()}
            >
              {step === "review" ? t(isReseed ? "confirmReseed" : "makeReady") : t("continue")}
              {step !== "review" && <ChevronRight className="ml-2 h-4 w-4" />}
            </Button>
          </div>
        )}
      </HeroFrame>

      <AlertDialog open={reseedDialogOpen} onOpenChange={setReseedDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("reseedConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("reseedConfirmDescription")}</AlertDialogDescription>
          </AlertDialogHeader>
          {preview && (
            <div className="grid grid-cols-3 gap-2 rounded-xl bg-muted/50 p-3 text-center text-sm">
              <div>{t("teams")}: {preview.diff.teams_before} → {preview.diff.teams_after}</div>
              <div>{t("players")}: {preview.diff.players_before} → {preview.diff.players_after}</div>
              <div>{t("picks")}: {preview.diff.picks_before} → {preview.diff.picks_after}</div>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={commitMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                commitMutation.mutate();
              }}
            >
              {t("confirmReseed")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
