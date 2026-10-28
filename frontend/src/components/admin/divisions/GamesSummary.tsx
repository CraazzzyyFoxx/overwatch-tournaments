"use client";

import { useMemo } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  bandsFromTiers,
  createLadder,
  standardTiers
} from "@/app/admin/settings/divisions/editor/draftReducer";
import { LadderBar } from "@/app/admin/settings/divisions/LadderBar";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { GameMark } from "@/components/workspace/GameMark";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { activeGridVersionId, resolveOwnerGrid } from "@/lib/divisions/grid";
import { DISCIPLINE_PARAM } from "@/lib/site/discipline-scope";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { DivisionGridEntity, Workspace } from "@/types/workspace.types";

type WorkspaceGrids = Pick<Workspace, "default_division_grid_versions" | "effective_division_grid_versions">;

/**
 * "All games": one row per enabled game saying which grid its ranks resolve through, so a multi-game workspace reads
 * its divisions at a glance; a row opens that game. A game's versions, history and editor live on its own view.
 */
export function GamesSummary({
  workspaceId,
  games,
  workspace,
  grids
}: Readonly<{
  workspaceId: number;
  /** The workspace's enabled games, in its order. */
  games: DisciplineDescriptor[];
  workspace: WorkspaceGrids | null | undefined;
  grids: DivisionGridEntity[];
}>) {
  const t = useTranslations("adminSettings.divisions");
  return (
    <section className="flex flex-col gap-3" aria-labelledby="divisions-games">
      <h2 id="divisions-games" className="text-ui font-semibold text-foreground">
        {t("games.title")}
      </h2>
      <Card asChild>
        <ul className="divide-y divide-border">
          {games.map((game) => (
            <GameRow key={game.code} workspaceId={workspaceId} game={game} workspace={workspace} grids={grids} />
          ))}
        </ul>
      </Card>
    </section>
  );
}

/** The summary's skeleton: the same rows, so nothing reflows when the grids land. */
export function GamesSummarySkeleton({ rows }: Readonly<{ rows: number }>) {
  return (
    <div aria-hidden className="flex flex-col gap-3">
      <Skeleton className="h-5 w-40" />
      <Card className="divide-y divide-border">
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="size-7 rounded-md" />
            <div className="flex flex-1 flex-col gap-1.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-56" />
            </div>
            <Skeleton className="hidden h-1.5 w-48 md:block" />
          </div>
        ))}
      </Card>
    </div>
  );
}

function GameRow({
  workspaceId,
  game,
  workspace,
  grids
}: Readonly<{
  workspaceId: number;
  game: DisciplineDescriptor;
  workspace: WorkspaceGrids | null | undefined;
  grids: DivisionGridEntity[];
}>) {
  const t = useTranslations("adminSettings.divisions");
  const metadata = useDisciplineMetadata(workspaceId, game.code).data;
  const ladder = useMemo(
    () => (metadata?.discipline.capabilities.native_ladder ? createLadder(metadata.native_ladder) : null),
    [metadata]
  );
  const active = resolveOwnerGrid(workspace, game.code);
  const explicit = activeGridVersionId(workspace, game.code) !== null;
  const own = active ? grids.find((grid) => grid.id === active.grid_id) : undefined;
  const bands = useMemo(
    () =>
      active ? bandsFromTiers(ladder, active.tiers) : ladder ? bandsFromTiers(ladder, standardTiers(ladder)) : [],
    [active, ladder]
  );

  const status = active
    ? own
      ? t("inForceTitle", { grid: own.name, version: active.version })
      : explicit
        ? `${active.label} · ${t("sharedGrid")}`
        : t("games.system", { label: active.label })
    : game.capabilities.native_ladder
      ? t("games.builtIn")
      : null;

  return (
    <li className="relative flex items-center gap-3 px-4 py-3 transition-colors hover:bg-[color:var(--aqt-overlay-2)]">
      <GameMark discipline={game} size={28} decorative />
      <div className="min-w-0 flex-1">
        <Link
          href={`/admin/settings/divisions?${DISCIPLINE_PARAM}=${encodeURIComponent(game.code)}`}
          className="block truncate text-ui font-medium text-foreground after:absolute after:inset-0 after:content-[''] focus-visible:outline-hidden focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-ring"
        >
          {game.name}
        </Link>
        {status ? (
          <p className="truncate text-caption text-muted-foreground" title={status}>
            {status}
          </p>
        ) : (
          <p className="text-caption text-warning">{t("games.needsGrid")}</p>
        )}
      </div>
      {bands.length > 0 ? (
        <span className="aqt-tnum shrink-0 text-caption text-muted-foreground">
          {t("divisionCount", { count: bands.length })}
        </span>
      ) : null}
      {ladder && bands.length > 0 ? (
        <LadderBar
          ladder={ladder}
          bands={bands}
          tone={active ? "accent" : "neutral"}
          className="hidden w-48 shrink-0 md:flex"
        />
      ) : null}
      <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </li>
  );
}
