"use client";

import { Fragment, type CSSProperties, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { skipToken, useQuery } from "@tanstack/react-query";

import { AdminSidebar } from "@/components/admin/AdminSidebar";
import AnnouncementBanner from "@/components/notifications/AnnouncementBanner";
import { AuditTrailProvider } from "@/components/kit/AuditTrailSheet";
import { adminRouteAccessOptions } from "@/components/admin/admin-navigation";
import {
  getBreadcrumbEntityRef,
  breadcrumbSegmentLabel
} from "@/components/admin/breadcrumb-registry";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator
} from "@/components/ui/breadcrumb";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { usePermissions } from "@/hooks/usePermissions";
import { SIDEBAR_COOKIE_NAMES } from "@/lib/sidebar-cookies";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { NotificationItem } from "@/types/notification.types";

function LoadingState() {
  return (
    <div className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <div className="inline-block size-8 animate-spin rounded-full border-4 border-current border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]" />
        <p className="mt-4 text-muted-foreground">Loading…</p>
      </div>
    </div>
  );
}

function UnauthorizedState() {
  return (
    <div className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">Unauthorized</h1>
        <p className="mt-4 text-muted-foreground">
          You do not have permission to access the admin panel.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Please contact an administrator if you believe this is an error.
        </p>
        <Link
          href="/"
          className="mt-6 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Go Home
        </Link>
      </div>
    </div>
  );
}

function EntityBreadcrumbName({
  queryKey,
  fallback
}: Readonly<{
  queryKey: readonly unknown[];
  fallback: string;
}>) {
  const { data } = useQuery({ queryKey, queryFn: skipToken });
  const name = (data as { name?: unknown } | undefined)?.name;
  return <>{typeof name === "string" && name ? name : fallback}</>;
}

function AdminBreadcrumb() {
  const pathname = usePathname();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const segments = pathname.split("/").filter(Boolean);
  const entityRef = getBreadcrumbEntityRef(segments, currentWorkspaceId);

  return (
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink href="/admin">Admin</BreadcrumbLink>
        </BreadcrumbItem>
        {segments.slice(1).map((segment, index) => {
          const href = `/admin/${segments.slice(1, index + 2).join("/")}`;
          const isLast = index === segments.length - 2;
          const label =
            entityRef && index + 1 === entityRef.segmentIndex ? (
              <EntityBreadcrumbName
                queryKey={entityRef.queryKey}
                fallback={breadcrumbSegmentLabel(segment)}
              />
            ) : (
              breadcrumbSegmentLabel(segment)
            );

          return (
            // Fragment, not a <div>: BreadcrumbList renders an <ol>, which
            // admits only <li> children. The wrapper broke list semantics on
            // every admin page.
            <Fragment key={`${segment}-${index}`}>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                {isLast ? (
                  <BreadcrumbPage>{label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink href={href}>{label}</BreadcrumbLink>
                )}
              </BreadcrumbItem>
            </Fragment>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}

const sidebarShellStyle = {
  "--sidebar-width": "15.5rem",
  "--sidebar-width-icon": "3.75rem",
  // The floating announcement anchors to `--aqt-banner-top`; the admin header
  // is `h-12`, shorter than the site's, so it gets its own clearance instead of
  // the site default (`--aqt-sticky-top`).
  "--aqt-banner-top": "3.75rem"
} as CSSProperties;

type AdminLayoutClientProps = {
  children: ReactNode;
  defaultSidebarOpen: boolean;
  /** Server-rendered active announcements; `undefined` when the server-side
   *  read failed, which makes the banner fetch them itself. */
  announcements: NotificationItem[] | undefined;
};

export function AdminLayoutClient({
  children,
  defaultSidebarOpen,
  announcements
}: Readonly<AdminLayoutClientProps>) {
  const pathname = usePathname();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const { isLoaded, canAccessAdminRoute } = usePermissions();

  if (!isLoaded) {
    return <LoadingState />;
  }

  const hasAccess = canAccessAdminRoute(adminRouteAccessOptions(pathname, currentWorkspaceId));

  if (!hasAccess) {
    return <UnauthorizedState />;
  }

  return (
    <TooltipProvider delayDuration={300}>
      <SidebarProvider
        cookieName={SIDEBAR_COOKIE_NAMES.admin}
        defaultOpen={defaultSidebarOpen}
        style={sidebarShellStyle}
      >
        {/* First focusable element: the sidebar puts ~30 nav links before the
            page content, so keyboard users need a way past them. */}
        <a
          href="#admin-content"
          className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:rounded-lg focus-visible:bg-primary focus-visible:px-3 focus-visible:py-2 focus-visible:text-sm focus-visible:font-medium focus-visible:text-primary-foreground"
        >
          Skip to content
        </a>
        <AdminSidebar />
        <SidebarInset className="min-w-0">
          <header className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-3 border-b border-border/50 bg-background/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80 md:px-5">
            <SidebarTrigger className="size-8 rounded-lg border border-border/60" />
            <Separator orientation="vertical" className="h-5" />
            <AdminBreadcrumb />
          </header>
          {/* Overlay chrome, not a row: it floats over the content below rather
              than displacing every admin screen by its own height. */}
          <AnnouncementBanner initial={announcements} />

          {/* Full-bleed on purpose: a centered 1720px cap left ~300px of dead
              gutter each side on a 2560 display. Wide tables scroll inside
              their own container, so the page itself never needs the cap.

              `overflow-x-clip`, never `overflow-x-hidden`: `hidden` on one axis
              forces the other to `auto`, which makes this div a scroll
              container that never scrolls — and every `position: sticky` inside
              (the row inspector) then sticks to it and never moves. `clip`
              trims the same overflow while leaving the y axis `visible`, so the
              window stays the scroll ancestor. */}
          <div
            id="admin-content"
            tabIndex={-1}
            className="flex w-full flex-1 flex-col gap-4 overflow-x-clip p-4 md:px-5"
          >
            {/* One drawer for the whole panel: every per-entity trail opens
                here, so no screen mounts its own copy and none can nest. */}
            <AuditTrailProvider>{children}</AuditTrailProvider>
          </div>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
