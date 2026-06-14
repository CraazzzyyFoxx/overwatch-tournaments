"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useSidebar } from "@/components/ui/sidebar";
import workspaceService from "@/services/workspace.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import type { WorkspaceMember } from "@/types/workspace.types";
import { cn } from "@/lib/utils";
import { memberDisplayName } from "@/lib/workspace-member";

/** Portal target rendered by {@link BalancerSidebar} in its footer. */
const PRESENCE_SLOT_ID = "balancer-presence-slot";
const MAX_VISIBLE_EXPANDED = 5;
const MAX_VISIBLE_COLLAPSED = 3;

type BalancerPresenceStackProps = {
  /** auth_user_id values currently connected to this tournament's balancer. */
  userIds: number[];
  workspaceId: number | null;
};

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "?";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

/**
 * Live avatar stack of users currently viewing this tournament's balancer page.
 * Rendered into the balancer sidebar footer via a portal so it stays out of the
 * already-crowded top control bar. User ids come from the realtime presence
 * frame; profiles are resolved from the workspace member list. Adapts its layout
 * to the sidebar's collapsed (icon) state.
 */
export function BalancerPresenceStack({ userIds, workspaceId }: BalancerPresenceStackProps) {
  const { state } = useSidebar();
  const collapsed = state === "collapsed";

  // The presence frame is broadcast to every viewer and includes ourselves;
  // hide the current user so the stack only shows *other* people viewing.
  const currentUserId = useAuthProfileStore((store) => store.user?.id ?? null);

  const [slot, setSlot] = useState<HTMLElement | null>(null);
  /* eslint-disable react-hooks/set-state-in-effect -- The portal target lives in the sidebar, outside this component, and is only available after hydration. */
  useEffect(() => {
    setSlot(document.getElementById(PRESENCE_SLOT_ID));
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  const membersQuery = useQuery({
    queryKey: ["workspace", "members", workspaceId],
    queryFn: () => workspaceService.getMembers(workspaceId as number),
    enabled: workspaceId !== null,
    staleTime: 5 * 60 * 1000
  });

  const membersById = useMemo(() => {
    const map = new Map<number, WorkspaceMember>();
    for (const member of membersQuery.data ?? []) {
      map.set(member.auth_user_id, member);
    }
    return map;
  }, [membersQuery.data]);

  const uniqueUserIds = useMemo(
    () =>
      Array.from(new Set(userIds))
        .filter((id) => id !== currentUserId)
        .sort((a, b) => a - b),
    [userIds, currentUserId]
  );

  if (!slot || uniqueUserIds.length === 0) {
    return null;
  }

  const maxVisible = collapsed ? MAX_VISIBLE_COLLAPSED : MAX_VISIBLE_EXPANDED;
  const visible = uniqueUserIds.slice(0, maxVisible);
  const overflow = uniqueUserIds.length - visible.length;

  const content = (
    <div className={cn("flex flex-col gap-1.5", collapsed ? "items-center" : "px-1")}>
      {!collapsed ? (
        <span className="px-1 text-[11px] font-medium text-sidebar-foreground/30">Viewing now</span>
      ) : null}
      <div
        className={cn(
          "flex",
          collapsed
            ? "flex-col items-center -space-y-2"
            : "items-center -space-x-2"
        )}
        title={collapsed ? `${uniqueUserIds.length} viewing` : undefined}
      >
        {visible.map((userId) => {
          const member = membersById.get(userId);
          const name = memberDisplayName(member, userId);
          return (
            <Avatar
              key={userId}
              title={name}
              className="h-7 w-7 border-2 border-sidebar bg-sidebar-accent text-xs"
            >
              {member?.avatar_url ? <AvatarImage src={member.avatar_url} alt={name} /> : null}
              <AvatarFallback className="text-[10px] font-medium text-sidebar-foreground">
                {initials(name)}
              </AvatarFallback>
            </Avatar>
          );
        })}
        {overflow > 0 ? (
          <span
            className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-sidebar bg-sidebar-accent text-[10px] font-medium text-sidebar-foreground/70"
            title={`${overflow} more viewer${overflow === 1 ? "" : "s"}`}
          >
            +{overflow}
          </span>
        ) : null}
      </div>
      {!collapsed ? (
        <span className="px-1 text-xs text-sidebar-foreground/55">
          {uniqueUserIds.length} viewing
        </span>
      ) : null}
    </div>
  );

  return createPortal(content, slot);
}
