"use client";

import { Eye, Radio } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { DraftPresenceState, DraftTeam } from "@/types/draft.types";

import { captainPresenceRows } from "./admin-control-model";

interface CaptainPresenceProps {
  teams: DraftTeam[];
  presence: DraftPresenceState;
}

export function CaptainPresence({ teams, presence }: CaptainPresenceProps) {
  const t = useTranslations("draftAdmin.controlRoom");
  const rows = captainPresenceRows(teams, presence);
  const online = rows.filter((row) => row.connected).length;
  return (
    <section aria-labelledby="captain-presence-heading" className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 id="captain-presence-heading" className="font-onest text-base font-semibold">
            {t("captainPresence")}
          </h3>
          <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">
            {t("captainPresenceCount", { online, total: rows.length })}
          </p>
        </div>
        <span className="flex items-center gap-2 font-mono text-xs text-[color:var(--aqt-fg-muted)]">
          <Eye className="h-4 w-4" />
          {presence.anonymous_viewer_count}
        </span>
      </div>
      <div className="space-y-1">
        {rows.map((row) => (
          <div
            key={row.teamId}
            className="flex min-h-11 items-center gap-3 border-t border-[color:var(--aqt-border)] py-2 first:border-t-0"
          >
            <span
              className={cn(
                "grid h-8 w-8 place-items-center rounded-lg bg-[color:var(--aqt-card-2)] font-onest text-xs font-semibold",
                row.connected && "text-[color:var(--aqt-teal)]"
              )}
            >
              {row.teamName.slice(0, 2).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{row.teamName}</span>
            <span className="flex items-center gap-1.5 text-xs text-[color:var(--aqt-fg-muted)]">
              <Radio
                className={cn(
                  "h-3.5 w-3.5",
                  row.connected ? "text-[color:var(--aqt-support)]" : "text-[color:var(--aqt-fg-faint)]"
                )}
              />
              {row.connected ? t("connected") : t("offline")}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

