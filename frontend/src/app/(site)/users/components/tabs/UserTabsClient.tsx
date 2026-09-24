"use client";

import React, { useEffect, useState, useTransition } from "react";
import { Tabs } from "@/components/ui/tabs";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import UserProfileTabList, { type TabBadges } from "@/app/(site)/users/components/tabs/UserProfileTabList";

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

  useEffect(() => {
    setValue(activeTab);
  }, [activeTab]);

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
      <div className="pt-6">{children}</div>
    </Tabs>
  );
};

export default UserTabsClient;
