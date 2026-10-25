"use client";

import React, { useState, useTransition } from "react";
import { Tabs } from "@/components/ui/tabs";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import UserProfileTabList, { type TabBadges } from "@/app/(site)/users/components/tabs/UserProfileTabList";
import { PROFILE_GAME_BOUND_PARAMS } from "@/app/(site)/users/components/shared/profile-games";
import { useGameBoundParams } from "@/components/workspace/scope-pill-store";

interface UserTabsClientProps {
  activeTab: string;
  children: React.ReactNode;
  badges?: TabBadges;
}

const UserTabsClient = ({ activeTab, children, badges }: UserTabsClientProps) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const [value, setValue] = useState(activeTab);
  useGameBoundParams(PROFILE_GAME_BOUND_PARAMS);

  // The server's tab wins once it changes (Back/Forward, a link). Adjusted
  // during render, so the previous tab is never painted first.
  const [syncedTab, setSyncedTab] = useState(activeTab);
  if (activeTab !== syncedTab) {
    setSyncedTab(activeTab);
    setValue(activeTab);
  }

  const onValueChange = (tab: string) => {
    setValue(tab);

    const nextSearchParams = new URLSearchParams(searchParams || undefined);
    nextSearchParams.set("tab", tab);

    startTransition(() => {
      router.push(`${pathname}?${nextSearchParams.toString()}`);
    });
  };

  return (
    <Tabs value={value} onValueChange={onValueChange}>
      {/* The negative gutter must mirror the (site) container's responsive padding
          (`px-4 md:px-6 xl:px-10`). A flat `-mx-10` overhung the viewport by 24px
          below `md`, which is what put a horizontal scrollbar on every profile at
          375px. Offset is the shared header-height token, not a magic `top-14`.
          `pt-3` is breathing room under the site header once stuck; the negative
          margin cancels it plus most of the layout's `gap-4 md:gap-8` so the row
          sits 16px under the hero at rest instead of 44px. */}
      <div className="sticky top-[var(--aqt-header-h)] z-40 -mx-4 -mt-3 bg-background px-4 pt-3 md:-mx-6 md:-mt-7 md:px-6 xl:-mx-10 xl:px-10">
        <UserProfileTabList badges={badges} />
      </div>
      {/* A tab's sticky rails stop under this bar, not under the site header alone: the bar ends 3rem (`pt-3` and the
          36px tab row) below the header, and the rails keep the cards' 14px gap from it. */}
      <div className="pt-6 [--aqt-sticky-top:calc(var(--aqt-header-h)_+_3.875rem)]">{children}</div>
    </Tabs>
  );
};

export default UserTabsClient;
