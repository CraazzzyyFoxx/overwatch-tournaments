"use client";

import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { AchievementCategory, AchievementRule } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";

import { groupRulesByCategory } from "../achievement-form.model";

/**
 * Picks the scope of an evaluation run. An empty selection means "everything",
 * which is why the count reads "all" rather than "0 selected". Mounted only
 * while open.
 */
export function EvaluateAchievementsDialog({
  onClose,
  tournaments,
  rules,
  tournamentId,
  onTournamentChange,
  selectedRuleIds,
  onSelectedRuleIdsChange,
  onRun,
  isRunning,
}: Readonly<{
  onClose: () => void;
  tournaments: Tournament[];
  rules: AchievementRule[];
  tournamentId?: number;
  onTournamentChange: (id?: number) => void;
  selectedRuleIds: Set<number>;
  onSelectedRuleIdsChange: (next: Set<number>) => void;
  onRun: () => void;
  isRunning: boolean;
}>) {
  const t = useTranslations("adminAchievements");
  const rulesByCategory = groupRulesByCategory(rules);

  const toggleCategory = (category: string, checked: boolean) => {
    const next = new Set(selectedRuleIds);
    (rulesByCategory[category] ?? []).forEach((rule) =>
      checked ? next.add(rule.id) : next.delete(rule.id),
    );
    onSelectedRuleIdsChange(next);
  };

  const toggleRule = (ruleId: number, checked: boolean) => {
    const next = new Set(selectedRuleIds);
    if (checked) next.add(ruleId);
    else next.delete(ruleId);
    onSelectedRuleIdsChange(next);
  };

  return (
    <EntityFormDialog
      open
      onOpenChange={(next) => !next && onClose()}
      title={t("evaluateDialog.title")}
      description={t("evaluateDialog.description")}
      onSubmit={onRun}
      submitLabel={t("evaluation.run")}
      submittingLabel={t("common.evaluating")}
      isSubmitting={isRunning}
    >
      <div className="space-y-2">
        <Label htmlFor="eval-tournament">{t("evaluateDialog.tournamentOptional")}</Label>
        <TournamentCombobox
          id="eval-tournament"
          tournaments={tournaments}
          value={tournamentId}
          onValueChange={onTournamentChange}
          placeholder={t("evaluateDialog.allTournaments")}
          size="default"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">
            {t.rich("evaluateDialog.achievementSelection", {
              count: selectedRuleIds.size,
              num: (chunks) => <span className="tabular-nums text-muted-foreground">{chunks}</span>,
            })}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onSelectedRuleIdsChange(new Set(rules.map((r) => r.id)))}
            >
              {t("evaluateDialog.selectAll")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onSelectedRuleIdsChange(new Set())}
            >
              {t("evaluateDialog.clear")}
            </Button>
          </div>
        </div>
        <ScrollArea className="h-[50vh] rounded border p-3">
          <div className="space-y-3">
            {Object.entries(rulesByCategory).map(([category, categoryRules]) => {
              const allChecked = categoryRules.every((r) => selectedRuleIds.has(r.id));
              const someChecked = categoryRules.some((r) => selectedRuleIds.has(r.id));
              return (
                <div key={category}>
                  <div className="flex items-center gap-2 mb-1">
                    <Checkbox
                      checked={allChecked ? true : someChecked ? "indeterminate" : false}
                      onCheckedChange={(checked) => toggleCategory(category, !!checked)}
                      aria-label={t("evaluateDialog.selectEvery", { category: t(`common.categoryValues.${category as AchievementCategory}`) })}
                    />
                    <span className="text-sm font-medium">
                      {t(`common.categoryValues.${category as AchievementCategory}`)}{" "}
                      <span className="tabular-nums text-muted-foreground">({categoryRules.length})</span>
                    </span>
                  </div>
                  <div className="ml-6 grid grid-cols-2 gap-1">
                    {categoryRules.map((rule) => (
                      <label key={rule.id} className="flex items-center gap-2 text-xs cursor-pointer">
                        <Checkbox
                          checked={selectedRuleIds.has(rule.id)}
                          onCheckedChange={(checked) => toggleRule(rule.id, !!checked)}
                          aria-label={t("evaluateDialog.evaluate", { name: rule.name })}
                        />
                        <span className="truncate">{rule.slug}</span>
                      </label>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </div>
    </EntityFormDialog>
  );
}
