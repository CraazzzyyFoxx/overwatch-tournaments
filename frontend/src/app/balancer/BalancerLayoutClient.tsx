"use client";

import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { BalancerShell } from "@/app/balancer/components/BalancerShell";
import { BalancerSidebar } from "@/components/balancer/BalancerSidebar";
import { adminEntryPermissions } from "@/components/admin/admin-navigation";
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
        <p className="mt-4 text-muted-foreground">
          The balancer workspace is available only to admins and tournament organizers.
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

function formatBreadcrumbLabel(segment: string) {
  const normalized = segment.replace(/-/g, " ");
  if (/^\d+$/.test(normalized)) return "Details";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function BalancerBreadcrumb() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);

  return (
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink href="/balancer">Balancer</BreadcrumbLink>
        </BreadcrumbItem>
        {segments.slice(1).map((segment, index) => {
          const href = `/balancer/${segments.slice(1, index + 2).join("/")}`;
          const isLast = index === segments.length - 2;
          const label = formatBreadcrumbLabel(segment);

          return (
            <div key={`${segment}-${index}`} className="flex items-center gap-2">
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                {isLast ? (
                  <BreadcrumbPage>{label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink href={href}>{label}</BreadcrumbLink>
                )}
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
  "--sidebar-width-icon": "3.75rem"
} as CSSProperties;

type BalancerLayoutClientProps = {
  children: ReactNode;
  defaultSidebarOpen: boolean;
};

export function BalancerLayoutClient({ children, defaultSidebarOpen }: BalancerLayoutClientProps) {
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { isLoaded, isOrganizer, canAccessAdminRoute } = usePermissions();

  if (!isLoaded) {
    return <LoadingState />;
  }

  const hasAdminAccess = canAccessAdminRoute({
    permissions: adminEntryPermissions,
    workspaceId: currentWorkspaceId,
    workspaceAdminVisible: true
  });
  const hasAccess = hasAdminAccess || isOrganizer;

  if (!hasAccess) {
    return <UnauthorizedState />;
  }

  return (
    <SidebarProvider
      className="admin-theme xl:h-svh xl:overflow-hidden"
      cookieName={SIDEBAR_COOKIE_NAMES.balancer}
      defaultOpen={defaultSidebarOpen}
      style={sidebarShellStyle}
    >
      <BalancerSidebar />
      <SidebarInset className="min-h-svh min-w-0 bg-background/95 xl:h-svh xl:overflow-hidden md:peer-data-[variant=inset]:border md:peer-data-[variant=inset]:border-border/50 md:peer-data-[variant=inset]:shadow-xl md:peer-data-[variant=inset]:shadow-black/10">
        <header className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-3 border-b border-border/50 bg-background/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/82 md:px-5">
          <SidebarTrigger className="size-8 rounded-lg border border-border/60" />
          <Separator orientation="vertical" className="h-5" />
          <BalancerBreadcrumb />
          <div id="balancer-header-slot" className="ml-auto flex min-w-0 items-center gap-2" />
        </header>

        <div className="flex flex-1 flex-col gap-4 overflow-x-hidden p-3 xl:min-h-0 xl:overflow-hidden md:p-4">
          <BalancerShell>{children}</BalancerShell>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
