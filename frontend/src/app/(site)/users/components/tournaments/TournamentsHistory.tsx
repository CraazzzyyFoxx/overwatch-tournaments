"use client";

import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { UserProfile, UserTournament } from "@/types/user.types";
import {
  type TournamentGroup,
  groupMaxNumber,
  groupRepId,
  groupTournamentIds,
  groupTournamentsByLeague
} from "@/app/(site)/users/components/tournaments/tournaments-history.helpers";
import TournamentsKpiStrip from "@/app/(site)/users/components/tournaments/TournamentsKpiStrip";
import TournamentsPlacementTimeline from "@/app/(site)/users/components/tournaments/TournamentsPlacementTimeline";
import TournamentList from "@/app/(site)/users/components/tournaments/TournamentList";
import TournamentDossier from "@/app/(site)/users/components/tournaments/TournamentDossier";

interface Props {
  tournaments: UserTournament[];
  selfUserId: number;
  /** Career totals for the KPI strip; optional so the tab still renders without it. */
  profile?: UserProfile | null;
}

/** Rep-id of the most-recent event group (greatest tournament number). */
const mostRecentKey = (groups: TournamentGroup[]): number | null => {
  let best: number | null = null;
  let bestNumber = -Infinity;
  for (const group of groups) {
    const number = groupMaxNumber(group);
    if (number > bestNumber) {
      bestNumber = number;
      best = groupRepId(group);
    }
  }
  return best;
};

const TournamentsHistory = ({ tournaments, selfUserId, profile = null }: Props) => {
  const searchParams = useSearchParams();
  const dossierRef = useRef<HTMLDivElement>(null);

  const groups = useMemo(() => groupTournamentsByLeague(tournaments), [tournaments]);

  // Default selection: the deep-linked event (?selectedTournamentId=) if it maps
  // to a group, otherwise the most-recent event.
  const initialKey = useMemo(() => {
    const raw = searchParams?.get("selectedTournamentId");
    const id = raw ? Number(raw) : NaN;
    if (Number.isFinite(id)) {
      const match = groups.find((group) => groupTournamentIds(group).includes(id));
      if (match) return groupRepId(match);
    }
    return mostRecentKey(groups);
    // Deep-link is read from the initial searchParams snapshot; selection is
    // client state thereafter (URL is kept in sync via replaceState on select).
  }, [groups, searchParams]);

  const [selectedKey, setSelectedKey] = useState<number | null>(initialKey);

  // Reconcile at render time (no effect) if the selection no longer maps to a
  // group — e.g. the tournaments prop changed.
  const validKeys = useMemo(() => groups.map(groupRepId), [groups]);
  const effectiveKey = selectedKey != null && validKeys.includes(selectedKey) ? selectedKey : initialKey;

  const selectedGroup = useMemo(
    () => groups.find((group) => groupRepId(group) === effectiveKey) ?? null,
    [groups, effectiveKey]
  );
  const selectedIds = useMemo(() => (selectedGroup ? groupTournamentIds(selectedGroup) : []), [selectedGroup]);

  const syncUrl = (id: number) => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    url.searchParams.set("selectedTournamentId", String(id));
    window.history.replaceState(null, "", url.toString());
  };

  const scrollToDossier = () => {
    const el = dossierRef.current;
    if (!el || typeof window === "undefined") return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  };

  const selectEvent = (tournamentId: number) => {
    const match = groups.find((group) => groupTournamentIds(group).includes(tournamentId));
    if (!match) return;
    const key = groupRepId(match);
    setSelectedKey(key);
    syncUrl(key);
    scrollToDossier();
  };

  return (
    <>
      <TournamentsKpiStrip profile={profile} tournaments={tournaments} />
      <TournamentsPlacementTimeline tournaments={tournaments} selectedIds={selectedIds} onSelect={selectEvent} />
      <div className="grid grid-cols-1 gap-3.5 min-[1081px]:grid-cols-[minmax(0,1fr)_404px]">
        <div ref={dossierRef} className="order-2 min-w-0 scroll-mt-4 min-[1081px]:order-1">
          <TournamentDossier group={selectedGroup} selfUserId={selfUserId} />
        </div>
        <div className="order-1 min-[1081px]:order-2">
          <TournamentList groups={groups} selectedKey={effectiveKey} onSelect={selectEvent} />
        </div>
      </div>
    </>
  );
};

export default TournamentsHistory;
