import React from "react";
import { cookies, headers } from "next/headers";
import Header from "@/components/Header";
import { Footer } from "@/components/Footer";
import AnnouncementBanner from "@/components/notifications/AnnouncementBanner";
import { Separator } from "@/components/ui/separator";
import notificationService from "@/services/notification.service";
import workspaceService from "@/services/workspace.service";
import {
  DISMISSED_ANNOUNCEMENTS_COOKIE,
  withoutDismissedAnnouncements
} from "@/lib/notifications/announcement-dismissed";
import { deriveWorkspacePalette } from "@/lib/workspace/theme";
import { WorkspaceThemeSync } from "@/components/workspace/WorkspaceThemeSync";
import { WorkspaceHostLock } from "@/components/workspace/WorkspaceHostLock";
import ZoneIntlProvider from "@/i18n/ZoneIntlProvider";
import type { NotificationItem } from "@/types/notification.types";
import type { Workspace } from "@/types/workspace.types";

// Resolve the current workspace server-side. On a tenant (white-label) host
// `proxy.ts` (Task 6) injects `x-owt-workspace-id` — authoritative, host
// beats cookie — so the palette seed and the tenant header logo both follow the
// host, not a stale cookie. On the apex we fall back to the workspace cookie
// (legacy `aqt-` as a second fallback). Failures degrade to null.
async function resolveCurrentWorkspace(): Promise<Workspace | null> {
  try {
    const h = await headers();
    const cookieStore = await cookies();
    const raw =
      h.get("x-owt-workspace-id") ??
      cookieStore.get("owt-workspace-id")?.value ??
      cookieStore.get("aqt-workspace-id")?.value;
    const id = raw ? Number(raw) : NaN;
    if (!Number.isFinite(id)) return null;
    return await workspaceService.getById(id);
  } catch {
    return null;
  }
}

// Active announcements, server-side, so the banner is in the first paint rather
// than dropping in after hydration and pushing the page down. The read is
// `AuthOptional`, so it works for an anonymous visitor too.
//
// `undefined` on failure, never `[]`: an empty array is a legitimate answer
// ("nothing to announce") that the banner would trust for a full staleTime,
// which would swallow a real announcement whenever SSR could not reach the
// gateway. Undefined lets the client fetch it instead.
async function resolveActiveAnnouncements(): Promise<NotificationItem[] | undefined> {
  try {
    return await notificationService.activeAnnouncements();
  } catch {
    return undefined;
  }
}

export default async function SiteLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const requestHeaders = await headers();
  const tenantMode = requestHeaders.get("x-owt-host-mode") === "tenant";
  // Custom workspace branding is tenant-only: a subdomain / custom-domain host
  // paints its workspace's palette. The shared platform (apex) host applies no
  // customization at all, so it needs neither the workspace nor a palette seed.
  const [workspace, announcements, cookieStore] = await Promise.all([
    tenantMode ? resolveCurrentWorkspace() : null,
    resolveActiveAnnouncements(),
    cookies()
  ]);

  const seed = workspace ? deriveWorkspacePalette(workspace) : null;
  const style: React.CSSProperties | undefined = seed
    ? ({ ...seed, backgroundColor: "var(--aqt-bg)" } as React.CSSProperties)
    : undefined;

  // On a tenant host the workspace switcher is replaced by the workspace's own
  // logo (icon + name) linking home; on the apex the switcher is shown.
  const tenantWorkspace =
    tenantMode && workspace
      ? { name: workspace.name, iconUrl: workspace.icon_url }
      : undefined;

  return (
    <ZoneIntlProvider zone="web">
      <div className="site-theme min-h-screen w-full" style={style}>
        <WorkspaceHostLock workspaceId={tenantMode && workspace ? workspace.id : null} />
        <WorkspaceThemeSync />
        <div className="w-full max-w-screen-3xl pt-6 mx-auto px-4 md:px-6 xl:px-10 h-full">
          <Header tenantMode={tenantMode} tenantWorkspace={tenantWorkspace} />
          <AnnouncementBanner
            initial={withoutDismissedAnnouncements(
              announcements,
              cookieStore.get(DISMISSED_ANNOUNCEMENTS_COOKIE)?.value
            )}
          />
          <div className="flex w-full flex-col min-h-[95%]">
            <main id="main-content" tabIndex={-1} className="flex flex-1 flex-col gap-4 pt-4 md:gap-8 md:pt-8">
              {children}
            </main>
          </div>
          <Separator className="mt-8" />
          <Footer />
        </div>
      </div>
    </ZoneIntlProvider>
  );
}
