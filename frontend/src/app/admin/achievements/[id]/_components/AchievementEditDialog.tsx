"use client";

import { useRef } from "react";
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
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  ACHIEVEMENT_IMAGE_ACCEPT,
  ACHIEVEMENT_IMAGE_PREVIEW_CLASS,
  MAX_ACHIEVEMENT_IMAGE_BYTES
} from "@/lib/uploads";
import type {
  AchievementCategory,
  AchievementGrain,
  AchievementRuleUpdateInput,
  AchievementScope
} from "@/types/admin.types";

import { CATEGORIES, GRAINS, SCOPES } from "../../achievement-meta";

/** Metadata only — the condition tree has its own card on the page. */
export function AchievementEditDialog({
  open,
  onOpenChange,
  slug,
  formData,
  onFormDataChange,
  imagePreview,
  onPickImage,
  onClearImage,
  onSubmit,
  isSubmitting,
  isDirty,
  errorMessage
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  slug: string;
  formData: AchievementRuleUpdateInput;
  onFormDataChange: (next: AchievementRuleUpdateInput) => void;
  imagePreview: string | null;
  onPickImage: (file: File) => void;
  onClearImage: () => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  isDirty: boolean;
  errorMessage?: string;
}>) {
  const imageInputRef = useRef<HTMLInputElement>(null);

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Edit: ${slug}`}
      description="Update achievement metadata"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      isSubmitting={isSubmitting}
      submittingLabel="Updating…"
      errorMessage={errorMessage}
      isDirty={isDirty}
    >
      <ScrollArea className="max-h-[60vh]">
        <div className="space-y-4 pr-4">
          <div className="space-y-2">
            <Label>Name</Label>
            <Input
              value={formData.name ?? ""}
              onChange={(e) => onFormDataChange({ ...formData, name: e.target.value })}
              required
            />
          </div>

          {/* Image upload */}
          <div className="space-y-2">
            <Label>Image</Label>
            <div className="flex items-center gap-4">
              {(imagePreview || formData.image_url) && (
                <img
                  src={imagePreview ?? formData.image_url ?? ""}
                  alt="Achievement"
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
                    if (!file) return;
                    if (file.size > MAX_ACHIEVEMENT_IMAGE_BYTES) {
                      alert("File too large (max 5 MB)");
                      return;
                    }
                    onPickImage(file);
                  }}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => imageInputRef.current?.click()}
                >
                  <Upload className="mr-2 h-4 w-4" />
                  {formData.image_url || imagePreview ? "Change Image" : "Upload Image"}
                </Button>
                {(imagePreview || formData.image_url) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      onClearImage();
                      onFormDataChange({ ...formData, image_url: null });
                    }}
                  >
                    <X className="mr-2 h-4 w-4" />
                    Remove
                  </Button>
                )}
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Description (RU)</Label>
              <Textarea
                value={formData.description_ru ?? ""}
                onChange={(e) => onFormDataChange({ ...formData, description_ru: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label>Description (EN)</Label>
              <Textarea
                value={formData.description_en ?? ""}
                onChange={(e) => onFormDataChange({ ...formData, description_en: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label>Category</Label>
              <Select
                value={formData.category ?? "overall"}
                onValueChange={(v) =>
                  onFormDataChange({ ...formData, category: v as AchievementCategory })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Scope</Label>
              <Select
                value={formData.scope ?? "global"}
                onValueChange={(v) => onFormDataChange({ ...formData, scope: v as AchievementScope })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SCOPES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Grain</Label>
              <Select
                value={formData.grain ?? "user"}
                onValueChange={(v) => onFormDataChange({ ...formData, grain: v as AchievementGrain })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {GRAINS.map((g) => (
                    <SelectItem key={g} value={g}>
                      {g}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </ScrollArea>
    </EntityFormDialog>
  );
}
