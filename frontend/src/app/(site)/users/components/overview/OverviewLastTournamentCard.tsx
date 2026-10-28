"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight, ChevronDown, Hourglass } from "lucide-react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { UserTournamentWithStats } from "@/types/user.types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import { type MapResultPip } from "@/app/(site)/users/components/overview/map-results";
import { UserTournamentStat } from "@/types/statistics.types";
import { CardSurface } from "@/components/profile/atoms";
import { ResTag, type ResTagKind } from "@/components/match/cells";
import { Button } from "@/components/ui/button";
import { triggerChevronClass } from "@/components/ui/chevron";
import { Eyebrow } from "@/components/ui/eyebrow";
import { isRankedEntry, LobbyStatGrid, type LobbyStatTile } from "@/components/profile/LobbyStatGrid";
import ProfileWidget from "@/components/profile/ProfileWidget";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useRoleName } from "@/hooks/useRoleName";
import { useFormatter } from "@/lib/datetime/client";
import { formatStat } from "@/lib/stats/format";
import { findRole } from "@/lib/roster/ontology";
import { tournamentHref } from "@/lib/tournament/url";
import { TournamentCombobox } from "@/components/tournaments/TournamentCombobox";
import LobbyLeaderboardModal from "@/app/(site)/users/components/overview/LobbyLeaderboardModal";

interface Props {
  /** Its owner workspace and game name and draw the role played (that workspace's sub-roles included). */
  tournament: UserTournamentWithStats;
  /** The server's read of that workspace and game's metadata, so the first paint names the role. */
  metadata?: DisciplineMetadata;
  /** The switcher's options: the profile's tournaments. */
  tournaments: readonly { id: number; name: string }[];
  /** Profile owner's user id — the row highlighted in the lobby leaderboard. */
  userId: number;
  mapPips?: MapResultPip[] | null;
}

const formatPercent = (value: number | null | undefined, digits = 0) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
};

// The card title IS the tournament switcher: heading type, no box. The title
// row truncates (clips), so the focus ring is drawn inside.
const HEADING_TRIGGER =
  "group/trigger -ml-1 min-w-0 max-w-full px-1 font-semibold focus-visible:ring-inset focus-visible:ring-offset-0";

// Map result → the same `ResTag` square the header's form streak uses, with
// its always-present letter/title (design-book: never colour alone).
const PIP_KIND: Record<MapResultPip, ResTagKind> = {
  win: "w",
  loss: "l",
  draw: "d"
};
const PIP_LABEL_KEY: Record<MapResultPip, string> = {
  win: "users.overview.win",
  loss: "users.overview.loss",
  draw: "users.overview.draw"
};
const PIP_TITLE_KEY: Record<MapResultPip, string> = {
  win: "users.overview.lastTournament.mapWon",
  loss: "users.overview.lastTournament.mapLost",
  draw: "users.overview.lastTournament.mapDraw"
};

const OverviewLastTournamentCard = ({ tournament, metadata, tournaments, userId, mapPips }: Props) => {
  const t = useTranslations();
  const nameOf = useRoleName();
  const format = useFormatter();
  const ontology = useDisciplineMetadata(tournament.workspace_id, tournament.discipline, metadata).data ?? null;
  const roleNode = ontology ? findRole(ontology, tournament.role) : null;
  // The exact role played, in the game's dictionary; one it does not know keeps its own code.
  const roleLabel = tournament.role === null ? t("common.roles.flex") : roleNode ? nameOf(roleNode) : tournament.role.role;
  const [lb, setLb] = useState<{ stat: string; label: string } | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const playtimeH = Math.floor(tournament.playtime / 3600);
  const playtimeM = Math.floor((tournament.playtime % 3600) / 60);
  const mapsLost = tournament.maps - tournament.maps_won;
  const winrate = tournament.maps > 0 ? tournament.maps_won / tournament.maps : null;
  // Real per-map order when the encounters carried it; otherwise the aggregate
  // W/L counts (flagged as such under the row).
  const resultPips: MapResultPip[] =
    mapPips && mapPips.length > 0
      ? mapPips
      : [
          ...Array.from({ length: tournament.maps_won }, () => "win" as const),
          ...Array.from({ length: Math.max(0, mapsLost) }, () => "loss" as const)
        ];

  const onSelectTournament = (id: number | undefined) => {
    if (id === undefined) return;
    const nextSearchParams = new URLSearchParams(searchParams || undefined);
    nextSearchParams.set("tournamentId", String(id));
    router.push(`${pathname}?${nextSearchParams.toString()}`);
  };
  // A deep-linked tournament outside the profile list must still name itself.
  const switcherTournaments = tournaments.some((tour) => tour.id === tournament.id)
    ? tournaments
    : [tournament, ...tournaments];

  // `stats` holds the ranked tournament stats the backend computes, keyed by stat code; one without a real rank in
  // a non-empty lobby is never drawn.
  const stats = tournament.stats as Record<string, UserTournamentStat | undefined>;
  const ranked = Object.values(stats).filter(isRankedEntry);
  const lobbySize = ranked[0]?.total ?? null;
  // The generic tiles: the game's declared stats the player is ranked on, in declared order, named and formatted by
  // their declaration. A game module draws its own selection and presentation instead (the `lobbyRankTiles` slot).
  const genericTiles: LobbyStatTile[] = (ontology?.stat_defs ?? [])
    .filter((def) => def.active)
    .sort((left, right) => left.sort_order - right.sort_order || left.code.localeCompare(right.code))
    .flatMap((def) => {
      const entry = stats[def.code];
      if (!isRankedEntry(entry)) return [];
      return [{ stat: def.code, label: def.name, rank: entry.rank, total: entry.total, value: formatStat(def, entry.value, format) }];
    });
  const openLeaderboard = (stat: string, label: string) => setLb({ stat, label });
  // A tournament the player is entered in but that has no recorded maps yet
  // (not played, or results not uploaded) comes back as all zeros. Printing
  // "Placed 0 · 0 maps · 0W · 0L" reads as a broken page, so say it plainly.
  const hasData = tournament.maps > 0 || ranked.length > 0;
  const placement = tournament.group_placement || tournament.playoff_placement || null;

  return (
    <>
    <CardSurface
      title={
        <span className="flex min-w-0 items-center gap-1">
          <TournamentCombobox
            tournaments={switcherTournaments}
            value={tournament.id}
            onValueChange={onSelectTournament}
            clearable={false}
            trigger={
              <Button variant="ghost" size="inline" className={HEADING_TRIGGER}>
                <span className="truncate">{tournament.name}</span>
                <ChevronDown aria-hidden className={triggerChevronClass} />
              </Button>
            }
          />
          <HoverPrefetchLink
            href={tournamentHref(tournament.id)}
            aria-label={t("users.overview.lastTournament.openTournament")}
            title={t("users.overview.lastTournament.openTournament")}
            className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-[color:var(--aqt-fg-dim)] outline-hidden transition-colors hover:bg-[hsl(0_0%_100%/0.04)] hover:text-[color:var(--aqt-teal)] focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]"
          >
            <ArrowUpRight aria-hidden className="size-4" />
          </HoverPrefetchLink>
        </span>
      }
    >
      <div className="flex flex-col gap-3.5">
        <div className="flex items-center gap-3.5">
          <DivisionIcon
            division={tournament.division}
            tournamentGrid={tournament.division_grid_version}
            discipline={tournament.discipline}
            width={52}
            height={52}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 font-onest text-title font-bold leading-none text-[color:var(--aqt-fg)]">
              <PlayerRoleIcon role={tournament.role} ontology={ontology} size={18} decorative />
              {roleLabel}
            </div>
            {hasData ? (
              <div className="aqt-tnum mt-1 text-caption text-[color:var(--aqt-fg-muted)]">
                {t("users.overview.lastTournament.placed")} <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">
                  {placement ?? "—"}
                </span>
                {" · "}
                {playtimeH > 0
                  ? t("users.overview.lastTournament.playtime", {
                      hours: String(playtimeH),
                      minutes: String(playtimeM)
                    })
                  : t("users.overview.lastTournament.playtimeNoHours", { minutes: String(playtimeM) })}
                {" · "}
                {t("users.overview.mapsCount", { count: tournament.maps })}
              </div>
            ) : null}
          </div>
          {hasData ? (
            <div className="text-right">
              <div className="aqt-display text-headline font-bold leading-none">
                <span style={{ color: "var(--aqt-emerald)" }}>{tournament.maps_won}</span>
                <span className="text-heading text-[color:var(--aqt-fg-faint)]"> {t("users.overview.win")}</span>
                <span className="mx-1.5">·</span>
                <span style={{ color: "var(--aqt-rose)" }}>{mapsLost}</span>
                <span className="text-heading text-[color:var(--aqt-fg-faint)]"> {t("users.overview.loss")}</span>
              </div>
              <div className="aqt-tnum mt-1 text-label text-[color:var(--aqt-fg-dim)]">{formatPercent(winrate)} {t("users.overview.lastTournament.mapWinrate")}</div>
            </div>
          ) : null}
        </div>
        {hasData ? null : (
          <div className="flex items-start gap-2.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-3 py-2.5">
            <Hourglass aria-hidden className="mt-0.5 size-4 shrink-0 text-[color:var(--aqt-fg-faint)]" />
            <div className="flex flex-col gap-0.5">
              <span className="text-caption font-semibold text-[color:var(--aqt-fg)]">
                {t("users.overview.lastTournament.noData")}
              </span>
              <span className="text-caption text-[color:var(--aqt-fg-muted)]">
                {t("users.overview.lastTournament.noDataHint")}
              </span>
            </div>
          </div>
        )}
        {/* Heroes played per THIS tournament is intentionally omitted: the
            UserTournamentWithStats shape carries no per-hero breakdown, so there
            is nothing real to show (design-book §5 — never fabricate data). */}
        {tournament.maps > 0 ? (
          <div className="flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3">
            <div className="flex items-center justify-between gap-2">
              <Eyebrow>{t("users.overview.lastTournament.mapResults")}</Eyebrow>
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                {t("users.overview.mapsCount", { count: tournament.maps })}
              </span>
            </div>
            <div className="flex flex-wrap gap-[3px]">
              {resultPips.map((pip, i) => (
                <ResTag
                  key={`${pip}${i}`}
                  kind={PIP_KIND[pip]}
                  title={t(PIP_TITLE_KEY[pip] as Parameters<typeof t>[0])}
                >
                  {t(PIP_LABEL_KEY[pip] as Parameters<typeof t>[0])}
                </ResTag>
              ))}
            </div>
            {mapPips && mapPips.length > 0 ? null : (
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
                {t("users.overview.lastTournament.mapResultsAggregate")}
              </span>
            )}
          </div>
        ) : null}
        {ranked.length > 0 ? (
          <div className="flex flex-col gap-4 border-t border-[color:var(--aqt-border)] pt-4">
            <div className="flex items-center justify-between gap-2">
              <Eyebrow>{t("users.overview.lastTournament.lobbyRank")}</Eyebrow>
              {lobbySize ? (
                <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                  {t("users.overview.lastTournament.players", { count: lobbySize })}
                </span>
              ) : null}
            </div>
            <ProfileWidget
              axis={tournament.workspace_id}
              discipline={tournament.discipline}
              slot="lobbyRankTiles"
              props={{ stats, onOpen: openLeaderboard }}
              fallback={<LobbyStatGrid tiles={genericTiles} onOpen={openLeaderboard} />}
            />
          </div>
        ) : null}
      </div>
    </CardSurface>
      <LobbyLeaderboardModal
        userId={userId}
        tournamentId={tournament.id}
        stat={lb?.stat ?? null}
        statLabel={lb?.label ?? ""}
        onClose={() => setLb(null)}
      />
    </>
  );
};

export default OverviewLastTournamentCard;
