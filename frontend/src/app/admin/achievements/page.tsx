"use client";

import { useId, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { MoreHorizontal, Play, Plus } from "lucide-react";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { EvaluationRunSummary } from "@/components/admin/achievements/EvaluationRunSummary";
import { gameFilterDefs } from "@/components/admin/game-filter";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters } from "@/components/kit/useFilters";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/spinner";
import { GameScopeGate } from "@/components/workspace/GameScopeGate";
import { useGameScope } from "@/hooks/useGameScope";
import { usePermissions } from "@/hooks/usePermissions";
import { defaultCreationGame, showsGameMarks } from "@/lib/site/discipline-scope";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { AchievementRule } from "@/types/admin.types";

import { AchievementFormDialog } from "./_components/AchievementFormDialog";
import { AchievementImportDialog } from "./_components/AchievementImportDialog";
import { AchievementOverridesCard } from "./_components/AchievementOverridesCard";
import { AchievementsTable } from "./_components/AchievementsTable";
import { DryRunResultPanel } from "./_components/DryRunResultPanel";
import { EvaluateAchievementsDialog } from "./_components/EvaluateAchievementsDialog";
import { useAchievementCatalog } from "./_hooks/useAchievementCatalog";
import { useAchievementRuleActions } from "./_hooks/useAchievementRuleActions";
import { useAchievementRuleForm } from "./_hooks/useAchievementRuleForm";

/** The one confirmation the page can ask for, with its subject. */
type Confirmation = { kind: "delete"; rule: AchievementRule } | { kind: "reset" };

/** A per-game bulk action (spec §7.1). Without a filtered game it is disabled and says why on a second line. */
function PerGameItem({
  game,
  onSelect,
  disabled = false,
  variant,
  children,
}: Readonly<{ game: string | null; onSelect: () => void; disabled?: boolean; variant?: "default" | "destructive"; children: ReactNode }>) {
  const t = useTranslations("common.discipline");
  return (
    <DropdownMenuItem onSelect={onSelect} disabled={disabled || game === null} variant={variant}>
      {game === null ? (
        <span>
          {children}
          <span className="block text-caption text-muted-foreground">{t("pickGameAction")}</span>
        </span>
      ) : (
        children
      )}
    </DropdownMenuItem>
  );
}

/**
 * The workspace's achievement rules: a multi page (spec §6.10). The game select in the filter bar narrows them to
 * one game; without it every game's rules with a "Game" column, and the bulk actions that act on one game's rules
 * wait for a game; a row acts in its own game.
 */
export default function AchievementsPage() {
  const t = useTranslations("adminAchievements");
  const router = useRouter();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const tGame = useTranslations("common.discipline");
  const scope = useGameScope({ axis: workspaceId ?? "all" });
  // The select writes `?discipline=`, which the scope reads back. `null`: every game; a code: that game's rules only.
  const game = scope.game;
  const gameDefs = gameFilterDefs(scope.games, tGame("column"), undefined, tGame("all"));
  const evaluateReasonId = useId();
  const filters = useFilters(gameDefs);
  const games = (scope.games ?? []).filter((entry) => entry.enabled);
  const showGame = scope.resolution !== null && showsGameMarks(scope.resolution, scope.games ?? []);

  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  // One domain dialog at a time; it is mounted only while open.
  const [dialog, setDialog] = useState<"evaluate" | "import" | null>(null);
  const [evalTournamentId, setEvalTournamentId] = useState<number | undefined>(undefined);
  const [evalSelectedRuleIds, setEvalSelectedRuleIds] = useState<Set<number>>(new Set());
  // The game an evaluation runs in: the page's, or under "all games" the evaluated rule's own.
  const [evalGame, setEvalGame] = useState<string | null>(null);
  const actionGame = game ?? evalGame;

  const canCreate = canAccessPermission("achievement.create", workspaceId);
  const canUpdate = canAccessPermission("achievement.update", workspaceId);
  const canDelete = canAccessPermission("achievement.delete", workspaceId);

  const { tournaments, overrides, allRules } = useAchievementCatalog({
    workspaceId,
    discipline: actionGame,
    pickersOpen: dialog === "evaluate",
  });
  // Evaluating names a tournament: only the evaluated game's can be one.
  const tournamentOptions = (tournaments?.results ?? []).filter((tournament) => tournament.discipline === actionGame);

  // Everything the page holds for one game — picked rules, the tournament, an open dialog — is that game's: when
  // the game (or the workspace) changes, it is dropped rather than carried into the next one.
  const scopeKey = `${workspaceId}:${game}`;
  const [heldScopeKey, setHeldScopeKey] = useState(scopeKey);
  if (heldScopeKey !== scopeKey) {
    setHeldScopeKey(scopeKey);
    setConfirmation(null);
    setDialog(null);
    setEvalTournamentId(undefined);
    setEvalSelectedRuleIds(new Set());
    setEvalGame(null);
  }

  // A new rule starts in the filtered game, else the first enabled one (spec §7.2); its game field can change it.
  const createGame = defaultCreationGame(game, games);
  const form = useAchievementRuleForm(workspaceId, createGame);

  const actions = useAchievementRuleActions({
    workspaceId,
    discipline: actionGame,
    onDeleted: () => setConfirmation(null),
    onEvaluated: () => {
      setDialog(null);
      setEvalGame(null);
    },
  });

  const openEvaluate = (ruleIds: Set<number>, ruleGame: string) => {
    setEvalGame(ruleGame);
    setEvalSelectedRuleIds(ruleIds);
    setEvalTournamentId(undefined);
    setDialog("evaluate");
  };

  const closeEvaluate = () => {
    setDialog(null);
    setEvalGame(null);
  };

  const closeImport = () => {
    setDialog(null);
    actions.dismissImportResult();
    actions.dismissImportError();
  };

  if (!workspaceId) {
    return (
      <div className="space-y-6">
        <AdminPageHeader title={t("common.achievements")} />
        <EmptyNote>{t("list.selectWorkspace")}</EmptyNote>
      </div>
    );
  }

  const resolved = scope.resolution?.game.kind === "all" || scope.resolution?.game.kind === "game";
  const busy = actions.seedMutation.isPending || actions.hardResetMutation.isPending;

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title={t("common.achievements")}
        actions={
          <>
            {resolved && (
              <>
                {game === null && (
                  <p id={evaluateReasonId} className="text-caption text-muted-foreground">
                    {tGame("pickGameAction")}
                  </p>
                )}
                <Button
                  variant="outline"
                  disabled={game === null}
                  aria-describedby={game === null ? evaluateReasonId : undefined}
                  onClick={() => game && openEvaluate(new Set(), game)}
                >
                  <Play className="mr-2 h-4 w-4" aria-hidden />
                  {t("list.evaluate")}
                </Button>
              </>
            )}
            {/* A new rule picks its game in the form: only a workspace with no game yet has nowhere to file it. */}
            {canCreate && (
              <Button onClick={form.openCreate} disabled={createGame === null}>
                <Plus className="mr-2 h-4 w-4" aria-hidden />
                {t("list.create")}
              </Button>
            )}
            {resolved && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label={t("common.moreActions")}
                    title={t("common.moreActions")}
                  >
                    {busy ? <Spinner /> : <MoreHorizontal className="h-4 w-4" aria-hidden />}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <PerGameItem game={game} onSelect={() => void actions.exportRules()}>
                    {t("list.exportJson")}
                  </PerGameItem>
                  {(canCreate || canUpdate) && (
                    <DropdownMenuItem onSelect={() => setDialog("import")}>{t("list.import")}</DropdownMenuItem>
                  )}
                  {canCreate && (
                    <>
                      <PerGameItem game={game} onSelect={() => actions.seed()} disabled={busy}>
                        {t("list.seedDefaults")}
                      </PerGameItem>
                      <DropdownMenuSeparator />
                      <PerGameItem
                        game={game}
                        onSelect={() => setConfirmation({ kind: "reset" })}
                        disabled={busy}
                        variant="destructive"
                      >
                        {t("list.hardReset")}
                      </PerGameItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </>
        }
      />

      <GameScopeGate scope={scope}>
        {() => (
          <>
            {actions.evaluationResult && (
              <EvaluationRunSummary
                run={actions.evaluationResult}
                onDismiss={actions.dismissEvaluationResult}
                tournamentName={
                  tournaments?.results.find(
                    (tournament) => tournament.id === actions.evaluationResult?.tournament_id,
                  )?.name
                }
              />
            )}

            {/* Pending from the moment a row's Test starts; it brings itself into view. */}
            {(actions.testMutation.isPending || actions.testResult) && (
              <DryRunResultPanel result={actions.testResult} onDismiss={actions.dismissTestResult} />
            )}

            <AchievementsTable
              workspaceId={workspaceId}
              discipline={game}
              showGame={showGame}
              toolbar={gameDefs.length > 0 ? <FilterBar defs={gameDefs} filters={filters} /> : undefined}
              actions={{
                canUpdate,
                canDelete,
                onOpen: (rule) => router.push(`/admin/achievements/${rule.id}`),
                onEdit: form.openEdit,
                onTest: (rule) => actions.testMutation.mutate(rule.id),
                onEvaluate: (rule) => openEvaluate(new Set([rule.id]), rule.discipline),
                onToggle: (rule) => actions.toggle(rule, !rule.enabled),
                onDelete: (rule) => setConfirmation({ kind: "delete", rule }),
              }}
            />

            {/* Manual overrides are read one game at a time: the card waits for a filtered game. */}
            {game !== null && overrides && overrides.length > 0 && (
              <AchievementOverridesCard
                overrides={overrides}
                rules={allRules ?? []}
                tournaments={tournamentOptions}
                onDelete={(id) => actions.removeOverride(id)}
                isDeleting={actions.deleteOverrideMutation.isPending}
              />
            )}

            {dialog === "evaluate" && (
              <EvaluateAchievementsDialog
                onClose={closeEvaluate}
                tournaments={tournamentOptions}
                rules={allRules ?? []}
                tournamentId={evalTournamentId}
                onTournamentChange={setEvalTournamentId}
                selectedRuleIds={evalSelectedRuleIds}
                onSelectedRuleIdsChange={setEvalSelectedRuleIds}
                onRun={() => actions.evaluate(evalTournamentId, evalSelectedRuleIds)}
                isRunning={actions.evaluateMutation.isPending}
              />
            )}

            {dialog === "import" && (
              <AchievementImportDialog
                onClose={closeImport}
                workspaceId={workspaceId}
                discipline={game}
                onImportFile={(file) => void actions.importRulesFromFile(file)}
                isImportingFile={actions.importMutation.isPending}
                result={actions.importResult}
                error={actions.importError}
                onImported={actions.setImportResult}
              />
            )}
          </>
        )}
      </GameScopeGate>

      <AchievementFormDialog form={form} games={games} />

      <ConfirmDialog
        open={confirmation !== null}
        onOpenChange={(open) => !open && setConfirmation(null)}
        onConfirm={() => {
          if (confirmation?.kind === "delete") {
            actions.remove(confirmation.rule);
          } else {
            setConfirmation(null);
            actions.hardReset();
          }
        }}
        pending={confirmation?.kind === "delete" ? actions.deleteMutation.isPending : actions.hardResetMutation.isPending}
        intent={
          confirmation?.kind === "delete"
            ? {
                title: t("list.deleteAchievement"),
                description: t("list.deleteDescription", {
                  name: confirmation.rule.name,
                  slug: confirmation.rule.slug,
                }),
                confirmLabel: actions.deleteMutation.isPending ? t("common.deleting") : t("common.delete"),
                tone: "danger",
                cascade: [t("list.deleteCascadeResult"), t("list.deleteCascadeOverride")],
              }
            : {
                title: t("list.resetTitle"),
                description: t("list.resetDescription"),
                confirmLabel: t("list.hardReset"),
                tone: "danger",
                cascade: [t("list.resetCascade")],
              }
        }
      />
    </div>
  );
}
