"use client";

import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQueries } from "@tanstack/react-query";
import type { UserTournamentEntry, UserTournamentList } from "@/types/user.types";
import userService from "@/services/user.service";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { userQueryKeys } from "@/lib/users/query-keys";
import TournamentsPlacementTimeline from "@/app/(site)/users/components/tournaments/TournamentsPlacementTimeline";
import TournamentList from "@/app/(site)/users/components/tournaments/TournamentList";
import TournamentDossier from "@/app/(site)/users/components/tournaments/TournamentDossier";

interface Props {
  tournaments: UserTournamentList;
  selfUserId: number;
  /** The career Titles figure of the KPI strip. */
  tournamentsWon: number;
  /** "All games": rows mark their game. */
  showGames?: boolean;
}

const TournamentsHistory = ({ tournaments, selfUserId, tournamentsWon, showGames = false }: Props) => {
  const searchParams = useSearchParams();
  const dossierRef = useRef<HTMLDivElement>(null);
  const reduceMotion = usePrefersReducedMotion();

  const events = tournaments.results;

  // Default selection: the deep-linked event (?selectedTournamentId=) if it is in the list, otherwise the
  // most-recent event.
  const initialId = useMemo(() => {
    const raw = searchParams?.get("selectedTournamentId");
    const id = raw ? Number(raw) : NaN;
    if (Number.isFinite(id) && events.some((t) => t.id === id)) return id;
    // The API returns events newest-first (by start date).
    return events.length ? events[0].id : null;
    // Deep-link is read from the initial searchParams snapshot; selection is
    // client state thereafter (URL is kept in sync via replaceState on select).
  }, [events, searchParams]);

  const [selectedId, setSelectedId] = useState<number | null>(initialId);

  // Reconcile at render time (no effect) if the selection is no longer in the list — e.g. the tournaments prop
  // changed.
  const effectiveId = selectedId != null && events.some((t) => t.id === selectedId) ? selectedId : initialId;
  const selected = useMemo(() => events.find((t) => t.id === effectiveId) ?? null, [events, effectiveId]);

  // Lazy dossier detail: the list endpoint never carries encounters — read them for the selected tournament only,
  // cached per tournament so re-selecting an event reads nothing, and merge them in (with its grid from the list)
  // before handing it to the dossier. A failed read leaves the run empty, without a toast.
  const [encounters] = useQueries({
    queries: (selected ? [selected] : []).map((t) => ({
      queryKey: userQueryKeys.tournamentEncounters(selfUserId, t.workspace_id, t.discipline, t.id),
      queryFn: () => userService.getUserTournamentEncounters(selfUserId, t.id),
      staleTime: 5 * 60 * 1000,
      meta: { suppressErrorToast: true }
    }))
  });
  const loadingEncounters = encounters?.isPending ?? false;

  const detailed: UserTournamentEntry | null = selected && {
    ...selected,
    division_grid_version:
      tournaments.division_grid_versions.find((version) => version.id === selected.division_grid_version_id) ?? null,
    encounters: encounters?.data ?? []
  };

  const syncUrl = (id: number) => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    url.searchParams.set("selectedTournamentId", String(id));
    window.history.replaceState(null, "", url.toString());
  };

  const scrollToDossier = () => {
    const el = dossierRef.current;
    if (!el || typeof window === "undefined") return;
    el.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  };

  const selectEvent = (tournamentId: number) => {
    if (!events.some((t) => t.id === tournamentId)) return;
    setSelectedId(tournamentId);
    syncUrl(tournamentId);
    scrollToDossier();
  };

  return (
    <>
      <TournamentsPlacementTimeline
        tournaments={tournaments.results}
        tournamentsWon={tournamentsWon}
        selectedIds={selected ? [selected.id] : []}
        onSelect={selectEvent}
      />
      <div className="grid grid-cols-1 gap-3.5 min-[1081px]:grid-cols-[minmax(0,1fr)_404px]">
        <div ref={dossierRef} className="order-2 min-w-0 scroll-mt-4 min-[1081px]:order-1">
          <TournamentDossier
            tournament={detailed}
            selfUserId={selfUserId}
            loadingEncounters={loadingEncounters}
          />
        </div>
        {/* Desktop: the list is taken out of flow so the row height is the dossier's and the list scrolls inside it. */}
        <div className="order-1 min-[1081px]:relative min-[1081px]:order-2 min-[1081px]:min-h-[520px]">
          <TournamentList tournaments={events} selectedId={effectiveId} onSelect={selectEvent} showGames={showGames} />
        </div>
      </div>
    </>
  );
};

export default TournamentsHistory;
