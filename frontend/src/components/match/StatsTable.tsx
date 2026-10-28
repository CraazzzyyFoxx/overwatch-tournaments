"use client";

import { useTranslations } from "next-intl";

import PlayerName from "@/components/PlayerName";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { useFormatter } from "@/lib/datetime/client";
import { formatStat } from "@/lib/stats/format";
import type { StatsTable } from "@/lib/stats/table";
import type { StatDefinition } from "@/types/discipline.types";

/**
 * A game-neutral statistics table: one section per participation (any number of them), one row per observed
 * member, one column per declared stat that was observed. Cells format by the stat's `value_format`; a stat the
 * member has no value for is an em dash, never a zero. A participation's team facts resolve their definitions
 * from the discipline's full `definitions`, not from the member columns, so a team-only stat keeps its name and
 * format. A handle links to its player's profile only through the canonical name (`playerName`).
 */
export default function StatsTableView({
  table,
  definitions,
  withMaps = false,
  empty = "members"
}: Readonly<{
  table: StatsTable;
  /** Every stat the discipline declares (`metadata.stat_defs`). */
  definitions: readonly StatDefinition[];
  /** Show how many matches each member was observed in (series tables). */
  withMaps?: boolean;
  /** What a participation without rows says: it observed no one, or none has values at the selected grain. */
  empty?: "members" | "values";
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const defs: Record<string, StatDefinition> = Object.fromEntries(
    definitions.map((def) => [def.code, def])
  );
  const span = 1 + (withMaps ? 1 : 0) + table.columns.length;

  return (
    <div className="overflow-hidden rounded-[12px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead scope="col" className="min-w-[200px]">
              {t("matches.native.player")}
            </TableHead>
            {withMaps ? (
              <TableHead
                scope="col"
                className="text-center"
                title={t("encounters.detail.colMapsTitle")}
              >
                {t("encounters.detail.colMaps")}
              </TableHead>
            ) : null}
            {table.columns.map((def) => (
              <TableHead key={def.code} scope="col" className="text-center whitespace-nowrap">
                {def.name}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        {table.sections.map((section) => {
          const teamFacts = Object.entries(section.teamFacts);
          return (
            <TableBody key={section.key} className="border-t border-[color:var(--aqt-border)]">
              <TableRow className="bg-[color:var(--aqt-overlay-2)]">
                {/* A team's name, not a column label: no uppercase on user content. */}
                <TableHead scope="colgroup" colSpan={span} className="text-caption normal-case tracking-normal text-[color:var(--aqt-fg)]">
                  <span className="inline-flex flex-wrap items-center gap-x-2">
                    <span>{section.name}</span>
                    <span className="text-label font-normal text-[color:var(--aqt-fg-dim)]">
                      {t("encounters.history.participation", { id: section.encounterTeamId })}
                      {section.live === false
                        ? ` · ${t("encounters.history.retiredParticipation")}`
                        : null}
                    </span>
                    {teamFacts.map(([code, value]) => (
                      <span
                        key={code}
                        className="aqt-tnum text-label font-normal text-[color:var(--aqt-fg-muted)]"
                      >
                        {defs[code]?.name ?? code}:{" "}
                        {defs[code]
                          ? formatStat(defs[code], value, format)
                          : format.number(value, { maximumFractionDigits: 2 })}
                      </span>
                    ))}
                  </span>
                </TableHead>
              </TableRow>
              {section.rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={span} className="text-center text-[color:var(--aqt-fg-dim)]">
                    {t(
                      empty === "members" ? "matches.native.noMembers" : "matches.native.noValues"
                    )}
                  </TableCell>
                </TableRow>
              ) : (
                section.rows.map((row) => (
                  <TableRow key={row.key}>
                    <TableCell>
                      <PlayerName
                        player={{ name: row.name }}
                        profileName={row.playerName || null}
                        includeSpecialization={false}
                      />
                    </TableCell>
                    {withMaps ? (
                      <TableCell className="aqt-tnum text-center">
                        {row.mapsPlayed ?? "—"}
                      </TableCell>
                    ) : null}
                    {table.columns.map((def) => (
                      <TableCell key={def.code} className="aqt-tnum text-center text-caption">
                        {formatStat(def, row.values[def.code], format)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              )}
            </TableBody>
          );
        })}
      </Table>
    </div>
  );
}
