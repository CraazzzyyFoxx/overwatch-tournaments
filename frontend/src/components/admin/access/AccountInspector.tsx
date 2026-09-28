"use client";

import { useQuery } from "@tanstack/react-query";

import { AccountStatusPills } from "@/components/admin/access/AccountCard";
import {
  AccountLinkedPlayer,
  AccountSignInMethods
} from "@/components/admin/access/AccountConnections";
import { AccountNotifications } from "@/components/admin/access/AccountNotifications";
import { AccountPermissions } from "@/components/admin/access/AccountPermissions";
import { AccountRestrictions } from "@/components/admin/access/AccountRestrictions";
import { AccountRoles } from "@/components/admin/access/AccountRoles";
import { Skeleton } from "@/components/ui/skeleton";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { rbacService } from "@/services/rbac.service";

export interface AccountInspectorProps {
  userId: number;
  /** `role.update` + `role.read`: roles and restrictions. */
  canAssignRoles: boolean;
  /** `auth_user.update`: the player link and the DM switches. */
  canUpdateAccount: boolean;
  /** Opens the identity in People, when the reader may see that list. */
  canReadPeople: boolean;
}

/**
 * Everything about one auth account, in the T2 inspector.
 *
 * One column on hairlines rather than tabs: investigating an account means
 * seeing its grants and its restrictions at once. What is read every time —
 * roles, the player, how it signs in, notifications — is open; restrictions
 * and the effective-permission dump fold to one line each. People › Account
 * renders the same blocks in two columns.
 */
export function AccountInspector({
  userId,
  canAssignRoles,
  canUpdateAccount,
  canReadPeople
}: Readonly<AccountInspectorProps>) {
  const accountQuery = useQuery({
    queryKey: accessQueryKeys.userDetail(userId),
    queryFn: () => rbacService.getUser(userId)
  });

  if (accountQuery.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  const account = accountQuery.data;
  if (!account) {
    return (
      <p className="text-sm text-muted-foreground">
        Could not load this account. Close the inspector and reopen it — the account may have just
        been deleted.
      </p>
    );
  }

  return (
    <div className="divide-y divide-border/60 [&>*]:py-4 [&>*:first-child]:pt-0 [&>*:last-child]:pb-0">
      <div className="space-y-2">
        <AccountStatusPills account={account} />
        <p className="text-xs tabular-nums text-muted-foreground">
          <span className="font-mono">#{account.id}</span> · Joined{" "}
          {account.created_at.slice(0, 10)}
        </p>
      </div>
      <AccountRoles userId={account.id} roles={account.roles} canEdit={canAssignRoles} />
      <AccountLinkedPlayer
        account={account}
        canManage={canUpdateAccount}
        canOpenPerson={canReadPeople}
      />
      <AccountSignInMethods userId={account.id} />
      <AccountNotifications userId={account.id} canEdit={canUpdateAccount} />
      <AccountRestrictions userId={account.id} canEdit={canAssignRoles} />
      <AccountPermissions permissions={account.effective_permissions} />
    </div>
  );
}
