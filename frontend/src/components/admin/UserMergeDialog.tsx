"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRightLeft, RefreshCw } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import type { MinimizedUser, User } from "@/types/user.types";
import type {
  UserMergeExecuteRequest,
  UserMergeFieldChoice,
  UserMergeFieldPolicy,
  UserMergeIdentityOption,
  UserMergeIdentitySelection,
  UserMergePreviewResponse
} from "@/types/admin.types";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig } from "@/lib/social-providers";

interface UserMergeDialogProps {
  sourceUser: User;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onMerged?: (targetUserId: number) => void;
}

type FieldKey = keyof UserMergeFieldPolicy;

// The backend reports affected-record counts under raw FK-path keys
// (e.g. "tournament.player.workspace_member_id"). Map them to human-readable
// labels for the admin preview; unknown keys fall back to the raw key.
const AFFECTED_RECORD_LABELS: Record<string, string> = {
  "tournament.player.workspace_member_id": "Tournament roster entries",
  "balancer.registration.workspace_member_id": "Balancer registrations",
  "achievements.evaluation_result.workspace_member_id": "Achievement results",
  "achievements.override.workspace_member_id": "Achievement overrides",
  "players.user.auth_user_id": "Linked account"
};

function affectedRecordLabel(key: string): string {
  return AFFECTED_RECORD_LABELS[key] ?? key;
}

function buildDefaultIdentitySelection(
  preview: UserMergePreviewResponse
): UserMergeIdentitySelection {
  return { social_account_ids: preview.source.social_accounts.map((item) => item.id) };
}

function mergePreviewToFieldPolicy(preview: UserMergePreviewResponse): UserMergeFieldPolicy {
  return {
    name: "target",
    avatar_url: "target"
  };
}

function FieldChoiceButtons({
  label,
  fieldKey,
  preview,
  value,
  onChange
}: {
  label: string;
  fieldKey: FieldKey;
  preview: UserMergePreviewResponse;
  value: UserMergeFieldChoice;
  onChange: (value: UserMergeFieldChoice) => void;
}) {
  const sourceValue = preview.field_options[fieldKey].source ?? "Empty";
  const targetValue = preview.field_options[fieldKey].target ?? "Empty";

  return (
    <div className="space-y-2">
      <Label className="text-sm">{label}</Label>
      <div className="grid grid-cols-2 gap-2">
        <Button
          type="button"
          variant={value === "source" ? "default" : "outline"}
          className="h-auto justify-start whitespace-normal px-3 py-2 text-left"
          onClick={() => onChange("source")}
        >
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide opacity-70">Source</div>
            <div className="text-sm">{sourceValue}</div>
          </div>
        </Button>
        <Button
          type="button"
          variant={value === "target" ? "default" : "outline"}
          className="h-auto justify-start whitespace-normal px-3 py-2 text-left"
          onClick={() => onChange("target")}
        >
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide opacity-70">Target</div>
            <div className="text-sm">{targetValue}</div>
          </div>
        </Button>
      </div>
    </div>
  );
}

function IdentitySelectionSection({
  label,
  items,
  selectedIds,
  onToggle
}: {
  label: string;
  items: UserMergeIdentityOption[];
  selectedIds: number[];
  onToggle: (identityId: number, checked: boolean) => void;
}) {
  if (items.length === 0) {
    return (
      <div className="space-y-2">
        <Label className="text-sm">{label}</Label>
        <div className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
          No source identities
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Label className="text-sm">{label}</Label>
      <div className="space-y-2">
        {items.map((item) => {
          const checked = selectedIds.includes(item.id);
          return (
            <label
              key={item.id}
              className="flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2"
            >
              <Checkbox
                checked={checked}
                onCheckedChange={(state) => onToggle(item.id, state === true)}
                className="mt-0.5"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <SocialIcon provider={item.provider} size={14} />
                  <span className="truncate text-sm font-medium">{item.value}</span>
                  <span className="text-xs text-muted-foreground">{getSocialProviderConfig(item.provider).label}</span>
                  {item.duplicate_on_target ? (
                    <Badge variant="outline" className="text-xs">
                      Duplicate on target
                    </Badge>
                  ) : null}
                </div>
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}

export function UserMergeDialog({
  sourceUser,
  open,
  onOpenChange,
  onMerged
}: UserMergeDialogProps) {
  const queryClient = useQueryClient();
  const [targetUser, setTargetUser] = useState<MinimizedUser | undefined>();
  const [fieldPolicy, setFieldPolicy] = useState<UserMergeFieldPolicy>({
    name: "target",
    avatar_url: "target"
  });
  const [identitySelection, setIdentitySelection] = useState<UserMergeIdentitySelection>({
    social_account_ids: []
  });
  const [confirmDelete, setConfirmDelete] = useState(false);

  const previewMutation = useMutation({
    mutationFn: () =>
      adminService.previewUserMerge({
        source_user_id: sourceUser.id,
        target_user_id: targetUser!.id
      }),
    onSuccess: (preview) => {
      setFieldPolicy(mergePreviewToFieldPolicy(preview));
      setIdentitySelection(buildDefaultIdentitySelection(preview));
      setConfirmDelete(false);
      executeMutation.reset();
    }
  });

  const executeMutation = useMutation({
    mutationFn: (payload: UserMergeExecuteRequest) => adminService.executeUserMerge(payload),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      onOpenChange(false);
      onMerged?.(result.surviving_target_user_id);
    }
  });

  const preview = previewMutation.data;
  const affectedEntries = useMemo(
    () =>
      Object.entries(preview?.affected_counts ?? {})
        .filter(([, count]) => count > 0)
        .sort((a, b) => b[1] - a[1]),
    [preview]
  );

  const handleTargetSelect = (user: MinimizedUser | undefined) => {
    setTargetUser(user);
    setFieldPolicy({ name: "target", avatar_url: "target" });
    setIdentitySelection({ social_account_ids: [] });
    setConfirmDelete(false);
    previewMutation.reset();
    executeMutation.reset();
  };

  const handleIdentityToggle = (identityId: number, checked: boolean) => {
    setIdentitySelection((prev) => ({
      social_account_ids: checked
        ? [...prev.social_account_ids, identityId]
        : prev.social_account_ids.filter((value) => value !== identityId)
    }));
  };

  const handleExecute = () => {
    if (!preview || !targetUser) return;
    executeMutation.mutate({
      source_user_id: sourceUser.id,
      target_user_id: targetUser.id,
      preview_fingerprint: preview.preview_fingerprint,
      field_policy: fieldPolicy,
      identity_selection: identitySelection
    });
  };

  const mergeBlocked = preview?.conflicts.has_auth_conflict ?? false;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ArrowRightLeft className="h-4 w-4" />
            Merge Player Profiles
          </DialogTitle>
          <DialogDescription>
            Merge source profile <strong>{sourceUser.name}</strong> into another existing player
            profile.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border px-4 py-3">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Source</div>
              <div className="mt-1 text-sm font-medium">{sourceUser.name}</div>
              <div className="text-xs text-muted-foreground">User #{sourceUser.id}</div>
            </div>
            <div className="space-y-2 rounded-lg border px-4 py-3">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Target</div>
              <UserSearchCombobox
                value={targetUser?.id}
                selectedName={targetUser?.name}
                onSelect={handleTargetSelect}
                placeholder="Select target profile"
                searchPlaceholder="Search target user..."
              />
            </div>
          </div>

          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => previewMutation.mutate()}
              disabled={!targetUser || previewMutation.isPending}
            >
              {previewMutation.isPending ? (
                <>
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                  Loading preview...
                </>
              ) : (
                "Preview merge"
              )}
            </Button>
          </div>

          {preview ? (
            <div className="space-y-5">
              {mergeBlocked ? (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Merge blocked</AlertTitle>
                  <AlertDescription>
                    {preview.conflicts.summary ?? "Both profiles are linked to auth accounts."}
                  </AlertDescription>
                </Alert>
              ) : null}

              <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
                <div className="space-y-4">
                  <FieldChoiceButtons
                    label="Keep name from"
                    fieldKey="name"
                    preview={preview}
                    value={fieldPolicy.name}
                    onChange={(value) => setFieldPolicy((prev) => ({ ...prev, name: value }))}
                  />
                  <FieldChoiceButtons
                    label="Keep avatar from"
                    fieldKey="avatar_url"
                    preview={preview}
                    value={fieldPolicy.avatar_url}
                    onChange={(value) => setFieldPolicy((prev) => ({ ...prev, avatar_url: value }))}
                  />
                </div>

                <div className="space-y-3">
                  <Label className="text-sm">Affected records</Label>
                  <div className="rounded-lg border p-3">
                    {affectedEntries.length > 0 ? (
                      <div className="space-y-2">
                        {affectedEntries.map(([key, count]) => (
                          <div
                            key={key}
                            className="flex items-center justify-between gap-3 text-sm"
                          >
                            <span className="text-muted-foreground">{affectedRecordLabel(key)}</span>
                            <Badge variant="secondary" className="tabular-nums">
                              {count}
                            </Badge>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-sm text-muted-foreground">
                        No linked records will be reassigned.
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <IdentitySelectionSection
                label="Social identities to move"
                items={preview.source.social_accounts}
                selectedIds={identitySelection.social_account_ids}
                onToggle={handleIdentityToggle}
              />

              <div className="space-y-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4">
                <label className="flex items-start gap-3">
                  <Checkbox
                    checked={confirmDelete}
                    onCheckedChange={(checked) => setConfirmDelete(checked === true)}
                    className="mt-0.5"
                  />
                  <div className="space-y-1">
                    <div className="text-sm font-medium">
                      I understand that the source profile will be permanently deleted after merge.
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Source: {sourceUser.name} #{sourceUser.id}
                      {targetUser ? ` -> Target: ${targetUser.name} #${targetUser.id}` : ""}
                    </div>
                  </div>
                </label>
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={handleExecute}
            disabled={!preview || mergeBlocked || !confirmDelete || executeMutation.isPending}
          >
            {executeMutation.isPending ? "Merging..." : "Execute merge"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
