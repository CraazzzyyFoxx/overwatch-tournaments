"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { Bookmark, Pin, Save, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { EncounterOverview, EncounterSavedView } from "@/types/encounter.types";

import { applyBuiltInView, BUILT_IN_VIEWS, type EncounterFilterState } from "./encounters.helpers";
import {
  countLabel,
  selectedViewId,
  toSavedFilterState,
  VIEW_SWATCH_COLOR
} from "./encounters.model";
import { useEncounterSavedViews } from "./useEncounterSavedViews";
import styles from "./Encounters.module.css";

/**
 * The view tab strip: the built-in presets, the viewer's own saved filter sets,
 * and the two dialogs that maintain them. Picking any tab replaces the whole
 * filter state — a preset is a named set of filters, not an extra narrowing on
 * top of what is already selected.
 */
export function EncountersViewsBar({
  filters,
  presetCounts,
  onApplyFilters
}: Readonly<{
  filters: EncounterFilterState;
  presetCounts: EncounterOverview["preset_counts"];
  onApplyFilters: (next: EncounterFilterState) => void;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [viewToDelete, setViewToDelete] = useState<EncounterSavedView | null>(null);
  const savedViews = useEncounterSavedViews({
    onSaved: () => setSaveDialogOpen(false),
    onDeleted: () => setViewToDelete(null)
  });
  const activeView = selectedViewId(filters);

  return (
    <>
      <section aria-label={t("encounters.aria.views")}>
        <div className={styles.views}>
          <span className={styles.viewsLabel}>
            <Bookmark aria-hidden className="h-3 w-3" /> {t("encounters.views")}
          </span>
          {BUILT_IN_VIEWS.map((view) => (
            <button
              key={view.id}
              type="button"
              aria-pressed={activeView === view.id}
              className={cn(styles.viewTab, activeView === view.id && styles.viewTabActive)}
              onClick={() => onApplyFilters(applyBuiltInView(view.id, filters))}
            >
              {view.showPin ? (
                <Pin aria-hidden className={cn("h-3 w-3", styles.viewPin)} fill="currentColor" />
              ) : view.swatch ? (
                <span
                  aria-hidden
                  className={styles.viewSwatch}
                  style={{ background: VIEW_SWATCH_COLOR[view.swatch] }}
                />
              ) : null}
              <span>{t(view.labelKey)}</span>
              <span className={styles.viewCount}>{countLabel(format, presetCounts[view.id])}</span>
            </button>
          ))}
          {savedViews.views?.map((view) => (
            <div key={view.id} className={styles.savedView}>
              <button
                type="button"
                className={cn(styles.viewTab, styles.savedViewMain)}
                onClick={() => onApplyFilters(toSavedFilterState(view))}
              >
                <Bookmark aria-hidden className="h-3 w-3" />
                <span>{view.name}</span>
              </button>
              <button
                type="button"
                className={styles.savedViewDelete}
                aria-label={t("encounters.savedView.deleteAria", { name: view.name })}
                disabled={savedViews.deletePending}
                onClick={() => setViewToDelete(view)}
              >
                <Trash2 aria-hidden className="h-3 w-3" />
              </button>
            </div>
          ))}
          <ConfirmDialog
            open={viewToDelete != null}
            onOpenChange={(open) => {
              if (!open) setViewToDelete(null);
            }}
            intent={{
              title: t("encounters.savedView.deleteTitle"),
              description: t("encounters.savedView.confirmDelete", {
                name: viewToDelete?.name ?? ""
              }),
              confirmLabel: t("common.delete"),
              tone: "danger"
            }}
            pending={savedViews.deletePending}
            onConfirm={() => {
              if (viewToDelete) savedViews.remove(viewToDelete.id);
            }}
          />
          <span className={styles.viewsSpacer} />
          <button
            type="button"
            className={styles.viewSave}
            onClick={() => {
              if (!savedViews.requireAuth()) return;
              setSaveName(t("encounters.savedView.promptDefault"));
              setSaveDialogOpen(true);
            }}
            disabled={savedViews.savePending}
          >
            {savedViews.savePending ? (
              <Spinner className="size-3" />
            ) : (
              <Save aria-hidden className="h-3 w-3" />
            )}
            <span>{t("encounters.savedView.saveCurrent")}</span>
          </button>
        </div>
      </section>

      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>{t("encounters.savedView.saveCurrent")}</DialogTitle>
          </DialogHeader>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              const name = saveName.trim();
              if (!name) return;
              savedViews.save(name, filters);
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="saved-view-name">{t("encounters.savedView.promptName")}</Label>
              <Input
                id="saved-view-name"
                value={saveName}
                onChange={(event) => setSaveName(event.target.value)}
                autoFocus
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setSaveDialogOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={!saveName.trim() || savedViews.savePending}>
                {t("common.save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
