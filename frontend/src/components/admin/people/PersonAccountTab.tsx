"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserRound } from "lucide-react";

import {
  AccountBlocksAsCards,
  AccountStatusPills,
  accountEmail,
  invalidateAccount
} from "@/components/admin/access/AccountCard";
import { AccountSignInMethods } from "@/components/admin/access/AccountConnections";
import { AccountNotifications } from "@/components/admin/access/AccountNotifications";
import { AccountPermissions } from "@/components/admin/access/AccountPermissions";
import { AccountRestrictions } from "@/components/admin/access/AccountRestrictions";
import { AccountRoles } from "@/components/admin/access/AccountRoles";
import {
  AuthUserSearchCombobox,
  type AuthUserOption
} from "@/components/kit/UserSearchCombobox";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { SettingGroup } from "@/components/kit/SettingRow";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useFormatter } from "@/lib/datetime/client";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import type { AuthAdminUser } from "@/types/rbac.types";

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

function LinkAccount({ personId }: Readonly<{ personId: number }>) {
  const t = useTranslations("adminPeople.account");
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<AuthUserOption | null>(null);

  const link = useMutation({
    mutationFn: (authUserId: number) =>
      rbacService.assignLinkedPlayer(authUserId, { player_id: personId }),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      notify.success(t("linked"));
    },
    onError: (error) => notify.apiError(error)
  });

  return (
    <div className="flex w-full max-w-md gap-2">
      <div className="min-w-0 flex-1">
        <AuthUserSearchCombobox
          value={picked?.id}
          selectedLabel={picked?.label}
          placeholder={t("find")}
          onSelect={(option) => setPicked(option ?? null)}
        />
      </div>
      <Button
        variant="outline"
        disabled={picked == null || link.isPending}
        onClick={() => picked && link.mutate(picked.id)}
      >
        {t("link")}
      </Button>
    </div>
  );
}

/**
 * Cuts the account off this player, behind a confirmation: the account keeps
 * its roles, but stops signing in as this person.
 */
function UnlinkAccount({
  account,
  personId
}: Readonly<{ account: AuthAdminUser; personId: number }>) {
  const t = useTranslations("adminPeople.account");
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const unlink = useMutation({
    mutationFn: () => rbacService.removeLinkedPlayer(account.id, personId),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      setConfirmOpen(false);
      notify.success(t("unlinked"));
    },
    onError: (error) => notify.apiError(error)
  });

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setConfirmOpen(true)}>
        {t("unlink")}
      </Button>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        pending={unlink.isPending}
        intent={{
          title: t("unlinkTitle"),
          description: t("unlinkDescription", { username: account.username }),
          confirmLabel: t("unlink"),
          tone: "danger"
        }}
        onConfirm={() => unlink.mutate()}
      />
    </>
  );
}

/** First load: the account card, then the two columns of block cards. */
function AccountTabSkeleton() {
  return (
    <div aria-hidden className="space-y-4">
      <Skeleton className="h-24 w-full rounded-xl" />
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl" />
      </div>
    </div>
  );
}

/**
 * The auth account that signs in as this person — the same blocks the Access
 * inspector stacks, here each its own card, in two columns: how it signs in and
 * what it may do on the left, what reaches it on the right. The player link is
 * not a block here: this page is that player.
 */
export function PersonAccountTab({
  personId,
  canReadAuth
}: Readonly<{ personId: number; canReadAuth: boolean }>) {
  const t = useTranslations("adminPeople.account");
  const format = useFormatter();
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
        title={t("notVisible")}
        description={t("grant")}
      />
    );
  }

  if (accountsQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("loadError")}
        onAction={() => void accountsQuery.refetch()}
        actionLabel={t("retry")}
      />
    );
  }

  if (accountsQuery.isLoading) return <AccountTabSkeleton />;

  if (!linked) {
    return (
      <EmptyNote
        icon={UserRound}
        title={t("none")}
        action={
          canUpdateAccount ? (
            <LinkAccount personId={personId} />
          ) : (
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/access/accounts">{t("open")}</Link>
            </Button>
          )
        }
      >
        {t("description")}
      </EmptyNote>
    );
  }

  const detail = detailQuery.data;
  const account = detail ?? linked;
  const email = accountEmail(linked);
  const accessHref = `/admin/access/accounts?search=${encodeURIComponent(linked.username)}&id=${linked.id}`;

  return (
    <div className="space-y-4">
      <SettingGroup
        id="account"
        title={`@${linked.username}`}
        actions={
          <>
            <Button asChild variant="outline" size="sm">
              <Link href={accessHref}>{t("openInAccess")}</Link>
            </Button>
            {canUpdateAccount ? <UnlinkAccount account={linked} personId={personId} /> : null}
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <AccountStatusPills account={account} />
          <p className="text-caption text-muted-foreground">
            <span className="font-mono tabular-nums">#{linked.id}</span>
            {" · "}
            {email ?? t("noEmail")}
            {" · "}
            <span className="tabular-nums">
              {t("joinedOn", { date: format.dateTime(new Date(linked.created_at), { dateStyle: "medium" }) })}
            </span>
          </p>
        </div>
      </SettingGroup>

      <AccountBlocksAsCards>
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-4">
            <AccountSignInMethods userId={linked.id} />
            <AccountRoles userId={linked.id} roles={account.roles} canEdit={canAssignRoles} />
            <AccountRestrictions userId={linked.id} canEdit={canAssignRoles} />
            {detail ? <AccountPermissions permissions={detail.effective_permissions} /> : null}
          </div>
          <div className="flex min-w-0 flex-col gap-4">
            <AccountNotifications userId={linked.id} canEdit={canUpdateAccount} />
          </div>
        </div>
      </AccountBlocksAsCards>
    </div>
  );
}
