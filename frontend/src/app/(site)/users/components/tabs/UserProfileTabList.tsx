"use client";

import { useTranslations } from "next-intl";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface TabBadges {
  tournaments?: number | null;
  matches?: number | null;
  heroes?: number | null;
  maps?: number | null;
  achievements?: number | null;
}

const UserProfileTabList = ({ badges }: { badges?: TabBadges }) => {
  const t = useTranslations();
  return (
    <TabsList>
      <TabsTrigger value="overview">{t("users.profile.tabs.overview")}</TabsTrigger>
      <TabsTrigger value="tournaments" badge={badges?.tournaments}>
        {t("users.profile.tabs.tournaments")}
      </TabsTrigger>
      <TabsTrigger value="matches" badge={badges?.matches}>
        {t("common.matches")}
      </TabsTrigger>
      <TabsTrigger value="heroes" badge={badges?.heroes}>
        {t("common.heroes")}
      </TabsTrigger>
      <TabsTrigger value="maps" badge={badges?.maps}>
        {t("users.profile.tabs.maps")}
      </TabsTrigger>
      <TabsTrigger value="achievements" badge={badges?.achievements}>
        {t("users.profile.tabs.achievements")}
      </TabsTrigger>
    </TabsList>
  );
};

export default UserProfileTabList;
