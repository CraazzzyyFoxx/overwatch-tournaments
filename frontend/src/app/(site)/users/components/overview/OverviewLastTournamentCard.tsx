"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight, Hourglass } from "lucide-react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { UserTournamentWithStats, UserTournamentSummary } from "@/types/user.types";
import { type MapResultPip } from "@/app/(site)/users/components/overview/map-results";
import { UserTournamentStat } from "@/types/statistics.types";
import { CardSurface, ProfileStat } from "@/app/(site)/users/components/shared/atoms";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { normalizePlayerRole, PLAYER_ROLE_LABEL_KEY, playerRoleTint } from "@/lib/roster/player-role";
import { tournamentHref } from "@/lib/tournament/url";
import { TournamentCombobox } from "@/app/(site)/users/components/shared/TournamentCombobox";
import LobbyLeaderboardModal from "@/app/(site)/users/components/overview/LobbyLeaderboardModal";

interface Props {
  tournament: UserTournamentWithStats;
  tournaments: UserTournamentSummary[];
  /** Profile owner's user id — the row highlighted in the lobby leaderboard. */
  userId: number;
  mapPips?: MapResultPip[] | null;
}

const compactNumber = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return value.toFixed(2);
};

const formatPercent = (value: number | null | undefined, digits = 0) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
};

// Role → its `--aqt-*` hue. Flex is a real roster role, so it gets its own
// token instead of falling through to damage.
const roleColor = (role: string) => `var(--aqt-${playerRoleTint(role) ?? "damage"})`;

// The card title IS the tournament switcher: heading type, no box. Focus is
// shown by colour + underline because the title row clips outside rings.
const HEADING_TRIGGER =
  "h-auto w-auto min-w-0 max-w-full justify-start gap-1.5 rounded-sm border-0 bg-transparent p-0 font-semibold text-[length:inherit] text-[color:var(--aqt-fg)] shadow-none hover:bg-transparent hover:text-[color:var(--aqt-teal)] focus-visible:ring-0 focus-visible:text-[color:var(--aqt-teal)] focus-visible:underline focus-visible:underline-offset-2 data-[state=open]:text-[color:var(--aqt-teal)]";

// Map result → the same `.aqt-form-chip` the header's form streak uses, with
// its always-present letter/title (design-book: never colour alone).
const PIP_CHIP: Record<MapResultPip, string> = {
  win: "aqt-form-chip w",
  loss: "aqt-form-chip l",
  draw: "aqt-form-chip d"
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

interface StatEntry {
  rank: number;
  total: number;
}

/** Lobby rank → "Top X%" label + a horizontal, fuller-is-better bar width.
 * (design-book §6 percentile language; rank 1 = best → full bar.) */
const percentile = (entry: StatEntry) => {
  const topPct = Math.max(1, Math.round((entry.rank / entry.total) * 100));
  const barPct = entry.total > 1 ? Math.round(((entry.total - entry.rank) / (entry.total - 1)) * 100) : 100;
  return { topPct, barPct };
};

/** One lobby-ranked stat: open KPI + percentile bar, opening the leaderboard. */
const LobbyStat = ({
  label,
  value,
  topLabel,
  barPct,
  highlight,
  onOpen,
  openLabel,
  hint
}: {
  label: string;
  value: string;
  topLabel: string;
  barPct: number;
  highlight?: "good" | "bad";
  onOpen: () => void;
  openLabel: string;
  hint: string;
}) => (
  <button
    type="button"
    onClick={onOpen}
    aria-label={openLabel}
    title={hint}
    className="-m-2 cursor-pointer rounded-lg p-2 text-left transition-colors hover:bg-[hsl(0_0%_100%/0.03)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
  >
    <ProfileStat
      size="md"
      label={label}
      value={value}
      sub={topLabel}
      color={highlight === "good" ? "var(--aqt-emerald)" : highlight === "bad" ? "var(--aqt-rose)" : undefined}
    >
      <div className="mt-1 h-[3px] w-full overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]">
        <div className="h-full rounded-full" style={{ width: `${barPct}%`, background: "var(--aqt-fg-muted)" }} />
      </div>
    </ProfileStat>
  </button>
);

const OverviewLastTournamentCard = ({ tournament, tournaments, userId, mapPips }: Props) => {
  const t = useTranslations();
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

  // `stats` is a partial map keyed by backend LogStatsName — only the ranked
  // tournament stats the backend computes are present. Access by string key and
  // guard each entry so a missing / degenerate rank never renders a tile.
  const s = tournament.stats as Record<string, UserTournamentStat | undefined>;
  type Tile = {
    key: string;
    /** Backend LogStatsName value the leaderboard modal fetches. */
    statName: string;
    label: string;
    entry: StatEntry;
    value: string;
    highlight?: "good" | "bad";
  };
  // Render order (design-book §3). Every key here is a ranked tournament stat
  // the backend emits (`tournament_stats`) and the lobby leaderboard accepts.
  const STAT_ORDER: { key: string; labelKey: string }[] = [
    { key: "kda", labelKey: "users.overview.lastTournament.stat.kda" },
    { key: "performance", labelKey: "users.overview.lastTournament.stat.mvpScore" },
    { key: "hero_damage_dealt", labelKey: "users.overview.lastTournament.stat.dmgPerMap" },
    { key: "eliminations", labelKey: "users.overview.lastTournament.stat.elims" },
    { key: "deaths", labelKey: "users.overview.lastTournament.stat.deaths" },
    { key: "assists", labelKey: "users.overview.lastTournament.stat.assists" },
    { key: "kd", labelKey: "users.overview.lastTournament.stat.kd" },
    { key: "damage_delta", labelKey: "users.overview.lastTournament.stat.dmgDelta" }
  ];
  const statTiles: Tile[] = [];
  for (const def of STAT_ORDER) {
    const entry = s?.[def.key];
    if (!entry || !Number.isFinite(entry.rank) || entry.total <= 0) continue;
    const isDelta = def.key === "damage_delta";
    // A negative delta already shows its sign; a positive one needs the `+` to
    // read as a delta rather than a plain count.
    const formatted = compactNumber(entry.value);
    statTiles.push({
      key: def.key,
      statName: def.key,
      label: t(def.labelKey as Parameters<typeof t>[0]),
      entry: { rank: entry.rank, total: entry.total },
      value: isDelta && entry.value >= 0 ? `+${formatted}` : formatted,
      highlight: isDelta ? (entry.value >= 0 ? "good" : "bad") : undefined
    });
  }
  const lobbySize = statTiles[0]?.entry.total ?? null;
  // A tournament the player is entered in but that has no recorded maps yet
  // (not played, or results not uploaded) comes back as all zeros. Printing
  // "Placed 0 · 0 maps · 0W · 0L" reads as a broken page, so say it plainly.
  const hasData = tournament.maps > 0 || statTiles.length > 0;
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
            ariaLabel={tournament.name}
            triggerClassName={HEADING_TRIGGER}
          />
          <HoverPrefetchLink
            href={tournamentHref(tournament.id)}
            aria-label={t("users.overview.lastTournament.openTournament")}
            title={t("users.overview.lastTournament.openTournament")}
            className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-[color:var(--aqt-fg-dim)] outline-none transition-colors hover:bg-[hsl(0_0%_100%/0.04)] hover:text-[color:var(--aqt-teal)] focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-[color:var(--aqt-teal)]"
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
            width={52}
            height={52}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 font-onest text-[20px] font-bold leading-none text-[color:var(--aqt-fg)]">
              <PlayerRoleIcon role={tournament.role} size={18} color={roleColor(tournament.role)} decorative />
              {t(PLAYER_ROLE_LABEL_KEY[normalizePlayerRole(tournament.role)] as Parameters<typeof t>[0])}
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
              <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                {t("users.overview.lastTournament.mapResults")}
              </span>
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                {t("users.overview.mapsCount", { count: tournament.maps })}
              </span>
            </div>
            <div className="flex flex-wrap gap-[3px]">
              {resultPips.map((pip, i) => (
                <span
                  key={`${pip}${i}`}
                  className={PIP_CHIP[pip]}
                  title={t(PIP_TITLE_KEY[pip] as Parameters<typeof t>[0])}
                >
                  {t(PIP_LABEL_KEY[pip] as Parameters<typeof t>[0])}
                </span>
              ))}
            </div>
            {mapPips && mapPips.length > 0 ? null : (
              <span className="aqt-tnum text-label text-[color:var(--aqt-fg-faint)]">
                {t("users.overview.lastTournament.mapResultsAggregate")}
              </span>
            )}
          </div>
        ) : null}
        {statTiles.length > 0 ? (
          <div className="flex flex-col gap-4 border-t border-[color:var(--aqt-border)] pt-4">
            <div className="flex items-center justify-between gap-2">
              <span className="text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                {t("users.overview.lastTournament.lobbyRank")}
              </span>
              {lobbySize ? (
                <span className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                  {t("users.overview.lastTournament.players", { count: lobbySize })}
                </span>
              ) : null}
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
              {statTiles.map((tile) => {
                const p = percentile(tile.entry);
                return (
                  <LobbyStat
                    key={tile.key}
                    label={tile.label}
                    value={tile.value}
                    topLabel={t("users.overview.lastTournament.rankTop", { pct: p.topPct })}
                    barPct={p.barPct}
                    highlight={tile.highlight}
                    onOpen={() => setLb({ stat: tile.statName, label: tile.label })}
                    openLabel={t("users.overview.leaderboard.open", { stat: tile.label })}
                    hint={t("users.overview.lastTournament.percentileHint")}
                  />
                );
              })}
            </div>
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
