"use client";

import type { CSSProperties } from "react";
import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { canSeat, type RoomSelection, type TeamView } from "@/lib/draft/room-model";
import { playerRoles, roleTopHeroes } from "@/lib/draft/workspace-model";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { DraftPlayer, DraftRole } from "@/types/draft.types";
import type { UserDraftCard } from "@/types/user.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl } from "@/utils/player";

import { MIN_WINRATE_MAPS, winrateColor } from "./PlayerCareer";

const PRIORITY_KEYS = ["primary", "second", "third"] as const;

const tint = (role: DraftRole, percent: number) =>
  `color-mix(in srgb, ${ROLE_ACCENT[role]} ${percent}%, transparent)`;

interface RoleTilesProps {
  player: DraftPlayer;
  selection: RoomSelection | null;
  onSelectRole: (role: DraftRole) => void;
  /** Tiles are buttons only when the seat selects for this team and the player is still available. */
  actingTeam: TeamView | null;
  /** The card's per-role maps; `null` while there is no card (no account, loading, error). */
  cardRoles: UserDraftCard["roles"] | null;
  divisionGrid: DivisionGrid;
}

/** One tile per role the player plays: rank, crest, sub-role, maps/WR on the role, top heroes. */
export function RoleTiles({
  player,
  selection,
  onSelectRole,
  actingTeam,
  cardRoles,
  divisionGrid
}: Readonly<RoleTilesProps>) {
  const t = useTranslations("draftRedesign");
  const roles = playerRoles(player);
  const displayName = player.battle_tag ?? `#${player.id}`;
  // The team a tile selects for; tiles are read-only chips without one.
  const team = player.status === "available" ? actingTeam : null;
  const interactive = team != null;

  if (roles.length === 0) {
    return (
      <p className="px-3.5 py-3 text-sm text-[color:var(--aqt-fg-muted)]">{t("noRoleHint")}</p>
    );
  }

  return (
    <div
      role="group"
      aria-label={t("island.rolesGroup")}
      className="grid grid-cols-1 gap-2 px-3.5 py-3 sm:grid-cols-[repeat(var(--tiles),minmax(0,1fr))]"
      style={{ "--tiles": roles.length } as CSSProperties}
    >
      {roles.map((role, index) => {
        const roleLabel = t(`roles.${role}`);
        // The role's OWN rank, never another role's: an unranked role shows the em-dash.
        const rank = player.role_ranks[role] ?? null;
        const division = resolveDivisionFromRank(divisionGrid, rank);
        const crestLabel = division != null ? getDivisionLabel(divisionGrid, division) : null;
        // Provenance only when it is NOT the registration itself.
        const source = player.role_sources[role] ?? null;
        const borrowed = rank != null && source != null && source !== "registration" ? source : null;
        const subRole = formatSubRoleLabel(player.role_sub_roles?.[role]);
        const heroes = roleTopHeroes(player, role).slice(0, 3);
        const usable = team != null && canSeat(team, role);
        const on = selection?.playerId === player.id && selection.role === role;
        const priority = PRIORITY_KEYS[index];
        const roleStats = cardRoles?.find((entry) => entry.role === role) ?? null;
        const share = roleStats && roleStats.maps > 0 ? roleStats.maps_won / roleStats.maps : 0;
        const lowMaps = (roleStats?.maps ?? 0) < MIN_WINRATE_MAPS;

        const title = [
          roleLabel,
          rank ?? "—",
          crestLabel,
          borrowed ? t(`rankSource.${borrowed}`) : null,
          team != null && !usable ? t("island.tile.noSlot", { team: team.team.name }) : null
        ]
          .filter((part) => part != null)
          .join(" · ");

        const content = (
          <>
            <span className="flex min-w-0 items-center gap-2">
              <PlayerRoleIcon role={getRoleIconName(role)} size={24} color={ROLE_ACCENT[role]} decorative />
              <span className="flex min-w-0 flex-col">
                <span className="whitespace-nowrap text-sm font-semibold leading-tight">{roleLabel}</span>
                {priority && (
                  <span
                    className="whitespace-nowrap text-label font-medium uppercase leading-snug tracking-label"
                    style={{ color: index === 0 ? "var(--aqt-teal)" : "var(--aqt-fg-muted)" }}
                    title={t("island.priorityTitle", { n: index + 1, total: roles.length })}
                  >
                    {t(`island.priority.${priority}`)}
                  </span>
                )}
              </span>
              <span className="ml-auto flex shrink-0 items-center gap-1.5">
                {borrowed && (
                  <span
                    className="rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-wide text-[color:var(--aqt-fg-faint)]"
                    title={t(`rankSource.${borrowed}`)}
                  >
                    {t(`rankSourceShort.${borrowed}`)}
                  </span>
                )}
                <span className="whitespace-nowrap text-[15px] font-semibold tabular-nums">{rank ?? "—"}</span>
                {division != null && (
                  <DivisionIcon
                    division={division}
                    tournamentGrid={divisionGrid}
                    width={28}
                    height={28}
                    className="h-7 w-7 shrink-0 object-contain"
                  />
                )}
              </span>
            </span>
            {(subRole || cardRoles) && (
              <span className="flex min-w-0 items-center gap-1.5">
                {subRole && (
                  <span className="min-w-0 truncate text-[13px] font-medium" title={subRole}>
                    {subRole}
                  </span>
                )}
                {cardRoles && (
                  <span
                    className="ml-auto shrink-0 whitespace-nowrap text-xs tabular-nums text-[color:var(--aqt-fg-muted)]"
                    title={roleStats && roleStats.maps > 0 && lowMaps ? t("island.tile.wrHidden") : t("island.tile.wrTitle")}
                  >
                    {roleStats && roleStats.maps > 0 ? (
                      <>
                        {t("island.tile.maps", { n: roleStats.maps })}
                        {" · "}
                        <span className="font-semibold" style={{ color: winrateColor(share, roleStats.maps) }}>
                          {lowMaps ? "—" : `${Math.round(share * 100)}%`}
                        </span>
                      </>
                    ) : (
                      t("island.tile.noMaps")
                    )}
                  </span>
                )}
              </span>
            )}
            {heroes.length > 0 && (
              <span className="flex items-center gap-1">
                {heroes.map((hero) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={hero.slug}
                    src={getHeroIconUrl(hero.slug, hero.imagePath)}
                    alt={hero.slug}
                    title={hero.slug}
                    width={32}
                    height={32}
                    className="h-8 w-8 rounded-full object-cover"
                  />
                ))}
              </span>
            )}
            {on && (
              <span
                className="absolute -right-2 -top-2 flex h-[22px] w-[22px] items-center justify-center rounded-full bg-[color:var(--aqt-teal)]"
                aria-hidden
              >
                <Check className="h-3.5 w-3.5 text-[color:var(--aqt-bg)]" strokeWidth={3} />
              </span>
            )}
          </>
        );

        const tileClass =
          "relative flex min-w-0 flex-col items-stretch gap-2 rounded-[10px] px-3 py-2 text-left text-[color:var(--aqt-fg)]";

        if (!interactive) {
          return (
            <div
              key={role}
              title={title}
              className={cn(tileClass, "border")}
              style={{ borderColor: tint(role, 50), background: tint(role, 8) }}
            >
              {content}
            </div>
          );
        }

        return (
          <button
            key={role}
            type="button"
            aria-pressed={on}
            aria-disabled={!usable || undefined}
            aria-label={t("island.tile.select", { player: displayName, role: roleLabel })}
            title={title}
            onClick={() => {
              if (usable) onSelectRole(role);
            }}
            className={cn(
              tileClass,
              "min-h-11 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-card-2)] motion-reduce:transition-none",
              on ? "border-2" : "border",
              usable ? "cursor-pointer" : "cursor-default border-dashed opacity-55"
            )}
            style={{
              borderColor: on ? "var(--aqt-teal)" : usable ? tint(role, 50) : "var(--aqt-border-2)",
              background: on
                ? "color-mix(in srgb, var(--aqt-teal) 14%, transparent)"
                : usable
                  ? tint(role, 8)
                  : "transparent"
            }}
          >
            {content}
          </button>
        );
      })}
    </div>
  );
}
