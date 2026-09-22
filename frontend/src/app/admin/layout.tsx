import type { ReactNode } from "react";
import { cookies } from "next/headers";

import { AdminLayoutClient } from "@/app/admin/AdminLayoutClient";
import ZoneIntlProvider from "@/i18n/ZoneIntlProvider";
import {
  DISMISSED_ANNOUNCEMENTS_COOKIE,
  withoutDismissedAnnouncements
} from "@/lib/notifications/announcement-dismissed";
import { SIDEBAR_COOKIE_NAMES, parseSidebarOpenCookie } from "@/lib/site/sidebar-cookies";
import notificationService from "@/services/notification.service";
import type { NotificationItem } from "@/types/notification.types";

type AdminLayoutProps = {
  children: ReactNode;
};

// Same server-side read as the public layout, and the same `undefined`-on-
// failure rule (see `(site)/layout.tsx`): the panel is a separate tree, and an
// operator notice that only reaches the site half is a notice half the
// audience never sees.
async function resolveActiveAnnouncements(): Promise<NotificationItem[] | undefined> {
  try {
    return await notificationService.activeAnnouncements();
  } catch {
    return undefined;
  }
}

export default async function AdminLayout({ children }: Readonly<AdminLayoutProps>) {
  const cookieStore = await cookies();
  const defaultSidebarOpen = parseSidebarOpenCookie(cookieStore.get(SIDEBAR_COOKIE_NAMES.admin)?.value) ?? true;
  const announcements = withoutDismissedAnnouncements(
    await resolveActiveAnnouncements(),
    cookieStore.get(DISMISSED_ANNOUNCEMENTS_COOKIE)?.value
  );

  return (
    <ZoneIntlProvider zone="admin">
      <AdminLayoutClient defaultSidebarOpen={defaultSidebarOpen} announcements={announcements}>
        {children}
      </AdminLayoutClient>
    </ZoneIntlProvider>
  );
}
