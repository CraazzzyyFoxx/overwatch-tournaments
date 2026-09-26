"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import type {
  AchievementOverrideCreateInput,
  AchievementRuleExportEnvelope,
  AchievementRuleImportResult,
  EvaluationRunRead,
} from "@/types/admin.types";

export interface DryRunResult {
  slug: string;
  count: number;
  sample: number[][];
}

/**
 * Everything the achievements screen *does* to the catalog: seeding, resetting,
 * JSON import/export, evaluation runs, dry runs, enable/disable, deletion and
 * manual overrides.
 *
 * The outcomes each action leaves on screen (the run summary, the import
 * report, the dry-run sample) are held here too — they are mutation results,
 * not page state, and nothing else decides when they appear.
 */
export function useAchievementRuleActions({
  workspaceId,
  /**
   * The hidden picker behind "Import JSON". Its value is cleared once a file
   * has been read, or the same file can never be picked twice in a row. It is
   * owned by the page: a ref handed back out of a hook makes everything else
   * the hook returns look ref-shaped to the compiler.
   */
  jsonInputRef,
  onDeleted,
  onEvaluated,
  onOverrideSaved,
  onOverrideRemoved,
}: {
  workspaceId: number | null;
  jsonInputRef: React.RefObject<HTMLInputElement | null>;
  onDeleted: () => void;
  onEvaluated: () => void;
  onOverrideSaved: () => void;
  onOverrideRemoved: () => void;
}) {
  const queryClient = useQueryClient();
  const listKey = achievementQueryKeys.adminList(workspaceId);

  const [evaluationResult, setEvaluationResult] = useState<EvaluationRunRead | null>(null);
  const [importResult, setImportResult] = useState<AchievementRuleImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<DryRunResult | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteAchievementRule(workspaceId!, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listKey });
      onDeleted();
    },
  });

  const seedMutation = useMutation({
    mutationFn: () => adminService.seedAchievementRules(workspaceId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKey }),
  });

  const hardResetMutation = useMutation({
    mutationFn: () => adminService.hardResetAchievementRules(workspaceId!),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: listKey });
      queryClient.invalidateQueries({ queryKey: achievementQueryKeys.overridesAll(workspaceId) });
      setEvaluationResult(data.run);
    },
  });

  const importMutation = useMutation({
    mutationFn: (data: AchievementRuleExportEnvelope) =>
      adminService.importAchievementRules(workspaceId!, data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: listKey });
      setImportResult(data);
      if (jsonInputRef.current) {
        jsonInputRef.current.value = "";
      }
    },
  });

  const evaluateMutation = useMutation({
    mutationFn: (params: { tournament_id?: number; rule_ids?: number[] }) =>
      adminService.evaluateAchievements(workspaceId!, params),
    onSuccess: (data) => {
      setEvaluationResult(data);
      onEvaluated();
    },
  });

  const testMutation = useMutation({
    mutationFn: (ruleId: number) => adminService.testAchievementRule(workspaceId!, ruleId),
    onSuccess: (data) =>
      setTestResult({ slug: data.rule_slug, count: data.qualifying_count, sample: data.sample }),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      adminService.updateAchievementRule(workspaceId!, id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKey }),
  });

  const overrideMutation = useMutation({
    mutationFn: (draft: AchievementOverrideCreateInput) =>
      adminService.createAchievementOverride(workspaceId!, draft),
    onSuccess: onOverrideSaved,
  });

  const deleteOverrideMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteAchievementOverride(workspaceId!, id),
    onSuccess: onOverrideRemoved,
  });

  /** Streams the workspace's rules to the browser as the JSON the importer reads back. */
  const exportRules = async () => {
    const { blob, filename } = await adminService.exportAchievementRules(workspaceId!);
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  };

  /**
   * Parses a picked export file and imports it. A parse failure is reported
   * rather than thrown: the likely cause is the wrong file, and the admin needs
   * to be told which one they picked.
   */
  const importRulesFromFile = async (file: File) => {
    setImportError(null);
    const text = await file.text();
    let parsed: AchievementRuleExportEnvelope;
    try {
      parsed = JSON.parse(text) as AchievementRuleExportEnvelope;
    } catch {
      setImportError(
        `“${file.name}” is not valid JSON. Import a file produced by Export JSON on this page, unedited.`,
      );
      if (jsonInputRef.current) {
        jsonInputRef.current.value = "";
      }
      return;
    }
    importMutation.mutate(parsed);
  };

  const evaluate = (tournamentId: number | undefined, ruleIds: Set<number>) =>
    evaluateMutation.mutate({
      tournament_id: tournamentId,
      rule_ids: ruleIds.size > 0 ? Array.from(ruleIds) : undefined,
    });

  return {
    evaluationResult,
    dismissEvaluationResult: () => setEvaluationResult(null),
    importResult,
    dismissImportResult: () => setImportResult(null),
    /** The library dialog imports through its own mutation and reports back here. */
    setImportResult,
    importError,
    dismissImportError: () => setImportError(null),
    testResult,
    dismissTestResult: () => setTestResult(null),
    deleteMutation,
    seedMutation,
    hardResetMutation,
    importMutation,
    evaluateMutation,
    testMutation,
    toggleMutation,
    overrideMutation,
    deleteOverrideMutation,
    exportRules,
    importRulesFromFile,
    evaluate,
  };
}
