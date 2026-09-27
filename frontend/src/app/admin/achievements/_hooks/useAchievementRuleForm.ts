"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { hasUnsavedChanges } from "@/lib/form-change";
import { MAX_ACHIEVEMENT_IMAGE_BYTES } from "@/lib/uploads";
import type {
  AchievementRule,
  AchievementRuleCreateInput,
  AchievementRuleUpdateInput,
} from "@/types/admin.types";

import {
  achievementFormDataWithSlug,
  emptyAchievementForm,
} from "../achievement-form.model";

/** What the create/edit dialog needs from the hook driving it. */
export interface AchievementRuleForm {
  open: boolean;
  editingRule: AchievementRule | null;
  formData: AchievementRuleCreateInput | AchievementRuleUpdateInput;
  setFormData: (data: AchievementRuleCreateInput | AchievementRuleUpdateInput) => void;
  imagePreview: string | null;
  imageError: string | null;
  imageInputRef: React.RefObject<HTMLInputElement | null>;
  isDirty: boolean;
  isSubmitting: boolean;
  /** Message of the failed create or update, whichever the dialog is running. */
  error?: string;
  openCreate: () => void;
  openEdit: (rule: AchievementRule) => void;
  /** Closes the dialog and drops the draft, image included. */
  reset: () => void;
  pickImage: (file: File) => void;
  clearImage: () => void;
  submit: (event: React.FormEvent) => void;
}

/**
 * The create/edit dialog's state and the two mutations behind it. Creating with
 * an image is two round-trips — the rule has to exist before its badge can be
 * uploaded against its slug — so the upload lives inside the create mutation
 * rather than in a second call site.
 */
export function useAchievementRuleForm(workspaceId: number | null): AchievementRuleForm {
  const queryClient = useQueryClient();
  const listKey = achievementQueryKeys.adminList(workspaceId);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<AchievementRule | null>(null);
  const [formData, setFormData] = useState<AchievementRuleCreateInput | AchievementRuleUpdateInput>({
    ...emptyAchievementForm,
  });
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const createMutation = useMutation({
    mutationFn: async (data: AchievementRuleCreateInput) => {
      const created = await adminService.createAchievementRule(workspaceId!, data);
      if (imageFile && created.slug) {
        const uploadResult = await adminService.uploadAchievementImage(created.slug, imageFile, workspaceId!);
        await adminService.updateAchievementRule(workspaceId!, created.id, {
          image_url: uploadResult.public_url,
        });
      }
      return created;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listKey });
      setCreateDialogOpen(false);
      setFormData({ ...emptyAchievementForm });
      setImageFile(null);
      setImagePreview(null);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: AchievementRuleUpdateInput }) =>
      adminService.updateAchievementRule(workspaceId!, id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: listKey });
      setEditingRule(null);
      setFormData({ ...emptyAchievementForm });
    },
  });

  const reset = () => {
    setCreateDialogOpen(false);
    setEditingRule(null);
    setFormData({ ...emptyAchievementForm });
    setImageFile(null);
    setImagePreview(null);
  };

  const openCreate = () => {
    createMutation.reset();
    updateMutation.reset();
    setFormData({ ...emptyAchievementForm });
    setCreateDialogOpen(true);
  };

  const openEdit = (rule: AchievementRule) => {
    updateMutation.reset();
    setEditingRule(rule);
    setFormData(achievementFormDataWithSlug(rule));
  };

  const pickImage = (file: File) => {
    if (file.size > MAX_ACHIEVEMENT_IMAGE_BYTES) {
      setImageError(
        `“${file.name}” is ${(file.size / 1024 / 1024).toFixed(1)} MB. Pick an image under 5 MB.`,
      );
      return;
    }
    setImageError(null);
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
  };

  const clearImage = () => {
    setImageFile(null);
    setImagePreview(null);
    setImageError(null);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingRule) {
      updateMutation.mutate({ id: editingRule.id, data: formData as AchievementRuleUpdateInput });
    } else {
      createMutation.mutate(formData as AchievementRuleCreateInput);
    }
  };

  const formInitial = editingRule ? achievementFormDataWithSlug(editingRule) : emptyAchievementForm;

  return {
    open: createDialogOpen || !!editingRule,
    editingRule,
    formData,
    setFormData,
    imagePreview,
    imageError,
    imageInputRef,
    isDirty: (createDialogOpen || !!editingRule) && hasUnsavedChanges(formData, formInitial),
    isSubmitting: createMutation.isPending || updateMutation.isPending,
    error: (editingRule ? updateMutation.error : createMutation.error) instanceof Error
      ? (editingRule ? updateMutation.error : createMutation.error)?.message
      : undefined,
    openCreate,
    openEdit,
    reset,
    pickImage,
    clearImage,
    submit,
  };
}
