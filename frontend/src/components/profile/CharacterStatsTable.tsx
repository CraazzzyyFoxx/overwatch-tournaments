"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { CardSurface } from "@/components/profile/atoms";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useFormatter } from "@/lib/datetime/client";
import { formatStat } from "@/lib/stats/format";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";
import type { CharacterSummary } from "@/types/user.types";

/**
 * A player's characters as a plain definition-driven table: one column per active stat the game declares and the
 * player has a value for (its declared name, order and `value_format`), the character's career value in each
 * cell. The generic view of a game whose module draws no characters tab of its own; a missing value is a dash.
 */
export default function CharacterStatsTable({
  axis,
  discipline,
  characters,
  title,
  action,
  limit
}: Readonly<{
  /** The viewed workspace axis the game's stat definitions are read on (a tenant host's own, never `all` there). */
  axis: WorkspaceAxis;
  discipline: string;
  characters: CharacterSummary[];
  /** Defaults to the localized "Characters". */
  title?: string;
  action?: ReactNode;
  limit?: number;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const definitions = useDisciplineMetadata(axis, discipline).data?.stat_defs ?? [];
  const present = new Set(characters.flatMap((row) => row.stats.map((stat) => stat.name)));
  const columns = definitions
    .filter((def) => def.active && present.has(def.code))
    .sort((a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code));
  const rows = limit === undefined ? characters : characters.slice(0, limit);

  return (
    <CardSurface title={title ?? t("common.characters")} action={action}>
      {rows.length === 0 ? (
        <div className="py-10 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.heroes.noStats")}</div>
      ) : (
        <Table className="border-collapse">
          <TableHeader>
            <TableRow>
              <TableHead scope="col" className="aqt-tnum px-3 py-2.5">
                {t("common.characters")}
              </TableHead>
              {columns.map((def) => (
                <TableHead key={def.code} scope="col" className="aqt-tnum whitespace-nowrap px-3 py-2.5 text-right">
                  {def.name}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.character.id}>
                <TableHead scope="row" className="px-3 py-2.5 text-caption font-normal normal-case tracking-normal">
                  <span className="flex items-center gap-2.5">
                    <CatalogEntityImage entity={row.character} size="sm" decorative />
                    <span className="truncate font-bold text-[color:var(--aqt-fg)]">{row.character.name}</span>
                  </span>
                </TableHead>
                {columns.map((def) => (
                  <TableCell key={def.code} className="aqt-tnum px-3 py-2.5 text-right text-[color:var(--aqt-fg-muted)]">
                    {formatStat(def, row.stats.find((stat) => stat.name === def.code)?.overall, format)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </CardSurface>
  );
}
