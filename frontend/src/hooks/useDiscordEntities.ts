import { useQuery } from "@tanstack/react-query";
import workspaceService from "@/services/workspace.service";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";

export function useDiscordRoles(workspaceId: number | null | undefined, enabled: boolean = true) {
  return useQuery({
    queryKey: workspaceQueryKeys.discordRoles(workspaceId),
    queryFn: () => workspaceService.getDiscordRoles(workspaceId!),
    enabled: Boolean(workspaceId && enabled),
    staleTime: 60 * 1000,
  });
}

export function useDiscordChannels(workspaceId: number | null | undefined, enabled: boolean = true) {
  return useQuery({
    queryKey: workspaceQueryKeys.discordChannels(workspaceId),
    queryFn: () => workspaceService.getDiscordChannels(workspaceId!),
    enabled: Boolean(workspaceId && enabled),
    staleTime: 60 * 1000,
  });
}

export function useDiscordGuildInfo(workspaceId: number | null | undefined, enabled: boolean = true) {
  return useQuery({
    queryKey: workspaceQueryKeys.discordGuild(workspaceId),
    queryFn: () => workspaceService.getDiscordGuildInfo(workspaceId!),
    enabled: Boolean(workspaceId && enabled),
    staleTime: 60 * 1000,
  });
}
