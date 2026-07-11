"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import userService from "@/services/user.service";
import type { LobbyLeaderboard } from "@/types/user.types";

// Stats where a lower value is better (rank 1 = lowest). Mirrors the backend's
// `is_ascending_stat`, restricted to the stats the tiles can open.
const INVERSE_STATS = new Set(["deaths", "performance"]);

interface Props {
  userId: number;
  tournamentId: number;
  /** Backend LogStatsName value, e.g. "kda" / "performance". Null = closed. */
  stat: string | null;
  statLabel: string;
  onClose: () => void;
}

const medalColor = (rank: number): string | undefined => {
  if (rank === 1) return "var(--aqt-gold)";
  if (rank === 2) return "var(--aqt-silver)";
  if (rank === 3) return "var(--aqt-bronze)";
  return undefined;
};

const fmtValue = (v: number): string => {
  if (!Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return v.toFixed(2);
};

const LobbyLeaderboardModal = ({ userId, tournamentId, stat, statLabel, onClose }: Props) => {
  const t = useTranslations();
  const [data, setData] = useState<LobbyLeaderboard | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [reqStat, setReqStat] = useState<string | null>(null);

  // Reset synchronously when the requested stat changes — a render-time state
  // adjustment (not an effect body), so we never call setState inside useEffect.
  if (stat !== reqStat) {
    setReqStat(stat);
    setData(null);
    setState(stat ? "loading" : "idle");
  }

  useEffect(() => {
    if (!stat) return;
    let cancelled = false;
    userService
      .getTournamentLeaderboard(userId, tournamentId, stat)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setState("idle");
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [stat, userId, tournamentId]);

  const isInverse = stat != null && INVERSE_STATS.has(stat);
  const entries = data?.entries ?? [];
  const leaderVal = entries.find((e) => e.rank === 1)?.value ?? entries[0]?.value ?? 0;
  const viewer = entries.find((e) => e.player_id === userId) ?? null;

  const barPct = (value: number): number => {
    if (!leaderVal || !value) return 0;
    const p = isInverse ? leaderVal / value : value / leaderVal;
    return Math.max(0, Math.min(100, p * 100));
  };

  return (
    <Dialog open={stat != null} onOpenChange={(o) => (!o ? onClose() : undefined)}>
      <DialogContent className="max-w-[620px] border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)]">
        <DialogHeader>
          <DialogTitle className="font-onest text-[color:var(--aqt-fg)]">{statLabel}</DialogTitle>
          <DialogDescription className="aqt-mono text-[color:var(--aqt-fg-muted)]">
            {data ? t("users.overview.lastTournament.players", { count: data.total_players }) : null}
            {data ? ` · ${t("users.overview.leaderboard.vsLeader")}` : null}
            {isInverse ? ` · ${t("users.overview.leaderboard.lowerIsBetter")}` : null}
          </DialogDescription>
        </DialogHeader>

        {viewer ? (
          <div className="aqt-mono rounded-[8px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-3 py-2 text-[12px] text-[color:var(--aqt-fg-muted)]">
            {t("users.overview.leaderboard.yourRank", {
              rank: viewer.rank,
              total: data?.total_players ?? entries.length,
              pct: Math.max(1, Math.round((viewer.rank / (data?.total_players ?? entries.length)) * 100))
            })}
          </div>
        ) : null}

        {state === "loading" ? (
          <div className="flex flex-col gap-1.5 py-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <span key={i} className="h-8 w-full animate-pulse rounded bg-[color:var(--aqt-card-2)]" />
            ))}
          </div>
        ) : state === "error" ? (
          <p className="py-6 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">{t("common.loadError")}</p>
        ) : entries.length === 0 ? (
          <p className="py-6 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">{t("common.noData")}</p>
        ) : (
          <div className="max-h-[60vh] overflow-y-auto">
            <table className="w-full border-collapse text-[13px]">
              <tbody>
                {entries.map((e) => {
                  const isYou = e.player_id === userId;
                  return (
                    <tr
                      key={e.player_id}
                      className="border-b border-[color:var(--aqt-border)] last:border-b-0"
                      style={isYou ? { background: "color-mix(in srgb, var(--aqt-teal) 12%, transparent)" } : undefined}
                    >
                      <td className="aqt-mono px-3 py-2 text-right align-middle" style={{ width: 40 }}>
                        <span className="font-bold" style={{ color: medalColor(e.rank) ?? "var(--aqt-fg-faint)" }}>
                          {e.rank}
                        </span>
                      </td>
                      <td className="px-3 py-2 align-middle">
                        <Link
                          href={`/users/${e.name.replace("#", "-")}`}
                          className="font-semibold text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-teal)]"
                        >
                          {e.name}
                        </Link>
                        {isYou ? (
                          <span className="aqt-mono ml-2 text-[10px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-teal)]">
                            {t("users.overview.leaderboard.you")}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 align-middle" style={{ width: 160 }}>
                        <div className="flex items-center gap-2">
                          <span className="h-[5px] flex-1 overflow-hidden rounded-full bg-[color:var(--aqt-card-2)]">
                            <span
                              className="block h-full rounded-full"
                              style={{
                                width: `${barPct(e.value)}%`,
                                background: "linear-gradient(90deg, var(--aqt-teal-deep), var(--aqt-teal))"
                              }}
                            />
                          </span>
                          <span className="aqt-mono w-14 text-right font-bold text-[color:var(--aqt-fg)]">
                            {fmtValue(e.value)}
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default LobbyLeaderboardModal;
