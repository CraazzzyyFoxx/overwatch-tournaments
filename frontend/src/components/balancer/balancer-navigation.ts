import { ArrowLeftRight, ClipboardList, FileSpreadsheet, Settings2, type LucideIcon, UserPlus } from "lucide-react";

import type { AppRole } from "@/hooks/usePermissions";

export type BalancerNavItem = {
  title: string;
  href: string;
  icon: LucideIcon;
  description: string;
};

export const balancerEntryRoles: AppRole[] = ["admin", "tournament_organizer"];

export const balancerNavigationItems: BalancerNavItem[] = [
  {
    title: "Workspace",
    href: "/balancer",
    icon: ArrowLeftRight,
    description: "Run balance candidates, tweak registrations, and export.",
  },
  {
    title: "Registrations",
    href: "/balancer/registrations",
    icon: UserPlus,
    description: "Manage registrations and balancer participation.",
  },
  {
    title: "Form",
    href: "/balancer/registrations/form",
    icon: ClipboardList,
    description: "Configure form fields and admission requirements.",
  },
  {
    title: "Google Sheets",
    href: "/balancer/registrations/feed",
    icon: FileSpreadsheet,
    description: "Configure feed sync, mapping, and source ingestion.",
  },
  {
    title: "Statuses",
    href: "/balancer/statuses",
    icon: Settings2,
    description: "Manage workspace-specific registration and balancer statuses.",
  },
];

export function isBalancerNavItemActive(pathname: string, href: string) {
  if (href === "/balancer") {
    return pathname === "/balancer";
  }

  if (href === "/balancer/registrations/feed") {
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  if (href === "/balancer/registrations/form") {
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  if (href === "/balancer/registrations") {
    return (
      pathname === href ||
      (pathname.startsWith(`${href}/`) &&
        !pathname.startsWith("/balancer/registrations/feed") &&
        !pathname.startsWith("/balancer/registrations/form"))
    );
  }

  return pathname === href || pathname.startsWith(`${href}/`);
}
