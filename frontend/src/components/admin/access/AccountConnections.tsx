"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Link2, Unlink } from "lucide-react";

import { AccountSection, invalidateAccount } from "@/components/admin/access/AccountCard";
import { ProviderBadge } from "@/components/admin/OAuthProviderBadge";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { getSingleLinkedPlayer } from "@/lib/auth/profile-links";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import type { AuthAdminUser } from "@/types/rbac.types";
import type { MinimizedUser } from "@/types/user.types";

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
  /** Off on the person's own page, where the link would point at itself. */
  canOpenPerson: boolean;
}>) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<MinimizedUser | null>(null);
  const linkedPlayer = getSingleLinkedPlayer(account.linked_players);

  const link = useMutation({
    mutationFn: (playerId: number) =>
      rbacService.assignLinkedPlayer(account.id, { player_id: playerId, is_primary: true }),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      setPicked(null);
      notify.success("Player identity linked");
    },
    onError: (error) => notify.apiError(error)
  });

  const unlink = useMutation({
    mutationFn: (playerId: number) => rbacService.removeLinkedPlayer(account.id, playerId),
    onSuccess: async () => {
      await invalidateAccount(queryClient);
      notify.success("Player identity unlinked");
    },
    onError: (error) => notify.apiError(error)
  });

  return (
    <AccountSection title="Player identity">
      {linkedPlayer ? (
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{linkedPlayer.player_name}</p>
            {canOpenPerson ? (
              <Link
                href={`/admin/people/${linkedPlayer.player_id}`}
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <ExternalLink aria-hidden className="size-3" />
                Open in People
              </Link>
            ) : (
              <p className="font-mono text-xs tabular-nums text-muted-foreground">
                #{linkedPlayer.player_id}
              </p>
            )}
          </div>
          {canManage ? (
            <Button
              variant="ghost"
              size="sm"
              aria-label={`Unlink player ${linkedPlayer.player_name} from this account`}
              disabled={unlink.isPending}
              onClick={() => unlink.mutate(linkedPlayer.player_id)}
            >
              <Unlink aria-hidden className="size-3.5" />
              Unlink
            </Button>
          ) : null}
        </div>
      ) : canManage ? (
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <UserSearchCombobox
              value={picked?.id}
              selectedName={picked?.name}
              placeholder="Find the player this login is…"
              searchPlaceholder="Search player identity…"
              onSelect={(user) => setPicked(user ?? null)}
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
      ) : (
        <p className="text-xs text-muted-foreground">
          Not linked. Nothing in the tournament history belongs to this login yet.
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
  const query = useQuery({
    queryKey: accessQueryKeys.userOauthConnections(userId),
    queryFn: () => rbacService.listOAuthConnections({ auth_user_id: userId, per_page: -1 })
  });
  const connections = query.data?.results ?? [];
  // Once per mount: "expired" is judged as of opening the account, not re-judged per render.
  const [now] = useState(() => Date.now());

  return (
    <AccountSection title="Sign-in methods" summary={query.data ? connections.length : undefined}>
      {query.isLoading ? (
        <Skeleton className="h-12 w-full" />
      ) : connections.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Email and password only — no OAuth provider is connected.
        </p>
      ) : (
        <ul className="space-y-2">
          {connections.map((connection) => {
            const expired =
              connection.token_expires_at != null &&
              new Date(connection.token_expires_at).getTime() < now;
            return (
              <li key={connection.id} className="flex items-center gap-2">
                <ProviderBadge provider={connection.provider} />
                <span className="min-w-0 flex-1 truncate text-sm">
                  {connection.username}
                  {connection.email ? (
                    <span className="text-muted-foreground"> · {connection.email}</span>
                  ) : null}
                </span>
                {expired ? (
                  <StatusPill
                    tone="warning"
                    title="Anything that calls this provider for the account fails until it reconnects."
                  >
                    Token expired
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
