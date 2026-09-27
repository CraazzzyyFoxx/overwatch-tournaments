"use client";

import Image from "next/image";
import { Upload, X } from "lucide-react";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
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

import { CATEGORIES, GRAINS, SCOPES } from "../achievement-meta";
import type { AchievementRuleForm } from "../_hooks/useAchievementRuleForm";

/**
 * Create and edit share one dialog: the fields are the same, and the only
 * difference is that an existing rule's slug is frozen. The condition tree is
 * not here — it is edited on the rule's own page, where there is room for it.
 */
export function AchievementFormDialog({ form }: Readonly<{ form: AchievementRuleForm }>) {
  const {
    open,
    editingRule,
    formData,
    setFormData,
    imagePreview,
    imageError,
    imageInputRef,
    isDirty,
    isSubmitting,
    error,
    reset,
    pickImage,
    clearImage,
    submit
  } = form;

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
      }}
      title={editingRule ? `Edit ${editingRule.slug}` : "Create achievement"}
      description={
        editingRule
          ? "Update the achievement metadata. The condition tree is edited on its detail page."
          : "Define a new achievement. Add its condition tree once it exists."
      }
      onSubmit={submit}
      isSubmitting={isSubmitting}
      submittingLabel={editingRule ? "Updating…" : "Creating…"}
      errorMessage={error}
      isDirty={isDirty}
    >
      <ScrollArea className="max-h-[60vh]">
        <div className="space-y-4 pr-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="slug">Slug</Label>
              <Input
                id="slug"
                value={(formData as AchievementRuleCreateInput).slug ?? ""}
                onChange={(e) => setFormData({ ...formData, slug: e.target.value })}
                placeholder="my-achievement"
                required
                disabled={!!editingRule}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={formData.name ?? ""}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="Achievement name"
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="desc_ru">Description (RU)</Label>
              <Textarea
                id="desc_ru"
                value={formData.description_ru ?? ""}
                onChange={(e) => setFormData({ ...formData, description_ru: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="desc_en">Description (EN)</Label>
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
              <Label htmlFor="rule-category">Category</Label>
              <Select
                value={formData.category ?? "overall"}
                onValueChange={(v) => setFormData({ ...formData, category: v as AchievementCategory })}
              >
                <SelectTrigger id="rule-category"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="rule-scope">Scope</Label>
              <Select
                value={formData.scope ?? "global"}
                onValueChange={(v) => setFormData({ ...formData, scope: v as AchievementScope })}
              >
                <SelectTrigger id="rule-scope"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SCOPES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="rule-grain">Grain</Label>
              <Select
                value={formData.grain ?? "user"}
                onValueChange={(v) => setFormData({ ...formData, grain: v as AchievementGrain })}
              >
                <SelectTrigger id="rule-grain"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {GRAINS.map((g) => <SelectItem key={g} value={g}>{g}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Image upload */}
          <div className="space-y-2">
            <p className="text-sm font-medium">Image</p>
            <div className="flex items-center gap-4">
              {(imagePreview || formData.image_url) && (
                <Image
                  src={imagePreview ?? (formData.image_url as string) ?? ""}
                  alt={formData.name ? `${formData.name} badge` : "Achievement badge"}
                  width={64}
                  height={64}
                  className={ACHIEVEMENT_IMAGE_PREVIEW_CLASS}
                />
              )}
              <div className="flex flex-col gap-2">
                <input
                  ref={imageInputRef}
                  type="file"
                  accept={ACHIEVEMENT_IMAGE_ACCEPT}
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) pickImage(file);
                  }}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => imageInputRef.current?.click()}
                >
                  <Upload className="mr-2 h-4 w-4" aria-hidden />
                  {imagePreview ? "Change image" : "Upload image"}
                </Button>
                {imagePreview && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={clearImage}
                  >
                    <X className="mr-2 h-4 w-4" aria-hidden />
                    Remove image
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
