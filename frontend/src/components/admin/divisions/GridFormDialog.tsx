"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { createLadder } from "@/app/admin/settings/divisions/editor/draftReducer";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { Field, FieldContent, FieldDescription, FieldLabel, FieldTitle } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { GameField } from "@/components/workspace/GameField";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { resolveOwnerGrid } from "@/lib/divisions/grid";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { DivisionGridEntity, Workspace } from "@/types/workspace.types";

import { matchesLadder } from "./model";

/** What the dialog is open for: a new grid (its game fixed by the page, or `null` to ask), or renaming one. */
export type GridForm =
  | { mode: "create"; game: string | null }
  | { mode: "rename"; grid: DivisionGridEntity };

export interface GridFormValues {
  name: string;
  discipline: string;
  /** The version to copy into v1; absent starts from the game's built-in ladder. */
  fromVersionId?: number;
}

type Base = "active" | "ladder";

/** Visual required marker; `required` on the control carries the semantics. */
const requiredMark = (
  <span aria-hidden className="ml-0.5 text-danger">
    *
  </span>
);

/**
 * "New grid" and "Rename grid" in one form dialog with a swapped mode (DESIGN §14: one form dialog per screen).
 *
 * A new grid is usually a variant of the one in force (another series, an experiment), so copying that version is
 * the first choice; the built-in ladder is the other. The choice appears only when the two differ: a version that
 * is still the plain ladder copies into nothing a ladder start would not give. The game is asked only where the page
 * has not fixed one (all games).
 */
export function GridFormDialog({
  form,
  workspaceId,
  games,
  workspace,
  grids,
  pending,
  error,
  onSubmit,
  onClose
}: Readonly<{
  form: GridForm;
  workspaceId: number;
  /** The workspace's games; only enabled ones are offered. */
  games: DisciplineDescriptor[];
  workspace: Pick<Workspace, "effective_division_grid_versions"> | null | undefined;
  /** The workspace's grids, to name the grid a version in force belongs to. */
  grids: DivisionGridEntity[];
  pending: boolean;
  error?: string;
  onSubmit: (values: GridFormValues) => void;
  onClose: () => void;
}>) {
  const t = useTranslations("adminSettings.divisions");
  const enabled = games.filter((game) => game.enabled);
  const creating = form.mode === "create";
  const [game, setGame] = useState(
    form.mode === "create" ? (form.game ?? enabled[0]?.code ?? "") : form.grid.discipline
  );
  const [name, setName] = useState(form.mode === "rename" ? form.grid.name : "");
  const [base, setBase] = useState<Base>("active");
  const [submitted, setSubmitted] = useState(false);

  const metadata = useDisciplineMetadata(workspaceId, creating && game ? game : null).data;
  const ladder = useMemo(
    () => (metadata?.discipline.capabilities.native_ladder ? createLadder(metadata.native_ladder) : null),
    [metadata]
  );
  const descriptor = enabled.find((entry) => entry.code === game);
  const short = descriptor?.short_name || game;
  const active = creating ? resolveOwnerGrid(workspace, game) : null;
  const activeName = active ? (grids.find((grid) => grid.id === active.grid_id)?.name ?? active.label) : "";
  // Worth copying only when it is not the plain ladder; without a ladder it is the only start there is.
  const copyable = active !== null && (ladder === null || !matchesLadder(ladder, active.tiers));
  const choice = copyable && ladder !== null;
  const fromVersionId = active && copyable && (!choice || base === "active") ? active.id : undefined;

  const errors: Record<string, string> = {};
  if (!name.trim()) errors.name = t("create.nameRequired");
  if (creating && !game) errors.game = t("create.gameRequired");
  const shownErrors = submitted ? errors : {};

  const options: { value: Base; title: string; hint: string }[] = choice
    ? [
        {
          value: "active",
          title: t("create.baseActive", { grid: activeName, version: active!.version }),
          hint: t("create.baseActiveHint")
        },
        {
          value: "ladder",
          title: t("create.baseLadder", { game: short }),
          hint: t("create.baseLadderHint", { count: ladder!.count })
        }
      ]
    : [];

  return (
    <EntityFormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={creating ? t("create.title") : t("rename.title")}
      // Where the page fixed the game, the dialog names it once instead of asking.
      description={creating && form.game !== null ? descriptor?.name : undefined}
      submitLabel={creating ? t("create.submit") : undefined}
      submittingLabel={creating ? t("create.submitting") : undefined}
      isSubmitting={pending}
      errorMessage={error}
      fieldErrors={shownErrors}
      isDirty={creating ? Boolean(name.trim()) : name.trim() !== form.grid.name}
      guardNavigation={false}
      contentClassName="max-w-xl"
      onSubmit={() => {
        setSubmitted(true);
        if (Object.keys(errors).length > 0) return;
        onSubmit({ name: name.trim(), discipline: game, fromVersionId });
      }}
    >
      {creating && form.game === null ? (
        <GameField id="division-grid-game" games={enabled} value={game} onChange={setGame} />
      ) : null}

      <div className="space-y-1.5">
        <Label htmlFor="division-grid-name">
          {t("create.name")}
          {requiredMark}
        </Label>
        <Input
          id="division-grid-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          autoFocus
          maxLength={255}
          aria-invalid={shownErrors.name ? true : undefined}
        />
      </div>

      {choice ? (
        <RadioGroup
          aria-label={t("create.base")}
          value={base}
          onValueChange={(next) => setBase(next as Base)}
          className="grid-cols-1 sm:grid-cols-2"
        >
          {options.map(({ value, title, hint }) => {
            const id = `division-grid-base-${value}`;
            return (
              <FieldLabel key={value} htmlFor={id}>
                <Field orientation="horizontal">
                  <RadioGroupItem
                    id={id}
                    value={value}
                    aria-labelledby={`${id}-title`}
                    aria-describedby={`${id}-hint`}
                  />
                  <FieldContent>
                    <FieldTitle id={`${id}-title`}>{title}</FieldTitle>
                    <FieldDescription id={`${id}-hint`} size="sm">
                      {hint}
                    </FieldDescription>
                  </FieldContent>
                </Field>
              </FieldLabel>
            );
          })}
        </RadioGroup>
      ) : null}

      {creating ? <p className="text-caption text-muted-foreground">{t("create.note")}</p> : null}
    </EntityFormDialog>
  );
}
