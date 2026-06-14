import type { ReactNode } from "react";
import { cookies } from "next/headers";

import { AdminLayoutClient } from "@/app/admin/AdminLayoutClient";
import { SIDEBAR_COOKIE_NAMES, parseSidebarOpenCookie } from "@/lib/sidebar-cookies";

type AdminLayoutProps = {
  children: ReactNode;
};

export default async function AdminLayout({ children }: AdminLayoutProps) {
  const cookieStore = await cookies();
  const defaultSidebarOpen = parseSidebarOpenCookie(cookieStore.get(SIDEBAR_COOKIE_NAMES.admin)?.value) ?? true;

  return <AdminLayoutClient defaultSidebarOpen={defaultSidebarOpen}>{children}</AdminLayoutClient>;
}
