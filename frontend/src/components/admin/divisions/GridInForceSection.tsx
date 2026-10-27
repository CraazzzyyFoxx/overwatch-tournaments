"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import type { Band, Ladder } from "@/app/admin/settings/divisions/editor/draftReducer";
import { LadderBar } from "@/app/admin/settings/divisions/LadderBar";
import { Card } from "@/components/ui/card";
import { useFormatter } from "@/lib/datetime/client";
import type { DivisionGridEntity, DivisionGridVersion } from "@/types/workspace.types";

/**
 * The grid one game's ranks resolve through right now, and the one thing worth doing next.
 *
 * Its title names the grid and version when the workspace owns them; a version of a grid it does not own (a system
 * or shared grid) has only its label to go by; with nothing in force the game's built-in ladder is what resolves.
 */
export function GridInForceSection({
  game,
  ladder,
  activeVersion,
  activeGrid,
  bands,
  systemFallback,
  nextAction
}: Readonly<{
  /** The game's short name. */
  game: string;
  ladder: Ladder | null;
  activeVersion: DivisionGridVersion | null;
  /** The workspace's own grid holding `activeVersion`; `null` for a system or shared grid. */
  activeGrid: DivisionGridEntity | null;
  /** The active version's divisions, or the game's built-in ladder when nothing is in force. */
  bands: Band[];
  /** Nothing is activated explicitly; the version shown is the resolved system grid. */
  systemFallback: boolean;
  nextAction: ReactNode;
}>) {
  const t = useTranslations("adminSettings.divisions");
  const format = useFormatter();
  const ranks = ladder ? t("ladder.rankCount", { count: ladder.count }) : null;

  const title = activeVersion
    ? activeGrid
      ? t("inForceTitle", { grid: activeGrid.name, version: activeVersion.version })
      : activeVersion.label
    : ladder
      ? t("builtInLadder", { game })
      : t("gridRequired");

  const meta = activeVersion
    ? [
        systemFallback ? t("systemFallback") : t("inForce"),
        !systemFallback && !activeGrid ? t("sharedGrid") : null,
        t("divisionCount", { count: bands.length }),
        ranks,
        activeVersion.published_at
          ? t("publishedOn", {
              date: format.dateTime(new Date(activeVersion.published_at), { dateStyle: "medium" })
            })
          : null
      ]
    : [t("noActiveVersion"), ladder ? t("divisionCount", { count: bands.length }) : null, ranks];

  return (
    <Card asChild>
      <section aria-labelledby="divisions-in-force" className="flex flex-col gap-4 p-4 sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h2 id="divisions-in-force" className="truncate text-ui font-semibold text-foreground" title={title}>
              {title}
            </h2>
            <p className="mt-1 text-caption text-muted-foreground">{meta.filter(Boolean).join(" · ")}</p>
          </div>
          {nextAction ? <div className="shrink-0">{nextAction}</div> : null}
        </div>

        {ladder ? (
          <LadderBar ladder={ladder} bands={bands} size="lg" tone={activeVersion ? "accent" : "neutral"} />
        ) : null}
      </section>
    </Card>
  );
}
