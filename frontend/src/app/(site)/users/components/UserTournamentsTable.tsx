"use client";

import React, { useEffect, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import DivisionIcon from "@/components/DivisionIcon";
import { UserTournament } from "@/types/user.types";
import { Accordion, AccordionContent, AccordionItem } from "@/components/ui/accordion";
import TournamentsIcon from "@/components/icons/TournamentsIcon";
import * as AccordionPrimitive from "@radix-ui/react-accordion";
import { ChevronDownIcon } from "@radix-ui/react-icons";
import { TournamentTeamTable } from "@/components/TournamentTeamCard";
import UserTournamentEncounters from "@/app/(site)/users/components/UserTournamentEncounters";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

export const UserTournamentStatsCard = ({ tournament }: { tournament: UserTournament }) => {
  const maps = tournament.maps_won + tournament.maps_lost;

  return (
    <>
      <div className="flex flex-row gap-2">
        <span>Matches</span>
        <span>{tournament.won + tournament.draw + tournament.lost}</span>
      </div>
      <div className="flex flex-row gap-2">
        <div>
          <span>{tournament.won}</span>
          <span className="text-muted-foreground">W</span>
        </div>
        <div>
          <span>{tournament.lost}</span>
          <span className="text-muted-foreground">L</span>
        </div>
        <div>
          <span>{tournament.draw}</span>
          <span className="text-muted-foreground">D</span>
        </div>
      </div>
      <span>
        Won {tournament.maps_won} of {maps} maps
      </span>
      <span>Winrate {Math.round((tournament.maps_won / maps) * 100)}%</span>
      <span>Closeness {(tournament.closeness * 100).toFixed(0)}%</span>
    </>
  );
};

export const getTournamentColor = (tournament: UserTournament) => {
  if (!tournament.placement) {
    return "from-transparent";
  }

  if (tournament.placement === 1) {
    return "from-firstPlaceBg";
  }

  if (tournament.placement === 2) {
    return "from-secondPlaceBg";
  }

  if (tournament.placement === 3) {
    return "from-thirdPlaceBg";
  }

  const topThreshold = tournament.id > 20 ? 13 : 7;
  if (tournament.placement <= topThreshold) {
    return "from-green-300";
  }

  return "from-transparent";
};

export const UserTournamentHeader = ({ tournament }: { tournament: UserTournament }) => {
  let tournamentNumber = tournament.number ? tournament.number.toString() : "";
  if (!tournamentNumber) {
    tournamentNumber = tournament.name.split(" | ")[1];
  }

  return (
    <AccordionPrimitive.Header className="flex">
      <div
        className={`bg-gradient-to-r ${getTournamentColor(tournament)} to-transparent md:min-w-80 xs:min-w-60`}
      />
      <AccordionPrimitive.Trigger className="flex flex-1 items-center justify-between py-4 text-sm font-medium transition-all hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background [&[data-state=open]>svg]:rotate-180 md:-ml-80 xs:-ml-60">
        <div className="grid xs:grid-cols-2 sm:grid-cols-11 md:gap-4 xs:gap-1.5 items-center w-full fixed-columns min-h-10 xs:ml-8 md:ml-0">
          <div className="col-span-1">
            <h3 className="scroll-m-20 text-2xl font-semibold tracking-tight xs:text-left md:text-center">
              <Link href={`/tournaments/${tournament.id}`}>{tournamentNumber}</Link>
            </h3>
          </div>
          <span className="col-span-2 text-left">Team {tournament.team}</span>
          <div className="flex col-span-2 justify-between xs:w-48 md:w-auto">
            <div className="flex items-center gap-4">
              <span>
                Place {tournament.placement ? tournament.placement : "-"} of{" "}
                {tournament.count_teams}
              </span>
            </div>
            <div className="flex flex-row gap-2 mb-2 items-center xs:ml-5 xl:ml-0">
              <div className="mt-0.5">
                <PlayerRoleIcon role={tournament.role} />
              </div>
              <DivisionIcon
                division={tournament.division}
                tournamentGrid={tournament.division_grid_version}
                width={32}
                height={32}
              />
            </div>
          </div>
        </div>
        <ChevronDownIcon className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 mr-8" />
      </AccordionPrimitive.Trigger>
    </AccordionPrimitive.Header>
  );
};

export const UserTournamentLeagueHeader = ({ tournament }: { tournament: UserTournament }) => {
  let tournamentNumber = tournament.name.split(" | ")[0];

  return (
    <AccordionPrimitive.Header className="flex">
      <AccordionPrimitive.Trigger className="flex flex-1 items-center justify-between py-4 text-sm font-medium transition-all hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background [&[data-state=open]>svg]:rotate-180">
        <div className="h-10">
          <div className="flex flex-row items-center gap-4">
            <h3 className="scroll-m-20 text-2xl font-semibold tracking-tight md:ml-10 xs:ml-8">
              {tournamentNumber}
            </h3>
          </div>
        </div>
        <ChevronDownIcon className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 mr-8" />
      </AccordionPrimitive.Trigger>
    </AccordionPrimitive.Header>
  );
};

export const UserTournamentContent = ({ tournament }: { tournament: UserTournament }) => {
  return (
    <AccordionContent className="p-10 grid grid-cols-7 gap-12">
      <Card className="md:col-span-2 xs:col-span-7">
        <CardContent className="mt-12 flex flex-col gap-2 items-center text-lg font-semibold">
          <UserTournamentStatsCard tournament={tournament} />
        </CardContent>
      </Card>
      <Card className="md:col-span-5 xs:col-span-7">
        <CardContent className="p-0">
          <TournamentTeamTable players={tournament.players} tournamentGrid={tournament.division_grid_version} />
        </CardContent>
      </Card>
      <Card className="col-span-7">
        <CardContent className="p-0 overflow-hidden">
          <UserTournamentEncounters tournament={tournament} team_id={tournament.team_id} />
        </CardContent>
      </Card>
    </AccordionContent>
  );
};

export const UserTournamentsTable = ({ tournaments }: { tournaments: UserTournament[] }) => {
  const searchParams = useSearchParams();
  const selectedFromUrl = searchParams ? searchParams.get("selectedTournamentId") : null;
  const [selectedTournamentId, setSelectedTournamentId] = React.useState<string | null>(selectedFromUrl);
  const [prevSelectedFromUrl, setPrevSelectedFromUrl] = React.useState<string | null>(selectedFromUrl);

  if (selectedFromUrl !== prevSelectedFromUrl) {
    setPrevSelectedFromUrl(selectedFromUrl);
    setSelectedTournamentId(selectedFromUrl);
  }

  const newTournaments: (UserTournament | UserTournament[])[] = useMemo(() => {
    const result: (UserTournament | UserTournament[])[] = [];
    let currentLeague: UserTournament[] = [];
    let leagueNameFlag = "";

    tournaments.forEach((tournament) => {
      if (tournament.is_league) {
        const leagueName = tournament.name.split(" | ")[0];

        if (leagueNameFlag && leagueNameFlag !== leagueName) {
          result.push(currentLeague);
          currentLeague = [];
        }

        leagueNameFlag = leagueName;
        currentLeague.push(tournament);
      } else {
        if (currentLeague.length > 0) {
          result.push(currentLeague);
          currentLeague = [];
          leagueNameFlag = "";
        }
        result.push(tournament);
      }
    });

    if (currentLeague.length > 0) {
      result.push(currentLeague);
    }

    return result;
  }, [tournaments]);



  const onSelect = (value: string) => {
    const newSearchParams = new URLSearchParams(searchParams);
    newSearchParams.set("selectedTournamentId", value);
    setSelectedTournamentId(value);
    // router.push(`${pathname}?${newSearchParams.toString()}`);
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-3">
          <TournamentsIcon />
          <span className="text-xl">Tournaments history</span>
        </CardTitle>
        <CardDescription>
          Placements, teams, and match breakdowns across tournament runs.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Accordion
          type="single"
          collapsible
          className="w-full"
          value={selectedTournamentId?.toString()}
          onValueChange={onSelect}
        >
          {newTournaments.map((tournament) => {
            if (!Array.isArray(tournament)) {
              return (
                <AccordionItem key={tournament.name} value={`t-${tournament.id}`}>
                  <UserTournamentHeader tournament={tournament} />
                  <UserTournamentContent tournament={tournament} />
                </AccordionItem>
              );
            } else {
              const leagueName = tournament[0].name.split(" | ")[0];
              return (
                <AccordionItem key={leagueName} value={`t-${leagueName}`}>
                  <UserTournamentLeagueHeader tournament={tournament[0]} />
                  <AccordionPrimitive.Content className="overflow-hidden text-sm data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down md:pl-16">
                    <div className="pt-0">
                      <Accordion type="single" collapsible className="w-full">
                        {tournament.map((leagueTournament: UserTournament, index: number) => {
                          return (
                            <AccordionItem
                              key={leagueTournament.name}
                              value={`tournaments-${leagueTournament.name}`}
                              className={index == tournament.length - 1 ? "border-none" : ""}
                            >
                              <UserTournamentHeader tournament={leagueTournament} />
                              <UserTournamentContent tournament={leagueTournament} />
                            </AccordionItem>
                          );
                        })}
                      </Accordion>
                    </div>
                  </AccordionPrimitive.Content>
                </AccordionItem>
              );
            }
          })}
        </Accordion>
      </CardContent>
    </Card>
  );
};
