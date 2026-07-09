"use client";

import { useTranslations } from "next-intl";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getDivisionLabel } from "@/lib/division-grid";
import type { TournamentHistoryEntry } from "@/types/registration.types";

const ROLE_TO_ICON: Record<string, string> = {
  tank: "Tank",
  dps: "Damage",
  support: "Support",
};

function getHistoryRoleLabel(
  role: string,
  t: ReturnType<typeof useTranslations<never>>,
): string {
  switch (role.toLowerCase()) {
    case "tank":
      return t("common.roles.tank");
    case "dps":
      return t("common.roles.dps");
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
}: {
  history: TournamentHistoryEntry[];
  /** True total of past tournaments; `history` may be capped to a recent subset. */
  count?: number;
}) {
  const t = useTranslations();

  if (!history || history.length === 0) {
    return (
      <span className="inline-flex items-center rounded-md border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-xs font-medium text-emerald-400">
        {t("tournamentDetail.newBadge")}
      </span>
    );
  }

  // `history` is already capped server-side; `total` (true count) drives the badge
  // and the "+N more" hint for the entries the backend trimmed.
  const total = count ?? history.length;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={t("tournamentDetail.previousTournaments", { count: total })}
            className="inline-flex items-center rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-xs font-medium text-white/65 transition hover:border-white/20 hover:bg-white/8 hover:text-white/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#111113]"
          >
            {total}x
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="max-w-xs border border-white/[0.08] bg-[#111113] px-3 py-2 text-white shadow-xl shadow-black/40"
        >
          <ul className="space-y-1 text-xs">
            {history.map((h) => {
              return (
                <li key={h.tournament_id} className="space-y-1">
                  <div className="text-white/80">{h.tournament_name}</div>
                  {(h.role || h.division != null) ? (
                    <div className="flex items-center gap-2 text-white/45">
                      {h.role ? (
                        <span
                          className="inline-flex items-center"
                          title={getHistoryRoleLabel(h.role, t)}
                        >
                          <PlayerRoleIcon
                            role={ROLE_TO_ICON[h.role] ?? h.role}
                            size={16}
                          />
                        </span>
                      ) : null}
                      {h.division != null ? (
                        <span
                          className="inline-flex items-center"
                          title={
                            getDivisionLabel(
                              h.division_grid_version ?? { tiers: [] },
                              h.division,
                            ) ?? t("common.divisionWithId", { id: h.division })
                          }
                        >
                          <PlayerDivisionIcon
                            division={h.division}
                            width={20}
                            height={20}
                            tournamentGrid={h.division_grid_version}
                          />
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
            {total > history.length && (
              <li className="text-white/30">
                +{total - history.length} {t("common.more")}
              </li>
            )}
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
