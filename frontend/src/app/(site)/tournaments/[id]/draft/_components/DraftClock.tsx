"use client";

import { useEffect, useState } from "react";

import { useTranslation } from "@/i18n/LanguageContext";
import { isUrgent, remainingMs } from "../_lib/draft-logic";

interface DraftClockProps {
  expiresAt: string | null;
  paused: boolean;
  compact?: boolean;
}

/**
 * Local countdown from an absolute server deadline. At zero it waits for the
 * server event that will commit the autopick.
 */
export function DraftClock({ expiresAt, paused, compact = false }: DraftClockProps) {
  const { t } = useTranslation();
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (paused || !expiresAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [paused, expiresAt]);

  if (paused) {
    return (
      <span className="font-mono tabular-nums text-amber-400">
        {compact ? t("draft.clock.pauseCompact") : t("draft.clock.paused")}
      </span>
    );
  }
  if (!expiresAt || now === null) {
    return <span className="font-mono tabular-nums text-[var(--aqt-fg-muted)]">--</span>;
  }

  const ms = remainingMs(expiresAt, now);
  if (ms <= 0) {
    return (
      <span className="font-mono tabular-nums text-rose-500">
        {compact ? t("draft.clock.autoCompact") : t("draft.clock.autopicking")}
      </span>
    );
  }
  const seconds = Math.ceil(ms / 1000);
  const className = isUrgent(ms)
    ? "font-mono tabular-nums text-rose-500 animate-pulse"
    : "font-mono tabular-nums text-[var(--aqt-teal)]";
  return <span className={className}>{seconds}s</span>;
}
