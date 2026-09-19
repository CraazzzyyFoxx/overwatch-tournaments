"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, getApiErrorMessage } from "@/lib/api-error";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import workspaceService from "@/services/workspace.service";
import type { Workspace } from "@/types/workspace.types";

interface WorkspaceFormData {
  slug: string;
  name: string;
  description: string;
}

const emptyForm: WorkspaceFormData = { slug: "", name: "", description: "" };

const ACCEPTED_IMAGE_TYPES = "image/webp,image/png,image/jpeg,image/gif";
const MAX_FILE_SIZE = 2 * 1024 * 1024; // 2 MB

/**
 * The two refusals self-service creation added, in words that say what to do.
 *
 * The backend answers with the bare machine codes (`workspace_create_limit_reached`,
 * `slug_reserved`), which are precise and unreadable; matching the code rather
 * than the prose keeps the mapping stable if the backend ever wraps them in a
 * sentence.
 */
function createFailure(error: unknown): string | undefined {
  if (!error) return undefined;
  const details = error instanceof ApiError ? error.details : [];
  const codes = details.map((detail) => `${detail.code} ${detail.msg}`).join(" ");

  if (codes.includes("workspace_create_limit_reached")) {
    return "You already own a workspace. One per account — ask the platform admins if you need another.";
  }
  if (codes.includes("slug_reserved")) {
    return "That address is reserved by the platform. Pick a different one.";
  }
  return getApiErrorMessage(error, "Could not create the workspace.");
}

/**
 * Creating a workspace, from the admin list and from the public
 * "get your own workspace" page alike.
 *
 * One dialog rather than one per entry point: creation is open to any active
 * account now, so the organiser's first form and the superuser's are the same
 * request with the same two refusals, and two copies would drift on the day
 * one of them grew a field.
 */
export function CreateWorkspaceDialog({
  open,
  onOpenChange,
  onCreated
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (workspace: Workspace) => void;
}>) {
  const [formData, setFormData] = useState<WorkspaceFormData>({ ...emptyForm });
  const [iconFile, setIconFile] = useState<File | null>(null);
  const [iconPreview, setIconPreview] = useState<string | null>(null);

  const reset = () => {
    setFormData({ ...emptyForm });
    setIconFile(null);
    setIconPreview(null);
  };

  const mutation = useMutation({
    mutationFn: async (data: WorkspaceFormData) => {
      const workspace = await workspaceService.create({
        slug: data.slug,
        name: data.name,
        description: data.description || undefined
      });
      // The icon travels through its own endpoint, so it can only be attached
      // once the workspace exists.
      if (iconFile) await workspaceService.uploadIcon(workspace.id, iconFile);
      return workspace;
    },
    onSuccess: (workspace) => {
      reset();
      onOpenChange(false);
      notify.success("Workspace created");
      onCreated?.(workspace);
    }
  });

  const isDirty = open && (hasUnsavedChanges(formData, emptyForm) || iconFile !== null);

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          mutation.reset();
        }
        onOpenChange(next);
      }}
      title="Create workspace"
      description="Create a new isolated workspace for tournaments"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate(formData);
      }}
      isSubmitting={mutation.isPending}
      submittingLabel="Creating workspace…"
      errorMessage={createFailure(mutation.error)}
      isDirty={isDirty}
    >
      <div className="space-y-4">
        <div>
          <Label htmlFor="slug">Slug *</Label>
          <Input
            id="slug"
            value={formData.slug}
            onChange={(event) =>
              setFormData({
                ...formData,
                slug: event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "")
              })
            }
            placeholder="my-workspace"
            required
          />
          <p className="mt-1 text-xs text-muted-foreground">URL-safe identifier (a-z, 0-9, -, _)</p>
        </div>
        <div>
          <Label htmlFor="name">Name *</Label>
          <Input
            id="name"
            value={formData.name}
            onChange={(event) => setFormData({ ...formData, name: event.target.value })}
            placeholder="My Workspace"
            required
          />
        </div>
        <div>
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={formData.description}
            onChange={(event) => setFormData({ ...formData, description: event.target.value })}
            placeholder="Optional description"
          />
        </div>
        <div>
          <p className="text-sm font-medium leading-none">Icon</p>
          <div className="mt-1.5">
            <EditableAvatar
              src={iconPreview}
              name={formData.name}
              size={64}
              shape="rounded"
              onSelectFile={(file) => {
                setIconFile(file);
                setIconPreview(URL.createObjectURL(file));
              }}
              onDelete={
                iconPreview
                  ? () => {
                      setIconFile(null);
                      setIconPreview(null);
                    }
                  : undefined
              }
              accept={ACCEPTED_IMAGE_TYPES}
              maxSizeBytes={MAX_FILE_SIZE}
              onError={(message) => notify.error(message)}
            />
          </div>
          <p className="mt-1 text-xs text-muted-foreground">PNG, JPEG, WebP or GIF, max 2 MB</p>
        </div>
      </div>
    </EntityFormDialog>
  );
}
