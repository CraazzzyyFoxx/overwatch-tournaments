"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Trophy } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail
} from "@/components/ui/sidebar";
import {
  balancerNavigationItems,
  isBalancerNavItemActive
} from "@/components/balancer/balancer-navigation";
import tournamentService from "@/services/tournament.service";
import {
  SidebarBackToSite,
  SidebarUserDropdown,
  SidebarWorkspaceLogoItem
} from "@/components/sidebar/sidebar-shared";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Tournament switcher
// ---------------------------------------------------------------------------

function SidebarTournamentSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  const raw = searchParams.get("tournament");
  const selectedId = raw ? Number(raw) : null;
  const validSelectedId = selectedId && Number.isFinite(selectedId) ? selectedId : null;

  const tournamentsQuery = useQuery({
    queryKey: ["balancer-public", "tournaments"],
    queryFn: () => tournamentService.getAll(),
    staleTime: Number.POSITIVE_INFINITY
  });

  const tournaments = tournamentsQuery.data?.results ?? [];
  const current = tournaments.find((t) => t.id === validSelectedId);

  useEffect(() => {
    if (validSelectedId !== null || tournaments.length === 0) return;
    const latest = tournaments[0];
    const params = new URLSearchParams(searchParams.toString());
    params.set("tournament", String(latest.id));
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  }, [tournaments, validSelectedId, pathname, router, searchParams]);

  const handleSelect = (id: number) => {
    const params = new URLSearchParams(searchParams.toString());
    if (id === validSelectedId) {
      params.delete("tournament");
    } else {
      params.set("tournament", String(id));
    }
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  };

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="h-10 rounded-lg px-2.5 text-sidebar-foreground/78 hover:text-sidebar-foreground group-data-[collapsible=icon]:justify-center"
            >
              <Trophy className="size-4 shrink-0" />
              <div className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
                <span className="truncate text-sm font-medium text-sidebar-foreground">
                  {current?.name ?? "Select tournament"}
                </span>
                {current && (
                  <span className="truncate text-[11px] text-sidebar-foreground/55">
                    #{current.id}
                  </span>
                )}
              </div>
              <ChevronsUpDown className="ml-auto size-4 text-sidebar-foreground/50 group-data-[collapsible=icon]:hidden" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-[--radix-dropdown-menu-trigger-width] min-w-56 max-h-80 overflow-y-auto"
            side="bottom"
            align="start"
            sideOffset={6}
          >
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              Tournaments
            </DropdownMenuLabel>
            {tournaments.length === 0 && (
              <DropdownMenuItem disabled className="text-xs text-muted-foreground">
                No tournaments found
              </DropdownMenuItem>
            )}
            {tournaments.map((t) => {
              const isActive = t.id === validSelectedId;
              return (
                <DropdownMenuItem
                  key={t.id}
                  onClick={() => handleSelect(t.id)}
                  className="gap-2.5 px-2 py-1.5"
                >
                  <Trophy className="size-4 shrink-0 text-muted-foreground" />
                  <span className="flex-1 truncate text-sm">{t.name}</span>
                  {isActive && <Check className="size-4 shrink-0" />}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

// ---------------------------------------------------------------------------
// Main sidebar
// ---------------------------------------------------------------------------

export function BalancerSidebar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return (
    <Sidebar collapsible="icon" variant="inset">
      <SidebarHeader className="px-3 pt-3 pb-2 group-data-[collapsible=icon]:px-1">
        <SidebarWorkspaceLogoItem href="/balancer" />
      </SidebarHeader>

      <SidebarContent className="px-2 pt-1 group-data-[collapsible=icon]:px-1">
        {/* Tournament switcher */}
        <SidebarGroup className="px-0 py-0">
          <div className="flex items-center gap-2 px-3 py-1.5 group-data-[collapsible=icon]:hidden">
            <span className="text-[11px] font-medium text-sidebar-foreground/30">Tournament</span>
          </div>
          <SidebarGroupContent>
            <SidebarTournamentSwitcher />
          </SidebarGroupContent>
        </SidebarGroup>

        <div className="mx-2 my-2 h-px bg-sidebar-border/40 group-data-[collapsible=icon]:mx-1" />

        {/* Navigation */}
        <SidebarGroup className="px-0 py-0">
          <div className="flex items-center gap-2 px-3 py-1.5 group-data-[collapsible=icon]:hidden">
            <span className="text-[11px] font-medium text-sidebar-foreground/30">Navigation</span>
          </div>
          <SidebarGroupContent>
            <SidebarMenu>
              {balancerNavigationItems.map((item) => {
                const isActive = isBalancerNavItemActive(pathname, item.href);
                const query = searchParams.toString();
                const href = query ? `${item.href}?${query}` : item.href;

                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActive}
                      tooltip={item.title}
                      className={cn(
                        "relative h-[30px] rounded-md px-2.5 text-[13px] transition-all",
                        "text-sidebar-foreground/55 hover:text-sidebar-foreground hover:bg-sidebar-accent/60",
                        isActive && [
                          "bg-sidebar-accent text-sidebar-foreground font-medium",
                          "before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2",
                          "before:h-4 before:w-[2px] before:rounded-full before:bg-sidebar-primary"
                        ]
                      )}
                    >
                      <Link href={href}>
                        <item.icon
                          className={cn(
                            "size-5",
                            isActive ? "text-sidebar-primary" : "text-sidebar-foreground/40"
                          )}
                        />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="px-2 pb-2 pt-0 group-data-[collapsible=icon]:px-1">
        <div className="mx-2 mb-1.5 h-px bg-sidebar-border/40" />
        <SidebarBackToSite />
        <SidebarUserDropdown />
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
