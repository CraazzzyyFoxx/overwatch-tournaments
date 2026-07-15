"use client";

import { Clock3, Pause, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { HeroCoord } from "@/components/site/PageHero";
import type { DraftBoard } from "@/types/draft.types";

import { DraftClock } from "./DraftClock";

interface CurrentPickProps {
  board: DraftBoard;
  isMyPick?: boolean;
}

export function CurrentPick({ board, isMyPick = false }: CurrentPickProps) {
  const t = useTranslations("draftRedesign");
  const current = board.current_pick;
  const team = current
    ? board.teams.find((candidate) => candidate.id === current.draft_team_id) ?? null
    : null;
  const blocked = board.session.blocked_reason === "role_shortage";
  return (
    <section className="border-b border-[color:var(--aqt-border)] pb-5" aria-labelledby="current-pick-heading">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <HeroCoord>{isMyPick ? t("yourTurn") : t("currentPick")}</HeroCoord>
          <h2 id="current-pick-heading" className="mt-2 font-onest text-2xl font-semibold sm:text-3xl">
            {team?.name ?? t("noActivePick")}
          </h2>
          <p className="mt-2 text-sm text-[color:var(--aqt-fg-muted)]">
            {current
              ? t("pickMeta", { pick: current.overall_no, total: board.picks.length })
              : t("pickIdle")}
          </p>
        </div>
        <div className="flex min-h-14 items-center gap-3 rounded-xl bg-[color:var(--aqt-card-2)] px-4">
          {blocked ? (
            <ShieldAlert className="h-5 w-5 text-[color:var(--aqt-live)]" />
          ) : board.session.status === "paused" ? (
            <Pause className="h-5 w-5 text-[color:var(--aqt-warm)]" />
          ) : (
            <Clock3 className="h-5 w-5 text-[color:var(--aqt-teal)]" />
          )}
          <span className="font-onest text-2xl font-semibold tabular-nums">
            <DraftClock
              expiresAt={current?.clock_expires_at ?? null}
              paused={board.session.status === "paused"}
              compact
            />
          </span>
        </div>
      </div>
      {(blocked || board.session.status === "paused") && (
        <div className="mt-4 border-l-2 border-[color:var(--aqt-warm)] pl-3 text-sm text-[color:var(--aqt-fg-muted)]">
          {blocked ? t("roleShortagePaused") : t("organizerPaused")}
        </div>
      )}
    </section>
  );
}
