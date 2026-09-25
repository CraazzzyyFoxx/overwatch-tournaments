"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { UserSearchCombobox } from "@/components/admin/UserSearchCombobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";

interface TeamCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tournamentId: number;
}

interface TeamCreateForm {
  name: string;
  captainId: number;
  captainName: string;
}

const EMPTY_FORM: TeamCreateForm = { name: "", captainId: 0, captainName: "" };

/**
 * Team identity only: name plus captain.
 *
 * The roster is built on the team page, which is a live editor — asking for the
 * whole roster up front is what forced the previous nested-dialog flow, and it
 * duplicated every roster control for a form that had to replay creates,
 * updates and deletes in dependency order on submit.
 */
export function TeamCreateDialog({ open, onOpenChange, tournamentId }: Readonly<TeamCreateDialogProps>) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<TeamCreateForm>(EMPTY_FORM);
  const [error, setError] = useState<string | undefined>();
  // Same convention as the balancer export: a team without its own name is known
  // by its captain's handle, battletag suffix dropped.
  const captainHandle = form.captainName.split("#")[0];
  const teamName = form.name.trim() || captainHandle;

  const createTeam = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: () =>
      adminService.createTeam({
        name: teamName,
        tournament_id: tournamentId,
        captain_id: form.captainId
      }),
    onSuccess: async (team) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["teams"] }),
        queryClient.invalidateQueries({ queryKey: ["admin", "tournament", tournamentId] })
      ]);
      notify.success("Team created — add its roster below");
      setForm(EMPTY_FORM);
      onOpenChange(false);
      router.push(`/admin/teams/${team.id}`);
    },
    onError: (mutationError: Error) => setError(mutationError.message)
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();

    if (form.captainId <= 0) {
      setError("Pick the captain.");
      return;
    }
    if (!teamName) {
      setError("Enter a team name.");
      return;
    }

    setError(undefined);
    createTeam.mutate();
  };

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          setForm(EMPTY_FORM);
          setError(undefined);
        }
        onOpenChange(nextOpen);
      }}
      title="Create team"
      description="Name the team and pick its captain. You will land on the team page to add players."
      onSubmit={handleSubmit}
      submitLabel="Create team"
      isSubmitting={createTeam.isPending}
      submittingLabel="Creating…"
      errorMessage={error}
      isDirty={open && hasUnsavedChanges(form, EMPTY_FORM)}
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="team-create-name">Team name</Label>
          <Input
            id="team-create-name"
            value={form.name}
            placeholder={captainHandle || "Team name"}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
          />
          <p className="text-xs text-muted-foreground">
            Leave empty to name the team after its captain.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="team-create-captain">Captain</Label>
          <UserSearchCombobox
            id="team-create-captain"
            value={form.captainId || undefined}
            selectedName={form.captainName || undefined}
            placeholder="Search user by name"
            onSelect={(user) =>
              setForm((current) => ({
                ...current,
                captainId: user?.id ?? 0,
                captainName: user?.name ?? ""
              }))
            }
          />
          <p className="text-xs text-muted-foreground">
            Add the captain to the roster on the team page — changing the captain later requires them
            to be a roster member.
          </p>
        </div>
      </div>
    </EntityFormDialog>
  );
}
