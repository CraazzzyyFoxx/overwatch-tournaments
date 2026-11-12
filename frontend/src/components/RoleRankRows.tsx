"use client";

import { useTranslations } from "next-intl";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { TONE_TEXT } from "@/components/ui/tone";
import { useRoleName } from "@/hooks/useRoleName";
import { findRole, type RoleOntology } from "@/lib/roster/ontology";
import type { RoleRef } from "@/lib/roster/team-format";
import { cn } from "@/lib/utils";
import type { DivisionGrid } from "@/types/workspace.types";

export interface RoleRankRow {
  role: RoleRef;
  /** `null` = declared but not rated, so not playable: the row dims and says so. */
  rank: number | null;
  /** Sub-role label for a leaf the dictionary does not name. */
  subrole?: string | null;
  primary?: boolean;
  /** Which layer the rank came from; `"none"` prints nothing. */
  source?: "registration" | "workspace" | "native" | "none" | null;
  /** The live in-game rank on the same scale as `rank`; printed only when it differs. */
  gameRank?: number | null;
}

/**
 * A player's roles one per line in priority order: position, glyph and name, crest and rank, then where the rank
 * came from. The detail-panel counterpart of `RoleRankList`, which packs the same roles into one inline row.
 */
export function RoleRankRows({
  rows,
  grid,
  ontology
}: Readonly<{ rows: readonly RoleRankRow[]; grid: DivisionGrid; ontology: RoleOntology | null }>) {
  const t = useTranslations("common.roleRankRows");
  const nameOf = useRoleName();
  return (
    <ol className="space-y-2">
      {rows.map((row, index) => {
        const role = ontology ? findRole(ontology, row.role) : null;
        const name = role ? nameOf(role) : row.role.role;
        const meta = [
          row.source && row.source !== "none" ? t(`source.${row.source}`) : null,
          row.gameRank != null && row.gameRank !== row.rank ? t("gameRank", { rank: row.gameRank }) : null
        ]
          .filter(Boolean)
          .join(" · ");
        return (
          <li
            key={`${row.role.dimension}:${row.role.role}-${index}`}
            className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-0.5"
          >
            <span className="flex size-5 items-center justify-center rounded-full border border-[color:var(--aqt-border-2)] text-[11px] tabular-nums text-[color:var(--aqt-fg-muted)]">
              {index + 1}
            </span>
            <span className={cn("flex min-w-0 items-center gap-1.5", row.rank == null && "opacity-60")}>
              <PlayerRoleIcon role={row.role} ontology={ontology} size={16} />
              <span className="truncate font-medium text-foreground" title={name}>
                {name}
              </span>
              {row.subrole ? (
                <span className="truncate text-[color:var(--aqt-fg-dim)]" title={row.subrole}>
                  {row.subrole}
                </span>
              ) : null}
              {row.primary ? <span className={cn("shrink-0 text-[11px]", TONE_TEXT.accent)}>{t("primary")}</span> : null}
            </span>
            {row.rank == null ? (
              <span className={cn("text-xs", TONE_TEXT.warning)}>{t("noRank")}</span>
            ) : (
              <RankCrest rank={row.rank} grid={grid} showValue className="font-semibold text-foreground" />
            )}
            {meta ? (
              <span className="col-span-2 col-start-2 text-[11px] text-[color:var(--aqt-fg-dim)]">{meta}</span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
