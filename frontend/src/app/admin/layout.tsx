import type { ReactNode } from "react";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { AdminLayoutClient } from "@/app/admin/AdminLayoutClient";
import { AuthProfileSeed } from "@/components/auth/AuthProfileSeed";
import ZoneIntlProvider from "@/i18n/ZoneIntlProvider";
import { getAccessToken, getRefreshToken } from "@/lib/auth/cookies";
import { fetchAuthProfileResponse, mapAuthProfile } from "@/lib/auth/profile";
import {
  DISMISSED_ANNOUNCEMENTS_COOKIE,
  withoutDismissedAnnouncements
} from "@/lib/notifications/announcement-dismissed";
import { SIDEBAR_COOKIE_NAMES, parseSidebarOpenCookie } from "@/lib/site/sidebar-cookies";
import notificationService from "@/services/notification.service";
import type { AuthProfile } from "@/stores/auth-profile.store";
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

// The panel's identity, resolved once on the server instead of once per page
// load in the browser. EVERY failure degrades to `null`, which is exactly the
// behaviour this layout had before — the client fetches `/auth/me` itself and
// the shell shows its spinner until it lands — so neither an access cookie
// that merely expired (the refresh cookie rescues it client-side, which no
// layout can do: it cannot set cookies) nor an identity-svc outage turns an
// admin page into a 500.
async function resolveServerProfile(accessToken: string): Promise<AuthProfile | null> {
  try {
    const response = await fetchAuthProfileResponse(accessToken);
    if (!response.ok) {
      return null;
    }
    return mapAuthProfile(await response.json());
  } catch {
    return null;
  }
}

export default async function AdminLayout({ children }: Readonly<AdminLayoutProps>) {
  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);

  // Neither session cookie: there is nothing the browser could recover from, so
  // the visitor is signed out — bounce them off the zone before they download
  // any of it. `?login=1&next=` is the site's own sign-in entry (see
  // `LoginModalTrigger`): it opens the auth modal on `/` and returns here after.
  if (!accessToken && !getRefreshToken(cookieStore)) {
    const returnTo = (await headers()).get("x-owt-pathname") ?? "/admin";
    redirect(`/?login=1&next=${encodeURIComponent(returnTo)}`);
  }

  const [announcements, profile] = await Promise.all([
    resolveActiveAnnouncements(),
    accessToken ? resolveServerProfile(accessToken) : null
  ]);

  const defaultSidebarOpen =
    parseSidebarOpenCookie(cookieStore.get(SIDEBAR_COOKIE_NAMES.admin)?.value) ?? true;

  return (
    <ZoneIntlProvider zone="admin">
      {profile ? <AuthProfileSeed profile={profile} /> : null}
      <AdminLayoutClient
        defaultSidebarOpen={defaultSidebarOpen}
        announcements={withoutDismissedAnnouncements(
          announcements,
          cookieStore.get(DISMISSED_ANNOUNCEMENTS_COOKIE)?.value
        )}
      >
        {children}
      </AdminLayoutClient>
    </ZoneIntlProvider>
  );
}
