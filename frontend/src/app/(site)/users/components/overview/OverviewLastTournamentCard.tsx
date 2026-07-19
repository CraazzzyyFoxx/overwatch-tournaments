"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { Trophy } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { UserTournamentWithStats, UserTournamentSummary } from "@/types/user.types";
import { UserTournamentStat } from "@/types/statistics.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import LobbyLeaderboardModal from "@/app/(site)/users/components/overview/LobbyLeaderboardModal";

interface Props {
  tournament: UserTournamentWithStats;
  tournaments: UserTournamentSummary[];
  /** Profile owner's user id — the row highlighted in the lobby leaderboard. */
  userId: number;
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

const roleColor = (role: string) => {
  if (role === "Tank") return "var(--aqt-tank)";
  if (role === "Support") return "var(--aqt-support)";
  return "var(--aqt-damage)";
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

const PercentileTile = ({
  label,
  value,
  topLabel,
  barPct,
  highlight,
  onOpen,
  openLabel
}: {
  label: string;
  value: string;
  topLabel?: string | null;
  barPct?: number | null;
  highlight?: "good" | "bad";
  /** When set, the tile becomes a button that opens the lobby leaderboard. */
  onOpen?: () => void;
  openLabel?: string;
}) => {
  const inner = (
    <>
      <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">{label}</div>
      <div
        className="aqt-display aqt-tnum text-[22px] font-bold leading-[1.05]"
        style={{ color: highlight === "good" ? "var(--aqt-emerald)" : highlight === "bad" ? "var(--aqt-rose)" : "var(--aqt-fg)" }}
      >
        {value}
      </div>
      {topLabel ? <div className="aqt-mono text-[11.5px] text-[color:var(--aqt-fg-muted)]">{topLabel}</div> : null}
      {barPct != null ? (
        <div className="mt-0.5 h-[5px] w-full overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]">
          <div
            className="h-full rounded-full"
            style={{ width: `${barPct}%`, background: "linear-gradient(90deg, var(--aqt-teal-deep), var(--aqt-teal))" }}
          />
        </div>
      ) : null}
    </>
  );
  const base = "flex flex-col gap-1.5 rounded-[8px] border border-[color:var(--aqt-border)] px-3 py-2.5 text-left";
  if (!onOpen) return <div className={base}>{inner}</div>;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={openLabel}
      className={`${base} cursor-pointer transition-colors hover:border-[color:var(--aqt-teal)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]`}
    >
      {inner}
    </button>
  );
};

const OverviewLastTournamentCard = ({ tournament, tournaments, userId }: Props) => {
  const t = useTranslations();
  const [lb, setLb] = useState<{ stat: string; label: string } | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const playtimeH = Math.floor(tournament.playtime / 3600);
  const playtimeM = Math.floor((tournament.playtime % 3600) / 60);
  const mapsLost = tournament.maps - tournament.maps_won;
  const winrate = tournament.maps > 0 ? tournament.maps_won / tournament.maps : null;

  const onSelectTournament = (value: string) => {
    const nextSearchParams = new URLSearchParams(searchParams || undefined);
    nextSearchParams.set("tournamentId", value);
    router.push(`${pathname}?${nextSearchParams.toString()}`);
  };

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
    statTiles.push({
      key: def.key,
      statName: def.key,
      label: t(def.labelKey as Parameters<typeof t>[0]),
      entry: { rank: entry.rank, total: entry.total },
      value: isDelta
        ? entry.value >= 0
          ? `+${compactNumber(entry.value)}`
          : compactNumber(entry.value)
        : compactNumber(entry.value),
      highlight: isDelta ? (entry.value >= 0 ? "good" : "bad") : undefined
    });
  }
  const lobbySize = statTiles[0]?.entry.total ?? null;

  return (
    <>
    <CardSurface
      title={
        <Link href={`/tournaments/${tournament.id}`} className="hover:text-[color:var(--aqt-teal)]">
          {tournament.name}
        </Link>
      }
      icon={<Trophy size={15} />}
      action={
        tournaments.length > 0 ? (
          <Select value={String(tournament.id)} onValueChange={onSelectTournament}>
            <SelectTrigger className="h-7 w-44 border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[12.5px]">
              <SelectValue placeholder={t("users.overview.lastTournament.selectTournament")} />
            </SelectTrigger>
            <SelectContent className="liquid-glass-panel max-h-[min(var(--radix-select-content-available-height),20rem)]">
              <SelectGroup>
                {tournaments.map((tour) => (
                  <SelectItem key={tour.id} value={String(tour.id)} className="text-[13px]">
                    {tour.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        ) : null
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
            <div
              className="aqt-display flex items-center gap-1.5 text-[20px] font-bold uppercase leading-none"
              style={{ color: roleColor(tournament.role) }}
            >
              <PlayerRoleIcon role={tournament.role} size={18} color={roleColor(tournament.role)} />
              {tournament.role}
            </div>
            <div className="aqt-mono mt-1 text-[13px] text-[color:var(--aqt-fg-muted)]">
              {t("users.overview.lastTournament.placed")} <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">
                {tournament.group_placement ?? tournament.playoff_placement ?? "—"}
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
          </div>
          <div className="text-right">
            <div className="aqt-display text-[28px] font-bold leading-none">
              <span style={{ color: "var(--aqt-emerald)" }}>{tournament.maps_won}</span>
              <span className="text-[18px] text-[color:var(--aqt-fg-faint)]"> {t("users.overview.win")}</span>
              <span className="mx-1.5">·</span>
              <span style={{ color: "var(--aqt-rose)" }}>{mapsLost}</span>
              <span className="text-[18px] text-[color:var(--aqt-fg-faint)]"> {t("users.overview.loss")}</span>
            </div>
            <div className="aqt-mono mt-1 text-[12px] text-[color:var(--aqt-fg-dim)]">{formatPercent(winrate)} {t("users.overview.lastTournament.mapWinrate")}</div>
          </div>
        </div>
        {/* Heroes played per THIS tournament is intentionally omitted: the
            UserTournamentWithStats shape carries no per-hero breakdown, so there
            is nothing real to show (design-book §5 — never fabricate data). */}
        {tournament.maps > 0 ? (
          <div className="flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
                {t("users.overview.lastTournament.mapResults")}
              </span>
              <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">
                {t("users.overview.mapsCount", { count: tournament.maps })}
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Array.from({ length: tournament.maps_won }).map((_, i) => (
                <span
                  key={`w${i}`}
                  className="aqt-display inline-flex h-[20px] w-[20px] items-center justify-center rounded-[4px] text-[11px] font-bold"
                  style={{
                    color: "var(--aqt-emerald)",
                    background: "hsl(150 57% 52% / 0.14)",
                    border: "1px solid hsl(150 57% 52% / 0.35)"
                  }}
                  title={t("users.overview.lastTournament.mapWon")}
                >
                  {t("users.overview.win")}
                </span>
              ))}
              {Array.from({ length: Math.max(0, mapsLost) }).map((_, i) => (
                <span
                  key={`l${i}`}
                  className="aqt-display inline-flex h-[20px] w-[20px] items-center justify-center rounded-[4px] text-[11px] font-bold"
                  style={{
                    color: "var(--aqt-rose)",
                    background: "hsl(349 84% 63% / 0.14)",
                    border: "1px solid hsl(349 84% 63% / 0.35)"
                  }}
                  title={t("users.overview.lastTournament.mapLost")}
                >
                  {t("users.overview.loss")}
                </span>
              ))}
            </div>
            <span className="aqt-mono text-[10.5px] text-[color:var(--aqt-fg-faint)]">
              {t("users.overview.lastTournament.mapResultsAggregate")}
            </span>
          </div>
        ) : null}
        {statTiles.length > 0 ? (
          <div className="flex flex-col gap-2.5 border-t border-[color:var(--aqt-border)] pt-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
                {t("users.overview.lastTournament.lobbyRank")}
              </span>
              {lobbySize ? (
                <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">
                  {t("users.overview.lastTournament.players", { count: lobbySize })}
                </span>
              ) : null}
            </div>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              {statTiles.map((tile) => {
                const p = percentile(tile.entry);
                return (
                  <PercentileTile
                    key={tile.key}
                    label={tile.label}
                    value={tile.value}
                    topLabel={t("users.overview.lastTournament.rankTop", { pct: p.topPct })}
                    barPct={p.barPct}
                    highlight={tile.highlight}
                    onOpen={() => setLb({ stat: tile.statName, label: tile.label })}
                    openLabel={t("users.overview.leaderboard.open", { stat: tile.label })}
                  />
                );
              })}
            </div>
            <span className="aqt-mono text-[10.5px] text-[color:var(--aqt-fg-faint)]">
              {t("users.overview.lastTournament.percentileHint")}
            </span>
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
