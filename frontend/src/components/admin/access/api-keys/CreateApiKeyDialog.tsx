"use client";

import { useId, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";

import { PermissionPicker } from "@/components/admin/access/PermissionPicker";
import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Input } from "@craazzzyyfoxx/admin-kit/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { Switch } from "@/components/ui/switch";
import { useCreateAccountApiKey } from "@/hooks/useAccountApiKeys";
import { notify } from "@/lib/notify";

import { scopePickerCatalog } from "./model";

/**
 * Issuing a key. The scope list is the shared `PermissionPicker` rather than a
 * private checkbox tree. `onCreated` receives the secret, which the server
 * returns exactly once.
 */
export function CreateApiKeyDialog({
  open,
  onOpenChange,
  workspaceId,
  workspaceName,
  isSuperuser,
  availableScopes,
  onCreated
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: number | null;
  workspaceName: string | undefined;
  isSuperuser: boolean;
  availableScopes: readonly string[];
  onCreated: (secret: string) => void;
}>) {
  const t = useTranslations("adminAccess.common");
  const ta = useTranslations("adminAccess.apiKeysUi");
  const [createName, setCreateName] = useState("");
  const [createExpiresAt, setCreateExpiresAt] = useState("");
  const [createScopes, setCreateScopes] = useState<Set<string>>(new Set());
  const [createSuperuser, setCreateSuperuser] = useState(false);
  const createNameId = useId();
  const superuserId = useId();
  const createMutation = useCreateAccountApiKey();

  // `available_scopes` is computed per workspace, so moving the chip drops the
  // draft selection: keeping it would offer the previous workspace's grants.
  const { catalog: scopeCatalog, wildcards: scopeWildcards } = scopePickerCatalog(availableScopes);

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) createMutation.reset();
      }}
      title={ta("createTitle")}
      description={ta("createDescription", { workspace: workspaceName ?? t("thisWorkspace") })}
      submitLabel={t("createKey")}
      submittingLabel={ta("creating")}
      isSubmitting={createMutation.isPending}
      isDirty={createName.trim().length > 0 || createScopes.size > 0 || createSuperuser}
      contentClassName="!max-w-2xl"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        if (createName.trim().length === 0) {
          notify.error(ta("nameValidation"), {
            description: ta("nameHint")
          });
          return;
        }
        if (workspaceId === null) return;
        if (createSuperuser && !createExpiresAt) {
          notify.error(ta("expiryValidation"), {
            description: ta("expiryHint")
          });
          return;
        }
        if (createScopes.size === 0 && !createSuperuser) {
          // Not a blocker: a scope-less key is a legitimate placeholder. It
          // is only worth saying out loud, because it will 403 on everything.
          notify.warning(ta("noScopesWarning"), {
            description: ta("noScopesHint")
          });
        }

        const expires = createExpiresAt ? new Date(createExpiresAt) : null;
        createMutation.mutate(
          {
            workspace_id: workspaceId,
            expires_at:
              expires && !Number.isNaN(expires.getTime()) ? expires.toISOString() : null,
            name: createName.trim(),
            scopes: [...createScopes],
            is_superuser: createSuperuser
          },
          {
            onSuccess: (result) => {
              onCreated(result.key);
              onOpenChange(false);
              setCreateName("");
              setCreateExpiresAt("");
              setCreateScopes(new Set());
              setCreateSuperuser(false);
              notify.success(ta("created"), {
                description: ta("createdDescription")
              });
            }
          }
        );
      }}
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor={createNameId}>{t("name")}</Label>
          <Input
            id={createNameId}
            required
            maxLength={100}
            value={createName}
            onChange={(event) => setCreateName(event.target.value)}
          />
        </div>

        <DateTimePicker
          id="create-api-key-expires-date"
          timeId="create-api-key-expires-time"
          dateLabel={t("expires")}
          timeLabel={t("time")}
          value={createExpiresAt}
          onChange={setCreateExpiresAt}
          placeholder={t("never")}
          clearLabel={t("never")}
          minDate={new Date()}
          disabled={createMutation.isPending}
        />

        {isSuperuser ? (
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-0.5">
              <Label htmlFor={superuserId}>{t("superuserAccess")}</Label>
              <p className="text-xs text-muted-foreground">
                {ta("superuserDescription")}
              </p>
            </div>
            <Switch
              id={superuserId}
              checked={createSuperuser}
              onCheckedChange={setCreateSuperuser}
              disabled={createMutation.isPending}
            />
          </div>
        ) : null}

        {availableScopes.length === 0 ? (
          <p className="text-caption text-warning">{ta("inertDescription")}</p>
        ) : (
          <PermissionPicker
            mode="list"
            catalog={scopeCatalog}
            wildcards={scopeWildcards}
            value={createScopes}
            onChange={setCreateScopes}
            readOnly={createMutation.isPending}
          />
        )}
      </div>
    </EntityFormDialog>
  );
}
