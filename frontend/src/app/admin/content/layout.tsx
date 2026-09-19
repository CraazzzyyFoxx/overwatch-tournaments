"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTabs, type AdminTabItem } from "@/components/kit/AdminTabs";

import { useOpenMissCount } from "./miss-queue";

const TABS = [
  { key: "heroes", label: "Heroes" },
  { key: "maps", label: "Maps" },
  { key: "gamemodes", label: "Gamemodes" },
  { key: "unresolved", label: "Unresolved names" }
] as const;

/**
 * Game content (F13): three catalogues the log parser reads, plus the triage
 * queue of names it could not resolve.
 *
 * The queue is not a fourth catalogue — it shares no code with the other
 * three — but it is the work the catalogues exist to absorb, so it sits beside
 * them with a badge saying how much of it is waiting.
 *
 * Navigation and chrome only: the tabs own no data beyond that count, and each
 * page keeps its own toolbar in the table.
 */
export default function GameContentLayout({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  // `/admin/content/<tab>` — the bare root redirects, so the fallback only
  // covers the frame between navigation and that redirect landing.
  const activeKey = pathname.split("/")[3] ?? TABS[0].key;
  const openMisses = useOpenMissCount();

  const items: AdminTabItem[] = TABS.map((tab) => ({
    key: tab.key,
    label: tab.label,
    href: `/admin/content/${tab.key}`,
    // An empty queue is not news: no badge rather than a zero.
    badge: tab.key === "unresolved" ? openMisses || undefined : undefined
  }));

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Game content"
        description="Heroes, maps and gamemodes used by the log parser and analytics."
      />
      <AdminTabs items={items} activeKey={activeKey} level={1} ariaLabel="Game content sections" />
      {children}
    </div>
  );
}
