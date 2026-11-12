"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import type { RegistrationTeam } from "@/types/registration-team.types";

import type { RegistrationTeamActions } from "./useRegistrationTeamActions";

/** Renaming a team from its row, prefilled with the name it has now. */
export function RenameTeamDialog({
  team,
  onClose,
  actions
}: Readonly<{
  team: RegistrationTeam | null;
  onClose: () => void;
  actions: RegistrationTeamActions;
}>) {
  const t = useTranslations("registrationTeams");
  const fieldId = useId();
  const [value, setValue] = useState(team?.name ?? "");

  // Another row's rename: the field opens on ITS name, not the last one's.
  const [target, setTarget] = useState(team);
  if (target !== team) {
    setTarget(team);
    setValue(team?.name ?? "");
  }

  return (
    <EntityFormDialog
      open={team != null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={t("rename.save")}
      submitLabel={t("rename.save")}
      isSubmitting={actions.isRenaming}
      errorMessage={actions.actionError ?? undefined}
      guardNavigation={false}
      onSubmit={() => {
        if (!team || !value.trim()) return;
        actions.rename({ teamId: team.id, name: value });
      }}
    >
      <div className="grid gap-1.5">
        <Label htmlFor={fieldId}>{t("create.nameLabel")}</Label>
        <Input
          id={fieldId}
          value={value}
          disabled={actions.isRenaming}
          onChange={(event) => setValue(event.target.value)}
        />
      </div>
    </EntityFormDialog>
  );
}
