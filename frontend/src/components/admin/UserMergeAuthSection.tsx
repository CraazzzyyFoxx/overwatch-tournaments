import { useId } from "react";

import type { AuthMergePolicy, AuthMergePreview } from "@/types/admin.types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const RESOURCE_LABELS: Record<string, string> = {
  oauth_connections: "OAuth logins moved",
  workspace_memberships: "Workspace memberships",
  roles: "Roles moved"
};

function resourceLabel(key: string) {
  if (RESOURCE_LABELS[key]) return RESOURCE_LABELS[key];
  if (key.startsWith("revoked_")) {
    const name = key.slice("revoked_".length).replace(/^auth\./, "").replaceAll("_", " ").replaceAll(".", " ");
    if (name === "api key") return "API keys revoked";
    if (name === "refresh token") return "Refresh tokens revoked";
    return `${name} revoked`;
  }
  return key.replaceAll("_", " ").replaceAll(".", " ");
}
function conflictValue(value: unknown) {
  if (value == null || value === "") return "Empty";
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
      <SelectTrigger id={id} className="h-10" aria-invalid={invalid} aria-describedby={describedBy}>
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
  const sectionId = useId();
  const survivor = preview.accounts.find((account) => account.id === policy.surviving_auth_user_id);
  const other = preview.accounts.find((account) => account.id !== policy.surviving_auth_user_id);
  const deletedAccountId = policy.other_account_action === "delete" ? other?.id : undefined;
  const deleting = deletedAccountId != null;
  const accountLabel = (id: number) => {
    const account = preview.accounts.find((item) => item.id === id);
    return `${account?.username ?? "Account"} (#${id})`;
  };

  return (
    <section className="space-y-4 rounded-lg border p-4" aria-labelledby={`${sectionId}-title`}>
      <h3 id={`${sectionId}-title`} className="text-sm font-semibold">Sign-in accounts and ownership</h3>
      <p className="max-w-[68ch] text-sm text-muted-foreground">
        Pick who owns the surviving player, and where each login goes. Passwords stay with their account.
      </p>
      {!reviewed ? (
        <Alert>
          <AlertTitle>Preview required</AlertTitle>
          <AlertDescription>
            Choices changed. Preview again before confirming. The counts below are from the previous preview.
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={`${sectionId}-owner`}>Surviving player owner</Label>
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
            <Label htmlFor={`${sectionId}-other`}>Other account: {accountLabel(other.id)}</Label>
            <MergeSelect
              id={`${sectionId}-other`}
              value={policy.other_account_action}
              options={[
                { value: "keep", label: "Keep account (unlink from the merged player)" },
                { value: "delete", label: "Delete account and transfer its resources" }
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
        {survivor ? `${accountLabel(survivor.id)} will own the target player.` : "Select a surviving owner."}
        {other ? ` ${accountLabel(other.id)} will be ${deleting ? "deleted after transfer" : "retained, without ownership of the merged player"}.` : ""}
      </p>
      {other && policy.other_account_action === "keep" && preview.memberships?.length ? (
        <div className="space-y-3">
          <h4 className="text-sm font-medium">Workspace memberships</h4>
          <p className="text-sm text-muted-foreground">
            Keeping {accountLabel(other.id)} unlinks it from the merged player. Move each operational
            workspace role onto the surviving account, or merge it when that account already belongs there.
          </p>
          {preview.memberships.map((membership) => (
            <div key={membership.workspace_id} className="space-y-2">
              <Label htmlFor={`${sectionId}-membership-${membership.workspace_id}`}>
                Workspace #{membership.workspace_id}: {membership.role_names.join(", ")} on {accountLabel(membership.auth_user_id)}
              </Label>
              <MergeSelect
                id={`${sectionId}-membership-${membership.workspace_id}`}
                value={policy.membership_actions?.find((item) => item.workspace_id === membership.workspace_id)?.action ?? ""}
                placeholder="Choose transfer or merge"
                options={[
                  { value: "transfer", label: "Transfer to surviving account" },
                  {
                    value: "merge",
                    label: "Merge with surviving membership",
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
            <div key={account.id} className="space-y-1.5 rounded-md border px-3 py-2 text-sm">
              <p className="font-medium break-words">{accountLabel(account.id)}</p>
              <p className="text-xs text-muted-foreground">
                {ownsPlayer ? "Owns the surviving player" : removed ? "Deleted after transfer" : "Kept, unlinked from the player"}
              </p>
              <p className="break-words text-muted-foreground">{account.email}</p>
              <p className="text-muted-foreground">
                {account.has_password ? "Password set" : "No password"}, {account.is_active ? "active" : "inactive"}
                {account.is_superuser ? ". Superuser status stays here" : ""}
              </p>
              <p>
                <span className="text-muted-foreground">Roles: </span>
                {account.roles.length
                  ? account.roles.map((role) => `${role.name}${role.workspace_id == null ? "" : ` in workspace ${role.workspace_id}`}`).join(", ")
                  : "none"}
              </p>
              {account.denies.length ? (
                <p>
                  <span className="text-muted-foreground">Denies: </span>
                  {account.denies.map((deny) => `${deny.resource} ${deny.action}${deny.reason ? ` (${deny.reason})` : ""}`).join(", ")}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
      <div className="space-y-3">
        <h4 className="text-sm font-medium">OAuth login destinations</h4>
        {preview.oauth_connections.length ? preview.oauth_connections.map((connection) => {
          const destination = policy.oauth_destinations.find((item) => item.connection_id === connection.id)?.auth_user_id
            ?? connection.auth_user_id;
          const invalidDestination = destination === deletedAccountId;
          return (
            <div key={connection.id} className="space-y-2">
              <Label htmlFor={`${sectionId}-oauth-${connection.id}`} className="break-words">
                {connection.provider}: {connection.username || connection.provider_user_id}
              </Label>
              <p className="text-xs text-muted-foreground">
                Subject {connection.provider_user_id}, connection #{connection.id}. Currently owned by {accountLabel(connection.auth_user_id)}.
              </p>
              <MergeSelect
                id={`${sectionId}-oauth-${connection.id}`}
                value={invalidDestination ? "" : String(destination)}
                placeholder="Choose a retained sign-in account"
                invalid={Boolean(invalidDestination)}
                describedBy={invalidDestination ? `${sectionId}-oauth-error-${connection.id}` : undefined}
                options={preview.accounts.map((account) => ({
                  value: String(account.id),
                  label: `${accountLabel(account.id)}${account.id === deletedAccountId ? " — selected for deletion" : ""}`,
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
                  Move this login to a retained account before deleting its current owner.
                </p>
              ) : null}
            </div>
          );
        }) : <EmptyNote>No OAuth logins on these accounts. Retained accounts must have a password.</EmptyNote>}
      </div>
      <div className="space-y-2">
        <h4 className="text-sm font-medium">What moves with the accounts</h4>
        {Object.entries(preview.resource_counts).some(([, count]) => count > 0) ? (
          <dl className="space-y-1.5 text-sm">
            {Object.entries(preview.resource_counts).filter(([, count]) => count > 0).map(([resource, count]) => (
              <div key={resource} className="flex items-baseline justify-between gap-3">
                <dt className="text-muted-foreground">{resourceLabel(resource)}</dt>
                <dd className="tabular-nums">{count}</dd>
              </div>
            ))}
          </dl>
        ) : <p className="text-sm text-muted-foreground">No auth-owned resources move in this preview.</p>}
        {preview.permission_changes ? (
          <p className="text-sm text-muted-foreground">Roles or access change. That needs its own confirmation below.</p>
        ) : null}
      </div>
      {preview.data_conflicts.map((conflict) => (
        <div key={conflict.key} className="space-y-2 rounded-md border p-3">
          <Label htmlFor={`${sectionId}-conflict-${conflict.key}`}>{conflict.label} ({conflict.resource})</Label>
          <div className="grid gap-3 sm:grid-cols-2 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">From the transferring account</p>
              <p className="whitespace-pre-wrap break-words">{conflictValue(conflict.source_value)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Already on the surviving account</p>
              <p className="whitespace-pre-wrap break-words">{conflictValue(conflict.target_value)}</p>
            </div>
          </div>
          <MergeSelect
            id={`${sectionId}-conflict-${conflict.key}`}
            value={policy.conflict_choices[conflict.key] ?? ""}
            placeholder="Choose which value to keep"
            options={[{ value: "source", label: "Incoming" }, { value: "target", label: "Existing" }]}
            onValueChange={(value) => onPolicyChange({
              ...policy,
              conflict_choices: { ...policy.conflict_choices, [conflict.key]: value as "source" | "target" }
            })}
          />
        </div>
      ))}
      {preview.issues.length ? (
        <Alert variant="destructive">
          <AlertTitle>{reviewed ? "Auth merge blocked" : "Issues from previous preview"}</AlertTitle>
          <AlertDescription><ul className="list-inside list-disc">{preview.issues.map((issue, index) => <li key={`${index}:${issue}`}>{issue}</li>)}</ul></AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}
