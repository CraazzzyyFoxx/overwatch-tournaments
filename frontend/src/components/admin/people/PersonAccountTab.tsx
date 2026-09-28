"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Link2, UserRound } from "lucide-react";

import {
  AccountStatusPills,
  accountEmail,
  invalidateAccount
} from "@/components/admin/access/AccountCard";
import {
  AccountLinkedPlayer,
  AccountSignInMethods
} from "@/components/admin/access/AccountConnections";
import { AccountNotifications } from "@/components/admin/access/AccountNotifications";
import { AccountPermissions } from "@/components/admin/access/AccountPermissions";
import { AccountRestrictions } from "@/components/admin/access/AccountRestrictions";
import { AccountRoles } from "@/components/admin/access/AccountRoles";
import {
  AuthUserSearchCombobox,
  type AuthUserOption
} from "@/components/kit/AuthUserSearchCombobox";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";

/**
 * The auth account linked to one player, if any.
 *
 * Shared cache entry with the People list: the link lives on the auth side
 * (`linked_players`), and there is no "account for player N" read.
 */
export function useLinkedAccount(personId: number, canReadAuth: boolean) {
  const accountsQuery = useQuery({
    queryKey: accessQueryKeys.usersAll(),
    queryFn: () => rbacService.listUsersAll(),
    enabled: canReadAuth
  });
  const linked =
    accountsQuery.data?.find((account) =>
      account.linked_players.some((link) => link.player_id === personId)
    ) ?? null;
  return { accountsQuery, linked };
}

/** Frame for a group of account blocks; the blocks themselves are frameless. */
function Panel({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="divide-y divide-border/60 rounded-xl border border-border/60 px-4 [&>*]:py-4">
      {children}
    </div>
  );
}

function LinkAccount({ personId }: Readonly<{ personId: number }>) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<AuthUserOption | null>(null);

  const link = useMutation({
    mutationFn: (authUserId: number) =>
      rbacService.assignLinkedPlayer(authUserId, { player_id: personId, is_primary: true }),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      notify.success("Account linked");
    },
    onError: (error) => notify.apiError(error)
  });

  return (
    <div className="flex w-full max-w-md gap-2">
      <div className="min-w-0 flex-1">
        <AuthUserSearchCombobox
          value={picked?.id}
          selectedLabel={picked?.label}
          placeholder="Find the login…"
          onSelect={(option) => setPicked(option ?? null)}
        />
      </div>
      <Button
        variant="outline"
        className="h-10"
        disabled={picked == null || link.isPending}
        onClick={() => picked && link.mutate(picked.id)}
      >
        <Link2 aria-hidden className="size-3.5" />
        Link
      </Button>
    </div>
  );
}

/**
 * The auth account that signs in as this person — the same blocks the Access
 * inspector stacks, in two columns: what the account may do on the left, how
 * it signs in and what reaches it on the right.
 */
export function PersonAccountTab({
  personId,
  canReadAuth
}: Readonly<{ personId: number; canReadAuth: boolean }>) {
  const { hasPermission } = usePermissions();
  const canAssignRoles = hasPermission("role.update") && hasPermission("role.read");
  const canUpdateAccount = hasPermission("auth_user.update");
  const { accountsQuery, linked } = useLinkedAccount(personId, canReadAuth);

  const detailQuery = useQuery({
    queryKey: accessQueryKeys.userDetail(linked?.id ?? null),
    queryFn: () => rbacService.getUser(linked!.id),
    enabled: linked != null
  });

  if (!canReadAuth) {
    return (
      <PageStateCard
        state="empty"
        title="Accounts are not visible to you"
        description="Reading auth accounts needs the global auth_user.read grant."
      />
    );
  }

  if (accountsQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title="Could not load accounts"
        onAction={() => void accountsQuery.refetch()}
        actionLabel="Try again"
      />
    );
  }

  if (accountsQuery.isLoading) {
    return <div className="h-40 animate-pulse rounded-lg bg-muted/40 motion-reduce:animate-none" />;
  }

  if (!linked) {
    return (
      <EmptyNote
        icon={UserRound}
        title="No account signs in as this player"
        action={
          canUpdateAccount ? (
            <LinkAccount personId={personId} />
          ) : (
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/access/accounts">
                <ExternalLink aria-hidden className="size-3.5" />
                Open Access accounts
              </Link>
            </Button>
          )
        }
      >
        Link the login this player uses — its roles, restrictions and notifications then show up
        here.
      </EmptyNote>
    );
  }

  const detail = detailQuery.data;
  const email = accountEmail(linked);
  const accessHref = `/admin/access/accounts?search=${encodeURIComponent(linked.username)}&id=${linked.id}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-display text-lg font-semibold">@{linked.username}</h2>
            <AccountStatusPills account={detail ?? linked} />
          </div>
          <p className="text-sm text-muted-foreground">
            <span className="font-mono tabular-nums">#{linked.id}</span>
            {" · "}
            {email ?? "No email — signed up through OAuth"}
            {" · "}
            <span className="tabular-nums">Joined {linked.created_at.slice(0, 10)}</span>
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href={accessHref}>
            <ExternalLink aria-hidden className="size-3.5" />
            Open in Access
          </Link>
        </Button>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel>
          <AccountRoles
            userId={linked.id}
            roles={(detail ?? linked).roles}
            canEdit={canAssignRoles}
          />
          <AccountRestrictions userId={linked.id} canEdit={canAssignRoles} />
          {detail ? <AccountPermissions permissions={detail.effective_permissions} /> : null}
        </Panel>

        <Panel>
          <AccountLinkedPlayer
            account={detail ?? linked}
            canManage={canUpdateAccount}
            canOpenPerson={false}
          />
          <AccountSignInMethods userId={linked.id} />
          <AccountNotifications userId={linked.id} canEdit={canUpdateAccount} />
        </Panel>
      </div>
    </div>
  );
}
