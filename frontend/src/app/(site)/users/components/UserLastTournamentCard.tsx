"use client";

import React from "react";
import { UserTournamentWithStats, UserTournamentSummary } from "@/types/user.types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Box, Clock } from "lucide-react";
import { ChartConfig, ChartContainer } from "@/components/ui/chart";
import { Label, Pie, PieChart } from "recharts";
import { TypographyH4 } from "@/components/ui/typography";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import Link from "next/link";
import DivisionIcon from "@/components/DivisionIcon";
import { getLastTournamentGridVersion } from "@/app/(site)/users/components/user-last-tournament-card.helpers";

export interface UserLastTournamentProps {
  tournament: UserTournamentWithStats | null;
  tournaments: UserTournamentSummary[];
}

export interface UserLastTournamentStatCardProps {
  name: string;
  value: number | string;
  rank: number;
  total: number;
}

const chartConfig = {
  wins: {
    label: "Wins",
    color: "#02755c"
  },
  loses: {
    label: "Loses",
    color: "#88202f"
  }
} satisfies ChartConfig;

const WinCircularChart = ({ tournament }: { tournament: UserTournamentWithStats }) => {
  const chartData = [
    { browser: "wins", count: tournament.maps_won, fill: "var(--color-wins)" },
    {
      browser: "loses",
      count: tournament.maps - tournament.maps_won,
      fill: "var(--color-loses)"
    }
  ];

  return (
    <ChartContainer config={chartConfig} className="aspect-square max-w-[80px]">
      <PieChart>
        <Pie
          isAnimationActive={true}
          animationBegin={0}
          animationDuration={1500}
          data={chartData}
          dataKey="count"
          nameKey="browser"
          innerRadius={30}
          outerRadius={40}
        >
          <Label
            content={({ viewBox }) => {
              if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                return (
                  <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                    <tspan
                      x={(viewBox.cx || 0) - 12}
                      y={(viewBox.cy || 0) - 10}
                      className="fill-foreground font-bold"
                    >
                      {tournament.maps_won}
                    </tspan>
                    <tspan
                      x={(viewBox.cx || 0) + 12}
                      y={(viewBox.cy || 0) - 10}
                      className="fill-foreground font-bold"
                    >
                      W
                    </tspan>
                    <tspan
                      x={(viewBox.cx || 0) - 12}
                      y={(viewBox.cy || 0) + 8}
                      className="fill-muted-foreground"
                    >
                      {tournament.maps - tournament.maps_won}
                    </tspan>
                    <tspan
                      x={(viewBox.cx || 0) + 12}
                      y={(viewBox.cy || 0) + 8}
                      className="fill-muted-foreground"
                    >
                      L
                    </tspan>
                  </text>
                );
              }
            }}
          />
        </Pie>
      </PieChart>
    </ChartContainer>
  );
};

const UserLastTournamentCardHerderSkeleton = () => {
  return (
    <div className="grid xl:grid-cols-4 md:grid-cols-2 items-center">
      <div className="flex flex-row col-span-1 gap-6">
        <div className="ml-8">
          <Skeleton className="h-16 w-16 rounded-full" />
        </div>
        <div className="flex flex-col gap-2 mt-2">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-6 w-36" />
        </div>
      </div>
      <div className="col-span-1">
        <div className="ml-16">
          <Skeleton className="h-16 w-16 rounded-full" />
        </div>
      </div>
    </div>
  );
};

const UserLastTournamentCardHeader = ({
  tournament,
  tournaments
}: {
  tournament: UserTournamentWithStats;
  tournaments: UserTournamentSummary[];
}) => {
  const tournamentGrid = getLastTournamentGridVersion(tournament.id, tournaments);

  return (
    <div className="grid lg:grid-cols-3 xs:grid-cols-1 md:grid-cols-2 items-center">
      <div className="flex flex-row col-span-1 gap-6 md:ml-12">
        <div className="xs:ml-4">
          <DivisionIcon
            division={tournament.division}
            tournamentGrid={tournamentGrid}
            width={60}
            height={60}
          />
        </div>
        <div className="flex flex-col">
          <span className="scroll-m-20 text-xl font-semibold tracking-tight text-muted-foreground">
            Role
          </span>
          <span className="flex flex-row items-center gap-2 scroll-m-20 text-2xl font-semibold tracking-tight">
            {tournament.role}
          </span>
        </div>
      </div>
      <div className="hidden col-span-1 md:block">
        <div className="ml-2">
          <WinCircularChart tournament={tournament} />
        </div>
      </div>
    </div>
  );
};

const UserLastTournamentStatCardBar = ({ rank, total }: UserLastTournamentStatCardProps) => {
  const valuePercentage = ((total - rank) / total) * 100;

  return (
    <div className="flex flex-col h-full">
      <div className="relative h-15 w-1.5 rounded-full bg-muted">
        <div
          className="absolute bottom-0 h-full w-full rounded-full bg-primary"
          style={{ height: `${valuePercentage}%` }}
        />
      </div>
    </div>
  );
};

const UserLastTournamentStatCardSkeleton = () => {
  return <Skeleton className="h-24 w-full" />;
};

const UserLastTournamentStatCard = ({
  name,
  value,
  rank,
  total
}: UserLastTournamentStatCardProps) => {
  return (
    <Card>
      <CardContent className="flex flex-row items-center gap-4 p-4">
        <UserLastTournamentStatCardBar rank={rank} total={total} value={value} name={name} />
        <div>
          <p className="text-xl text-muted-foreground font-medium">{name}</p>
          <TypographyH4>{value}</TypographyH4>
          <p className="text-xs text-muted-foreground">
            {rank} from {total}
          </p>
        </div>
      </CardContent>
    </Card>
  );
};

export const UserLastTournamentCardSkeleton = () => {
  return (
    <Card className="flex flex-col gap-4 w-full">
      <CardHeader>
        <CardTitle className="flex xl:flex-row md:flex-col xl:gap-10 md:gap-4 xl:items-center">
          <div className="flex flex-row items-center gap-2 scroll-m-20 text-2xl font-semibold tracking-tight">
            <Box />
            <Skeleton className="h-8 w-60" />
          </div>
          <div className="flex flex-row gap-10 xs:items-center justify-between">
            <div className="flex flex-row gap-10 items-center">
              <div className="flex flex-row items-center text-sm text-muted-foreground gap-2">
                <Clock />
                <Skeleton className="h-5 w-36" />
              </div>
              <Skeleton className="h-5 w-28" />
            </div>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <UserLastTournamentCardHerderSkeleton />
        <div className="grid grid-cols-1 xl:grid-cols-4 lg:grid-cols-3 md:grid-cols-2 gap-4 mt-8">
          <UserLastTournamentStatCardSkeleton />
          <UserLastTournamentStatCardSkeleton />
          <UserLastTournamentStatCardSkeleton />
          <UserLastTournamentStatCardSkeleton />
          <UserLastTournamentStatCardSkeleton />
          <UserLastTournamentStatCardSkeleton />
          <UserLastTournamentStatCardSkeleton />
          <UserLastTournamentStatCardSkeleton />
        </div>
      </CardContent>
    </Card>
  );
};

const UserLastTournamentCard = ({ tournament, tournaments }: UserLastTournamentProps) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  if (!tournament) {
    return <></>;
  }

  const playtime = tournament.playtime / 3600;
  let tournamentName = `${tournament.number} Tournament`;
  if (!tournament.number) {
    tournamentName = tournament.name;
  }

  const onSelect = (value: number) => {
    const newSearchParams = new URLSearchParams(searchParams);
    newSearchParams.set("tournamentId", String(value));
    return router.push(`${pathname}?${newSearchParams.toString()}`);
  };

  return (
    <Card className="w-full lg:h-110">
      <CardHeader className="flex lg:flex-row xs:flex-col lg:gap-10 xs:gap-4 lg:items-center">
        <CardTitle className="flex flex-1 lg:flex-row xs:flex-col lg:gap-10 xs:gap-4 lg:items-center lg:mx-2">
          <div className="flex flex-row items-center gap-2 scroll-m-20 text-xl font-semibold tracking-tight">
            <Box />
            <div className="flex flex-row gap-6">
              <Link href={`/tournaments/${tournament.id}`}>{tournamentName}</Link>
            </div>
          </div>
          <div className="flex flex-1 xs:flex-col xs:gap-4 xs1:flex-row xs1:items-center justify-between">
            <div className="flex flex-row gap-10">
              <div className="flex flex-row text-sm text-muted-foreground gap-2">
                <Clock />
                <span>{playtime.toFixed(1)}h Playtime</span>
              </div>
              <span className="text-sm text-muted-foreground">{tournament.maps} maps</span>
            </div>
            <Select
              value={tournament.id.toString()}
              onValueChange={(value) => onSelect(Number(value))}
            >
              <SelectTrigger className="w-55">
                <SelectValue placeholder="Select a fruit" />
              </SelectTrigger>
              <SelectContent className="liquid-glass-panel max-h-[min(var(--radix-select-content-available-height),20rem)]">
                <SelectGroup>
                  {tournaments.map((tournament) => (
                    <SelectItem key={tournament.id} value={tournament.id.toString()}>
                      {tournament.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <UserLastTournamentCardHeader tournament={tournament} tournaments={tournaments} />
        {tournament.stats ? (
          <div className="grid grid-cols-1 xl:grid-cols-4 lg:grid-cols-3 md:grid-cols-2 gap-4 mt-8">
            <UserLastTournamentStatCard
              name="Winrate"
              value={`${(tournament.stats.winrate.value * 100).toFixed(2)}%`}
              rank={tournament.stats.winrate.rank}
              total={tournament.stats.winrate.total}
            />
            <UserLastTournamentStatCard
              name="K/D Ratio"
              value={tournament.stats.kd?.value}
              rank={tournament.stats.kd?.rank}
              total={tournament.stats.kd?.total}
            />
            <UserLastTournamentStatCard
              name="KDA Ratio"
              value={tournament.stats.kda?.value}
              rank={tournament.stats.kda?.rank}
              total={tournament.stats.kda?.total}
            />
            <UserLastTournamentStatCard
              name="MVP Score"
              value={tournament.stats.performance?.value}
              rank={tournament.stats.performance?.rank}
              total={tournament.stats.performance?.total}
            />
            <UserLastTournamentStatCard
              name="Eliminations"
              value={tournament.stats.eliminations?.value}
              rank={tournament.stats.eliminations?.rank}
              total={tournament.stats.eliminations?.total}
            />
            <UserLastTournamentStatCard
              name="Deaths"
              value={tournament.stats.deaths?.value}
              rank={tournament.stats.deaths?.rank}
              total={tournament.stats.deaths?.total}
            />
            <UserLastTournamentStatCard
              name="Damage/Map"
              value={tournament.stats.hero_damage_dealt?.value}
              rank={tournament.stats.hero_damage_dealt?.rank}
              total={tournament.stats.hero_damage_dealt?.total}
            />
            <UserLastTournamentStatCard
              name="Damage Delta"
              value={tournament.stats.damage_delta?.value}
              rank={tournament.stats.damage_delta?.rank}
              total={tournament.stats.damage_delta?.total}
            />
          </div>
        ) : (
          <></>
        )}
      </CardContent>
    </Card>
  );
};

export default UserLastTournamentCard;
