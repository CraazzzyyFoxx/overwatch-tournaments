"use client";

import { CircleHelp } from "lucide-react";

import { CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

const ComparePageHeader = () => {
  return (
    <CardHeader className="relative pb-3">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <CardTitle className="text-2xl">Users Compare</CardTitle>
          <CardDescription>Compare overall performance on a hero/map.</CardDescription>
        </div>
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label="Open compare guide"
              className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border border-border/60 bg-background/20 text-muted-foreground transition-colors hover:bg-background/35 hover:text-foreground"
            >
              <CircleHelp className="h-4 w-4" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-90 max-w-[calc(100vw-2rem)]">
            <div className="space-y-2">
              <div className="text-sm font-semibold">Как пользоваться</div>
              <ol className="list-decimal space-y-1 pl-4 text-sm text-muted-foreground">
                <li>Выбери своего игрока в блоке Selected user.</li>
                <li>
                  В Compare against выбери пользователя для head-to-head, либо очисти выбор для сравнения с all
                  players avg.
                </li>
                <li>
                  При выборе target user фильтры division автоматически очищаются, и сравнение идет в режиме target
                  user.
                </li>
                <li>Выбери scope: Overall performance или Hero/Map performance.</li>
                <li>В Hero/Map primary hero синхронизирует compare hero; изменение compare hero не трогает primary.</li>
                <li>Для all players avg можно сузить baseline через role/division фильтры.</li>
              </ol>
            </div>
          </PopoverContent>
        </Popover>
      </div>
    </CardHeader>
  );
};

export default ComparePageHeader;
