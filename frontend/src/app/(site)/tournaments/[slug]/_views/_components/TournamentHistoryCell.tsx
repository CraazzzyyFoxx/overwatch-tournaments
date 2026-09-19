"use client";

import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { getDivisionLabel } from "@/lib/division-grid";
import type { TournamentHistoryEntry } from "@/types/registration.types";

const ROLE_TO_ICON: Record<string, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex",
};

function getHistoryRoleLabel(
  role: string,
  t: ReturnType<typeof useTranslations<never>>,
): string {
  switch (role.toLowerCase()) {
    case "tank":
      return t("common.roles.tank");
    case "damage":
      return t("common.roles.damage");
    case "support":
      return t("common.roles.support");
    case "flex":
      return t("common.roles.flex");
    default:
      return role;
  }
}

export default function TournamentHistoryCell({
  history,
  count,
}: Readonly<{
  history: TournamentHistoryEntry[];
  /** True total of past tournaments; `history` may be capped to a recent subset. */
  count?: number;
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
          <button
            type="button"
            aria-label={t("tournamentDetail.previousTournaments", { count: total })}
            className="inline-flex items-center rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-1.5 py-0.5 text-xs font-medium tabular-nums text-[color:var(--aqt-fg-muted)] outline-none transition hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-bg)]"
          >
            {total}x
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="max-w-xs border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-3 py-2 text-[color:var(--aqt-fg)] shadow-xl shadow-black/40"
        >
          <ul className="space-y-1 text-xs">
            {history.map((h) => {
              return (
                <li key={h.tournament_id} className="space-y-1">
                  <div className="text-[color:var(--aqt-fg)]">{h.tournament_name}</div>
                  {(h.role || h.division != null) ? (
                    <div className="flex items-center gap-2 text-[color:var(--aqt-fg-dim)]">
                      {h.role ? (
                        <span className="inline-flex items-center">
                          <span className="sr-only">{getHistoryRoleLabel(h.role, t)}</span>
                          <PlayerRoleIcon
                            role={ROLE_TO_ICON[h.role] ?? h.role}
                            size={16}
                            aria-hidden
                          />
                        </span>
                      ) : null}
                      {h.division != null ? (
                        <span className="inline-flex items-center">
                          <span className="sr-only">
                            {getDivisionLabel(
                              h.division_grid_version ?? { tiers: [] },
                              h.division
                            ) ?? t("common.divisionWithId", { id: h.division })}
                          </span>
                          <DivisionIcon
                            division={h.division}
                            width={20}
                            height={20}
                            tournamentGrid={h.division_grid_version}
                            aria-hidden
                          />
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
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
