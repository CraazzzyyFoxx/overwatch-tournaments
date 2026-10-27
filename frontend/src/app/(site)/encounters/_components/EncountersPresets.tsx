"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, Save, Trash2 } from "lucide-react";

import { useFormatter } from "@/lib/datetime/client";
import { ApiError } from "@/lib/api/error";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { EncounterOverview, EncounterSavedView } from "@/types/encounter.types";

import { QUICK_FILTERS, sameFilters, savedViewState } from "./encounters.helpers";
import { useEncounterSavedViews } from "./useEncounterSavedViews";
import type { EncountersFilterControls } from "./useEncountersFilters";

function refusal(error: unknown, code: string): boolean {
  return error instanceof ApiError && error.details.some((detail) => detail.code === code);
}

/**
 * «Подборки ▾»: the quick filters (toggles that narrow the current filters, each with its count under them), the
 * viewer's saved views (applying one replaces the whole filter state; the one matching it exactly is checked) and
 * «Сохранить текущие фильтры». «Моя команда» needs an account, so an anonymous viewer is not offered it.
 */
export function EncountersPresets({
  controls,
  counts,
  triggerClassName
}: Readonly<{
  controls: EncountersFilterControls;
  counts: EncounterOverview["counts"] | undefined;
  triggerClassName?: string;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const { user } = useAuthProfile();
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [viewToDelete, setViewToDelete] = useState<EncounterSavedView | null>(null);
  const saved = useEncounterSavedViews({
    onSaved: () => setSaveOpen(false),
    onDeleted: () => setViewToDelete(null)
  });
  // What the reads use: a saved view is compared with, and saved as, the filters in effect.
  const filters = controls.effectiveFilters;
  const quickFilters = QUICK_FILTERS.filter((quick) => quick.id !== "my_team" || user);
  const activeCount = quickFilters.filter((quick) => quick.isOn(filters)).length;
  const saveError = saved.saveError
    ? refusal(saved.saveError, "saved_view_exists")
      ? t("encounters.savedViews.exists")
      : refusal(saved.saveError, "saved_view_limit")
        ? t("encounters.savedViews.limit")
        : t("encounters.savedViews.failed")
    : null;

  return (
    <>
      {/* Not modal: a dialog opened from an item must not inherit the menu's pointer lock. */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className={triggerClassName}>
            {t("encounters.presets.trigger")}
            {activeCount ? (
              <span className="tabular-nums text-[color:var(--aqt-teal)]">{format.number(activeCount)}</span>
            ) : null}
            <ChevronDown aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          <DropdownMenuLabel>{t("encounters.presets.quick")}</DropdownMenuLabel>
          {quickFilters.map((quick) => (
            <DropdownMenuCheckboxItem
              key={quick.id}
              checked={quick.isOn(filters)}
              onCheckedChange={(on) => controls.patchFilters(quick.patch(on))}
              // Toggles add up: the menu stays open for the next one.
              onSelect={(event) => event.preventDefault()}
            >
              {t(quick.label)}
              {counts ? (
                <span className="ml-auto pl-4 tabular-nums text-muted-foreground">{format.number(counts[quick.id])}</span>
              ) : null}
            </DropdownMenuCheckboxItem>
          ))}

          {saved.views?.length ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>{t("encounters.presets.saved")}</DropdownMenuLabel>
              {saved.views.map((view) => {
                const state = savedViewState(view.filters);
                return (
                  <div key={view.id} className="flex items-center">
                    <DropdownMenuCheckboxItem
                      className="min-w-0 flex-1"
                      checked={sameFilters(state, filters)}
                      onCheckedChange={() => controls.applyFilters(state)}
                    >
                      <span className="truncate">{view.name}</span>
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuItem
                      aria-label={t("encounters.savedViews.deleteAria", { name: view.name })}
                      disabled={saved.deletePending}
                      variant="destructive"
                      onSelect={() => setViewToDelete(view)}
                    >
                      <Trash2 aria-hidden />
                    </DropdownMenuItem>
                  </div>
                );
              })}
            </>
          ) : null}

          <DropdownMenuSeparator />
          <DropdownMenuItem
            disabled={saved.savePending}
            onSelect={() => {
              if (!saved.requireAuth()) return;
              saved.clearSaveError();
              setSaveName(t("encounters.savedViews.defaultName"));
              setSaveOpen(true);
            }}
          >
            <Save aria-hidden />
            {t("encounters.presets.save")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <ConfirmDialog
        open={viewToDelete != null}
        onOpenChange={(open) => {
          if (!open) setViewToDelete(null);
        }}
        intent={{
          title: t("encounters.savedViews.deleteTitle"),
          description: t("encounters.savedViews.deleteBody", { name: viewToDelete?.name ?? "" }),
          confirmLabel: t("common.delete"),
          tone: "danger"
        }}
        pending={saved.deletePending}
        onConfirm={() => {
          if (viewToDelete) saved.remove(viewToDelete.id);
        }}
      />

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>{t("encounters.presets.save")}</DialogTitle>
          </DialogHeader>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              const name = saveName.trim();
              if (name) saved.save(name, filters);
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="saved-view-name">{t("encounters.savedViews.nameLabel")}</Label>
              <Input
                id="saved-view-name"
                value={saveName}
                aria-invalid={saveError ? true : undefined}
                aria-describedby={saveError ? "saved-view-error" : undefined}
                onChange={(event) => {
                  setSaveName(event.target.value);
                  if (saveError) saved.clearSaveError();
                }}
                autoFocus
              />
              {saveError ? (
                <p id="saved-view-error" role="alert" className="text-caption text-[color:var(--aqt-rose)]">
                  {saveError}
                </p>
              ) : null}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setSaveOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={!saveName.trim() || saved.savePending}>
                {t("common.save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
