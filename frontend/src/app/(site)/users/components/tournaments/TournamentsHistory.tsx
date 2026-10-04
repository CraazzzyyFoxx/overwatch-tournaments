"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EncounterWithUserStats, UserProfile, UserTournament } from "@/types/user.types";
import userService from "@/services/user.service";
import {
  type TournamentGroup,
  groupRepId,
  groupTournamentIds,
  groupTournamentsByLeague,
  isLeagueGroup
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
    // The API returns events newest-first (by start date).
    return groups.length ? groupRepId(groups[0]) : null;
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

  // Lazy dossier detail: the list endpoint never populates `encounters` (see
  // UserTournament.encounters) — fetch them per tournament id in the
  // selected group only, and merge the results in before handing the group
  // to the dossier. Mirrors LobbyLeaderboardModal's reset-on-param-change
  // pattern: a synchronous state adjustment during render, not an effect.
  const [selectionKey, setSelectionKey] = useState<number | null>(effectiveKey);
  const [encountersByTournamentId, setEncountersByTournamentId] = useState<
    Map<number, EncounterWithUserStats[]>
  >(new Map());
  const [encountersStatus, setEncountersStatus] = useState<"idle" | "loading" | "error">(
    selectedIds.length > 0 ? "loading" : "idle"
  );

  if (effectiveKey !== selectionKey) {
    setSelectionKey(effectiveKey);
    setEncountersByTournamentId(new Map());
    setEncountersStatus(selectedIds.length > 0 ? "loading" : "idle");
  }

  useEffect(() => {
    if (selectedIds.length === 0) return;
    let cancelled = false;
    Promise.all(
      selectedIds.map((id) =>
        userService.getUserTournamentEncounters(selfUserId, id).then((list) => [id, list] as const)
      )
    )
      .then((pairs) => {
        if (cancelled) return;
        setEncountersByTournamentId(new Map(pairs));
        setEncountersStatus("idle");
      })
      .catch(() => {
        if (!cancelled) setEncountersStatus("error");
      });
    return () => {
      cancelled = true;
    };
    // effectiveKey (not selectedIds) is the selection identity this fetch is
    // for; selectedIds is memoized off the same selection so it never drifts.
  }, [effectiveKey, selfUserId, selectedIds]);

  const detailedGroup: TournamentGroup | null = useMemo(() => {
    if (!selectedGroup) return null;
    const attach = (t: UserTournament): UserTournament => ({
      ...t,
      encounters: encountersByTournamentId.get(t.id) ?? []
    });
    return isLeagueGroup(selectedGroup) ? selectedGroup.map(attach) : attach(selectedGroup);
  }, [selectedGroup, encountersByTournamentId]);

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
          <TournamentDossier
            group={detailedGroup}
            selfUserId={selfUserId}
            loadingEncounters={encountersStatus === "loading"}
          />
        </div>
        {/* Desktop: the list is taken out of flow so the row height is the dossier's and the list scrolls inside it. */}
        <div className="order-1 min-[1081px]:relative min-[1081px]:order-2 min-[1081px]:min-h-[520px]">
          <TournamentList groups={groups} selectedKey={effectiveKey} onSelect={selectEvent} />
        </div>
      </div>
    </>
  );
};

export default TournamentsHistory;
