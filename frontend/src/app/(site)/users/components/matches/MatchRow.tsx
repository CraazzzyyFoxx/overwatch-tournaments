"use client";

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ResTag, ScoreCell, StagePill } from "@/app/(site)/users/components/shared/atoms";
import MvpMatchPill from "@/components/match/MvpMatchPill";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { HeroStrip } from "@/components/hero/HeroImage";
import { TooltipProvider } from "@/components/ui/tooltip";
import { EncounterWithUserStats } from "@/types/user.types";
import type { Hero } from "@/types/hero.types";

export const stageKindFor = (name: string | undefined): "group" | "playoffs" | "finals" | "default" => {
  if (!name) return "default";
  const lower = name.toLowerCase();
  if (lower.includes("final")) return "finals";
  if (lower.includes("playoff") || lower.includes("bracket")) return "playoffs";
  if (lower.includes("group") || lower.match(/^[a-h]$/i)) return "group";
  return "default";
};

export const stageLabel = (name: string | undefined): string => name?.trim() || "—";

interface MatchRowProps {
  enc: EncounterWithUserStats;
  selfUserId: number;
}

const MatchRow = ({ enc, selfUserId }: MatchRowProps) => {
  const router = useRouter();
  const isUserHome = (enc.home_team?.players ?? []).some((p) => p.user_id === selfUserId);
  const userScore = isUserHome ? enc.score.home : enc.score.away;
  const oppScore = isUserHome ? enc.score.away : enc.score.home;
  const kind = stageKindFor(enc.stage_item?.name ?? enc.stage?.name);
  const scoreKind = userScore > oppScore ? "win" : userScore < oppScore ? "loss" : "draw";
  const resKind = userScore > oppScore ? "w" : userScore < oppScore ? "l" : "d";
  const tNum = enc.tournament?.number ?? enc.tournament_id;
  const opponentName = isUserHome ? enc.away_team?.name : enc.home_team?.name;
  const userTeamName = isUserHome ? enc.home_team?.name : enc.away_team?.name;
  const heroSet = new Set<string>();
  const heroList: Pick<Hero, "name" | "image_path" | "role">[] = [];
  (enc.matches ?? []).forEach((match) => {
    // MatchWithUserStats.heroes is already the viewer's heroes for
    // this match (computed server-side from MatchStatistics).
    (match.heroes ?? []).forEach((h) => {
      if (!heroSet.has(h.name)) {
        heroSet.add(h.name);
        heroList.push({ name: h.name, image_path: h.image_path, role: h.type ?? h.role });
      }
    });
  });

  const mvpMatches = (enc.matches ?? []).filter((m) => m.performance != null);

  return (
    <tr
      onClick={() => router.push(`/encounters/${enc.id}`)}
      className="cursor-pointer border-b border-[hsl(215_20%_10%)] transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.025)]"
    >
      <td className="px-3.5 py-3">
        <Link
          href={`/tournaments/${enc.tournament_id}`}
          onClick={(e) => e.stopPropagation()}
          className="aqt-mono inline-flex items-center gap-1.5 rounded-[5px] border px-2 py-0.5 text-[10.5px] font-bold"
          style={{
            background: "hsl(174 72% 46% / 0.08)",
            borderColor: "hsl(174 72% 46% / 0.25)",
            color: "var(--aqt-teal)"
          }}
        >
          T {tNum}
        </Link>
      </td>
      <td className="px-3.5 py-3">
        <StagePill kind={kind}>{stageLabel(enc.stage_item?.name ?? enc.stage?.name)}</StagePill>
      </td>
      <td className="px-3.5 py-3">
        <span className="inline-flex items-center gap-2">
          <ResTag kind={resKind} />
          <Link
            href={`/encounters/${enc.id}`}
            onClick={(e) => e.stopPropagation()}
            className="hover:text-[color:var(--aqt-teal)]"
          >
            {userTeamName} vs {opponentName}
          </Link>
        </span>
      </td>
      <td className="px-3.5 py-3">
        <ScoreCell kind={scoreKind} value={`${userScore}-${oppScore}`} />
      </td>
      <td className="px-3.5 py-3">
        <HeroStrip heroes={heroList} size="sm" limit={4} />
      </td>
      <td className="px-3.5 py-3">
        {mvpMatches.length > 0 ? (
          <TooltipProvider delayDuration={150}>
            <span className="inline-flex items-center gap-1">
              {mvpMatches.map((m) => (
                <MvpMatchPill key={m.id} match={m} />
              ))}
            </span>
          </TooltipProvider>
        ) : (
          <span className="aqt-mono text-[color:var(--aqt-fg-faint)]">—</span>
        )}
      </td>
      <td className="aqt-mono px-3.5 py-3 text-[11px] text-[color:var(--aqt-fg-dim)]">
        {enc.closeness != null ? `${(enc.closeness * 100).toFixed(0)}%` : "—"}
      </td>
      <td className="px-3.5 py-3" onClick={(e) => e.stopPropagation()}>
        <MatchLogIndicator
          hasLogs={enc.has_logs}
          logs={
            enc.has_logs
              ? (enc.matches ?? []).map((m, i) => ({ matchId: m.id, label: m.map?.name ?? `Map ${i + 1}` }))
              : undefined
          }
        />
      </td>
    </tr>
  );
};

export default MatchRow;
