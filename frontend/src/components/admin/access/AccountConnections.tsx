"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AccountSection, invalidateAccount } from "@/components/admin/access/AccountCard";
import { ProviderMark } from "@/components/admin/OAuthProviderMark";
import { LoadErrorNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { UserSearchCombobox } from "@/components/kit/UserSearchCombobox";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { getSingleLinkedPlayer } from "@/lib/auth/profile-links";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import type { AuthAdminUser } from "@/types/rbac.types";
import type { MinimizedUser } from "@/types/user.types";
import { useTranslations } from "next-intl";

/**
 * The player identity this login plays as. One link at most, so it is one row
 * with its action, or a picker when there is none.
 */
export function AccountLinkedPlayer({
  account,
  canManage,
  canOpenPerson
}: Readonly<{
  account: AuthAdminUser;
  canManage: boolean;
  /** Off when the reader may not open People: the player id is shown instead. */
  canOpenPerson: boolean;
}>) {
  const t = useTranslations("adminAccess.connectionsUi");
  const tc = useTranslations("adminAccess.common");
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<MinimizedUser | null>(null);
  const linkedPlayer = getSingleLinkedPlayer(account.linked_players);

  const link = useMutation({
    mutationFn: (playerId: number) =>
      rbacService.assignLinkedPlayer(account.id, { player_id: playerId }),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      setPicked(null);
      notify.success(t("linked"));
    },
    onError: (error) => notify.apiError(error)
  });

  const unlink = useMutation({
    mutationFn: (playerId: number) => rbacService.removeLinkedPlayer(account.id, playerId),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      notify.success(t("unlinked"));
    },
    onError: (error) => notify.apiError(error)
  });

  return (
    <AccountSection title={tc("playerIdentity")}>
      {linkedPlayer ? (
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{linkedPlayer.player_name}</p>
            {canOpenPerson ? (
              <Link
                href={`/admin/people/${linkedPlayer.player_id}`}
                className="text-xs text-primary hover:underline"
              >
                {tc("openPeople")}
              </Link>
            ) : (
              <p className="text-xs tabular-nums text-muted-foreground">#{linkedPlayer.player_id}</p>
            )}
          </div>
          {canManage ? (
            <Button
              variant="ghost"
              size="sm"
              aria-label={t("unlinkLabel", { player: linkedPlayer.player_name })}
              disabled={unlink.isPending}
              onClick={() => unlink.mutate(linkedPlayer.player_id)}
            >
              {tc("unlink")}
            </Button>
          ) : null}
        </div>
      ) : canManage ? (
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <UserSearchCombobox
              value={picked?.id}
              selectedLabel={picked?.name}
              placeholder={tc("findPlayer")}
              searchPlaceholder={tc("searchPlayerIdentity")}
              onSelect={(user) => setPicked(user ?? null)}
            />
          </div>
          <Button
            variant="outline"
            disabled={picked == null || link.isPending}
            onClick={() => picked && link.mutate(picked.id)}
          >
            {tc("link")}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {t("notLinkedHistory")}
        </p>
      )}
    </AccountSection>
  );
}

/**
 * How the account signs in. Only a problem is marked — a green tick on every
 * healthy row was four icons that said nothing.
 */
export function AccountSignInMethods({ userId }: Readonly<{ userId: number }>) {
  const t = useTranslations("adminAccess.connectionsUi");
  const tc = useTranslations("adminAccess.common");
  const query = useQuery({
    queryKey: accessQueryKeys.userOauthConnections(userId),
    queryFn: () => rbacService.listOAuthConnections({ auth_user_id: userId, per_page: -1 })
  });
  const connections = query.data?.results ?? [];
  // Once per mount: "expired" is judged as of opening the account, not re-judged per render.
  const [now] = useState(() => Date.now());

  return (
    <AccountSection title={tc("signInMethods")}>
      {query.isLoading ? (
        <Skeleton className="h-12 w-full" />
      ) : query.isError ? (
        <LoadErrorNote onRetry={() => void query.refetch()} />
      ) : connections.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("noOauth")}
        </p>
      ) : (
        <ul className="space-y-2">
          {connections.map((connection) => {
            const expired =
              connection.token_expires_at != null &&
              new Date(connection.token_expires_at).getTime() < now;
            return (
              <li key={connection.id} className="flex items-center gap-2">
                <ProviderMark provider={connection.provider} />
                <span className="min-w-0 flex-1 truncate text-sm">
                  {connection.username}
                  {connection.email ? (
                    <span className="text-muted-foreground"> · {connection.email}</span>
                  ) : null}
                </span>
                {expired ? (
                  <StatusPill tone="warning" title={t("expiredTitle")}>
                    {t("tokenExpired")}
                  </StatusPill>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </AccountSection>
  );
}
