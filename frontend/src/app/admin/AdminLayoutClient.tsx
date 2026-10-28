"use client";

import { Fragment, type CSSProperties, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { skipToken, useQuery } from "@tanstack/react-query";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { AdminSidebar } from "@/components/admin/AdminSidebar";
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
import { Skeleton } from "@/components/ui/skeleton";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { SIDEBAR_COOKIE_NAMES } from "@/lib/site/sidebar-cookies";
import { useWorkspaceStore } from "@/stores/workspace.store";

/** The page area's outline: a title row and one panel. Also `admin/loading.tsx`. */
export function AdminContentSkeleton() {
  return (
    <>
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-64 w-full rounded-xl" />
    </>
  );
}

/** The shell's own outline (sidebar column + header bar) while permissions load. */
function LoadingState() {
  const t = useTranslations("adminShell.layout");
  return (
    <div role="status" className="flex h-screen w-full">
      <span className="sr-only">{t("loading")}</span>
      <Skeleton className="hidden h-full w-[15.5rem] shrink-0 rounded-none md:block" />
      <div className="flex flex-1 flex-col">
        <Skeleton className="h-12 w-full rounded-none" />
        <div className="flex flex-col gap-4 p-4 md:px-5">
          <AdminContentSkeleton />
        </div>
      </div>
    </div>
  );
}

function UnauthorizedState() {
  const t = useTranslations("adminShell.layout");
  const router = useRouter();
  return (
    <main className="flex min-h-screen w-full items-center justify-center p-4">
      <PageStateCard
        state="error"
        headingLevel={1}
        className="w-full max-w-md"
        title={t("unauthorized")}
        description={t("noPermission")}
        actionLabel={t("goHome")}
        onAction={() => router.push("/")}
      />
    </main>
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
  const t = useTranslations("adminShell.layout");
  const tShell = useTranslations("adminShell");
  const pathname = usePathname();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const segments = pathname.split("/").filter(Boolean);
  const entityRef = getBreadcrumbEntityRef(segments, currentWorkspaceId);

  return (
    <Breadcrumb>
      <BreadcrumbList>
        {/* The root is the page the sidebar calls Dashboard: one name for it. */}
        <BreadcrumbItem>
          {segments.length > 1 ? (
            <BreadcrumbLink asChild>
              <HoverPrefetchLink href="/admin">{tShell("nav.dashboard")}</HoverPrefetchLink>
            </BreadcrumbLink>
          ) : (
            <BreadcrumbPage>{tShell("nav.dashboard")}</BreadcrumbPage>
          )}
        </BreadcrumbItem>
        {segments.slice(1).map((segment, index) => {
          const href = `/admin/${segments.slice(1, index + 2).join("/")}`;
          const isLast = index === segments.length - 2;
          const label =
            entityRef && index + 1 === entityRef.segmentIndex ? (
              <EntityBreadcrumbName
                queryKey={entityRef.queryKey}
                fallback={breadcrumbSegmentLabel(segment, (key) => t(key as never))}
              />
            ) : (
              breadcrumbSegmentLabel(segment, (key) => t(key as never))
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
                  <BreadcrumbLink asChild>
                    <HoverPrefetchLink href={href}>{label}</HoverPrefetchLink>
                  </BreadcrumbLink>
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
  "--sidebar-width-icon": "3.75rem"
} as CSSProperties;

type AdminLayoutClientProps = {
  children: ReactNode;
  defaultSidebarOpen: boolean;
};

export function AdminLayoutClient({ children, defaultSidebarOpen }: Readonly<AdminLayoutClientProps>) {
  const t = useTranslations("adminShell.layout");
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
    <TooltipProvider>
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
          {t("skipToContent")}
        </a>
        <AdminSidebar />
        <SidebarInset className="min-w-0">
          <header className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-3 border-b border-border/50 bg-background px-4 md:px-5">
            <SidebarTrigger />
            <Separator orientation="vertical" className="h-5" />
            <AdminBreadcrumb />
          </header>
          {/* Full-bleed on purpose: a centered 1720px cap left ~300px of dead
              gutter each side on a 2560 display. Wide tables scroll inside
              their own container, so the page itself never needs the cap.

              `overflow-x-clip`, never `overflow-x-hidden`: `hidden` on one axis
              forces the other to `auto`, which makes this div a scroll
              container that never scrolls — and every `position: sticky` inside
              (the row inspector) then sticks to it and never moves. `clip`
              trims the same overflow while leaving the y axis `visible`, so the
              window stays the scroll ancestor. */}
          <main
            id="admin-content"
            tabIndex={-1}
            className="flex w-full flex-1 flex-col gap-4 overflow-x-clip p-4 md:px-5"
          >
            {/* One drawer for the whole panel: every per-entity trail opens
                here, so no screen mounts its own copy and none can nest. */}
            <AuditTrailProvider>{children}</AuditTrailProvider>
          </main>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
