"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import teamService from "@/services/team.service";
import { TournamentTeamCard, TournamentTeamCardSkeleton } from "@/components/TournamentTeamCard";
import tournamentService from "@/services/tournament.service";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useQuery } from "@tanstack/react-query";
import TeamComboBox from "@/components/TeamComboBox";
import { Team } from "@/types/team.types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const TeamsPage = () => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const stickyRef = useRef<HTMLDivElement | null>(null);

  const [sortBy, setSortBy] = useState<"placement" | "group" | "avg_sr">("avg_sr");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [previousElement, setPreviousElement] = useState<HTMLElement | null>(null);
  const [selectedTeam, setSelectedTeam] = useState<string>("");

  const parseId = useCallback((value: string | null) => {
    if (!value) return null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return null;
    return parsed;
  }, []);

  const tournamentId = useMemo(() => {
    return parseId(searchParams.get("tournamentId"));
  }, [parseId, searchParams]);

  const {
    data: tournamentsData,
    isSuccess: isSuccessTournaments,
    isLoading: loadingTournaments,
    isError: isErrorTournaments
  } = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll()
  });
  const {
    data: teamsData,
    isLoading: teamsLoading,
    isError: isErrorTeams
  } = useQuery({
    queryKey: ["teams", tournamentId, sortBy, sortOrder],
    queryFn: () => teamService.getAll(tournamentId as number, sortBy, sortOrder),
    enabled: tournamentId != null
  });

  const activeTournament = useMemo(() => {
    if (!tournamentId) return null;
    return tournamentsData?.results?.find((t) => t.id === tournamentId) || null;
  }, [tournamentId, tournamentsData?.results]);

  useEffect(() => {
    const nextParams = new URLSearchParams(searchParams);
    if (tournamentId == null && isSuccessTournaments && tournamentsData?.results?.[0]?.id) {
      nextParams.set("tournamentId", String(tournamentsData.results[0].id));
      router.replace(`${pathname}?${nextParams.toString()}`);
    }
  }, [pathname, router, searchParams, tournamentsData?.results, isSuccessTournaments, tournamentId]);

  useEffect(() => {
    const handle = setTimeout(() => {
      setSelectedTeam("");
      setPreviousElement((el) => {
        el?.classList.remove("ring-2", "ring-ring", "ring-offset-2", "ring-offset-background");
        return null;
      });
    }, 0);
    return () => clearTimeout(handle);
  }, [tournamentId]);

  const pushTournamentId = useCallback(
    (newTournamentId: string) => {
      const nextParams = new URLSearchParams(searchParams || undefined);
      nextParams.set("tournamentId", String(newTournamentId));
      router.push(`${pathname}?${nextParams.toString()}`);
    },
    [pathname, router, searchParams]
  );

  const getScrollOffset = useCallback(() => {
    const rect = stickyRef.current?.getBoundingClientRect();
    if (!rect) return 124;
    return rect.bottom + 16;
  }, []);

  const scrollToTeam = useCallback((team: Team) => {
    setSelectedTeam(team.name);
    setTimeout(() => {
      const element = document.getElementById(team.id.toString());
      setPreviousElement((prev) => {
        prev?.classList.remove("ring-2", "ring-ring", "ring-offset-2", "ring-offset-background");
        return element;
      });
      if (element) {
        const bodyRect = document.body.getBoundingClientRect().top;
        const elementRect = element.getBoundingClientRect().top;
        const elementPosition = elementRect - bodyRect;
        const offsetPosition = elementPosition - getScrollOffset();

        window.scrollTo({
          top: offsetPosition,
          behavior: "smooth"
        });
        element.classList.add("ring-2", "ring-ring", "ring-offset-2", "ring-offset-background");
      }
    }, 250);
  }, [getScrollOffset]);

  const teams = teamsData?.results || [];
  const isEmptyTeams = !teamsLoading && tournamentId != null && teams.length === 0;

  return (
    <div className="liquid-glass flex flex-col gap-4 md:gap-8">
      <div ref={stickyRef} className="sticky top-14 z-40 -mx-4 md:-mx-6 xl:-mx-10 px-4 md:px-6 xl:px-10 pb-4">
        <Card className="overflow-hidden">
          <CardHeader className="p-4 pb-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex flex-col gap-1">
                <h1 className="text-2xl font-semibold leading-none tracking-tight">Teams</h1>
                <p className="text-sm text-muted-foreground hidden sm:block">
                  Browse balanced teams, jump to a team, and adjust sorting.
                </p>
              </div>

              <div className="flex flex-wrap items-center justify-start gap-2 sm:justify-end">
                {loadingTournaments ? (
                  <Skeleton className="h-6 w-56" />
                ) : isErrorTournaments ? (
                  <Badge variant="outline">Failed to load tournaments</Badge>
                ) : null}
              </div>
            </div>
          </CardHeader>

          <CardContent className="p-4 pt-3">
            <div className="grid gap-3 xs:grid-cols-1 sm:grid-cols-2 lg:flex lg:flex-wrap lg:items-end">
              <div className="grid gap-1">
                <span className="text-xs text-muted-foreground">Tournament</span>
                <Select
                  value={tournamentId?.toString()}
                  onValueChange={(value) => pushTournamentId(value)}
                  disabled={loadingTournaments || isErrorTournaments}
                >
                  <SelectTrigger
                    aria-label="Tournament"
                    className="h-10 cursor-pointer xs:w-full md:w-62.5"
                  >
                    <SelectValue
                      placeholder={
                        loadingTournaments
                          ? "Loading tournaments..."
                          : isErrorTournaments
                            ? "Failed to load tournaments"
                            : "Select a tournament"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent className="liquid-glass-panel max-h-[min(var(--radix-select-content-available-height),20rem)]">
                    <SelectGroup>
                      {tournamentsData?.results.map((item) => (
                        <SelectItem key={item.id} value={item.id.toString()}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-1">
                <span className="text-xs text-muted-foreground">Jump to team</span>
                {teamsLoading ? (
                  <Skeleton className="h-10 xs:w-full md:w-62.5" />
                ) : (
                  <TeamComboBox
                    teams={teams}
                    onSelect={scrollToTeam}
                    selectedTeam={selectedTeam}
                    variant="glass"
                  />
                )}
              </div>

              <div className="grid gap-1">
                <span className="text-xs text-muted-foreground">Sort by</span>
                <Select value={sortBy} onValueChange={(value) => setSortBy(value as typeof sortBy)}>
                  <SelectTrigger aria-label="Sort by" className="h-10 cursor-pointer xs:w-full md:w-62.5">
                    <SelectValue placeholder="Sort by" />
                  </SelectTrigger>
                  <SelectContent className="liquid-glass-panel">
                    <SelectItem value="avg_sr">Avg. SR</SelectItem>
                    <SelectItem value="placement">Placement</SelectItem>
                    <SelectItem value="group">Group</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-1">
                <span className="text-xs text-muted-foreground">Order</span>
                <Select value={sortOrder} onValueChange={(value) => setSortOrder(value as typeof sortOrder)}>
                  <SelectTrigger aria-label="Order" className="h-10 cursor-pointer xs:w-full md:w-62.5">
                    <SelectValue placeholder="Order" />
                  </SelectTrigger>
                  <SelectContent className="liquid-glass-panel">
                    <SelectItem value="asc">Ascending</SelectItem>
                    <SelectItem value="desc">Descending</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {tournamentId == null && !loadingTournaments ? (
        <Card>
          <CardHeader>
            <div className="text-sm text-muted-foreground">Select a tournament to view teams.</div>
          </CardHeader>
        </Card>
      ) : isErrorTeams ? (
        <Card>
          <CardHeader>
            <div className="text-sm text-muted-foreground">Failed to load teams.</div>
          </CardHeader>
        </Card>
      ) : isEmptyTeams ? (
        <Card>
          <CardHeader>
            <div className="text-sm text-muted-foreground">No teams found for this tournament.</div>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid grid-cols-2 xs:grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 md:gap-8">
          {teamsLoading || loadingTournaments ? (
            <>
              <TournamentTeamCardSkeleton />
              <TournamentTeamCardSkeleton />
              <TournamentTeamCardSkeleton />
              <TournamentTeamCardSkeleton />
              <TournamentTeamCardSkeleton />
              <TournamentTeamCardSkeleton />
            </>
          ) : (
            teams.map((team) => <TournamentTeamCard key={team.id} team={team} />)
          )}
        </div>
      )}
    </div>
  );
};

const TeamsPageFallback = () => {
  return (
    <div className="liquid-glass flex flex-col gap-4 md:gap-8">
      <div className="-mx-4 md:-mx-6 xl:-mx-10 px-4 md:px-6 xl:px-10">
        <Card className="overflow-hidden">
          <CardHeader className="p-4 pb-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div className="flex flex-col gap-2">
                <Skeleton className="h-8 w-40" />
                <Skeleton className="hidden sm:block h-4 w-80" />
              </div>
              <Skeleton className="h-6 w-56" />
            </div>
          </CardHeader>
          <CardContent className="p-4 pt-3">
            <div className="grid gap-3 xs:grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-2 xs:grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 md:gap-8">
        <TournamentTeamCardSkeleton />
        <TournamentTeamCardSkeleton />
        <TournamentTeamCardSkeleton />
        <TournamentTeamCardSkeleton />
        <TournamentTeamCardSkeleton />
        <TournamentTeamCardSkeleton />
      </div>
    </div>
  );
};

const TeamsPageWrapper = () => (
  <Suspense fallback={<TeamsPageFallback />}>
    <TeamsPage />
  </Suspense>
);

export default TeamsPageWrapper;
