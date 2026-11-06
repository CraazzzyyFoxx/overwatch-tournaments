"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { usePermissions } from "@/hooks/usePermissions";
import { formationModes } from "@/lib/tournament/flow-nodes";
import type { Tournament } from "@/types/tournament.types";

import type { TabAccess } from "./tab-guards";

/**
 * The tab a hub path is on: the first segment after `basePath`, `fallback`
 * for the bare base path. `segment` is that raw segment; `active` is it only
 * when it names one of `tabs`, else `fallback`.
 */
export function useSubTabSegment<T extends string>(
  basePath: string,
  tabs: readonly T[],
  fallback: T
): { segment: string; active: T; isKnown: boolean } {
  const pathname = usePathname();
  const segment = pathname.startsWith(basePath)
    ? (pathname.slice(basePath.length).split("/").find(Boolean) ?? fallback)
    : fallback;
  const isKnown = (tabs as readonly string[]).includes(segment);
  return { segment, active: isKnown ? (segment as T) : fallback, isKnown };
}

/** A hub tab's sub-tab row over its body; the body waits until the open sub-tab is `allowed`. */
export function SubTabShell({
  items,
  activeKey,
  ariaLabel,
  allowed,
  children
}: Readonly<{
  items: readonly LinkTabItem[];
  activeKey: string;
  ariaLabel: string;
  allowed: boolean;
  children: ReactNode;
}>) {
  return (
    <div className="space-y-4">
      <LinkTabs items={items} activeKey={activeKey} level={2} ariaLabel={ariaLabel} />
      {allowed ? children : null}
    </div>
  );
}

/** What the caller may open in this tournament's hub, in the tournament's own workspace. */
export function useTabAccess(tournament: Tournament | undefined): TabAccess {
  const { canAccessPermission } = usePermissions();
  const workspaceId = tournament?.workspace_id ?? null;
  return {
    canUpdateTournament: canAccessPermission("tournament.update", workspaceId),
    canUpdateEncounter: canAccessPermission("match.update", workspaceId),
    canTeamRead: canAccessPermission("team.read", workspaceId),
    canTeamCreate: canAccessPermission("team.create", workspaceId),
    canReadTournamentLink: canAccessPermission("tournament_link.read", workspaceId),
    canDeleteTournament: canAccessPermission("tournament.delete", workspaceId),
    hasDraftFormation: formationModes(tournament).has("draft")
  };
}
