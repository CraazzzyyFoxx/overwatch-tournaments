"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import type { Ladder } from "@/app/admin/settings/divisions/editor/draftReducer";
import {
  VersionHistory,
  type VersionHistoryProps
} from "@/app/admin/settings/divisions/VersionHistory";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import type { DivisionGridEntity, DivisionGridVersion } from "@/types/workspace.types";

import { editorHref } from "./model";

/**
 * The open grid of one game: which grid it is (a select only when the game has more than one), its menu, and its
 * version history. A game with no grid of its own says so; the in-force card above carries the action that makes one.
 */
export function GridSection({
  game,
  grids,
  selectedGrid,
  onSelectGrid,
  menu,
  versions,
  ladder,
  activeVersionId,
  tournamentCounts,
  activatable,
  onActivate
}: Readonly<
  Pick<VersionHistoryProps, "activeVersionId" | "tournamentCounts" | "activatable" | "onActivate"> & {
    /** The game's short name, for the empty state. */
    game: string;
    /** The game's grids in the workspace. */
    grids: DivisionGridEntity[];
    selectedGrid: DivisionGridEntity | null;
    onSelectGrid: (gridId: string) => void;
    /** The grid menu, beside the grid's name. */
    menu: ReactNode;
    versions: DivisionGridVersion[];
    ladder: Ladder | null;
  }
>) {
  const t = useTranslations("adminSettings.divisions");

  if (selectedGrid === null) {
    return (
      <section className="flex min-w-0 flex-col gap-3" aria-labelledby="divisions-history">
        <h2 id="divisions-history" className="text-ui font-semibold text-foreground">
          {t("versionHistory")}
        </h2>
        <EmptyNote title={t("noGrid.title", { game })}>{t("noGrid.description")}</EmptyNote>
      </section>
    );
  }

  const gridLabel = (grid: DivisionGridEntity) =>
    grid.archived_at ? t("archivedGrid", { name: grid.name }) : grid.name;

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="divisions-history">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {grids.length > 1 ? (
            <>
              <label className={eyebrowClass("muted")} htmlFor="division-grid-select">
                {t("grid")}
              </label>
              <Select value={String(selectedGrid.id)} onValueChange={onSelectGrid}>
                <SelectTrigger id="division-grid-select" className="w-72 max-w-full">
                  <SelectValue placeholder={t("chooseGrid")} />
                </SelectTrigger>
                <SelectContent>
                  {grids.map((grid) => (
                    <SelectItem key={grid.id} value={String(grid.id)}>
                      {gridLabel(grid)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          ) : (
            <>
              <span className={eyebrowClass("muted")}>{t("grid")}</span>
              <span className="truncate text-ui font-semibold text-foreground" title={selectedGrid.name}>
                {gridLabel(selectedGrid)}
              </span>
            </>
          )}
        </div>
        {menu}
      </div>

      <h2 id="divisions-history" className="text-ui font-semibold text-foreground">
        {t("versionHistory")}
      </h2>
      {versions.length === 0 ? (
        <EmptyNote title={t("noVersions")}>{t("noVersionsDescription")}</EmptyNote>
      ) : (
        <VersionHistory
          versions={versions}
          activeVersionId={activeVersionId}
          ladder={ladder}
          tournamentCounts={tournamentCounts}
          activatable={activatable}
          onActivate={onActivate}
          editorHref={editorHref}
        />
      )}
    </section>
  );
}
