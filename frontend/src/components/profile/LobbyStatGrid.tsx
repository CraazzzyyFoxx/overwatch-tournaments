"use client";

import { useTranslations } from "next-intl";

import { ProfileStat } from "@/components/profile/atoms";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";

/** One lobby-ranked tournament stat of a player: its rank among the lobby and the displayed value. */
export interface LobbyStatTile {
  /** The stat code the lobby leaderboard reads. */
  stat: string;
  label: string;
  rank: number;
  total: number;
  value: string;
  highlight?: "good" | "bad";
}

/** Whether a ranked stat entry is drawable: a finite rank in a non-empty lobby. */
export const isRankedEntry = (entry: { rank: number; total: number } | undefined): entry is { rank: number; total: number } =>
  entry !== undefined && Number.isFinite(entry.rank) && entry.total > 0;

/** Lobby rank → "Top X%" label + a horizontal, fuller-is-better bar width.
 * (design-book §6 percentile language; rank 1 = best → full bar.) */
const percentile = (tile: LobbyStatTile) => {
  const topPct = Math.max(1, Math.round((tile.rank / tile.total) * 100));
  const barPct = tile.total > 1 ? Math.round(((tile.total - tile.rank) / (tile.total - 1)) * 100) : 100;
  return { topPct, barPct };
};

/**
 * The lobby-rank grid of a profile's tournament card: one open KPI + percentile bar per ranked stat, each opening
 * the lobby leaderboard. The generic card fills it from the game's declared stats; a game module may fill it with its
 * own selection and presentation (the `lobbyRankTiles` profile slot).
 */
export function LobbyStatGrid({
  tiles,
  onOpen
}: Readonly<{ tiles: LobbyStatTile[]; onOpen: (stat: string, label: string) => void }>) {
  const t = useTranslations();
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
      {tiles.map((tile) => {
        const p = percentile(tile);
        return (
          <RowButton
            key={tile.stat}
            onClick={() => onOpen(tile.stat, tile.label)}
            aria-label={t("users.overview.leaderboard.open", { stat: tile.label })}
            title={t("users.overview.lastTournament.percentileHint")}
            className="-m-2 w-auto rounded-lg p-2"
          >
            <ProfileStat
              size="md"
              label={tile.label}
              value={tile.value}
              sub={t("users.overview.lastTournament.rankTop", { pct: p.topPct })}
              color={
                tile.highlight === "good" ? "var(--aqt-emerald)" : tile.highlight === "bad" ? "var(--aqt-rose)" : undefined
              }
            >
              <div className="mt-1 h-[3px] w-full overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]">
                <div className="h-full rounded-full" style={{ width: `${p.barPct}%`, background: "var(--aqt-fg-muted)" }} />
              </div>
            </ProfileStat>
          </RowButton>
        );
      })}
    </div>
  );
}
