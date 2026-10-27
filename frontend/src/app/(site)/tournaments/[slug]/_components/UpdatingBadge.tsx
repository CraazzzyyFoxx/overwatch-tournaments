"use client";

import { useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";

const subscribeNoop = () => () => {};

/**
 * The "a background refresh is in flight" affordance for every tournament data
 * page. It was copied byte-for-byte into five pages; a single definition keeps
 * the one polite live region, the one accessible name and the
 * reduced-motion-safe spinner from drifting apart.
 *
 * Renders nothing until the page has hydrated. A refresh in flight is browser
 * state the server render never has — the shell's realtime catch-up, or data
 * that went stale while the page loaded, starts one before a tab's Suspense
 * boundary hydrates — so a badge in the hydrating render was a mismatch that
 * threw the whole tab away. It appears on the re-render right after.
 */
export function UpdatingBadge() {
  const t = useTranslations();
  const isHydrated = useSyncExternalStore(subscribeNoop, () => true, () => false);
  if (!isHydrated) return null;

  return (
    <Badge
      tone="accent"
      shape="pill"
      className="pointer-events-none fixed bottom-5 right-5 z-40 size-9 justify-center p-0 backdrop-blur-md"
      role="status"
      aria-live="polite"
      aria-label={t("tournamentDetail.pageState.updating")}
    >
      <Spinner />
    </Badge>
  );
}
