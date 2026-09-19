"use client";

import type { AdminTabItem } from "@/components/kit/AdminTabs";
import { useQueryParams } from "@/hooks/useQueryParams";

export interface CollectorSlot {
  key: string;
  label: string;
  /** Slots are optional: streams has no history, and Settings is superuser-only. */
  hidden?: boolean;
}

/**
 * Resolves `?tab=` against a collector's slots (F14 ·2).
 *
 * Shared by all three collector pages so the URL contract cannot drift between
 * them — the old screens kept the tab in `useState` (and subscriptions read
 * `?tab=` once at mount), which is exactly why Rank's and Streams' Settings
 * could not be linked to at all.
 *
 * An absent or unreachable tab falls back to the first visible slot instead of
 * 404ing: `?tab=settings` typed by a non-superuser is a link that lost its
 * audience, not a broken route.
 */
export function useCollectorTab(
  collector: string,
  slots: CollectorSlot[]
): { activeKey: string; items: AdminTabItem[] } {
  const { searchParams } = useQueryParams();
  const visible = slots.filter((slot) => !slot.hidden);
  const requested = searchParams?.get("tab") ?? "";

  return {
    activeKey: visible.some((slot) => slot.key === requested)
      ? requested
      : (visible[0]?.key ?? "status"),
    items: visible.map((slot) => ({
      key: slot.key,
      label: slot.label,
      href: `/admin/collectors/${collector}?tab=${slot.key}`
    }))
  };
}
