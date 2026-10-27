"use client";

import { createContext, useContext, useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import type { QueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";

import { SettingGroup } from "@/components/kit/SettingRow";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { getSingleLinkedPlayer } from "@/lib/auth/profile-links";
import { cn } from "@/lib/utils";
import type { AuthAdminUser } from "@/types/rbac.types";

/**
 * The parts every account block shares, so the Access inspector and the
 * People › Account tab are one surface laid out twice, not two surfaces.
 *
 * The container decides the frame: the inspector stacks the blocks open, on
 * hairlines in one column; the person hub wraps them in `AccountBlocksAsCards`,
 * where each block is a `SettingGroup` card like every other hub section.
 */

const AsCards = createContext(false);

/** Every account block below renders as its own card. */
export function AccountBlocksAsCards({ children }: Readonly<{ children: ReactNode }>) {
  return <AsCards.Provider value>{children}</AsCards.Provider>;
}

/** Right of a block title: a count or a verdict, in body case. */
const SUMMARY_CLASS = "text-xs font-normal normal-case tracking-normal text-muted-foreground";

export function AccountSection({
  title,
  summary,
  action,
  children
}: Readonly<{ title: string; summary?: ReactNode; action?: ReactNode; children: ReactNode }>) {
  const asCard = useContext(AsCards);
  // No anchor links to a block; the card needs an id all the same.
  const id = useId();
  if (asCard) {
    return (
      <SettingGroup id={id} title={title} summary={summary} actions={action}>
        <div className="space-y-2.5">{children}</div>
      </SettingGroup>
    );
  }
  return (
    <section className="space-y-2.5">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <h3 className={eyebrowClass("muted")}>
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
 * active restriction) is never hidden behind the chevron. As a card, the
 * chevron sits at the end of the card's title line and a collapsed card is
 * that line alone.
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
  const asCard = useContext(AsCards);
  const id = useId();
  // The card's own state while the block leaves `open` uncontrolled.
  const [ownOpen, setOwnOpen] = useState(false);
  if (asCard) {
    const isOpen = open ?? ownOpen;
    const contentId = `${id}-content`;
    return (
      <SettingGroup
        id={id}
        title={title}
        summary={summary}
        actions={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={title}
            aria-expanded={isOpen}
            aria-controls={isOpen ? contentId : undefined}
            onClick={() => {
              setOwnOpen(!isOpen);
              onOpenChange?.(!isOpen);
            }}
          >
            <ChevronDown
              aria-hidden
              className={cn("transition-transform motion-reduce:transition-none", isOpen && "rotate-180")}
            />
          </Button>
        }
      >
        {preview}
        {isOpen ? (
          <div id={contentId} className="space-y-2.5">
            {children}
          </div>
        ) : null}
      </SettingGroup>
    );
  }
  return (
    <Collapsible open={open} onOpenChange={onOpenChange} asChild>
      <section className="space-y-2.5">
        <h3>
          <CollapsibleTrigger className="group flex min-h-7 w-full items-center gap-1.5 rounded-md text-left focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring">
            <ChevronRight
              aria-hidden
              className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90 motion-reduce:transition-none"
            />
            <span className={eyebrowClass("muted")}>{title}</span>
            {summary != null ? <span className={SUMMARY_CLASS}>{summary}</span> : null}
          </CollapsibleTrigger>
        </h3>
        {preview}
        <CollapsibleContent className="space-y-2.5">{children}</CollapsibleContent>
      </section>
    </Collapsible>
  );
}

/** Only the states that want attention: active and verified are the norm and render nothing. */
export function AccountStatusPills({ account }: Readonly<{ account: AuthAdminUser }>) {
  const t = useTranslations("adminAccess.common");
  if (account.is_active && !account.is_superuser) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {account.is_active ? null : <StatusPill tone="neutral">{t("inactive")}</StatusPill>}
      {account.is_superuser ? <StatusPill tone="danger">{t("superuser")}</StatusPill> : null}
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
