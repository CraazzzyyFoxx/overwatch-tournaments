import React from "react";
import Image from "next/image";
import Link from "next/link";
import { Crown } from "lucide-react";

import { cn } from "@/lib/utils";
import { HeroBestStat, HeroWithUserStats } from "@/types/hero.types";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { formatPercent, formatSeconds, formatStatValue } from "./utils";

export const BestResult = ({
  name,
  stat,
  best,
  all
}: {
  name: string;
  stat?: HeroBestStat | null;
  best?: HeroBestStat | null;
  all: boolean;
}) => {
  if (!stat) {
    return <span className="text-muted-foreground">-</span>;
  }

  const isGlobalBest = !all && !!best && stat.value === best.value;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-sm font-medium transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          href={`/encounters/${stat.encounter_id}`}
        >
          <span className="tabular-nums">{formatStatValue(name, stat.value)}</span>
          {isGlobalBest ? <Crown className="h-4 w-4 text-yellow-500" aria-label="Global best" /> : null}
        </Link>
      </TooltipTrigger>
      <TooltipContent className="w-72 overflow-hidden border border-border/50 bg-background/80 p-0 backdrop-blur-xl">
        <Link href={`/encounters/${stat.encounter_id}`} className="block">
          <div className="relative h-28 w-full">
            <Image
              src={stat.map_image_path}
              alt={stat.map_name}
              fill
              className="object-cover brightness-75"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-background via-background/40 to-background/20" />
          </div>
          <div className="p-3">
            <div className="line-clamp-2 text-sm font-semibold tracking-tight text-foreground">
              {stat.tournament_name}
            </div>
            <div className="mt-1 truncate text-xs text-muted-foreground">{stat.map_name}</div>
            {all ? (
              <div className="mt-2 text-xs text-muted-foreground">
                Player: <span className="font-medium text-foreground">{stat.player_name.split("#")[0]}</span>
              </div>
            ) : null}
          </div>
        </Link>
      </TooltipContent>
    </Tooltip>
  );
};

export const KpiCard = ({
  label,
  value,
  subtitle
}: {
  label: string;
  value: string;
  subtitle?: string;
}) => {
  return (
    <Card>
      <CardHeader className="p-4 pb-1">
        <CardTitle className="text-xs font-semibold tracking-tight text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className="truncate text-xl font-bold leading-none tabular-nums" title={value}>
          {value}
        </div>
        {subtitle ? <div className="mt-1 truncate text-[11px] text-muted-foreground">{subtitle}</div> : null}
      </CardContent>
    </Card>
  );
};

export const HeroListItem = ({
  hero,
  selected,
  onSelect,
  playtimeSeconds,
  share
}: {
  hero: HeroWithUserStats;
  selected: boolean;
  onSelect: () => void;
  playtimeSeconds: number;
  share: number;
}) => {
  const role = (hero.hero as unknown as { type?: string; role?: string }).type ??
    (hero.hero as unknown as { type?: string; role?: string }).role;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group w-full cursor-pointer rounded-xl border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-border/80 bg-muted/25"
          : "border-border/60 bg-background/15 hover:bg-muted/20"
      )}
      aria-pressed={selected}
    >
      <div className="flex min-w-0 items-center gap-3">
        <div
          className="relative h-10 w-10 shrink-0 overflow-hidden"
        >
          <Image
            src={hero.hero.image_path}
            alt={hero.hero.name}
            fill
            className="object-contain select-none"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div className="truncate font-semibold">{hero.hero.name}</div>
            <div className="text-xs text-muted-foreground tabular-nums">{formatSeconds(playtimeSeconds)}</div>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <Progress
              value={Math.max(0, Math.min(100, share * 100))}
              className="h-1.5 bg-muted/40 [&>div]:bg-foreground/70"
              aria-label="Playtime share"
            />
            <div className="w-10 shrink-0 text-right text-[11px] text-muted-foreground tabular-nums">
              {formatPercent(share, 0)}
            </div>
          </div>
          {role ? (
            <div className="mt-2">
              <Badge variant="outline" className="text-[11px]">
                {role}
              </Badge>
            </div>
          ) : null}
        </div>
      </div>
    </button>
  );
};
