"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import workspaceService from "@/services/workspace.service";
import type { WorkspaceMember } from "@/types/workspace.types";
import { cn } from "@/lib/utils";

const MAX_VISIBLE = 5;

type BalancerPresenceStackProps = {
  /** auth_user_id values currently connected to this tournament's balancer. */
  userIds: number[];
  workspaceId: number | null;
  className?: string;
};

function memberDisplayName(member: WorkspaceMember | undefined, userId: number): string {
  if (!member) {
    return `User #${userId}`;
  }
  const fullName = [member.first_name, member.last_name].filter(Boolean).join(" ").trim();
  return fullName || member.username || member.email || `User #${userId}`;
}

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
 * Live AvatarStack of users currently viewing this tournament's balancer page.
 * User ids come from the realtime presence frame; profiles are resolved from
 * the workspace member list.
 */
export function BalancerPresenceStack({
  userIds,
  workspaceId,
  className
}: BalancerPresenceStackProps) {
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

  const uniqueUserIds = useMemo(() => Array.from(new Set(userIds)).sort((a, b) => a - b), [userIds]);

  if (uniqueUserIds.length === 0) {
    return null;
  }

  const visible = uniqueUserIds.slice(0, MAX_VISIBLE);
  const overflow = uniqueUserIds.length - visible.length;

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="flex items-center -space-x-2">
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
              <AvatarFallback className="text-[10px] font-medium">{initials(name)}</AvatarFallback>
            </Avatar>
          );
        })}
        {overflow > 0 ? (
          <span
            className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-background bg-muted text-[10px] font-medium text-muted-foreground"
            title={`${overflow} more viewer${overflow === 1 ? "" : "s"}`}
          >
            +{overflow}
          </span>
        ) : null}
      </div>
      <span className="text-xs text-muted-foreground">
        {uniqueUserIds.length} viewing
      </span>
    </div>
  );
}
