"use client";

import React, { useCallback } from "react";
import { useTranslations } from "next-intl";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";

const TournamentProfileTabList = () => {
  const t = useTranslations();
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
          {t("common.overview")}
        </TabsTrigger>
        <TabsTrigger value="teams" onClick={() => navToTab("teams")}>
          {t("common.teams")}
        </TabsTrigger>
        <TabsTrigger value="matches" onClick={() => navToTab("matches")}>
          {t("common.matches")}
        </TabsTrigger>
        <TabsTrigger value="heroes" onClick={() => navToTab("heroes")}>
          {t("common.heroes")}
        </TabsTrigger>
        <TabsTrigger value="standings" onClick={() => navToTab("standings")}>
          {t("common.standings")}
        </TabsTrigger>
      </TabsList>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
};

export default TournamentProfileTabList;
