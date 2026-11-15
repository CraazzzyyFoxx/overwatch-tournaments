"use client";

import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { hasUnsavedChanges } from "@/lib/form-change";
import type { StandingUpdateInput } from "@/types/admin.types";
import type { Standings } from "@/types/tournament.types";

import { standingFormOf } from "./model";

/** Hand-correcting one standings row's record and tiebreakers. */
export function StandingEditDialog({
  editing,
  form,
  onFormChange,
  onClose,
  isSubmitting,
  error,
  onSave
}: Readonly<{
  /** `null` = closed. */
  editing: Standings | null;
  form: StandingUpdateInput;
  onFormChange: (form: StandingUpdateInput) => void;
  onClose: () => void;
  isSubmitting: boolean;
  error: Error | null;
  onSave: (payload: { id: number; data: StandingUpdateInput }) => void;
}>) {
  const t = useTranslations("adminTournaments.standings");
  return (
    <EntityFormDialog
      open={editing != null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={t("edit")}
      description={t("editDescription")}
      isSubmitting={isSubmitting}
      submittingLabel={t("updating")}
      errorMessage={error ? t("updateError", { message: error.message }) : undefined}
      isDirty={editing != null && hasUnsavedChanges(form, standingFormOf(editing))}
      onSubmit={(event) => {
        event.preventDefault();
        if (editing) onSave({ id: editing.id, data: form });
      }}
    >
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="standing-points">{t("points")}</Label>
          <NumberInput
            id="standing-points"
            min={0}
            value={form.points ?? 0}
            onValueChange={(next) => onFormChange({ ...form, points: next ?? 0 })}
          />
        </div>
        <div>
          <Label htmlFor="standing-win">{t("wins")}</Label>
          <NumberInput
            id="standing-win"
            integer
            min={0}
            value={form.win ?? 0}
            onValueChange={(next) => onFormChange({ ...form, win: next ?? 0 })}
          />
        </div>
        <div>
          <Label htmlFor="standing-draw">{t("draws")}</Label>
          <NumberInput
            id="standing-draw"
            integer
            min={0}
            value={form.draw ?? 0}
            onValueChange={(next) => onFormChange({ ...form, draw: next ?? 0 })}
          />
        </div>
        <div>
          <Label htmlFor="standing-lose">{t("losses")}</Label>
          <NumberInput
            id="standing-lose"
            integer
            min={0}
            value={form.lose ?? 0}
            onValueChange={(next) => onFormChange({ ...form, lose: next ?? 0 })}
          />
        </div>
        <div>
          <Label htmlFor="standing-buchholz">{t("buchholzMedian")}</Label>
          <NumberInput
            id="standing-buchholz"
            value={form.buchholz ?? 0}
            onValueChange={(next) => onFormChange({ ...form, buchholz: next ?? 0 })}
          />
        </div>
        <div>
          <Label htmlFor="standing-tb">{t("headToHead")}</Label>
          <NumberInput
            id="standing-tb"
            integer
            min={0}
            value={form.tb ?? 0}
            onValueChange={(next) => onFormChange({ ...form, tb: next ?? 0 })}
          />
        </div>
      </div>
    </EntityFormDialog>
  );
}
