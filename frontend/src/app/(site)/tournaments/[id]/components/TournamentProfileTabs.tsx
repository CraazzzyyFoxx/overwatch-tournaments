"use client";

import React, { useCallback } from "react";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";

const TournamentProfileTabList = () => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const navToTab = useCallback(
    (tab: string) => {
      const newSearchParams = new URLSearchParams(searchParams || undefined);
      newSearchParams.set("tab", tab);
      router.push(`${pathname}?${newSearchParams.toString()}`);
    },
    [searchParams, pathname, router]
  );

  return (
    <ScrollArea className="mb-8 max-w-[600px]">
      <TabsList className="grid w-[600px] grid-cols-5 mb-4">
        <TabsTrigger value="overview" onClick={() => navToTab("overview")}>
          Overview
        </TabsTrigger>
        <TabsTrigger value="teams" onClick={() => navToTab("teams")}>
          Teams
        </TabsTrigger>
        <TabsTrigger value="matches" onClick={() => navToTab("matches")}>
          Matches
        </TabsTrigger>
        <TabsTrigger value="heroes" onClick={() => navToTab("heroes")}>
          Heroes
        </TabsTrigger>
        <TabsTrigger value="standings" onClick={() => navToTab("standings")}>
          Standings
        </TabsTrigger>
      </TabsList>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
};

export default TournamentProfileTabList;
