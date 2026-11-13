"use client";

import { useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { UserSearchCombobox } from "@/components/kit/UserSearchCombobox";
import { Input } from "@craazzzyyfoxx/admin-kit/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import { canonicalDisplay } from "@/lib/player";
import adminService from "@/services/admin.service";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

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
  const t = useTranslations("adminPeople.createTeam");
  const router = useRouter();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<TeamCreateForm>(EMPTY_FORM);
  const [error, setError] = useState<string | undefined>();
  // Same convention as the balancer export: a team without its own name is known
  // by its captain's handle, battletag suffix dropped.
  const captainHandle = canonicalDisplay(form.captainName).name;
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
        queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.teamsAll() }),
        queryClient.invalidateQueries({ queryKey: adminQueryKeys.tournament(tournamentId) })
      ]);
      notify.success(t("created"));
      setForm(EMPTY_FORM);
      onOpenChange(false);
      router.push(`/admin/teams/${team.id}`);
    },
    onError: (mutationError: Error) => setError(mutationError.message)
  });

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();

    if (form.captainId <= 0) {
      setError(t("pickCaptain"));
      return;
    }
    if (!teamName) {
      setError(t("enterName"));
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
      title={t("title")}
      description={t("description")}
      onSubmit={handleSubmit}
      submitLabel={t("submit")}
      isSubmitting={createTeam.isPending}
      submittingLabel={t("creating")}
      errorMessage={error}
      isDirty={open && hasUnsavedChanges(form, EMPTY_FORM)}
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="team-create-name">{t("teamName")}</Label>
          <Input
            id="team-create-name"
            value={form.name}
            placeholder={captainHandle || undefined}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
          />
          <p className="text-xs text-muted-foreground">
            {t("nameHint")}
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="team-create-captain">{t("captain")}</Label>
          <UserSearchCombobox
            id="team-create-captain"
            value={form.captainId || undefined}
            selectedLabel={form.captainName}
            placeholder={t("searchUser")}
            onSelect={(user) =>
              setForm((current) => ({
                ...current,
                captainId: user?.id ?? 0,
                captainName: user?.name ?? ""
              }))
            }
          />
          <p className="text-xs text-muted-foreground">
            {t("rosterHint")}
          </p>
        </div>
      </div>
    </EntityFormDialog>
  );
}
