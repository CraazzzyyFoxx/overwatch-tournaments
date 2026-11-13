"use client";

import { useTranslations } from "next-intl";

import { useLiveMinutes } from "@/app/balancer/mix/_hooks/useLiveMinutes";
import { StatusDot } from "@craazzzyyfoxx/admin-kit/ui/status-dot";
import { cn } from "@/lib/utils";
import type { MixLobbyState } from "@/services/custom-game.service";

const STAGE_TONE = {
  idle: "neutral",
  ready: "accent",
  pregame: "accent",
  live: "danger",
  draft_setup: "accent",
  draft_live: "danger"
} as const;

/**
 * A lobby's stage (spec §5) as one status: its dot and word, and -- given `startedAt`, once its match or its draft
 * runs -- for how long. There is no automatic timeout, so the minutes are how a host notices a match nobody recorded.
 * One fact, said where the lobby is named: the mix header, a room's title row, a lobby card.
 */
export function LobbyStage({
  state,
  startedAt,
  className
}: Readonly<{ state: MixLobbyState; startedAt?: string | null; className?: string }>) {
  const t = useTranslations("mixes.room");
  const minutes = useLiveMinutes(state, startedAt);
  return (
    <span className={cn("flex shrink-0 items-center gap-1.5 text-caption text-[color:var(--aqt-fg-muted)]", className)}>
      <StatusDot tone={STAGE_TONE[state]} pulse={state === "live" || state === "draft_live"} className="size-2" />
      {t(`state.${state}`)}
      {minutes != null ? (
        <span className="aqt-tnum text-[color:var(--aqt-fg-dim)]">{`· ${t("elapsed", { minutes })}`}</span>
      ) : null}
    </span>
  );
}
