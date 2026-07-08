"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

export interface TabBadges {
  tournaments?: number | null;
  matches?: number | null;
  heroes?: number | null;
  maps?: number | null;
  achievements?: number | null;
}

const TabButton = ({ value, label, badge }: { value: string; label: string; badge?: number | null }) => (
  <TabsTrigger
    value={value}
    className={cn(
      "h-9 rounded-lg px-4 text-[14px] font-semibold gap-2 data-[state=active]:bg-[hsl(174_72%_46%_/_0.14)] data-[state=active]:text-[color:var(--aqt-teal)] data-[state=active]:shadow-[inset_0_0_0_1px_hsl(174_72%_46%_/_0.3)]"
    )}
  >
    <span>{label}</span>
    {badge !== undefined && badge !== null ? (
      <span
        className="aqt-mono rounded-[4px] px-1.5 py-px text-[11px] font-semibold"
        style={{
          color: "var(--aqt-fg-faint)",
          background: "hsl(0 0% 100% / 0.04)"
        }}
      >
        {badge}
      </span>
    ) : null}
  </TabsTrigger>
);

const UserProfileTabList = ({ badges }: { badges?: TabBadges }) => {
  const t = useTranslations();
  return (
    <ScrollArea className="aqt-player">
      <TabsList className="h-11 w-max rounded-[11px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-1 gap-0.5">
        <TabButton value="overview" label={t("users.profile.tabs.overview")} />
        <TabButton value="tournaments" label={t("users.profile.tabs.tournaments")} badge={badges?.tournaments} />
        <TabButton value="matches" label={t("common.matches")} badge={badges?.matches} />
        <TabButton value="heroes" label={t("common.heroes")} badge={badges?.heroes} />
        <TabButton value="maps" label={t("users.profile.tabs.maps")} badge={badges?.maps} />
        <TabButton value="achievements" label={t("users.profile.tabs.achievements")} badge={badges?.achievements} />
      </TabsList>
      <ScrollBar orientation="horizontal" />
    </ScrollArea>
  );
};

export default UserProfileTabList;
