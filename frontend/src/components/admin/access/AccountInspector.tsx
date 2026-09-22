"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, CheckCircle, Link2, Shield, ShieldAlert, Trash2, XCircle } from "lucide-react";

import { AccountRestrictions } from "@/components/admin/access/AccountRestrictions";
import { ProviderBadge } from "@/components/admin/OAuthProviderBadge";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { getSingleLinkedPlayer } from "@/lib/auth/profile-links";
import { notify } from "@/lib/notify";
import { rbacService } from "@/services/rbac.service";
import type { RbacRole } from "@/types/rbac.types";
import type { MinimizedUser } from "@/types/user.types";

function Field({ label, children }: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <div className="mt-0.5 break-words text-sm">{children}</div>
    </div>
  );
}

export interface AccountInspectorProps {
  userId: number;
  canAssignRoles: boolean;
  canManageLinkedPlayers: boolean;
  /** Opens the identity in People, when the reader may see that list. */
  canReadPeople: boolean;
  /** Every role assignable in the current scope. */
  roles: RbacRole[];
}

/**
 * Everything about one auth account, in the T2 inspector.
 *
 * This is the four-tab modal the accounts list used to open: roles, linked
 * player, OAuth connections and permissions stacked in one scrollable panel
 * instead of behind a `Tabs` inside a `Dialog`. Nothing is hidden behind a tab
 * because the whole point of investigating an account is seeing its grants and
 * its restrictions at the same time.
 */
export function AccountInspector({
  userId,
  canAssignRoles,
  canManageLinkedPlayers,
  canReadPeople,
  roles
}: Readonly<AccountInspectorProps>) {
  const queryClient = useQueryClient();
  const [roleToAssign, setRoleToAssign] = useState("");
  const [playerId, setPlayerId] = useState<number | null>(null);
  const [playerName, setPlayerName] = useState("");

  const accountQuery = useQuery({
    queryKey: ["access-admin", "users", userId],
    queryFn: () => rbacService.getUser(userId)
  });

  const oauthQuery = useQuery({
    queryKey: ["access-admin", "users", userId, "oauth-connections"],
    queryFn: () => rbacService.listOAuthConnections({ auth_user_id: userId, per_page: -1 })
  });

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["access-admin", "users"] }),
      queryClient.invalidateQueries({ queryKey: ["access-admin", "roles"] })
    ]);
  };

  const assignRole = useMutation({
    mutationFn: (roleId: number) => rbacService.assignRole({ user_id: userId, role_id: roleId }),
    onSuccess: async () => {
      await invalidate();
      setRoleToAssign("");
      notify.success("Role assigned");
    },
    onError: (error) => notify.apiError(error)
  });

  const removeRole = useMutation({
    mutationFn: (roleId: number) => rbacService.removeRole({ user_id: userId, role_id: roleId }),
    onSuccess: async () => {
      await invalidate();
      notify.success("Role removed");
    },
    onError: (error) => notify.apiError(error)
  });

  const linkPlayer = useMutation({
    mutationFn: (player: number) =>
      rbacService.assignLinkedPlayer(userId, { player_id: player, is_primary: true }),
    onSuccess: async () => {
      await invalidate();
      setPlayerId(null);
      setPlayerName("");
      notify.success("Linked analytics account assigned");
    },
    onError: (error) => notify.apiError(error)
  });

  const unlinkPlayer = useMutation({
    mutationFn: (player: number) => rbacService.removeLinkedPlayer(userId, player),
    onSuccess: async () => {
      await invalidate();
      notify.success("Linked analytics account removed");
    },
    onError: (error) => notify.apiError(error)
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

  const linkedPlayer = getSingleLinkedPlayer(account.linked_players);
  const assignedRoleIds = new Set(account.roles.map((role) => role.id));
  const assignableRoles = roles.filter((role) => !assignedRoleIds.has(role.id));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {account.is_active ? (
          <StatusIcon icon={CheckCircle} label="Active" variant="success" />
        ) : (
          <StatusIcon icon={XCircle} label="Inactive" variant="muted" />
        )}
        {account.is_verified ? (
          <StatusIcon icon={BadgeCheck} label="Verified" variant="info" />
        ) : null}
        {account.is_superuser ? (
          <StatusIcon icon={ShieldAlert} label="Superuser" variant="destructive" />
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Account id">
          <span className="font-mono tabular-nums">#{account.id}</span>
        </Field>
        <Field label="Created">
          <span className="tabular-nums">{account.created_at.slice(0, 10)}</span>
        </Field>
      </div>

      <section className="space-y-2 rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>Assigned roles</p>
        {account.roles.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No roles. This account only has what every signed-in user gets.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {account.roles.map((role) => (
              <li key={role.id} className="flex items-center justify-between gap-2">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{role.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {role.description || "No description"}
                  </span>
                </span>
                {canAssignRoles ? (
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={`Remove role ${role.name} from this account`}
                    disabled={removeRole.isPending}
                    onClick={() => removeRole.mutate(role.id)}
                  >
                    Remove
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {canAssignRoles ? (
          <div className="space-y-2 border-t border-border/60 pt-2">
            <Label htmlFor="assign-role">Assign another role</Label>
            <Select value={roleToAssign} onValueChange={setRoleToAssign}>
              <SelectTrigger id="assign-role">
                <SelectValue placeholder="Select a role" />
              </SelectTrigger>
              <SelectContent>
                {assignableRoles.map((role) => (
                  <SelectItem key={role.id} value={String(role.id)}>
                    {role.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              disabled={assignRole.isPending}
              onClick={() => {
                if (!roleToAssign) {
                  notify.error("Pick a role first.", {
                    description: "Choose a role from the list, then assign it."
                  });
                  return;
                }
                assignRole.mutate(Number(roleToAssign));
              }}
            >
              <Shield aria-hidden className="size-3.5" />
              Assign role
            </Button>
          </div>
        ) : null}
      </section>

      <section className="space-y-2 rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>Linked player identity</p>
        {linkedPlayer ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">
                {linkedPlayer.player_name}
              </span>
              {canReadPeople ? (
                <Link
                  href={`/admin/people/${linkedPlayer.player_id}`}
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <Link2 aria-hidden className="size-3.5" />
                  Open the person card in People
                </Link>
              ) : (
                <span className="block font-mono text-xs tabular-nums text-muted-foreground">
                  #{linkedPlayer.player_id}
                </span>
              )}
            </span>
            {canManageLinkedPlayers ? (
              <Button
                variant="outline"
                size="sm"
                aria-label={`Unlink player ${linkedPlayer.player_name} from this account`}
                disabled={unlinkPlayer.isPending}
                onClick={() => unlinkPlayer.mutate(linkedPlayer.player_id)}
              >
                <Trash2 aria-hidden className="size-3.5" />
                Unlink
              </Button>
            ) : null}
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              Nothing in the tournament history belongs to this login yet.
            </p>
            {canManageLinkedPlayers ? (
              <div className="space-y-2">
                <Label htmlFor="assign-analytics-account">Assign a player identity</Label>
                <UserSearchCombobox
                  id="assign-analytics-account"
                  value={playerId ?? undefined}
                  selectedName={playerName || undefined}
                  placeholder="Select player identity"
                  searchPlaceholder="Search player identity…"
                  onSelect={(user: MinimizedUser | undefined) => {
                    setPlayerId(user?.id ?? null);
                    setPlayerName(user?.name ?? "");
                  }}
                />
                <Button
                  size="sm"
                  disabled={linkPlayer.isPending}
                  onClick={() => {
                    if (playerId == null) {
                      notify.error("Pick a player identity first.", {
                        description: "Search for the player this login belongs to, then assign it."
                      });
                      return;
                    }
                    linkPlayer.mutate(playerId);
                  }}
                >
                  <Link2 aria-hidden className="size-3.5" />
                  Assign identity
                </Button>
              </div>
            ) : null}
          </>
        )}
      </section>

      <section className="space-y-2 rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>OAuth connections</p>
        {oauthQuery.isLoading ? (
          <Skeleton className="h-12 w-full" />
        ) : oauthQuery.data?.results.length ? (
          <ul className="space-y-1.5">
            {oauthQuery.data.results.map((connection) => {
              const expired = connection.token_expires_at
                ? new Date(connection.token_expires_at) < new Date()
                : false;
              return (
                <li key={connection.id} className="flex items-center justify-between gap-2">
                  <span className="min-w-0">
                    <ProviderBadge provider={connection.provider} />
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {connection.username}
                      {connection.email ? ` · ${connection.email}` : ""}
                    </span>
                  </span>
                  {connection.token_expires_at ? (
                    expired ? (
                      <StatusIcon icon={ShieldAlert} label="Expired" variant="destructive" />
                    ) : (
                      <StatusIcon icon={CheckCircle} label="Active" variant="success" />
                    )
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">
            None. This account signs in with its email and password only.
          </p>
        )}
      </section>

      <AccountRestrictions userId={account.id} canEdit={canAssignRoles} />

      <section className="space-y-2 rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>
          Effective permissions ({account.effective_permissions.length})
        </p>
        {account.effective_permissions.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            None. Assign a role above to grant access.
          </p>
        ) : (
          <div className="flex max-h-48 flex-wrap gap-1 overflow-y-auto">
            {account.effective_permissions.map((permission) => (
              <Badge key={permission} variant="outline" className="font-mono text-xs">
                {permission}
              </Badge>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
