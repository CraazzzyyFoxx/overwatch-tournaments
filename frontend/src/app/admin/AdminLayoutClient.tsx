"use client";

import { type CSSProperties, type ReactNode, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { AdminSidebar } from "@/components/admin/AdminSidebar";
import { adminEntryPermissions, getMatchingAdminRoute } from "@/components/admin/admin-navigation";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { usePermissions } from "@/hooks/usePermissions";
import { SIDEBAR_COOKIE_NAMES } from "@/lib/sidebar-cookies";
import { useWorkspaceStore } from "@/stores/workspace.store";

function LoadingState() {
  return (
    <div className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <div className="inline-block size-8 animate-spin rounded-full border-4 border-current border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]" />
        <p className="mt-4 text-muted-foreground">Loading...</p>
      </div>
    </div>
  );
}

function UnauthorizedState() {
  return (
    <div className="flex h-screen w-full items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold">Unauthorized</h1>
        <p className="mt-4 text-muted-foreground">You do not have permission to access the admin panel.</p>
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

function formatBreadcrumbLabel(segment: string) {
  const normalized = segment.replace(/-/g, " ");
  if (/^\d+$/.test(normalized)) {
    return "Details";
  }

  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function AdminBreadcrumb() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);

  return (
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink href="/admin">Admin</BreadcrumbLink>
        </BreadcrumbItem>
        {segments.slice(1).map((segment, index) => {
          const href = `/admin/${segments.slice(1, index + 2).join("/")}`;
          const isLast = index === segments.length - 2;
          const label = formatBreadcrumbLabel(segment);

          return (
            <div key={`${segment}-${index}`} className="flex items-center gap-2">
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                {isLast ? <BreadcrumbPage>{label}</BreadcrumbPage> : <BreadcrumbLink href={href}>{label}</BreadcrumbLink>}
              </BreadcrumbItem>
            </div>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}

const sidebarShellStyle = {
  "--sidebar-width": "15.5rem",
  "--sidebar-width-icon": "3.75rem",
} as CSSProperties;

type AdminLayoutClientProps = {
  children: ReactNode;
  defaultSidebarOpen: boolean;
};

export function AdminLayoutClient({ children, defaultSidebarOpen }: AdminLayoutClientProps) {
  const pathname = usePathname();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const { isLoaded, canAccessAdminRoute } = usePermissions();

  useEffect(() => {
    document.body.classList.add("admin-theme");
    return () => document.body.classList.remove("admin-theme");
  }, []);

  if (!isLoaded) {
    return <LoadingState />;
  }

  const matchingRoute = getMatchingAdminRoute(pathname);
  const hasAccess = matchingRoute
    ? canAccessAdminRoute({
        permissions: matchingRoute.permissions,
        workspaceId: matchingRoute.workspaceAdminVisible ? null : currentWorkspaceId,
        globalOnly: matchingRoute.globalOnly,
        workspaceAdminVisible: matchingRoute.workspaceAdminVisible,
        superuserOnly: matchingRoute.superuserOnly,
      })
    : canAccessAdminRoute({
        permissions: adminEntryPermissions,
        workspaceId: currentWorkspaceId,
      });

  if (!hasAccess) {
    return <UnauthorizedState />;
  }

  return (
    <TooltipProvider delayDuration={300}>
      <SidebarProvider
        className="admin-theme"
        cookieName={SIDEBAR_COOKIE_NAMES.admin}
        defaultOpen={defaultSidebarOpen}
        style={sidebarShellStyle}
      >
        <AdminSidebar />
        <SidebarInset className="min-h-svh min-w-0 bg-background/95 md:peer-data-[variant=inset]:border md:peer-data-[variant=inset]:border-border/50 md:peer-data-[variant=inset]:shadow-xl md:peer-data-[variant=inset]:shadow-black/10">
          <header className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-3 border-b border-border/50 bg-background/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/82 md:px-5">
            <SidebarTrigger className="size-8 rounded-lg border border-border/60" />
            <Separator orientation="vertical" className="h-5" />
            <AdminBreadcrumb />
          </header>

          <div className="flex flex-1 flex-col gap-4 overflow-x-hidden p-4">{children}</div>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
