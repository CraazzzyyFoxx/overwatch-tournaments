"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { rbacService } from "@/services/rbac.service";
import { accessQueryKeys } from "@/lib/access/query-keys";

function Field({ label, children }: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <div className="mt-1 break-words text-sm text-foreground">{children}</div>
    </div>
  );
}

/**
 * The auth account that signs in as this person — read-only.
 *
 * Everything editable about an account (roles, denies, sessions, the link
 * itself) lives in Access, so this is a summary with a way over there rather
 * than a second editing surface for the same record.
 */
export function PersonAccountTab({
  personId,
  personName,
  canReadAuth
}: Readonly<{ personId: number; personName: string; canReadAuth: boolean }>) {
  const accountsHref = `/admin/access/accounts?q=${encodeURIComponent(personName.split("#")[0] || personName)}`;

  // Shared cache entry with the People list: the link lives on the auth side
  // (`linked_players`), and there is no "account for player N" read.
  const accountsQuery = useQuery({
    queryKey: accessQueryKeys.usersAll(),
    queryFn: () => rbacService.listUsersAll(),
    enabled: canReadAuth
  });

  const linked =
    accountsQuery.data?.find((account) =>
      account.linked_players.some((link) => link.player_id === personId)
    ) ?? null;

  const detailQuery = useQuery({
    queryKey: accessQueryKeys.user(linked?.id ?? null),
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
      <div className="space-y-3">
        <PageStateCard
          state="empty"
          title="No account is linked to this identity"
          description="Nobody signs in as this player. Link an account from Access."
        />
        <div className="flex justify-center">
          <Button asChild variant="outline" size="sm">
            <Link href={accountsHref}>
              <ExternalLink aria-hidden className="size-3.5" />
              Open Access accounts
            </Link>
          </Button>
        </div>
      </div>
    );
  }

  const detail = detailQuery.data ?? linked;
  const primaryLink = linked.linked_players.find((link) => link.player_id === personId);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">{detail.username || detail.email}</h2>
        <Button asChild variant="outline" size="sm">
          <Link href={accountsHref}>
            <ExternalLink aria-hidden className="size-3.5" />
            Open in Access
          </Link>
        </Button>
      </div>

      <div className="grid gap-4 rounded-xl border border-border/60 p-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Account id">
          <span className="font-mono tabular-nums">#{detail.id}</span>
        </Field>
        <Field label="Email">{detail.email}</Field>
        <Field label="Status">
          <StatusPill tone={detail.is_active ? "success" : "danger"}>
            {detail.is_active ? "Active" : "Disabled"}
          </StatusPill>
        </Field>
        <Field label="Verified">{detail.is_verified ? "Yes" : "No"}</Field>
        <Field label="Superuser">{detail.is_superuser ? "Yes" : "No"}</Field>
        <Field label="Link">
          {primaryLink?.is_primary ? "Primary player" : "Secondary player"}
        </Field>
        <Field label="Roles">
          {detail.roles.length === 0 ? (
            <span className="text-muted-foreground">None</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {detail.roles.map((role) => (
                <Badge key={role.id} variant="outline" className="font-normal">
                  {role.name}
                </Badge>
              ))}
            </div>
          )}
        </Field>
        <Field label="Created">
          <span className="tabular-nums">{detail.created_at.slice(0, 10)}</span>
        </Field>
      </div>
    </div>
  );
}
