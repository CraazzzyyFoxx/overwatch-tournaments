"use client";

import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useRoleName } from "@/hooks/useRoleName";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { findRole } from "@/lib/roster/ontology";
import type { TournamentHistoryEntry } from "@/types/registration.types";

export default function TournamentHistoryCell({
  history,
  count,
  workspaceId,
}: Readonly<{
  history: TournamentHistoryEntry[];
  /** True total of past tournaments; `history` may be capped to a recent subset. */
  count?: number;
  /** The roster's workspace: every past tournament in `history` is one of its own. */
  workspaceId: number;
}>) {
  const t = useTranslations();

  if (!history || history.length === 0) {
    return (
      <span className="inline-flex items-center rounded-md border border-[color:color-mix(in_srgb,var(--aqt-emerald)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] px-1.5 py-0.5 text-xs font-medium text-[color:var(--aqt-emerald)]">
        {t("tournamentDetail.newBadge")}
      </span>
    );
  }

  // `history` is already capped server-side; `total` (true count) drives the badge
  // and the "+N more" hint for the entries the backend trimmed.
  const total = count ?? history.length;

  return (
    <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="xs"
            aria-label={t("tournamentDetail.previousTournaments", { count: total })}
            className="tabular-nums"
          >
            {total}x
          </Button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="max-w-xs px-3 py-2"
        >
          <ul className="space-y-1 text-xs">
            {history.map((h) => (
              <HistoryItem key={h.tournament_id} entry={h} workspaceId={workspaceId} />
            ))}
            {total > history.length && (
              <li className="text-[color:var(--aqt-fg-dim)]">
                +{total - history.length} {t("common.more")}
              </li>
            )}
          </ul>
        </TooltipContent>
      </Tooltip>
  );
}

/** One past tournament, drawn in ITS game's ontology (read on demand; the viewed game's is already cached). */
function HistoryItem({ entry: h, workspaceId }: Readonly<{ entry: TournamentHistoryEntry; workspaceId: number }>) {
  const t = useTranslations();
  const nameOf = useRoleName();
  // Until that game's metadata resolves (or when it is not installed) the role stays neutral and by code.
  const ontology = useDisciplineMetadata(workspaceId, h.discipline).data ?? null;
  // The exact leaf the participation was played as (`damage_hitscan`, not its parent `damage`).
  const node = h.role && ontology ? findRole(ontology, h.role) : null;

  return (
    <li className="space-y-1">
      <div className="text-[color:var(--aqt-fg)]">{h.tournament_name}</div>
      {(h.role || h.division != null) ? (
        <div className="flex items-center gap-2 text-[color:var(--aqt-fg-dim)]">
          {h.role ? (
            <span className="inline-flex items-center">
              <span className="sr-only">{node ? nameOf(node) : h.role.role}</span>
              <PlayerRoleIcon role={h.role} ontology={ontology} size={16} aria-hidden />
            </span>
          ) : null}
          {h.division != null ? (
            <span className="inline-flex items-center">
              <span className="sr-only">
                {getDivisionLabel(h.division_grid_version ?? { tiers: [] }, h.division) ??
                  t("common.divisionWithId", { id: h.division })}
              </span>
              <DivisionIcon
                division={h.division}
                width={20}
                height={20}
                tournamentGrid={h.division_grid_version}
                discipline={h.discipline}
                aria-hidden
              />
            </span>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
