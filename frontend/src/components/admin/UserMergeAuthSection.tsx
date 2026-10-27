import { useId } from "react";
import { useTranslations } from "next-intl";

import type { AuthMergePolicy, AuthMergePreview } from "@/types/admin.types";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getSocialProviderConfig } from "@/lib/social/providers";

function conflictValue(value: unknown, emptyLabel: string) {
  if (value == null || value === "") return emptyLabel;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}


type MergeSelectOption = { value: string; label: string; disabled?: boolean };

function MergeSelect({ id, value, options, placeholder, invalid, describedBy, onValueChange }: Readonly<{
  id: string;
  value: string;
  options: MergeSelectOption[];
  placeholder?: string;
  invalid?: boolean;
  describedBy?: string;
  onValueChange: (value: string) => void;
}>) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger id={id} aria-invalid={invalid} aria-describedby={describedBy}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value} disabled={option.disabled}>{option.label}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** What happens to one auth account once the merge goes through. */
function accountFateKey(ownsPlayer: boolean, removed: boolean) {
  if (ownsPlayer) return "ownsPlayer";
  if (removed) return "accountDeleted";
  return "keptUnlinked";
}

export function UserMergeAuthSection({
  preview,
  policy,
  reviewed,
  onPolicyChange
}: Readonly<{
  preview: AuthMergePreview;
  policy: AuthMergePolicy;
  reviewed: boolean;
  onPolicyChange: (policy: AuthMergePolicy) => void;
}>) {
  const t = useTranslations("adminPeople.mergeAuth");
  const sectionId = useId();
  const survivor = preview.accounts.find((account) => account.id === policy.surviving_auth_user_id);
  const other = preview.accounts.find((account) => account.id !== policy.surviving_auth_user_id);
  const deletedAccountId = policy.other_account_action === "delete" ? other?.id : undefined;
  const deleting = deletedAccountId != null;
  const otherAccountKey = deleting ? "deletedAfterTransfer" : "retainedUnlinked";
  const resourceLabel = (resource: string) => {
    if (resource === "oauth_connections") return t("resource.oauthLoginsMoved");
    if (resource === "workspace_memberships") return t("resource.workspaceMemberships");
    if (resource === "roles") return t("resource.rolesMoved");
    if (resource.startsWith("revoked_")) {
      const name = resource.slice("revoked_".length).replace(/^auth\./, "").replaceAll("_", " ").replaceAll(".", " ");
      if (name === "api key") return t("resource.apiKeysRevoked");
      if (name === "refresh token") return t("resource.refreshTokensRevoked");
    }
    return resource;
  };
  const accountLabel = (id: number) => {
    const account = preview.accounts.find((item) => item.id === id);
    return t("accountLabel", { account: account?.username ?? t("accountFallback"), id });
  };

  return (
    <section className="space-y-4 border-t pt-4" aria-labelledby={`${sectionId}-title`}>
      <h3 id={`${sectionId}-title`} className="text-sm font-semibold">{t("title")}</h3>
      <p className="max-w-[68ch] text-sm text-muted-foreground">
        {t("description")}
      </p>
      {!reviewed ? (
        <Alert>
          <AlertTitle>{t("previewRequired")}</AlertTitle>
          <AlertDescription>
            {t("changed")}
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={`${sectionId}-owner`}>{t("owner")}</Label>
          <MergeSelect
            id={`${sectionId}-owner`}
            value={String(policy.surviving_auth_user_id)}
            options={preview.accounts.map((account) => ({ value: String(account.id), label: accountLabel(account.id) }))}
            onValueChange={(value) => onPolicyChange({
              ...policy,
              surviving_auth_user_id: Number(value),
              conflict_choices: {},
              membership_actions: []
            })}
          />
        </div>
        {other ? (
          <div className="space-y-2">
            <Label htmlFor={`${sectionId}-other`}>{t("otherAccountLabel", { account: accountLabel(other.id) })}</Label>
            <MergeSelect
              id={`${sectionId}-other`}
              value={policy.other_account_action}
              options={[
                { value: "keep", label: t("keep") },
                { value: "delete", label: t("deleteTransfer") }
              ]}
              onValueChange={(value) => onPolicyChange({
                ...policy,
                other_account_action: value as "keep" | "delete",
                conflict_choices: {},
                membership_actions: []
              })}
            />
          </div>
        ) : null}
      </div>
      <p className="text-sm">
        {survivor ? t("ownerSummary", { account: accountLabel(survivor.id) }) : t("selectOwner")}
        {other ? ` ${t(otherAccountKey, { account: accountLabel(other.id) })}` : ""}
      </p>
      {other && policy.other_account_action === "keep" && preview.memberships?.length ? (
        <div className="space-y-3">
          <h4 className="text-sm font-medium">{t("memberships")}</h4>
          <p className="text-sm text-muted-foreground">
            {t("membershipDescription")}
          </p>
          {preview.memberships.map((membership) => (
            <div key={membership.workspace_id} className="space-y-2">
              <Label htmlFor={`${sectionId}-membership-${membership.workspace_id}`}>
                {t("membership", { id: membership.workspace_id, roles: membership.role_names.join(", "), account: accountLabel(membership.auth_user_id) })}
              </Label>
              <MergeSelect
                id={`${sectionId}-membership-${membership.workspace_id}`}
                value={policy.membership_actions?.find((item) => item.workspace_id === membership.workspace_id)?.action ?? ""}
                placeholder={t("chooseTransfer")}
                options={[
                  { value: "transfer", label: t("transfer") },
                  {
                    value: "merge",
                    label: t("mergeMembership"),
                    disabled: !membership.can_merge
                  }
                ]}
                onValueChange={(value) => onPolicyChange({
                  ...policy,
                  membership_actions: [
                    ...(policy.membership_actions ?? []).filter((item) => item.workspace_id !== membership.workspace_id),
                    { workspace_id: membership.workspace_id, action: value as "transfer" | "merge" }
                  ].sort((a, b) => a.workspace_id - b.workspace_id)
                })}
              />
            </div>
          ))}
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        {preview.accounts.map((account) => {
          const ownsPlayer = account.id === survivor?.id;
          const removed = account.id === deletedAccountId;
          return (
            <div key={account.id} className="space-y-1.5 text-sm">
              <p className="font-medium break-words">{accountLabel(account.id)}</p>
              <p className="text-xs text-muted-foreground">
                {t(accountFateKey(ownsPlayer, removed))}
              </p>
              <p className="break-words text-muted-foreground">{account.email}</p>
              <p className="text-muted-foreground">
                {t("accountFacts", {
                  password: account.has_password ? "yes" : "no",
                  active: account.is_active ? "yes" : "no"
                })}
              </p>
              {account.is_superuser ? (
                <p className="text-muted-foreground">{t("superuserStatus")}</p>
              ) : null}
              <p>
                {t("rolesLine", {
                  roles: account.roles.length
                    ? account.roles.map((role) => role.workspace_id == null
                      ? role.name
                      : t("roleWorkspace", { role: role.name, id: role.workspace_id })).join(", ")
                    : t("none")
                })}
              </p>
              {account.denies.length ? (
                <p>
                  {t("deniesLine", {
                    denies: account.denies
                      .map((deny) => `${deny.resource} ${deny.action}${deny.reason ? ` (${deny.reason})` : ""}`)
                      .join(", ")
                  })}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
      <div className="space-y-3">
        <h4 className="text-sm font-medium">{t("oauth")}</h4>
        {preview.oauth_connections.length ? preview.oauth_connections.map((connection) => {
          const destination = policy.oauth_destinations.find((item) => item.connection_id === connection.id)?.auth_user_id
            ?? connection.auth_user_id;
          const invalidDestination = destination === deletedAccountId;
          return (
            <div key={connection.id} className="space-y-2">
              <Label htmlFor={`${sectionId}-oauth-${connection.id}`} className="break-words">
                {getSocialProviderConfig(connection.provider).label}: {connection.username || connection.provider_user_id}
              </Label>
              <p className="text-xs text-muted-foreground">
                {t("connectionInfo", { subject: connection.provider_user_id, id: connection.id, account: accountLabel(connection.auth_user_id) })}
              </p>
              <MergeSelect
                id={`${sectionId}-oauth-${connection.id}`}
                value={invalidDestination ? "" : String(destination)}
                placeholder={t("chooseAccount")}
                invalid={Boolean(invalidDestination)}
                describedBy={invalidDestination ? `${sectionId}-oauth-error-${connection.id}` : undefined}
                options={preview.accounts.map((account) => ({
                  value: String(account.id),
                  label: account.id === deletedAccountId
                    ? t("selectedForDeletion", { account: accountLabel(account.id) })
                    : accountLabel(account.id),
                  disabled: account.id === deletedAccountId
                }))}
                onValueChange={(value) => onPolicyChange({
                  ...policy,
                  oauth_destinations: [
                    ...policy.oauth_destinations.filter((item) => item.connection_id !== connection.id),
                    { connection_id: connection.id, auth_user_id: Number(value) }
                  ].sort((a, b) => a.connection_id - b.connection_id)
                })}
              />
              {invalidDestination ? (
                <p id={`${sectionId}-oauth-error-${connection.id}`} className="text-sm text-danger">
                  {t("moveLogin")}
                </p>
              ) : null}
            </div>
          );
        }) : <EmptyNote>{t("noLogins")}</EmptyNote>}
      </div>
      <div className="space-y-2">
        <h4 className="text-sm font-medium">{t("moves")}</h4>
        {Object.entries(preview.resource_counts).some(([, count]) => count > 0) ? (
          <dl className="space-y-1.5 text-sm">
            {Object.entries(preview.resource_counts).filter(([, count]) => count > 0).map(([resource, count]) => (
              <div key={resource} className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">{resourceLabel(resource)}</dt>
                <dd className="tabular-nums">{count}</dd>
              </div>
            ))}
          </dl>
        ) : <p className="text-sm text-muted-foreground">{t("noResources")}</p>}
        {preview.permission_changes ? (
          <p className="text-sm text-muted-foreground">{t("roleWarning")}</p>
        ) : null}
      </div>
      {preview.data_conflicts.map((conflict) => (
        <div key={conflict.key} className="space-y-2 border-t pt-3">
          <Label htmlFor={`${sectionId}-conflict-${conflict.key}`}>{conflict.label} ({conflict.resource})</Label>
          <div className="grid gap-3 sm:grid-cols-2 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">{t("from")}</p>
              <p className="whitespace-pre-wrap break-words">{conflictValue(conflict.source_value, t("empty"))}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">{t("already")}</p>
              <p className="whitespace-pre-wrap break-words">{conflictValue(conflict.target_value, t("empty"))}</p>
            </div>
          </div>
          <MergeSelect
            id={`${sectionId}-conflict-${conflict.key}`}
            value={policy.conflict_choices[conflict.key] ?? ""}
            placeholder={t("chooseValue")}
            options={[{ value: "source", label: t("incoming") }, { value: "target", label: t("existing") }]}
            onValueChange={(value) => onPolicyChange({
              ...policy,
              conflict_choices: { ...policy.conflict_choices, [conflict.key]: value as "source" | "target" }
            })}
          />
        </div>
      ))}
      {preview.issues.length ? (
        <Alert tone="danger">
          <AlertTitle>{reviewed ? t("blocked") : t("previousIssues")}</AlertTitle>
          <AlertDescription><ul className="list-inside list-disc">{preview.issues.map((issue, index) => <li key={`${index}:${issue}`}>{issue}</li>)}</ul></AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}
