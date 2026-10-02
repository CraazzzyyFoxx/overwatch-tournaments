"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRightLeft } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import type { MinimizedUser, User } from "@/types/user.types";
import type {
  AuthMergePolicy,
  UserMergeExecuteRequest,
  UserMergeFieldChoice,
  UserMergeFieldPolicy,
  UserMergeIdentityOption,
  UserMergeIdentitySelection,
  UserMergePreviewRequest,
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
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { UserMergeAuthSection } from "./UserMergeAuthSection";

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

export function UserMergeDialog(props: Readonly<UserMergeDialogProps>) {
  return <UserMergeDialogSession key={`${props.sourceUser.id}:${props.open}`} {...props} />;
}

function UserMergeDialogSession({
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
  const [authPolicy, setAuthPolicy] = useState<AuthMergePolicy | undefined>();
  const [preview, setPreview] = useState<UserMergePreviewResponse>();
  const [reviewedRequest, setReviewedRequest] = useState<string>();
  const [previewPending, setPreviewPending] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmAuthChanges, setConfirmAuthChanges] = useState(false);
  const [confirmAuthDeletion, setConfirmAuthDeletion] = useState(false);
  const [confirmPermissionChanges, setConfirmPermissionChanges] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const confirmId = useId();
  const previewSequence = useRef(0);
  const alive = useRef(true);
  const executePending = useRef(false);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      previewSequence.current += 1;
    };
  }, []);

  const resetConfirmations = () => {
    setConfirmDelete(false);
    setConfirmAuthChanges(false);
    setConfirmAuthDeletion(false);
    setConfirmPermissionChanges(false);
    setSubmitError(null);
  };

  const request: UserMergePreviewRequest = {
    source_user_id: sourceUser.id,
    target_user_id: targetUser?.id ?? 0,
    ...(authPolicy ? { auth_policy: authPolicy } : {})
  };
  const requestKey = JSON.stringify(request);
  const reviewed = Boolean(preview && reviewedRequest === requestKey);

  const handlePreview = async () => {
    if (!targetUser || executePending.current) return;
    const sequence = ++previewSequence.current;
    const submittedRequest = request;
    const firstPreview = !preview;
    resetConfirmations();
    setReviewedRequest(undefined);
    setPreviewPending(true);
    setPreviewError(null);
    executeMutation.reset();
    try {
      const result = await adminService.previewUserMerge(submittedRequest);
      if (!alive.current || sequence !== previewSequence.current) return;
      if (result.source.id !== submittedRequest.source_user_id || result.target.id !== submittedRequest.target_user_id) {
        setPreviewError("The preview does not match the selected profiles. Run Preview merge again.");
        return;
      }
      const normalizedPolicy = result.auth_merge?.policy;
      const submittedPolicy = submittedRequest.auth_policy;
      if (submittedPolicy && (
        !normalizedPolicy ||
        normalizedPolicy.surviving_auth_user_id !== submittedPolicy.surviving_auth_user_id ||
        normalizedPolicy.other_account_action !== submittedPolicy.other_account_action ||
        submittedPolicy.oauth_destinations.some((destination) =>
          normalizedPolicy.oauth_destinations.find((item) => item.connection_id === destination.connection_id)?.auth_user_id !== destination.auth_user_id
        ) ||
        Object.entries(submittedPolicy.conflict_choices).some(([key, value]) =>
          normalizedPolicy.conflict_choices[key] !== value
        )
      )) {
        setPreviewError("The preview does not match the submitted account choices. Run Preview merge again.");
        return;
      }
      setPreview(result);
      setAuthPolicy(normalizedPolicy);
      setReviewedRequest(JSON.stringify({
        source_user_id: submittedRequest.source_user_id,
        target_user_id: submittedRequest.target_user_id,
        ...(normalizedPolicy ? { auth_policy: normalizedPolicy } : {})
      }));
      if (firstPreview) {
        setFieldPolicy({ name: "target", avatar_url: "target" });
        setIdentitySelection({
          social_account_ids: result.source.social_accounts.map((item) => item.id)
        });
      }
      resetConfirmations();
    } catch (error) {
      if (alive.current && sequence === previewSequence.current) {
        setPreviewError(error instanceof Error ? error.message : "The preview could not be built.");
      }
    } finally {
      if (alive.current && sequence === previewSequence.current) setPreviewPending(false);
    }
  };

  const executeMutation = useMutation({
    mutationFn: (payload: UserMergeExecuteRequest) => adminService.executeUserMerge(payload),
    onSuccess: async (result) => {
      // Auth deletion can transfer resources across all user/workspace surfaces.
      await Promise.all([
        queryClient.invalidateQueries(),
        useAuthProfileStore.getState().fetchMe({ force: true })
      ]);
      if (!alive.current) return;
      onOpenChange(false);
      onMerged?.(result.surviving_target_user_id);
    },
    onError: () => {
      if (!alive.current) return;
      setReviewedRequest(undefined);
      resetConfirmations();
    },
    onSettled: () => {
      executePending.current = false;
    }
  });

  const affectedEntries = useMemo(
    () =>
      Object.entries(preview?.affected_counts ?? {})
        .filter(([, count]) => count > 0)
        .sort((a, b) => b[1] - a[1]),
    [preview]
  );

  const handleTargetSelect = (user: MinimizedUser | undefined) => {
    if (executePending.current) return;
    previewSequence.current += 1;
    setPreviewPending(false);
    setTargetUser(user);
    setFieldPolicy({ name: "target", avatar_url: "target" });
    setIdentitySelection({ social_account_ids: [] });
    setAuthPolicy(undefined);
    setPreview(undefined);
    setReviewedRequest(undefined);
    setPreviewError(null);
    resetConfirmations();
    executeMutation.reset();
  };

  const handlePolicyChange = (policy: AuthMergePolicy) => {
    previewSequence.current += 1;
    setPreviewPending(false);
    setAuthPolicy(policy);
    setReviewedRequest(undefined);
    setPreviewError(null);
    resetConfirmations();
    executeMutation.reset();
  };

  const handleFieldChange = (field: FieldKey, value: UserMergeFieldChoice) => {
    setFieldPolicy((previous) => ({ ...previous, [field]: value }));
    resetConfirmations();
  };

  const handleIdentityToggle = (identityId: number, checked: boolean) => {
    resetConfirmations();
    setIdentitySelection((prev) => ({
      social_account_ids: checked
        ? [...prev.social_account_ids, identityId]
        : prev.social_account_ids.filter((value) => value !== identityId)
    }));
  };

  // Checked on submit rather than by disabling the button, so the reader is
  // told which step is outstanding instead of meeting a dead control.
  const handleExecute = () => {
    if (!open || executePending.current) return;
    if (!targetUser) {
      setSubmitError("Choose the target profile the source should merge into.");
      return;
    }
    if (!preview || !reviewed || previewPending) {
      setSubmitError("Run “Preview merge” for the current account choices before confirming the merge.");
      return;
    }
    if (mergeBlocked) {
      setSubmitError("Resolve the blocking issues and run Preview merge again.");
      return;
    }
    if (preview.auth_merge?.data_conflicts.some((conflict) => !authPolicy?.conflict_choices[conflict.key])) {
      setSubmitError("Choose Incoming or Existing for every resource conflict, then preview again.");
      return;
    }
    if (preview.auth_merge && !confirmAuthChanges) {
      setSubmitError("Acknowledge the reviewed sign-in and account ownership changes.");
      document.getElementById(`${confirmId}-auth`)?.focus();
      return;
    }
    if (deletedAccount && !confirmAuthDeletion) {
      setSubmitError(`Separately acknowledge deletion of ${deletedAccount.username} (#${deletedAccount.id}).`);
      document.getElementById(`${confirmId}-auth-delete`)?.focus();
      return;
    }
    if (preview.auth_merge?.permission_changes && !confirmPermissionChanges) {
      setSubmitError("Separately acknowledge the reviewed sign-in access, role, explicit-deny, and resource ownership changes.");
      document.getElementById(`${confirmId}-permissions`)?.focus();
      return;
    }
    if (!confirmDelete) {
      setSubmitError("Tick the confirmation box to acknowledge that the source profile is deleted.");
      document.getElementById(confirmId)?.focus();
      return;
    }
    setSubmitError(null);
    executePending.current = true;
    executeMutation.mutate({
      source_user_id: sourceUser.id,
      target_user_id: targetUser.id,
      ...(authPolicy ? { auth_policy: authPolicy } : {}),
      preview_fingerprint: preview.preview_fingerprint,
      field_policy: fieldPolicy,
      identity_selection: identitySelection,
      confirm_auth_changes: confirmAuthChanges,
      confirm_auth_deletion: confirmAuthDeletion,
      confirm_permission_changes: confirmPermissionChanges
    });
  };

  const deletedAccount = authPolicy?.other_account_action === "delete"
    ? preview?.auth_merge?.accounts.find((account) => account.id !== authPolicy.surviving_auth_user_id)
    : undefined;
  const mergeBlocked = reviewed && Boolean(
    preview?.conflicts.has_auth_conflict || preview?.auth_merge?.issues.length
  );

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => {
      if (executePending.current) return;
      if (!nextOpen) {
        previewSequence.current += 1;
        setReviewedRequest(undefined);
        resetConfirmations();
      }
      onOpenChange(nextOpen);
    }}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ArrowRightLeft className="h-4 w-4" aria-hidden />
            Merge player profiles
          </DialogTitle>
          <DialogDescription>
            Merge the records and selected identities attached to <strong>{sourceUser.name}</strong>
            onto the target, then permanently delete the source player. Review sign-in accounts separately.
          </DialogDescription>
        </DialogHeader>

        <fieldset disabled={executeMutation.isPending} className="min-w-0 space-y-5">
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
            {previewError && (
              <p role="alert" className="mr-auto text-sm text-danger">
                The preview could not be built: {previewError}
              </p>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={handlePreview}
              disabled={!targetUser || previewPending || executeMutation.isPending}
            >
              {previewPending ? (
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
                    {preview.conflicts.summary ?? "Resolve the auth issues below before merging."}
                  </AlertDescription>
                </Alert>
              ) : null}

              {preview.auth_merge && authPolicy ? (
                <UserMergeAuthSection
                  preview={preview.auth_merge}
                  policy={authPolicy}
                  reviewed={reviewed}
                  onPolicyChange={handlePolicyChange}
                />
              ) : null}

              <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
                <div className="space-y-4">
                  <FieldChoiceButtons
                    label="Keep name from"
                    fieldKey="name"
                    preview={preview}
                    value={fieldPolicy.name}
                    onChange={(value) => handleFieldChange("name", value)}
                  />
                  <FieldChoiceButtons
                    label="Keep avatar from"
                    fieldKey="avatar_url"
                    preview={preview}
                    value={fieldPolicy.avatar_url}
                    onChange={(value) => handleFieldChange("avatar_url", value)}
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
                {preview.auth_merge ? (
                  <div className="flex items-start gap-3">
                    <Checkbox
                      id={`${confirmId}-auth`}
                      checked={confirmAuthChanges}
                      disabled={!reviewed || previewPending}
                      onCheckedChange={(checked) => setConfirmAuthChanges(checked === true)}
                      className="mt-0.5"
                    />
                    <Label htmlFor={`${confirmId}-auth`} className="text-sm leading-snug">
                      I reviewed the OAuth destinations, retained login access and ownership changes
                      for the target player. Its owner will be account #{authPolicy?.surviving_auth_user_id}.
                      Sessions and API keys for both affected accounts will be revoked; retained accounts must sign in again.
                    </Label>
                  </div>
                ) : null}
                {deletedAccount ? (
                  <div className="flex items-start gap-3">
                    <Checkbox
                      id={`${confirmId}-auth-delete`}
                      checked={confirmAuthDeletion}
                      disabled={!reviewed || previewPending}
                      onCheckedChange={(checked) => setConfirmAuthDeletion(checked === true)}
                      className="mt-0.5"
                    />
                    <Label htmlFor={`${confirmId}-auth-delete`} className="text-sm leading-snug">
                      I separately confirm permanent deletion of sign-in account {deletedAccount.username}
                      {" "} (#{deletedAccount.id}), after the reviewed resource transfers.
                      Sessions and API keys for both affected accounts will be revoked.
                    </Label>
                  </div>
                ) : null}
                {preview.auth_merge?.permission_changes ? (
                  <div className="flex items-start gap-3">
                    <Checkbox
                      id={`${confirmId}-permissions`}
                      checked={confirmPermissionChanges}
                      disabled={!reviewed || previewPending}
                      onCheckedChange={(checked) => setConfirmPermissionChanges(checked === true)}
                      className="mt-0.5"
                    />
                    <Label htmlFor={`${confirmId}-permissions`} className="text-sm leading-snug">
                      I reviewed and acknowledge sign-in access, roles and explicit denies, and resource access/ownership changes.
                    </Label>
                  </div>
                ) : null}
                <div className="flex items-start gap-3">
                  <Checkbox
                    id={confirmId}
                    checked={confirmDelete}
                    disabled={!reviewed || previewPending}
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
        </fieldset>

        <DialogFooter className="flex-col items-stretch gap-2 sm:flex-row sm:items-center">
          {submitError && <p role="alert" className="mr-auto text-sm text-danger">{submitError}</p>}
          {executeMutation.error instanceof Error && (
            <p role="alert" className="mr-auto text-sm text-danger">
              The merge did not run: {executeMutation.error.message}
            </p>
          )}
          <Button type="button" variant="outline" disabled={executeMutation.isPending} onClick={() => {
            previewSequence.current += 1;
            setReviewedRequest(undefined);
            resetConfirmations();
            onOpenChange(false);
          }}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={handleExecute}
            disabled={mergeBlocked || previewPending || executeMutation.isPending}
          >
            {executeMutation.isPending ? "Merging…" : "Merge and delete source"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
