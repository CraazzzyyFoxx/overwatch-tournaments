"use client";

import { Eye, Radio, WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { DraftPresenceState, DraftTeam } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";

interface DraftConnectionStatusProps {
  state: RealtimeConnectionState;
  presence: DraftPresenceState;
  teams: DraftTeam[];
}

export function DraftConnectionStatus({ state, presence, teams }: DraftConnectionStatusProps) {
  const t = useTranslations("draftRedesign");
  const captainAuthIds = new Set(
    teams
      .map((team) => team.captain_auth_user_id)
      .filter((id): id is number => id != null)
  );
  const onlineCaptains = Object.keys(presence.users).filter((id) => captainAuthIds.has(Number(id))).length;
  const connected = state === "connected";
  return (
    <div
      className="flex flex-wrap items-center gap-x-6 gap-y-2 border-y border-[color:var(--aqt-border)] px-1 py-3 text-sm"
      role="status"
      aria-live="polite"
    >
      <span className="flex items-center gap-2">
        {connected ? (
          <Radio className="h-4 w-4 text-[color:var(--aqt-support)]" />
        ) : (
          <WifiOff className="h-4 w-4 text-[color:var(--aqt-warm)]" />
        )}
        <span className={cn("font-medium", !connected && "text-[color:var(--aqt-warm)]")}>
          {t(`connection.${state}`)}
        </span>
      </span>
      <span className="font-mono text-xs text-[color:var(--aqt-fg-muted)]">
        {t("captainsOnline", { online: onlineCaptains, total: teams.length })}
      </span>
      <span className="ml-auto flex items-center gap-2 font-mono text-xs text-[color:var(--aqt-fg-muted)]">
        <Eye className="h-4 w-4" />
        {t("anonymousViewers", { count: presence.anonymous_viewer_count })}
      </span>
    </div>
  );
}

