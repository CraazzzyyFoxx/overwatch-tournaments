"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, ArrowRightLeft } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import adminService from "@/services/admin.service";
import type { MinimizedUser, User } from "@/types/user.types";
import type {
  AuthMergePolicy,
  UserMergeExecuteRequest,
  UserMergeFieldChoice,
  UserMergeFieldPolicy,
  UserMergeIdentitySelection,
  UserMergePreviewRequest,
  UserMergePreviewResponse
} from "@/types/admin.types";
import { UserSearchCombobox } from "@/components/kit/ServerSearchCombobox";
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
import { Label } from "@/components/ui/label";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { UserMergeAuthSection } from "./UserMergeAuthSection";
import { AffectedRecordsSummary } from "./user-merge/AffectedRecordsSummary";
import { FieldChoiceButtons, type FieldKey } from "./user-merge/FieldChoiceButtons";
import { IdentitySelectionSection } from "./user-merge/IdentitySelectionSection";
import { authPolicyDiverged } from "./user-merge/model";

interface UserMergeDialogProps {
  sourceUser: User;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onMerged?: (targetUserId: number) => void;
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
  const t = useTranslations("adminPeople.merge");
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
        setPreviewError(t("previewMismatchSelected"));
        return;
      }
      const normalizedPolicy = result.auth_merge?.policy;
      const submittedPolicy = submittedRequest.auth_policy;
      if (submittedPolicy && authPolicyDiverged(submittedPolicy, normalizedPolicy)) {
        setPreviewError(t("previewMismatchSubmitted"));
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
        setPreviewError(error instanceof Error ? error.message : t("previewBuildFailed"));
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
      setSubmitError(t("chooseTarget"));
      return;
    }
    if (!preview || !reviewed || previewPending) {
      setSubmitError(t("previewBeforeConfirm"));
      return;
    }
    if (mergeBlocked) {
      setSubmitError(t("resolveBlocked"));
      return;
    }
    if (preview.auth_merge?.data_conflicts.some((conflict) => !authPolicy?.conflict_choices[conflict.key])) {
      setSubmitError(t("chooseConflicts"));
      return;
    }
    if (preview.auth_merge && !confirmAuthChanges) {
      setSubmitError(t("ackAuth"));
      document.getElementById(`${confirmId}-auth`)?.focus();
      return;
    }
    if (deletedAccount && !confirmAuthDeletion) {
      setSubmitError(t("ackDeletion", { username: deletedAccount.username, id: deletedAccount.id }));
      document.getElementById(`${confirmId}-auth-delete`)?.focus();
      return;
    }
    if (preview.auth_merge?.permission_changes && !confirmPermissionChanges) {
      setSubmitError(t("ackPermissions"));
      document.getElementById(`${confirmId}-permissions`)?.focus();
      return;
    }
    if (!confirmDelete) {
      setSubmitError(t("ackSourceDeletion"));
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
      <DialogContent variant="panel" className="max-h-[min(92dvh,52rem)] max-w-3xl">
        <DialogHeader variant="panel">
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription className="max-w-[62ch]">{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
          <fieldset disabled={executeMutation.isPending} className="min-w-0 space-y-6">
          <div className="grid items-end gap-3 sm:grid-cols-[1fr_auto_1fr]">
            <div className="space-y-1">
              <p className="text-sm font-medium">{t("deletedAfterMerge")}</p>
              <p className="truncate font-medium">{sourceUser.name}</p>
              <p className="text-caption tabular-nums text-muted-foreground">#{sourceUser.id}</p>
            </div>
            <ArrowRightLeft className="mx-auto hidden h-4 w-4 text-muted-foreground sm:mb-3 sm:block" aria-hidden />
            <div className="space-y-2">
              <Label htmlFor="merge-target-user">{t("target")}</Label>
              <UserSearchCombobox
                id="merge-target-user"
                value={targetUser?.id}
                selectedLabel={targetUser?.name}
                onSelect={handleTargetSelect}
                placeholder={t("targetPlaceholder")}
                searchPlaceholder={t("targetSearch")}
              />
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={handlePreview}
                disabled={!targetUser || previewPending || executeMutation.isPending}
              >
                {previewPending ? (
                  <>
                    <Spinner className="mr-2" />
                    {t("loading")}
                  </>
                ) : (
                  t("preview")
                )}
              </Button>
              {previewError ? (
                <p role="alert" className="text-sm text-danger">{previewError}</p>
              ) : null}
            </div>
          </div>

          {preview ? (
            <div className="space-y-5">
              {mergeBlocked ? (
                <Alert tone="danger">
                  <AlertTriangle className="h-4 w-4" aria-hidden />
                  <AlertTitle>{t("blocked")}</AlertTitle>
                  <AlertDescription>
                    {preview.conflicts.summary ?? t("resolveAuthIssues")}
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
                    label={t("keepName")}
                    fieldKey="name"
                    preview={preview}
                    value={fieldPolicy.name}
                    sourceName={sourceUser.name}
                    targetName={targetUser?.name ?? t("target")}
                    onChange={(value) => handleFieldChange("name", value)}
                  />
                  <FieldChoiceButtons
                    label={t("keepAvatar")}
                    fieldKey="avatar_url"
                    preview={preview}
                    value={fieldPolicy.avatar_url}
                    sourceName={sourceUser.name}
                    targetName={targetUser?.name ?? t("target")}
                    onChange={(value) => handleFieldChange("avatar_url", value)}
                  />
                </div>

                <AffectedRecordsSummary preview={preview} targetName={targetUser?.name ?? t("target")} />
              </div>

              <IdentitySelectionSection
                label={t("socialToMove")}
                items={preview.source.social_accounts}
                selectedIds={identitySelection.social_account_ids}
                onToggle={handleIdentityToggle}
              />

              <div className="space-y-3 border-t pt-4">
                <div>
                  <p className="text-sm font-medium">{t("before")}</p>
                  <p className="mt-1 max-w-[68ch] text-sm text-muted-foreground">
                    {t("sessions")}
                  </p>
                </div>
                {!reviewed ? (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className={previewError ? "text-sm text-danger" : "text-sm text-muted-foreground"}>
                      {previewError ?? t("choicesChanged")}
                    </p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={handlePreview}
                      disabled={previewPending || executeMutation.isPending}
                    >
                      {previewPending ? (
                        <>
                          <Spinner className="mr-2" />
                          {t("loading")}
                        </>
                      ) : (
                        t("preview")
                      )}
                    </Button>
                  </div>
                ) : null}
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
                      {authPolicy
                        ? t("reviewOauthWithAccount", { id: authPolicy.surviving_auth_user_id })
                        : t("reviewOauth")}
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
                      {t("confirmDeleteAccount", {
                        username: deletedAccount.username,
                        id: deletedAccount.id
                      })}
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
                      {t("reviewRoles")}
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
                  <Label htmlFor={confirmId} className="text-sm leading-snug">
                    {targetUser
                      ? t("confirmSourceWithTarget", {
                          source: sourceUser.name,
                          sourceId: sourceUser.id,
                          target: targetUser.name,
                          targetId: targetUser.id
                        })
                      : t("confirmSource", { source: sourceUser.name, sourceId: sourceUser.id })}
                  </Label>
                </div>
              </div>
            </div>
          ) : null}
          </fieldset>
        </div>

        <DialogFooter variant="panel" className="sm:items-center">
          {submitError && <p role="alert" className="text-sm text-danger sm:mr-auto">{submitError}</p>}
          {executeMutation.error instanceof Error && (
            <p role="alert" className="text-sm text-danger sm:mr-auto">
              {t("failedWithMessage", { message: executeMutation.error.message })}
            </p>
          )}
          <Button type="button" variant="outline" disabled={executeMutation.isPending} onClick={() => {
            previewSequence.current += 1;
            setReviewedRequest(undefined);
            resetConfirmations();
            onOpenChange(false);
          }}>
            {t("cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={handleExecute}
            disabled={mergeBlocked || previewPending || executeMutation.isPending}
          >
            {executeMutation.isPending ? t("merging") : t("mergeAndDelete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
