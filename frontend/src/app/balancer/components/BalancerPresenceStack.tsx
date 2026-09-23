"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import workspaceService from "@/services/workspace.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import type { WorkspaceMember } from "@/types/workspace.types";
import { memberDisplayName } from "@/lib/workspace/member";

/** Portal target rendered by {@link BalancerToolTopBar}. */
const PRESENCE_SLOT_ID = "balancer-presence-slot";
const MAX_VISIBLE = 5;

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
 * Rendered into the tool top-bar via a portal (D30). User ids come from the
 * realtime presence frame; profiles are resolved from the workspace member list.
 */
export function BalancerPresenceStack({ userIds, workspaceId }: BalancerPresenceStackProps) {
  // The presence frame is broadcast to every viewer and includes ourselves;
  // hide the current user so the stack only shows *other* people viewing.
  const currentUserId = useAuthProfileStore((store) => store.user?.id ?? null);

  const [slot, setSlot] = useState<HTMLElement | null>(null);
  /* eslint-disable react-hooks/set-state-in-effect -- The portal target lives in the top-bar, outside this component, and is only available after hydration. */
  useEffect(() => {
    setSlot(document.getElementById(PRESENCE_SLOT_ID));
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  const membersQuery = useQuery({
    queryKey: ["workspace", "members", workspaceId],
    queryFn: () => workspaceService.getMembersAll(workspaceId as number),
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

  const visible = uniqueUserIds.slice(0, MAX_VISIBLE);
  const overflow = uniqueUserIds.length - visible.length;

  const content = (
    <div
      className="flex items-center -space-x-2"
      title={`${uniqueUserIds.length} viewing`}
    >
      {visible.map((userId) => {
        const member = membersById.get(userId);
        const name = memberDisplayName(member, userId);
        return (
          <Avatar
            key={userId}
            title={name}
            className="h-7 w-7 border-2 border-background bg-muted text-xs"
          >
            {member?.avatar_url ? <AvatarImage src={member.avatar_url} alt={name} /> : null}
            <AvatarFallback className="text-label font-medium text-foreground">
              {initials(name)}
            </AvatarFallback>
          </Avatar>
        );
      })}
      {overflow > 0 ? (
        <span
          className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-background bg-muted text-label font-medium text-muted-foreground"
          title={`${overflow} more viewer${overflow === 1 ? "" : "s"}`}
        >
          +{overflow}
        </span>
      ) : null}
    </div>
  );

  return createPortal(content, slot);
}
