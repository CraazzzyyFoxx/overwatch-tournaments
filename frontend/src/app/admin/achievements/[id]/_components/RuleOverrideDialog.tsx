"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { UserSearchCombobox } from "@/components/kit/ServerSearchCombobox";
import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { AchievementOverrideCreateInput } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";

/** The draft an admin is filling in, before it becomes an override on this rule. */
export interface RuleOverrideDraft {
  userId?: number;
  userName: string;
  action: "grant" | "revoke";
  reason: string;
  tournamentId?: number;
}

/**
 * Grants or revokes one rule for one player by hand. Overrides are made from
 * the rule's own page, so the rule is fixed; the tournaments offered are that
 * rule's game's. Missing fields are named on submit rather than by disabling
 * the button, so the reader sees what is missing instead of guessing.
 */
export function RuleOverrideDialog({
  open,
  onOpenChange,
  ruleId,
  ruleName,
  tournaments,
  draft,
  onDraftChange,
  onSubmit,
  isSaving,
  saveError,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ruleId: number;
  ruleName: string;
  tournaments: Tournament[];
  draft: RuleOverrideDraft;
  onDraftChange: (next: RuleOverrideDraft) => void;
  onSubmit: (input: AchievementOverrideCreateInput) => void;
  isSaving: boolean;
  saveError?: string;
}>) {
  const t = useTranslations("adminAchievements");
  const [formError, setFormError] = useState<string | null>(null);

  const submit = () => {
    const missing = [
      draft.userId ? null : t("overrideDialog.missingUser"),
      draft.reason.trim() ? null : t("overrideDialog.missingReason"),
    ].filter((label): label is string => label !== null);
    if (missing.length > 0) {
      setFormError(t("overrideDialog.pickFirst", { items: missing.join(", ") }));
      return;
    }
    setFormError(null);
    onSubmit({
      achievement_rule_id: ruleId,
      user_id: draft.userId!,
      tournament_id: draft.tournamentId ?? null,
      action: draft.action,
      reason: draft.reason,
    });
  };

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setFormError(null);
        onOpenChange(next);
      }}
      title={t("overrideDialog.title", { name: ruleName })}
      description={t("overrideDialog.description")}
      onSubmit={submit}
      isSubmitting={isSaving}
      submitLabel={
        draft.action === "grant" ? t("overrideDialog.grantAchievement") : t("overrideDialog.revokeAchievement")
      }
      errorMessage={
        formError ?? (saveError ? t("overrideDialog.saveError", { error: saveError }) : undefined)
      }
      contentClassName="max-w-lg"
    >
      <div className="space-y-2">
        <Label htmlFor="override-user">{t("overrideDialog.user")}</Label>
        <UserSearchCombobox
          id="override-user"
          value={draft.userId}
          selectedLabel={draft.userName}
          onSelect={(user) => onDraftChange({ ...draft, userId: user?.id, userName: user?.name ?? "" })}
        />
      </div>
      <div className="space-y-2">
        <span id="override-action" className="block text-sm font-medium leading-none">
          {t("overrideDialog.action")}
        </span>
        <ToggleGroup
          variant="pill"
          size="sm"
          aria-labelledby="override-action"
          value={draft.action}
          onValueChange={(action) => onDraftChange({ ...draft, action: action as RuleOverrideDraft["action"] })}
        >
          <ToggleGroupItem value="grant">{t("overrideDialog.grant")}</ToggleGroupItem>
          <ToggleGroupItem value="revoke">{t("overrideDialog.revoke")}</ToggleGroupItem>
        </ToggleGroup>
      </div>
      <div className="space-y-2">
        <Label htmlFor="override-tournament">{t("overrideDialog.tournamentOptional")}</Label>
        <TournamentCombobox
          id="override-tournament"
          tournaments={tournaments}
          value={draft.tournamentId}
          onValueChange={(tournamentId) => onDraftChange({ ...draft, tournamentId })}
          placeholder={t("overrideDialog.none")}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="override-reason">{t("overrideDialog.reason")}</Label>
        <Textarea
          id="override-reason"
          value={draft.reason}
          onChange={(e) => onDraftChange({ ...draft, reason: e.target.value })}
        />
      </div>
    </EntityFormDialog>
  );
}
