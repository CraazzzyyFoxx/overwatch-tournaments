"use client";

import { useId, useMemo, useState } from "react";
import { AlertTriangle, ArrowRightLeft } from "lucide-react";
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
import { Spinner } from "@/components/ui/spinner";
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
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { SocialIcon } from "@/components/social/SocialIcon";
import { getSocialProviderConfig } from "@/lib/social/providers";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { adminQueryKeys } from "@/lib/admin/query-keys";

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

function FieldChoiceButtons({
  label,
  fieldKey,
  preview,
  value,
  onChange
}: Readonly<{
  label: string;
  fieldKey: FieldKey;
  preview: UserMergePreviewResponse;
  value: UserMergeFieldChoice;
  onChange: (value: UserMergeFieldChoice) => void;
}>) {
  const groupId = useId();
  const sourceValue = preview.field_options[fieldKey].source ?? "Empty";
  const targetValue = preview.field_options[fieldKey].target ?? "Empty";

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium" id={groupId}>
        {label}
      </p>
      <div className="grid grid-cols-2 gap-2" role="group" aria-labelledby={groupId}>
        <Button
          type="button"
          variant={value === "source" ? "default" : "outline"}
          className="h-auto justify-start whitespace-normal px-3 py-2 text-left"
          aria-pressed={value === "source"}
          onClick={() => onChange("source")}
        >
          <div className="space-y-1">
            <div className={EYEBROW_CLASS}>Source</div>
            <div className="text-sm">{sourceValue}</div>
          </div>
        </Button>
        <Button
          type="button"
          variant={value === "target" ? "default" : "outline"}
          className="h-auto justify-start whitespace-normal px-3 py-2 text-left"
          aria-pressed={value === "target"}
          onClick={() => onChange("target")}
        >
          <div className="space-y-1">
            <div className={EYEBROW_CLASS}>Target</div>
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
}: Readonly<{
  label: string;
  items: UserMergeIdentityOption[];
  selectedIds: number[];
  onToggle: (identityId: number, checked: boolean) => void;
}>) {
  const groupId = useId();

  if (items.length === 0) {
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium">{label}</p>
        <EmptyNote>
          The source profile has no linked social accounts, so nothing moves across.
        </EmptyNote>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium" id={groupId}>
        {label}
      </p>
      <div className="space-y-2" role="group" aria-labelledby={groupId}>
        {items.map((item) => {
          const checked = selectedIds.includes(item.id);
          const providerLabel = getSocialProviderConfig(item.provider).label;
          return (
            <div
              key={item.id}
              className="flex items-start gap-3 rounded-md border px-3 py-2"
            >
              <Checkbox
                checked={checked}
                onCheckedChange={(state) => onToggle(item.id, state === true)}
                className="mt-0.5"
                aria-label={`Move the ${providerLabel} identity ${item.value} to the target profile`}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <SocialIcon provider={item.provider} size={14} />
                  <span className="truncate text-sm font-medium">{item.value}</span>
                  <span className="text-xs text-muted-foreground">{providerLabel}</span>
                  {item.duplicate_on_target ? (
                    <Badge variant="outline" className="text-xs">
                      Duplicate on target
                    </Badge>
                  ) : null}
                </div>
              </div>
            </div>
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
}: Readonly<UserMergeDialogProps>) {
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
  const [submitError, setSubmitError] = useState<string | null>(null);
  const confirmId = useId();

  const previewMutation = useMutation({
    mutationFn: () =>
      adminService.previewUserMerge({
        source_user_id: sourceUser.id,
        target_user_id: targetUser!.id
      }),
    onSuccess: (preview) => {
      setFieldPolicy({ name: "target", avatar_url: "target" });
      setIdentitySelection({
        social_account_ids: preview.source.social_accounts.map((item) => item.id)
      });
      setConfirmDelete(false);
      setSubmitError(null);
      executeMutation.reset();
    }
  });

  const executeMutation = useMutation({
    mutationFn: (payload: UserMergeExecuteRequest) => adminService.executeUserMerge(payload),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: adminQueryKeys.users() });
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
    setSubmitError(null);
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

  // Checked on submit rather than by disabling the button, so the reader is
  // told which step is outstanding instead of meeting a dead control.
  const handleExecute = () => {
    if (!targetUser) {
      setSubmitError("Choose the target profile the source should merge into.");
      return;
    }
    if (!preview) {
      setSubmitError("Run “Preview merge” first — the merge is checked against that preview.");
      return;
    }
    if (!confirmDelete) {
      setSubmitError("Tick the confirmation box to acknowledge that the source profile is deleted.");
      return;
    }
    setSubmitError(null);
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
            <ArrowRightLeft className="h-4 w-4" aria-hidden />
            Merge player profiles
          </DialogTitle>
          <DialogDescription>
            Everything attached to <strong>{sourceUser.name}</strong> moves onto the target profile,
            and the source profile is then deleted for good. Preview the merge before running it.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg border px-4 py-3">
              <p className={EYEBROW_CLASS}>Source</p>
              <p className="mt-1 text-sm font-medium">{sourceUser.name}</p>
              <p className="text-xs text-muted-foreground tabular-nums">User #{sourceUser.id}</p>
            </div>
            <div className="space-y-2 rounded-lg border px-4 py-3">
              <Label htmlFor="merge-target-user" className={EYEBROW_CLASS}>
                Target
              </Label>
              <UserSearchCombobox
                id="merge-target-user"
                value={targetUser?.id}
                selectedName={targetUser?.name}
                onSelect={handleTargetSelect}
                placeholder="Select target profile"
                searchPlaceholder="Search target user…"
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-3">
            {previewMutation.error instanceof Error && (
              <p className="mr-auto text-sm text-danger">
                The preview could not be built: {previewMutation.error.message}
              </p>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={() => previewMutation.mutate()}
              disabled={!targetUser || previewMutation.isPending}
            >
              {previewMutation.isPending ? (
                <>
                  <Spinner className="mr-2" />
                  Loading preview…
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
                  <AlertTriangle className="h-4 w-4" aria-hidden />
                  <AlertTitle>Merge blocked</AlertTitle>
                  <AlertDescription>
                    {preview.conflicts.summary ??
                      "Both profiles are linked to a sign-in account. Unlink one of them before merging."}
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
                  <p className="text-sm font-medium" id="merge-affected-records">
                    Records moving to {targetUser?.name ?? "the target"}
                  </p>
                  <div className="rounded-lg border p-3" aria-labelledby="merge-affected-records">
                    {affectedEntries.length > 0 ? (
                      <div className="space-y-2">
                        {affectedEntries.map(([key, count]) => (
                          <div
                            key={key}
                            className="flex items-center justify-between gap-3 text-sm"
                          >
                            <span className="text-muted-foreground">
                              {AFFECTED_RECORD_LABELS[key] ?? key}
                            </span>
                            <Badge variant="secondary" className="tabular-nums">
                              {count}
                            </Badge>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Nothing is linked to the source profile, so no records get reassigned.
                      </p>
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
                <div className="flex items-start gap-3">
                  <Checkbox
                    id={confirmId}
                    checked={confirmDelete}
                    onCheckedChange={(checked) => setConfirmDelete(checked === true)}
                    className="mt-0.5"
                  />
                  <div className="space-y-1">
                    <Label htmlFor={confirmId} className="text-sm font-medium leading-snug">
                      {targetUser
                        ? `I understand that ${sourceUser.name} (#${sourceUser.id}) is deleted for good, and that its rosters, registrations, achievements and selected identities become part of ${targetUser.name} (#${targetUser.id}).`
                        : `I understand that ${sourceUser.name} (#${sourceUser.id}) is deleted for good once the merge runs.`}
                    </Label>
                    <p className="text-xs text-muted-foreground tabular-nums">
                      {sourceUser.name} #{sourceUser.id}
                      {targetUser ? ` → ${targetUser.name} #${targetUser.id}` : ""}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter className="flex-col items-stretch gap-2 sm:flex-row sm:items-center">
          {submitError && <p className="mr-auto text-sm text-danger">{submitError}</p>}
          {executeMutation.error instanceof Error && (
            <p className="mr-auto text-sm text-danger">
              The merge did not run: {executeMutation.error.message}
            </p>
          )}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={handleExecute}
            disabled={mergeBlocked || executeMutation.isPending}
          >
            {executeMutation.isPending ? "Merging…" : "Merge and delete source"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
