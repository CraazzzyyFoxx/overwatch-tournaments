"use client";

import { useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { isUrgent, remainingMs } from "@/lib/draft/logic";

interface DraftClockProps {
  expiresAt: string | null;
  paused: boolean;
  compact?: boolean;
}

/**
 * Local countdown from an absolute server deadline. At zero it waits for the
 * server event that will commit the autopick.
 */
export function DraftClock({ expiresAt, paused, compact = false }: Readonly<DraftClockProps>) {
  const t = useTranslations();
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (paused || !expiresAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [paused, expiresAt]);

  if (paused) {
    return (
      <span className="tabular-nums text-[color:var(--aqt-amber)]">
        {compact ? t("draft.clock.pauseCompact") : t("draft.clock.paused")}
      </span>
    );
  }
  if (!expiresAt || now === null) {
    return <span className="tabular-nums text-[color:var(--aqt-fg-muted)]">--</span>;
  }

  const ms = remainingMs(expiresAt, now);
  if (ms <= 0) {
    return (
      <span className="tabular-nums text-[color:var(--aqt-rose)]">
        {compact ? t("draft.clock.autoCompact") : t("draft.clock.autopicking")}
      </span>
    );
  }
  const seconds = Math.ceil(ms / 1000);
  const className = isUrgent(ms)
    ? "tabular-nums text-[color:var(--aqt-rose)] animate-pulse motion-reduce:animate-none"
    : "tabular-nums text-[color:var(--aqt-teal)]";
  return <span className={className}>{seconds}s</span>;
}
