"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Loader2, UserMinus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { rbacService } from "@/services/rbac.service";

interface TournamentPreviewAllowlistProps {
  tournamentId: number;
  workspaceId: number;
}

/**
 * Editor for a hidden tournament's preview allowlist (issue #115). Add/remove
 * mutate immediately (independent of the settings form save). Candidate users
 * come from the workspace RBAC user list — ``.id`` is the auth-user id, which is
 * what the allowlist keys on.
 */
export function TournamentPreviewAllowlist({
  tournamentId,
  workspaceId
}: TournamentPreviewAllowlistProps) {
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);

  const accessQueryKey = ["tournament-preview-access", tournamentId] as const;

  const { data: entries, isLoading: entriesLoading } = useQuery({
    queryKey: accessQueryKey,
    queryFn: () => adminService.getTournamentPreviewAccess(tournamentId)
  });

  const { data: candidates } = useQuery({
    queryKey: ["rbac-users", workspaceId, "all"],
    queryFn: () => rbacService.listUsersAll({ workspace_id: workspaceId })
  });

  const nameByAuthUserId = useMemo(() => {
    const map = new Map<number, string>();
    for (const user of candidates ?? []) {
      map.set(user.id, user.username || user.email || `#${user.id}`);
    }
    return map;
  }, [candidates]);

  const allowedIds = useMemo(
    () => new Set((entries ?? []).map((entry) => entry.auth_user_id)),
    [entries]
  );

  const addMutation = useMutation({
    mutationFn: (authUserId: number) =>
      adminService.addTournamentPreviewUser(tournamentId, authUserId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: accessQueryKey });
      notify.success("Added to preview allowlist");
    },
    onError: (error) => notify.apiError(error)
  });

  const removeMutation = useMutation({
    mutationFn: (authUserId: number) =>
      adminService.removeTournamentPreviewUser(tournamentId, authUserId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: accessQueryKey });
      notify.success("Removed from preview allowlist");
    },
    onError: (error) => notify.apiError(error)
  });

  const selectableCandidates = (candidates ?? []).filter((user) => !allowedIds.has(user.id));

  return (
    <div className="space-y-3">
      <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            size="sm"
            className="justify-between w-full"
            disabled={addMutation.isPending}
          >
            <span className="truncate text-muted-foreground">Add a user to the allowlist…</span>
            <ChevronsUpDown className="ml-2 size-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command>
            <CommandInput placeholder="Search user by name…" />
            <CommandList>
              <CommandEmpty>No users found.</CommandEmpty>
              <CommandGroup>
                {selectableCandidates.map((user) => (
                  <CommandItem
                    key={user.id}
                    value={`${user.username} ${user.email}`}
                    onSelect={() => {
                      addMutation.mutate(user.id);
                      setPickerOpen(false);
                    }}
                  >
                    <Check className="mr-2 size-4 opacity-0" />
                    <span className="truncate">{user.username || user.email || `#${user.id}`}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {entriesLoading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          Loading allowlist…
        </div>
      ) : (entries ?? []).length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No preview users yet. Add accounts that may view this hidden tournament.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {(entries ?? []).map((entry) => (
            <li
              key={entry.id}
              className="flex items-center justify-between gap-2 rounded-md border border-border/50 bg-muted/20 px-3 py-1.5"
            >
              <span className="truncate text-sm">
                {nameByAuthUserId.get(entry.auth_user_id) ?? `User #${entry.auth_user_id}`}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-destructive hover:text-destructive"
                onClick={() => removeMutation.mutate(entry.auth_user_id)}
                disabled={removeMutation.isPending}
              >
                <UserMinus className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
