"use client";

import type { CSSProperties } from "react";
import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { aggregateRoleStats } from "@/lib/roster/role-ref";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { tint } from "@/lib/colors";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { canSeat, type RoomSelection, type TeamView } from "@/lib/draft/room-model";
import { playerRoles, roleTopHeroes } from "@/lib/draft/workspace-model";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { ratedDimension, roleTint, showsRoles, type RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { DraftPlayer, DraftRole } from "@/types/draft.types";
import type { UserDraftCard } from "@/types/user.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl } from "@/lib/player";

import { MIN_WINRATE_MAPS, winrateColor } from "./PlayerCareer";

const PRIORITY_KEYS = ["primary", "second", "third"] as const;

interface RoleTilesProps {
  player: DraftPlayer;
  selection: RoomSelection | null;
  onSelectRole: (role: DraftRole) => void;
  /** Tiles are buttons only when the seat selects for this team and the player is still available. */
  actingTeam: TeamView | null;
  /** The player's career card; `null` without one (no account, error, or still loading). */
  card: UserDraftCard | null;
  /** The card is on its way: its lines hold their place instead of popping in. */
  cardPending: boolean;
  /** Only an organizer can act on a missing rank, so only an organizer is told how. */
  isAdmin: boolean;
  divisionGrid: DivisionGrid;
  /** The session owner's role dictionary: names, glyphs and colours of every tile. */
  ontology: RoleOntology | null;
}

/** One tile per role the player plays: rank, crest, sub-role, maps/WR on the role, top characters with their WR. */
export function RoleTiles({
  player,
  selection,
  onSelectRole,
  actingTeam,
  card,
  cardPending,
  isAdmin,
  divisionGrid,
  ontology
}: Readonly<RoleTilesProps>) {
  const t = useTranslations("draftRedesign");
  const slotLabel = useSlotLabel(ontology);
  const ratedCode = ontology ? (ratedDimension(ontology)?.code ?? null) : null;
  const roles = playerRoles(player);
  // A one-role game's tile is the player, not a role: no role name, no priority.
  const named = showsRoles(ontology);
  const displayName = player.display.name;
  // The team a tile selects for; tiles are read-only chips without one.
  const team = player.status === "available" ? actingTeam : null;
  const interactive = team != null;
  // Stats lines render whenever a card exists or is coming, so arriving data fills them in place.
  const withStats = card != null || cardPending;
  const characterRecords = new Map(card?.characters?.map((entry) => [entry.character.slug, entry]) ?? []);
  const roleTotals = aggregateRoleStats(card?.roles ?? []);

  if (roles.length === 0) {
    return (
      <p className="px-3.5 py-3 text-body text-[color:var(--aqt-fg-muted)]">
        {isAdmin ? t("noRoleHint") : t("noRoleHintViewer")}
      </p>
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
        const roleLabel = slotLabel(role);
        const accent = roleTint(ontology, role);
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
        const priority = named ? PRIORITY_KEYS[index] : undefined;
        const roleStats = roleTotals.find((entry) => entry.role?.dimension === ratedCode && entry.role.role === role) ?? null;
        const share = roleStats && roleStats.maps > 0 ? roleStats.maps_won / roleStats.maps : 0;
        const lowMaps = (roleStats?.maps ?? 0) < MIN_WINRATE_MAPS;

        const title = [
          named ? roleLabel : null,
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
              <PlayerRoleIcon role={role} ontology={ontology} size={24} decorative />
              <span className="flex min-w-0 flex-col">
                {named && <span className="whitespace-nowrap text-body font-semibold leading-tight">{roleLabel}</span>}
                {(priority || subRole) && (
                  <span className="flex min-w-0 items-center gap-1 whitespace-nowrap text-label font-medium leading-snug">
                    {priority && (
                      <span
                        style={{ color: index === 0 ? "var(--aqt-fg)" : "var(--aqt-fg-muted)" }}
                        title={t("island.priorityTitle", { n: index + 1, total: roles.length })}
                      >
                        {t(`island.priority.${priority}`)}
                      </span>
                    )}
                    {priority && subRole && <span className="text-[color:var(--aqt-fg-faint)]">·</span>}
                    {subRole && (
                      <span className="min-w-0 truncate text-[color:var(--aqt-fg-muted)]" title={subRole}>
                        {subRole}
                      </span>
                    )}
                  </span>
                )}
              </span>
              <span className="ml-auto flex shrink-0 items-center gap-1.5">
                {borrowed && (
                  <span
                    className="rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]"
                    title={t(`rankSource.${borrowed}`)}
                  >
                    {t(`rankSourceShort.${borrowed}`)}
                  </span>
                )}
                <span className="whitespace-nowrap text-ui font-semibold tabular-nums">{rank ?? "—"}</span>
                <RankCrest division={division} grid={divisionGrid} size={28} tooltip={false} />
              </span>
            </span>
            {(heroes.length > 0 || withStats) && (
              <span className="flex min-w-0 items-center gap-2">
                {heroes.length > 0 && (
                  <span className="flex items-start gap-1">
                    {heroes.map((hero) => {
                      const record = characterRecords.get(hero.slug);
                      const name = record?.character.name ?? hero.slug;
                      const heroShare = record && record.maps > 0 ? record.maps_won / record.maps : 0;
                      const heroLow = record == null || record.maps < MIN_WINRATE_MAPS;
                      const heroTitle =
                        card == null
                          ? name
                          : record == null
                            ? `${name} · ${t("island.tile.noMaps")}`
                            : `${name} · ${t("island.tile.maps", { n: record.maps })} · ${
                                heroLow ? t("island.stats.winrateHidden") : `${Math.round(heroShare * 100)}%`
                              }`;
                      return (
                        <span key={hero.slug} className="flex w-8 flex-col items-center gap-0.5" title={heroTitle}>
                          <CatalogEntityImage
                            entity={{ name, image_path: getHeroIconUrl(hero.slug, hero.imagePath) }}
                            size={32}
                            title={heroTitle}
                          />
                          {withStats && (
                            <span
                              className="text-label font-semibold leading-none tabular-nums"
                              style={{ color: record ? winrateColor(heroShare, record.maps) : "var(--aqt-fg-muted)" }}
                            >
                              {cardPending ? (
                                <Skeleton variant="text" aria-hidden className="w-6" />
                              ) : heroLow ? (
                                "—"
                              ) : (
                                `${Math.round(heroShare * 100)}%`
                              )}
                            </span>
                          )}
                        </span>
                      );
                    })}
                  </span>
                )}
                {withStats && (
                  <span
                    className="ml-auto shrink-0 whitespace-nowrap text-label tabular-nums text-[color:var(--aqt-fg-muted)]"
                    title={roleStats && roleStats.maps > 0 && lowMaps ? t("island.tile.wrHidden") : t("island.tile.wrTitle")}
                  >
                    {cardPending ? (
                      <Skeleton variant="text" aria-hidden className="w-20" />
                    ) : roleStats && roleStats.maps > 0 ? (
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
              style={{ borderColor: tint(accent, 50), background: tint(accent, 8) }}
            >
              {content}
            </div>
          );
        }

        return (
          <RowButton
            key={role}
            aria-pressed={on}
            aria-disabled={!usable || undefined}
            aria-label={
              named
                ? t("island.tile.select", { player: displayName, role: roleLabel })
                : t("island.tile.selectPlayer", { player: displayName })
            }
            title={title}
            onClick={() => {
              if (usable) onSelectRole(role);
            }}
            className={cn(
              tileClass,
              "min-h-11 motion-reduce:transition-none",
              on ? "border-2" : "border",
              usable ? "cursor-pointer" : "cursor-default border-dashed opacity-55"
            )}
            style={{
              borderColor: on ? "var(--aqt-teal)" : usable ? tint(accent, 50) : "var(--aqt-border-2)",
              background: on
                ? tint("var(--aqt-teal)", 14)
                : usable
                  ? tint(accent, 8)
                  : "transparent"
            }}
          >
            {content}
          </RowButton>
        );
      })}
    </div>
  );
}
