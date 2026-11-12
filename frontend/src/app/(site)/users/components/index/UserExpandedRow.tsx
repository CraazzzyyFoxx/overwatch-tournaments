"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { useRoleName } from "@/hooks/useRoleName";
import { findRole, type RoleOntology } from "@/lib/roster/ontology";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import type { PlayerIdentity } from "@/components/PlayerAvatar";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { PlaceBadge } from "@/components/ui/place-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { winrateColor } from "@/lib/colors";
import { getPlayerSlug } from "@/lib/player";
import { formatOptional } from "@/app/(site)/users/components/shared/list-utils";
import { SummaryStrip } from "@/app/(site)/users/components/tournaments/tournaments-history.atoms";
import userService from "@/services/user.service";
import { userQueryKeys } from "@/lib/users/query-keys";

const sharePct = (won: number, total: number): number | null =>
  total > 0 ? (won / total) * 100 : null;

function Winrate({ won, total }: Readonly<{ won: number; total: number }>) {
  const pct = sharePct(won, total);
  if (pct === null) return <span className="text-[color:var(--aqt-fg-faint)]">-</span>;
  return (
    <span className="font-semibold tabular-nums" style={{ color: winrateColor(pct) }}>
      {pct.toFixed(0)}%
    </span>
  );
}

/**
 * The per-player drawer. Its data is a separate read, fired only once the row
 * is actually open — the index ships ~100 rows a page and nobody opens 100.
 */
export function UserExpandedRow({
  user,
  workspaceId,
  discipline,
  ontology,
  compareSelected,
  compareDisabled,
  onToggleCompare
}: Readonly<{
  user: PlayerIdentity;
  workspaceId: number | "all" | null;
  /** The index's game: the drawer's career is that game's. */
  discipline: string;
  /** That game's role dictionary; `null` while it loads (roles then read by code). */
  ontology: RoleOntology | null;
  compareSelected: boolean;
  compareDisabled: boolean;
  onToggleCompare: () => void;
}>) {
  const t = useTranslations();
  const nameOf = useRoleName();
  const { data, isPending, isError } = useQuery({
    queryKey: userQueryKeys.draftCard(user.id, workspaceId, discipline),
    queryFn: () => userService.getDraftCard(user.id, discipline, workspaceId),
    staleTime: 60_000
  });

  if (isError) {
    return (
      <p className="px-4 py-5 text-caption text-[color:var(--aqt-rose)]">
        {t("users.list.errors.details")}
      </p>
    );
  }

  if (isPending || !data) {
    return (
      <div className="space-y-3 px-4 py-5">
        <Skeleton className="h-14" />
        <Skeleton className="h-28" />
      </div>
    );
  }

  const slug = getPlayerSlug(user.name);
  const winratePct = sharePct(data.maps_won, data.maps_won + data.maps_lost);

  return (
    <div className="space-y-5 px-4 py-5">
      <SummaryStrip
        cells={[
          { key: "tournaments", label: t("common.tournaments"), value: data.tournaments },
          { key: "tournamentsWon", label: t("users.list.expanded.tournamentsWon"), value: data.tournaments_won },
          { key: "maps", label: t("users.list.expanded.mapsLabel"), value: data.maps },
          {
            key: "winrate",
            label: t("users.list.table.winrate"),
            value: winratePct === null ? "-" : `${winratePct.toFixed(0)}%`,
            color: winratePct === null ? undefined : winrateColor(winratePct)
          },
          { key: "avgPlacement", label: t("users.list.table.avgPlacement"), value: formatOptional(data.avg_placement) },
          {
            key: "bestPlacement",
            label: t("users.list.table.bestPlacement"),
            value: data.best_placement ? <PlaceBadge place={data.best_placement} /> : "-"
          }
        ]}
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <section className="space-y-2">
          <Eyebrow>{t("users.list.expanded.roles")}</Eyebrow>
          {data.roles.length === 0 ? (
            <p className="text-caption text-[color:var(--aqt-fg-faint)]">
              {t("users.list.expanded.noRoleData")}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {data.roles.map((role) => {
                const node = ontology ? findRole(ontology, role.role) : null;
                const label = role.role === null ? t("common.roles.flex") : node ? nameOf(node) : role.role.role;
                return (
                <li key={`${role.role?.dimension}-${role.role?.role}`} className="flex items-center gap-2 text-caption">
                  <PlayerRoleIcon role={role.role} ontology={ontology} size={16} decorative />
                  <span className="text-[color:var(--aqt-fg-muted)]">
                    {label}
                  </span>
                  <span className="ml-auto flex items-center gap-3">
                    <Winrate won={role.maps_won} total={role.maps} />
                    <span className="tabular-nums text-[color:var(--aqt-fg-faint)]">
                      {t("users.list.expanded.maps", { count: role.maps })}
                    </span>
                  </span>
                </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="space-y-2">
          <Eyebrow>{t("users.list.expanded.recentTournaments")}</Eyebrow>
          {data.recent_tournaments.length === 0 ? (
            <p className="text-caption text-[color:var(--aqt-fg-faint)]">
              {t("users.list.expanded.noTournaments")}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {data.recent_tournaments.map((tournament) => (
                <li key={tournament.id} className="flex items-center gap-2 text-caption">
                  {tournament.placement ? <PlaceBadge place={tournament.placement} /> : null}
                  <HoverPrefetchLink
                    href={`/tournaments/${tournament.id}`}
                    className="truncate text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-teal)]"
                  >
                    {tournament.name}
                  </HoverPrefetchLink>
                  {tournament.teams_count ? (
                    <span className="ml-auto shrink-0 tabular-nums text-[color:var(--aqt-fg-faint)]">
                      {t("users.list.expanded.outOf", { count: tournament.teams_count })}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="space-y-2">
          <Eyebrow>{t("users.list.expanded.heroes")}</Eyebrow>
          {!data.characters?.length ? (
            <p className="text-caption text-[color:var(--aqt-fg-faint)]">
              {t("users.list.expanded.noHeroData")}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {data.characters.slice(0, 5).map((entry) => (
                <li key={entry.character.id} className="flex items-center gap-2 text-caption">
                  <CatalogEntityImage entity={entry.character} size="sm" decorative />
                  <span className="truncate text-[color:var(--aqt-fg-muted)]">{entry.character.name}</span>
                  <span className="ml-auto flex items-center gap-3">
                    <Winrate won={entry.maps_won} total={entry.maps} />
                    <span className="tabular-nums text-[color:var(--aqt-fg-faint)]">
                      {t("users.list.expanded.maps", { count: entry.maps })}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button asChild variant="outline" size="sm">
          <HoverPrefetchLink href={`/users/${slug}`}>{t("users.list.expanded.openProfile")}</HoverPrefetchLink>
        </Button>
        <Button asChild variant="outline" size="sm">
          <HoverPrefetchLink href={`/users/${slug}?tab=matches`}>{t("common.matches")}</HoverPrefetchLink>
        </Button>
        <Button asChild variant="outline" size="sm">
          <HoverPrefetchLink href={`/users/${slug}?tab=heroes`}>{t("common.characters")}</HoverPrefetchLink>
        </Button>
        {/* A disabled `Button` takes no pointer events, so the limit hint sits on a wrapper. */}
        <span title={compareDisabled && !compareSelected ? t("users.list.compare.limit") : undefined}>
          <Button
            variant="outline"
            size="sm"
            onClick={onToggleCompare}
            disabled={compareDisabled && !compareSelected}
            aria-pressed={compareSelected}
          >
            {compareSelected
              ? t("users.list.compare.removeShort")
              : t("users.list.compare.addShort")}
          </Button>
        </span>
      </div>
    </div>
  );
}
