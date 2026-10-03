import { useId } from "react";

import type { AuthMergePolicy, AuthMergePreview } from "@/types/admin.types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyNote } from "@/components/kit/EmptyNote";

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
      <p className="text-sm text-muted-foreground">
        Social profile identities are not sign-in connections. Choose the owner of the surviving
        player and the destination of each real OAuth login below. Passwords, email, active status
        and superuser status stay with their account; credentials are never combined.
      </p>
      {!reviewed ? (
        <Alert>
          <AlertTitle>Preview required</AlertTitle>
          <AlertDescription>
            Account choices have changed. Counts, permission effects and issues below belong to the
            previous preview. Run Preview merge again before acknowledging or executing this plan.
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
              conflict_choices: {}
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
                conflict_choices: {}
              })}
            />
          </div>
        ) : null}
      </div>
      <p className="text-sm">
        {survivor ? `${accountLabel(survivor.id)} will own the target player.` : "Select a surviving owner."}
        {other ? ` ${accountLabel(other.id)} will be ${deleting ? "deleted after transfer" : "retained, without ownership of the merged player"}.` : ""}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {preview.accounts.map((account) => (
          <div key={account.id} className="space-y-2 rounded-md border p-3 text-sm">
            <p className="font-medium break-words">{accountLabel(account.id)}</p>
            <p className="break-words text-muted-foreground">{account.email}</p>
            <div className="flex flex-wrap gap-1">
              <Badge variant="outline">{account.has_password ? "Password set" : "No password"}</Badge>
              <Badge variant="outline">{account.is_active ? "Active" : "Inactive"}</Badge>
              {account.is_superuser ? <Badge variant="outline">Superuser (not transferred)</Badge> : null}
            </div>
            <p className="font-medium">Roles</p>
            {account.roles.length ? (
              <ul className="list-inside list-disc break-words">
                {account.roles.map((role) => (
                  <li key={`${role.id}:${role.workspace_id}`}>
                    {role.name} — {role.workspace_id == null ? "global" : `workspace #${role.workspace_id}`}
                  </li>
                ))}
              </ul>
            ) : <p className="text-muted-foreground">None</p>}
            <p className="font-medium">Explicit denies (preserved)</p>
            {account.denies.length ? (
              <ul className="list-inside list-disc break-words">
                {account.denies.map((deny) => (
                  <li key={`${deny.permission_id}:${deny.workspace_id}`}>
                    {deny.resource}:{deny.action} — {deny.workspace_id == null ? "global" : `workspace #${deny.workspace_id}`}
                    {deny.reason ? ` (${deny.reason})` : ""}
                  </li>
                ))}
              </ul>
            ) : <p className="text-muted-foreground">None</p>}
          </div>
        ))}
      </div>
      <div className="space-y-3">
        <h4 className="text-sm font-medium">OAuth login destinations</h4>
        {preview.oauth_connections.length ? preview.oauth_connections.map((connection) => {
          const destination = policy.oauth_destinations.find((item) => item.connection_id === connection.id)?.auth_user_id
            ?? connection.auth_user_id;
          const invalidDestination = destination === deletedAccountId;
          return (
            <div key={connection.id} className="space-y-2 rounded-md border p-3">
              <Label htmlFor={`${sectionId}-oauth-${connection.id}`} className="break-words">
                {connection.provider}: {connection.username || connection.provider_user_id} (subject {connection.provider_user_id}, connection #{connection.id})
              </Label>
              <p className="text-xs text-muted-foreground">Currently owned by {accountLabel(connection.auth_user_id)}</p>
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
        <h4 className="text-sm font-medium">Reviewed resource transfers</h4>
        {Object.entries(preview.resource_counts).length ? (
          <dl className="space-y-2 text-sm">
            {Object.entries(preview.resource_counts).map(([resource, count]) => (
              <div key={resource} className="flex items-start justify-between gap-3">
                <dt className="break-words text-muted-foreground">{resource.replaceAll("_", " ")}</dt>
                <dd><Badge variant="secondary">{count}</Badge></dd>
              </div>
            ))}
          </dl>
        ) : <p className="text-sm text-muted-foreground">No auth-owned resources transfer in this preview.</p>}
        <p className="text-sm text-muted-foreground">
          {preview.permission_changes
            ? "The reviewed plan changes sign-in access, roles, explicit denies, or resource ownership. Review both accounts above; permission changes require a separate acknowledgement."
            : "The reviewed plan does not change sign-in access, roles, explicit denies, or resource ownership."}
          {" Sessions and API keys for both affected accounts are revoked, not transferred; retained accounts must sign in again."}
          {preview.policy.other_account_action === "keep"
            ? " Retained accounts must still have a usable login and cannot be unlinked from required operational memberships."
            : ""}
        </p>
      </div>
      {preview.data_conflicts.map((conflict) => (
        <div key={conflict.key} className="space-y-2 rounded-md border p-3">
          <Label htmlFor={`${sectionId}-conflict-${conflict.key}`}>{conflict.label} ({conflict.resource})</Label>
          <div className="grid gap-3 sm:grid-cols-2 text-xs">
            <div><p className="font-medium">Incoming (transferring account)</p><pre className="whitespace-pre-wrap break-all">{JSON.stringify(conflict.source_value, null, 2)}</pre></div>
            <div><p className="font-medium">Existing (surviving account)</p><pre className="whitespace-pre-wrap break-all">{JSON.stringify(conflict.target_value, null, 2)}</pre></div>
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
