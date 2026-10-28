"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  pivotCurrentRanks,
  signed,
  type MatrixCell,
  type MatrixLine,
  type RankMatrix
} from "@/components/admin/people/personRanks.model";
import { EmptyNote, LoadErrorNote } from "@/components/kit/EmptyNote";
import { SettingGroup } from "@/components/kit/SettingRow";
import { formatDate } from "@/components/kit/format-time";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { registrationRoles } from "@/lib/roster/ontology";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import { cn } from "@/lib/utils";
import { workspacePlayerService } from "@/services/workspace-player.service";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { DivisionGrid } from "@/types/workspace.types";

/** The row label stays put while the role columns scroll under it on a phone; the card's fill hides them. */
const STICKY = "sticky left-0 z-[1] bg-card";

/**
 * «Текущие ранги»: what the person is rated at now in one game, layer × role — the tournament number first, then
 * canon, the in-game ladder, the hidden rating and each author's book. Read-only: the roster's rank editor owns writes.
 */
export function PersonRankMatrix({
  workspaceId,
  personId,
  game,
  axis
}: Readonly<{ workspaceId: number; personId: number; game: string; axis: WorkspaceAxis }>) {
  const t = useTranslations("adminPeople.rank");
  const tOverview = useTranslations("admin.rankOverview");
  // No `layer`: the server's default is the six current layers.
  const query = useQuery({
    queryKey: adminQueryKeys.rankOverview(workspaceId, { discipline: game, playerId: personId, layers: "current" }),
    queryFn: () => workspacePlayerService.listRanks(workspaceId, { discipline: game, playerId: personId, perPage: 100 })
  });
  const metadata = useDisciplineMetadata(axis, game);
  const ontology = metadata.data ?? null;
  const matrix = useMemo(
    () => pivotCurrentRanks(query.data?.results ?? [], registrationRoles(ontology).map((role) => role.code)),
    [query.data, ontology]
  );

  return (
    <SettingGroup id="current-ranks" title={t("current")}>
      {query.isError || metadata.isError ? (
        <LoadErrorNote
          title={tOverview("loadError")}
          onRetry={() => {
            void query.refetch();
            void metadata.refetch();
          }}
        />
      ) : query.isPending || metadata.isPending ? (
        <div className="space-y-2" aria-hidden>
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-9 w-full max-w-xl" />
          ))}
        </div>
      ) : matrix.layers.length + matrix.authors.length === 0 ? (
        <EmptyNote>{t("noRanks")}</EmptyNote>
      ) : (
        <MatrixTable matrix={matrix} ontology={ontology} game={game} />
      )}
    </SettingGroup>
  );
}

function MatrixTable({
  matrix,
  ontology,
  game
}: Readonly<{ matrix: RankMatrix; ontology: DisciplineMetadata | null; game: string }>) {
  const t = useTranslations("adminPeople.rank");
  const tOverview = useTranslations("admin.rankOverview");
  const slotLabel = useSlotLabel(ontology);
  const grid = useDivisionGrid(game);
  const { roles, layers, authors } = matrix;

  return (
    <div
      role="region"
      aria-label={t("matrixLabel")}
      tabIndex={0}
      className="overflow-x-auto focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
    >
      <Table className="w-auto border-collapse text-left" wrapperClassName="overflow-visible">
        <TableHeader>
          <TableRow className="border-border/60">
            <TableHead scope="col" className={cn(STICKY, "py-2 pl-0 pr-6")}>
              <span className="sr-only">{tOverview("columns.layer")}</span>
            </TableHead>
            {roles.map((role) => (
              <TableHead key={role ?? ""} scope="col" className="px-3 py-2">
                {role === null ? null : (
                  <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                    <PlayerRoleIcon role={role} ontology={ontology} size={16} decorative />
                    {slotLabel(role)}
                  </span>
                )}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {layers.map((line) => (
            <MatrixRow key={line.key} line={line} roles={roles} grid={grid} />
          ))}
          {authors.length > 0 ? (
            <TableRow className="border-border/60 hover:bg-transparent">
              <TableHead scope="colgroup" colSpan={roles.length + 1} className="px-0 pt-5 pb-1.5">
                <Eyebrow tone="muted" className="sticky left-0">
                  {t("authors", { count: authors.length })}
                </Eyebrow>
              </TableHead>
            </TableRow>
          ) : null}
          {authors.map((line) => (
            <MatrixRow key={line.key} line={line} roles={roles} grid={grid} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function MatrixRow({
  line,
  roles,
  grid
}: Readonly<{ line: MatrixLine; roles: RankMatrix["roles"]; grid: DivisionGrid }>) {
  const t = useTranslations("adminPeople.rank");
  const tOverview = useTranslations("admin.rankOverview");
  const label = line.layer === "author" ? (line.label ?? "") : t(`rows.${line.layer}`);
  // The tournament number's source is said once under the label when the row agrees, per cell when it does not.
  const sourced = line.layer === "effective_tournament";
  return (
    <TableRow className="border-border/60 hover:bg-transparent">
      <TableHead
        scope="row"
        className={cn(STICKY, "py-2.5 pl-0 pr-6 font-normal normal-case tracking-normal text-card-foreground")}
      >
        <span className="block max-w-48 truncate text-body font-medium" title={label}>
          {label}
        </span>
        {sourced && line.source ? (
          <span className="block text-caption text-muted-foreground">{tOverview(`sources.${line.source}`)}</span>
        ) : null}
      </TableHead>
      {roles.map((role) => {
        const cell = line.cells.get(role);
        return (
          <TableCell key={role ?? ""} className="px-3 py-2.5">
            {cell ? <RankValue cell={cell} grid={grid} withSource={sourced && !line.source} /> : null}
          </TableCell>
        );
      })}
    </TableRow>
  );
}

/** A division crest (its name in `title`) and the number, with what qualifies it for its layer. */
function RankValue({ cell, grid, withSource }: Readonly<{ cell: MatrixCell; grid: DivisionGrid; withSource: boolean }>) {
  const tOverview = useTranslations("admin.rankOverview");
  const format = useFormatter();
  const { row, mix } = cell;
  // The native ladder is only readable as its own naming ("grandmaster 5"); the number and the account go in `title`.
  const ladder =
    row.layer === "native" && row.native_division
      ? `${row.native_division}${row.native_tier == null ? "" : ` ${row.native_tier}`}`
      : null;
  const title = mix
    ? [tOverview("layers.effective_mix"), row.source ? tOverview(`sources.${row.source}`) : null].filter(Boolean).join(" · ")
    : ladder
      ? [String(row.rank_value), row.context?.label, formatDate(format, row.at)].filter(Boolean).join(" · ")
      : undefined;

  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={title}>
      {row.division == null ? null : (
        <span className="inline-flex shrink-0" title={getDivisionLabel(grid, row.division) ?? undefined}>
          <DivisionIcon division={row.division} tournamentGrid={grid} width={20} height={20} />
        </span>
      )}
      <span className={cn("text-body tabular-nums", ladder && "capitalize", mix && "text-muted-foreground")}>
        {ladder ?? row.rank_value}
      </span>
      {row.layer === "hidden" && row.sigma != null ? (
        <span className="text-caption tabular-nums text-muted-foreground">±{Math.round(row.sigma)}</span>
      ) : null}
      {row.layer === "author" && row.canon_diff ? (
        <span className="text-caption tabular-nums text-muted-foreground">{signed(row.canon_diff)}</span>
      ) : null}
      {withSource && row.source ? (
        <span className="text-caption text-muted-foreground">{tOverview(`sources.${row.source}`)}</span>
      ) : null}
    </span>
  );
}
