"use client";

import { Eye, Radio, WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";

import { teamInitials } from "@/app/(site)/tournaments/components/tournaments-helpers";
import { cn } from "@/lib/utils";
import type { DraftPresenceState, DraftTeam } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";

interface DraftConnectionStatusProps {
  state: RealtimeConnectionState;
  presence: DraftPresenceState;
  teams: DraftTeam[];
  currentUserId?: number | null;
}

export function DraftConnectionStatus({ state, presence, teams, currentUserId }: DraftConnectionStatusProps) {
  const t = useTranslations("draftRedesign");
  const captainAuthIds = new Set(
    teams
      .map((team) => team.captain_auth_user_id)
      .filter((id): id is number => id != null)
  );
  const onlineCaptains = Object.keys(presence.users).filter((id) => captainAuthIds.has(Number(id))).length;
  const connected = state === "connected";
  return (
    <div className="border-y border-[color:var(--aqt-border)] px-1 py-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm" role="status" aria-live="polite">
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
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {teams.map((team) => {
          const isOnline = team.captain_auth_user_id != null && presence.users[team.captain_auth_user_id] != null;
          const isYou = currentUserId != null && team.captain_auth_user_id === currentUserId;
          const dotLabel = isOnline ? t("captainOnline") : t("captainOffline");
          return (
            <span
              key={team.id}
              className="flex items-center gap-1.5 rounded-full border border-[color:var(--aqt-border)] px-2 py-1 text-xs"
            >
              <span className="grid h-5 w-5 place-items-center rounded-full bg-[color:var(--aqt-card-2)] text-[10px] font-semibold">
                {teamInitials(team.name)}
              </span>
              <span className="font-medium">{team.name}</span>
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  isOnline ? "bg-[color:var(--aqt-support)]" : "bg-[color:var(--aqt-fg-faint)]"
                )}
                title={dotLabel}
                aria-label={dotLabel}
              />
              {isYou ? (
                <span className="font-mono text-[10px] text-[color:var(--aqt-teal)]">{t("you")}</span>
              ) : null}
            </span>
          );
        })}
      </div>
    </div>
  );
}

