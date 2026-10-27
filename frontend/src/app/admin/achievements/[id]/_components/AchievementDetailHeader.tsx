"use client";

import { useTranslations } from "next-intl";
import { MoreHorizontal } from "lucide-react";

import { EntityHubHeader } from "@/components/kit/EntityHubHeader";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/spinner";
import type { AchievementRule } from "@/types/admin.types";

/**
 * The rule's hub header: name, slug, a pill only when the rule is disabled.
 * The two per-rule tasks (test, run) sit beside Edit, the primary action, and
 * say so while they run; enabling and deletion are in the menu.
 */
export function AchievementDetailHeader({
  rule,
  canUpdate,
  canDelete,
  isTesting,
  isEvaluating,
  onTest,
  onEvaluate,
  onToggle,
  onEdit,
  onDelete,
}: Readonly<{
  rule: AchievementRule;
  canUpdate: boolean;
  canDelete: boolean;
  isTesting: boolean;
  isEvaluating: boolean;
  onTest: () => void;
  onEvaluate: () => void;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}>) {
  const t = useTranslations("adminAchievements");
  return (
    <EntityHubHeader
      backHref="/admin/achievements"
      title={rule.name}
      status={rule.enabled ? undefined : { label: t("common.disabled"), tone: "neutral" }}
      meta={[<span key="slug" className="font-mono text-caption">{rule.slug}</span>]}
      actions={
        <>
          <Button variant="outline" onClick={onTest} disabled={isTesting}>
            {isTesting && <Spinner />}
            {isTesting ? t("common.testing") : t("detail.testConditions")}
          </Button>
          <Button variant="outline" onClick={onEvaluate} disabled={isEvaluating}>
            {isEvaluating && <Spinner />}
            {isEvaluating ? t("common.evaluating") : t("detail.runEvaluation")}
          </Button>
          {canUpdate && <Button onClick={onEdit}>{t("detail.editAchievement")}</Button>}
          {(canUpdate || canDelete) && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label={t("common.moreActions")}
                  title={t("common.moreActions")}
                >
                  <MoreHorizontal className="h-4 w-4" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {canUpdate && (
                  <DropdownMenuItem onSelect={onToggle}>
                    {rule.enabled ? t("detail.disableAchievement") : t("detail.enableAchievement")}
                  </DropdownMenuItem>
                )}
                {canUpdate && canDelete && <DropdownMenuSeparator />}
                {canDelete && (
                  <DropdownMenuItem onSelect={onDelete} variant="destructive">
                    {t("detail.deleteAchievement")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </>
      }
    />
  );
}
