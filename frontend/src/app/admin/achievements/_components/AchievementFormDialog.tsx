"use client";

import Image from "@/components/ui/image";
import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { InspectorField } from "@/components/kit/InspectorField";
import { Button } from "@/components/ui/button";
import { FileButton } from "@/components/ui/file-button";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { GameField } from "@/components/workspace/GameField";
import {
  ACHIEVEMENT_IMAGE_ACCEPT,
  ACHIEVEMENT_IMAGE_PREVIEW_CLASS,
} from "@/lib/uploads";
import type {
  AchievementCategory,
  AchievementGrain,
  AchievementRuleCreateInput,
  AchievementScope,
} from "@/types/admin.types";
import type { DisciplineDescriptor } from "@/types/discipline.types";

import { CATEGORIES, GRAINS, SCOPES } from "../achievement-meta";
import type { AchievementRuleForm } from "../_hooks/useAchievementRuleForm";
import { useDisciplineLabel } from "../_hooks/useDisciplineLabel";
import { RuleEntityField } from "./RuleEntityField";

/**
 * Create and edit share one dialog, on the list and on a rule's own page: the
 * fields are the same, and the only difference is that an existing rule's slug
 * is frozen. An existing rule's game is its own and immutable, so it is stated;
 * a new rule picks it in the game field (spec §7.2). The condition tree is not
 * here — it is edited on the rule's own page, where there is room for it.
 */
export function AchievementFormDialog({
  form,
  games = [],
}: Readonly<{ form: AchievementRuleForm; games?: DisciplineDescriptor[] }>) {
  const t = useTranslations("adminAchievements");
  const {
    open,
    editingRule,
    formData,
    setFormData,
    imagePreview,
    imageError,
    isDirty,
    isSubmitting,
    error,
    reset,
    pickImage,
    clearImage,
    submit,
    discipline
  } = form;
  const disciplineLabel = useDisciplineLabel();

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
      }}
      title={editingRule ? t("form.editTitle", { slug: editingRule.slug }) : t("form.createTitle")}
      description={
        editingRule
          ? t("form.editDescription")
          : t("form.createDescription")
      }
      onSubmit={submit}
      isSubmitting={isSubmitting}
      errorMessage={error}
      isDirty={isDirty}
    >
      <ScrollArea className="max-h-[60vh]">
        <div className="space-y-4 pr-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="slug">{t("common.slug")}</Label>
              <Input
                id="slug"
                value={(formData as AchievementRuleCreateInput).slug ?? ""}
                onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                required
                disabled={!!editingRule}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="name">{t("common.name")}</Label>
              <Input
                id="name"
                value={formData.name ?? ""}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            {discipline && !editingRule && games.length > 1 ? (
              <GameField
                id="rule-game"
                games={games}
                value={discipline}
                onChange={form.chooseDiscipline}
                disabled={isSubmitting}
              />
            ) : discipline ? (
              <InspectorField label={t("form.discipline")}>{disciplineLabel(discipline)}</InspectorField>
            ) : null}
            {discipline && (
              <RuleEntityField
                discipline={discipline}
                value={formData.entity_id}
                onChange={(entity_id) => setFormData({ ...formData, entity_id })}
              />
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="desc_ru">{t("common.descriptionRu")}</Label>
              <Textarea
                id="desc_ru"
                value={formData.description_ru ?? ""}
                onChange={(e) => setFormData({ ...formData, description_ru: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="desc_en">{t("common.descriptionEn")}</Label>
              <Textarea
                id="desc_en"
                value={formData.description_en ?? ""}
                onChange={(e) => setFormData({ ...formData, description_en: e.target.value })}
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="rule-category">{t("common.category")}</Label>
              <Select
                value={formData.category ?? "overall"}
                onValueChange={(v) => setFormData({ ...formData, category: v as AchievementCategory })}
              >
                <SelectTrigger id="rule-category"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{t(`common.categoryValues.${c}`)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="rule-scope">{t("common.scope")}</Label>
              <Select
                value={formData.scope ?? "global"}
                onValueChange={(v) => setFormData({ ...formData, scope: v as AchievementScope })}
              >
                <SelectTrigger id="rule-scope"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SCOPES.map((s) => <SelectItem key={s} value={s}>{t(`common.scopeValues.${s}`)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="rule-grain">{t("common.grain")}</Label>
              <Select
                value={formData.grain ?? "user"}
                onValueChange={(v) => setFormData({ ...formData, grain: v as AchievementGrain })}
              >
                <SelectTrigger id="rule-grain"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {GRAINS.map((g) => <SelectItem key={g} value={g}>{t(`common.grainValues.${g}`)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Image upload */}
          <div className="space-y-2">
            <p className="text-sm font-medium">{t("common.image")}</p>
            <div className="flex items-center gap-4">
              {(imagePreview || formData.image_url) && (
                <Image
                  src={imagePreview ?? (formData.image_url as string) ?? ""}
                  alt={formData.name ? t("form.namedBadge", { name: formData.name }) : t("form.badgeAlt")}
                  width={64}
                  height={64}
                  className={ACHIEVEMENT_IMAGE_PREVIEW_CLASS}
                />
              )}
              <div className="flex flex-col gap-2">
                <FileButton
                  accept={ACHIEVEMENT_IMAGE_ACCEPT}
                  variant="outline"
                  size="sm"
                  onFiles={([file]) => pickImage(file)}
                >
                  {imagePreview || formData.image_url ? t("form.changeImage") : t("form.uploadImage")}
                </FileButton>
                {(imagePreview || formData.image_url) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      clearImage();
                      if (formData.image_url) setFormData({ ...formData, image_url: null });
                    }}
                  >
                    {t("form.removeImage")}
                  </Button>
                )}
              </div>
            </div>
            {imageError && <p className="text-sm text-danger">{imageError}</p>}
          </div>
        </div>
      </ScrollArea>
    </EntityFormDialog>
  );
}
