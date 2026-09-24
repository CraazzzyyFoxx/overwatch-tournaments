"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { EncounterWithUserStats } from "@/types/user.types";
import type { Hero } from "@/types/hero.types";
import { HeroStrip } from "@/components/hero/HeroImage";
import { type ScoreKind } from "@/components/match/cells";
import MvpMatchPill from "@/components/match/MvpMatchPill";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { TooltipProvider } from "@/components/ui/tooltip";

// ─── Encounter row (expanded matches table) ─────────────────────────────────────

const scoreAccent: Record<ScoreKind, string> = {
  win: "var(--aqt-emerald)",
  loss: "var(--aqt-rose)",
  draw: "var(--aqt-amber)"
};

const EncounterRow = ({
  enc,
  selfUserId,
  teamId
}: {
  enc: EncounterWithUserStats;
  selfUserId: number;
  teamId: number;
}) => {
  const t = useTranslations();
  const isUserHome =
    enc.home_team_id === teamId || (enc.home_team?.players ?? []).some((p) => p.user_id === selfUserId);

  const userScore = isUserHome ? enc.score.home : enc.score.away;
  const oppScore = isUserHome ? enc.score.away : enc.score.home;
  const scoreKind: ScoreKind = userScore > oppScore ? "win" : userScore < oppScore ? "loss" : "draw";

  const opponent = isUserHome ? enc.away_team?.name : enc.home_team?.name;

  // Per-map result pips (from the user's team perspective).
  const mapPips: ScoreKind[] = (enc.matches ?? []).map((m) => {
    const userMapScore = isUserHome ? m.score.home : m.score.away;
    const oppMapScore = isUserHome ? m.score.away : m.score.home;
    return userMapScore > oppMapScore ? "win" : userMapScore < oppMapScore ? "loss" : "draw";
  });
  const mapsWon = mapPips.filter((k) => k === "win").length;
  const mapsLost = mapPips.filter((k) => k === "loss").length;

  // Unique heroes across all maps in the encounter.
  const heroes: Hero[] = [];
  const seen = new Set<string>();
  for (const m of enc.matches ?? []) {
    for (const h of m.heroes ?? []) {
      const key = h.image_path || h.name;
      if (key && !seen.has(key)) {
        seen.add(key);
        heroes.push(h);
      }
    }
  }

  const stageLabel = enc.stage_item?.name ?? enc.stage?.name ?? enc.name ?? "—";

  return (
    <HoverPrefetchLink
      href={`/encounters/${enc.id}`}
      className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-2.5 text-ui transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.025)] md:grid-cols-[1fr_auto_auto_auto_auto_auto_auto]"
      style={{ boxShadow: `inset 3px 0 0 0 ${scoreAccent[scoreKind]}` }}
    >
      {/* Stage + opponent */}
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate font-medium text-[color:var(--aqt-fg)]">{opponent ?? enc.name}</span>
        <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-dim)]">{stageLabel}</span>
      </div>

      {/* Heroes */}
      <div className="hidden items-center md:flex">
        <HeroStrip heroes={heroes} size="sm" limit={6} />
      </div>

      {/* MVP pills (per map) — hover shows the map it was earned on */}
      <div className="hidden items-center gap-1 md:flex">
        <TooltipProvider delayDuration={150}>
          {(enc.matches ?? []).map((m) => (
            <MvpMatchPill key={m.id} match={m} />
          ))}
        </TooltipProvider>
      </div>

      {/* Closeness */}
      {enc.closeness != null ? (
        <span className="aqt-tnum hidden text-caption text-[color:var(--aqt-fg-dim)] md:block">
          {(enc.closeness * 100).toFixed(0)}%
        </span>
      ) : (
        <span className="hidden md:block" />
      )}

      {/* Per-map result pips */}
      {mapPips.length > 0 ? (
        <div
          className="hidden items-center gap-1 md:flex"
          aria-label={t("users.tournaments.dossier.mapResults", { won: mapsWon, lost: mapsLost })}
        >
          {mapPips.map((kind, i) => (
            <span
              key={i}
              className="h-1.5 w-1.5 rounded-[2px]"
              style={{ background: scoreAccent[kind] }}
              aria-hidden="true"
            />
          ))}
        </div>
      ) : (
        <span className="hidden md:block" />
      )}

      {/* Score */}
      <span
        className={cn(
          "aqt-tnum min-w-[52px] text-right text-base font-bold",
          scoreKind === "win" && "text-[color:var(--aqt-emerald)]",
          scoreKind === "loss" && "text-[color:var(--aqt-rose)]",
          scoreKind === "draw" && "text-[color:var(--aqt-amber)]"
        )}
      >
        {userScore} – {oppScore}
      </span>

      {/* Logs — click shield, not a control: the whole row is one link, so a
          click on the log badge must not navigate. No keyboard twin by design:
          this only catches clicks on the indicator's non-focusable `<span>`
          variants; its focusable ones stop propagation themselves. */}
      <div
        role="presentation"
        className="hidden justify-end md:flex"
        onClick={(e) => e.preventDefault()}
      >
        <MatchLogIndicator
          hasLogs={enc.has_logs}
          logs={
            enc.has_logs
              ? (enc.matches ?? []).map((m, i) => ({
                  matchId: m.id,
                  label: m.map?.name ?? t("users.tournaments.mapNumber", { n: String(i + 1) })
                }))
              : undefined
          }
        />
      </div>
    </HoverPrefetchLink>
  );
};

export default EncounterRow;
