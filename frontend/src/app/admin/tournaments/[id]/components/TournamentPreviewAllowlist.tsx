"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserMinus } from "lucide-react";
import { Combobox } from "@/components/kit/Combobox";
import { Button } from "@/components/ui/button";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { rbacService } from "@/services/rbac.service";
import { Spinner } from "@/components/ui/spinner";

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
}: Readonly<TournamentPreviewAllowlistProps>) {
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [candidateSearch, setCandidateSearch] = useState("");

  const accessQueryKey = ["tournament-preview-access", tournamentId] as const;

  const { data: entries, isLoading: entriesLoading } = useQuery({
    queryKey: accessQueryKey,
    queryFn: () => adminService.getTournamentPreviewAccess(tournamentId)
  });

  const { data: candidates, isLoading: candidatesLoading } = useQuery({
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
      <Combobox
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        label="Add a user to the allowlist…"
        disabled={addMutation.isPending}
        searchValue={candidateSearch}
        onSearchValueChange={setCandidateSearch}
        searchLabel="Search workspace users"
        searchPlaceholder="Search user by name…"
        emptyMessage={
          candidatesLoading ? (
            <span className="flex items-center justify-center gap-2 text-muted-foreground">
              <Spinner className="size-3.5" />
              Loading workspace users…
            </span>
          ) : (
            "No matching users. Only workspace members can be added."
          )
        }
      >
        <CommandGroup>
          {selectableCandidates.map((user) => (
            <CommandItem
              key={user.id}
              value={`${user.username} ${user.email}`}
              onSelect={() => {
                addMutation.mutate(user.id);
                setPickerOpen(false);
                setCandidateSearch("");
              }}
            >
              <span className="truncate">{user.username || user.email || `#${user.id}`}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </Combobox>

      {entriesLoading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Spinner className="size-3.5" />
          Loading allowlist…
        </div>
      ) : (entries ?? []).length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No preview users yet. Add accounts that may view this hidden tournament.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {(entries ?? []).map((entry) => {
            const displayName =
              nameByAuthUserId.get(entry.auth_user_id) ?? `User #${entry.auth_user_id}`;
            return (
              <li
                key={entry.id}
                className="flex items-center justify-between gap-2 rounded-md border border-border/50 bg-muted/20 px-3 py-1.5"
              >
                <span className="truncate text-sm">{displayName}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`Remove ${displayName} from the preview allowlist`}
                  className="h-7 px-2 text-destructive hover:text-destructive"
                  onClick={() => removeMutation.mutate(entry.auth_user_id)}
                  disabled={removeMutation.isPending}
                >
                  <UserMinus className="size-3.5" aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
