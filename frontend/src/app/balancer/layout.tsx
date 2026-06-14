import type { ReactNode } from "react";
import { cookies } from "next/headers";

import { BalancerLayoutClient } from "@/app/balancer/BalancerLayoutClient";
import { SIDEBAR_COOKIE_NAMES, parseSidebarOpenCookie } from "@/lib/sidebar-cookies";

type BalancerLayoutProps = {
  children: ReactNode;
};

export default async function BalancerLayout({ children }: BalancerLayoutProps) {
  const cookieStore = await cookies();
  const defaultSidebarOpen = parseSidebarOpenCookie(cookieStore.get(SIDEBAR_COOKIE_NAMES.balancer)?.value) ?? true;

  return <BalancerLayoutClient defaultSidebarOpen={defaultSidebarOpen}>{children}</BalancerLayoutClient>;
}
