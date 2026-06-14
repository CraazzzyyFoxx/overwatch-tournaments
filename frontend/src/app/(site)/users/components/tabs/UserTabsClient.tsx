"use client";

import React, { useEffect, useState, useTransition } from "react";
import { Tabs } from "@/components/ui/tabs";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import UserProfileTabList, { type TabBadges } from "@/app/(site)/users/components/tabs/UserProfileTabList";

export interface UserTabsClientProps {
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
      <div className="sticky top-14 z-40 -mx-10 px-10 pt-4 pb-4 bg-background">
        <UserProfileTabList badges={badges} />
      </div>
      <div className="pt-6">{children}</div>
    </Tabs>
  );
};

export default UserTabsClient;
