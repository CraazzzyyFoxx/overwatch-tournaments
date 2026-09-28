"use client";

import type { ReactNode } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";

import { StatusPill } from "@/components/kit/StatusPill";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { getSingleLinkedPlayer } from "@/lib/auth/profile-links";
import type { AuthAdminUser } from "@/types/rbac.types";

/**
 * The parts every account block shares, so the Access inspector and the
 * People › Account tab are one surface laid out twice, not two surfaces.
 *
 * Blocks are frameless: the inspector stacks them on hairlines, the person hub
 * groups them into cards, so the frame belongs to the container.
 */

/** Right of a block title: a count or a verdict, in body case. */
const SUMMARY_CLASS = "text-xs font-normal normal-case tracking-normal text-muted-foreground";

export function AccountSection({
  title,
  summary,
  action,
  children
}: Readonly<{ title: string; summary?: ReactNode; action?: ReactNode; children: ReactNode }>) {
  return (
    <section className="space-y-2.5">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h3 className={EYEBROW_CLASS}>
          {title}
          {summary != null ? <span className={`ml-2 ${SUMMARY_CLASS}`}>{summary}</span> : null}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

/**
 * A block read far more rarely than it is scrolled past. Collapsed it is one
 * line with its verdict; `preview` renders either way, so what matters (an
 * active restriction) is never hidden behind the chevron.
 */
export function AccountDisclosure({
  title,
  summary,
  preview,
  open,
  onOpenChange,
  children
}: Readonly<{
  title: string;
  summary?: ReactNode;
  preview?: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
}>) {
  return (
    <Collapsible open={open} onOpenChange={onOpenChange} asChild>
      <section className="space-y-2.5">
        <h3>
          <CollapsibleTrigger className="group flex min-h-7 w-full items-center gap-1.5 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <ChevronRight
              aria-hidden
              className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90 motion-reduce:transition-none"
            />
            <span className={EYEBROW_CLASS}>{title}</span>
            {summary != null ? <span className={SUMMARY_CLASS}>{summary}</span> : null}
          </CollapsibleTrigger>
        </h3>
        {preview}
        <CollapsibleContent className="space-y-2.5">{children}</CollapsibleContent>
      </section>
    </Collapsible>
  );
}

export function AccountStatusPills({ account }: Readonly<{ account: AuthAdminUser }>) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <StatusPill tone={account.is_active ? "success" : "neutral"} dot>
        {account.is_active ? "Active" : "Inactive"}
      </StatusPill>
      {account.is_verified ? <StatusPill tone="info">Verified</StatusPill> : null}
      {account.is_superuser ? <StatusPill tone="danger">Superuser</StatusPill> : null}
    </div>
  );
}

/**
 * An OAuth sign-up without an email is stored as
 * `{provider_user_id}@{provider}.oauth` — a unique key, not an address, and
 * not something to headline an account with.
 */
export function accountEmail(account: Pick<AuthAdminUser, "email">): string | null {
  return account.email.endsWith(".oauth") ? null : account.email;
}

/** The name a person recognises: the linked player, then the login name. */
export function accountTitle(account: AuthAdminUser): string {
  return (
    getSingleLinkedPlayer(account.linked_players)?.player_name ||
    account.username ||
    account.email
  );
}

/** A role or link write changes the account row, its detail and the role lists. */
export function invalidateAccount(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: accessQueryKeys.users() }),
    queryClient.invalidateQueries({ queryKey: accessQueryKeys.roles() })
  ]);
}
