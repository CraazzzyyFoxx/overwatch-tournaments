"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { SlotProps } from "@/disciplines/types";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { availableRounds } from "./stats";
import { owMatchView, type OwTeam } from "./view";
import Scoreboard from "./Scoreboard";
import Breakdown from "./Breakdown";
import KillFeedTimeline from "./KillFeedTimeline";

type Tab = "tables" | "breakdown" | "timeline";

/** A fight by its place in the timeline: the round and its 1-based number inside the round (`readFights`). */
export interface FightRef {
  round: number;
  fight: number;
}

/** A request to bring a fight into view; `nonce` repeats a jump to the fight already focused. */
export interface FightFocus extends FightRef {
  nonce: number;
}

interface MatchStatsViewProps {
  match: MatchWithStats;
  metadata: DisciplineMetadata;
  home: OwTeam;
  away: OwTeam;
}

const MatchStatsView = ({ match, metadata, home, away }: MatchStatsViewProps) => {
  const t = useTranslations();
  const [tab, setTab] = useState<Tab>("tables");
  const [round, setRound] = useState(0);
  const [focus, setFocus] = useState<FightFocus | null>(null);

  const rounds = availableRounds(home, away).filter((value) => value > 0);
  // A round picked on one map stays meaningful only while this map has it.
  const activeRound = rounds.includes(round) ? round : 0;

  const gotoFight = (fight: FightRef) => {
    setFocus((previous) => ({ ...fight, nonce: (previous?.nonce ?? 0) + 1 }));
    setTab("timeline");
  };

  return (
    <Tabs
      value={tab}
      onValueChange={(value) => {
        setTab(value as Tab);
        // A jump is a one-off: coming back to the timeline later must not scroll to it again.
        setFocus(null);
      }}
      className="flex flex-col gap-4"
    >
      {/* The row carries the tabs' baseline so the round toggle can share it on the right; on a phone the
          toggle goes above and the tabs keep the baseline. */}
      <div className="flex flex-wrap items-end justify-between gap-x-4 border-b border-[color:var(--aqt-border)]">
        <TabsList className="shadow-none max-sm:w-full sm:w-auto">
          <TabsTrigger value="tables">{t("matches.tab.tables")}</TabsTrigger>
          <TabsTrigger value="breakdown">{t("matches.tab.breakdown")}</TabsTrigger>
          <TabsTrigger value="timeline">{t("matches.tab.timeline")}</TabsTrigger>
        </TabsList>
        {/* One round is the whole map: a choice between them only exists from two. */}
        {rounds.length > 1 ? (
          <div className="flex items-center gap-2 py-1.5 max-sm:order-first">
            <Eyebrow>{t("matches.roundLabel")}</Eyebrow>
            <ToggleGroup
              value={String(activeRound)}
              onValueChange={(value) => value && setRound(Number(value))}
              variant="pill"
              size="sm"
              aria-label={t("matches.roundLabel")}
            >
              <ToggleGroupItem value="0">{t("matches.allMatch")}</ToggleGroupItem>
              {rounds.map((value) => (
                <ToggleGroupItem key={value} value={String(value)} aria-label={t("matches.round", { round: value })}>
                  {t("matches.roundShort", { round: value })}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        ) : null}
      </div>

      <TabsContent value="tables">
        <Scoreboard home={home} away={away} round={activeRound} metadata={metadata} />
      </TabsContent>
      <TabsContent value="breakdown">
        <Breakdown
          match={match}
          home={home}
          away={away}
          round={activeRound}
          metadata={metadata}
          onGotoFight={gotoFight}
        />
      </TabsContent>
      <TabsContent value="timeline">
        <KillFeedTimeline
          matchId={match.id}
          members={match.statistics.members}
          home={home}
          away={away}
          round={activeRound}
          focus={focus}
        />
      </TabsContent>
    </Tabs>
  );
};

/**
 * The Overwatch scoreboard of a duel: the per-player table, the breakdown (team totals, player of the map, map
 * flow, lineups, role duels, shares) and the kill timeline, all read for the whole map or one round. The host renders
 * it only for a match with exactly two participants.
 */
export default function MatchStats({ match, metadata }: Readonly<SlotProps["matchStats"]>) {
  const view = owMatchView(match);
  if (!view) return null;
  return <MatchStatsView match={match} metadata={metadata} home={view.home} away={view.away} />;
}
