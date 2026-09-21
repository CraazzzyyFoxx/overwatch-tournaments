"use client";

import { useTranslations } from "next-intl";

import { HeroCoord } from "@/components/site/PageHero";
import type { DraftBoard } from "@/types/draft.types";

import { accentToken, resolveDraftAccent } from "@/lib/draft-visual";
import { DraftClockRing } from "./DraftClockRing";

interface CurrentPickProps {
  board: DraftBoard;
}

/**
 * Spectator-only. A captain reads the same state off `PickCommandBar`, which
 * is why nothing here is written in the second person.
 */
export function CurrentPick({ board }: Readonly<CurrentPickProps>) {
  const t = useTranslations("draftRedesign");
  const current = board.current_pick;
  const team = current
    ? board.teams.find((candidate) => candidate.id === current.draft_team_id) ?? null
    : null;
  const accent = resolveDraftAccent(board);
  const accentColor = accentToken(accent);
  const blocked = accent === "blocked";
  const paused = board.session.status === "paused";

  return (
    <section
      className="rounded-2xl border bg-[color:var(--aqt-card)] p-5 shadow-lg"
      style={{ borderColor: `color-mix(in srgb, ${accentColor} 45%, var(--aqt-border))` }}
      aria-labelledby="current-pick-heading"
    >
      <span aria-hidden className="mb-4 block h-0.5 w-12 rounded" style={{ background: accentColor }} />
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <HeroCoord>{t("currentPick")}</HeroCoord>
          <h2 id="current-pick-heading" className="mt-2 font-onest text-2xl font-semibold sm:text-3xl">
            {team?.name ?? t("noActivePick")}
          </h2>
          <p className="mt-2 text-sm text-[color:var(--aqt-fg-muted)]">
            {current
              ? t("pickMeta", { pick: current.overall_no, total: board.picks.length })
              : t("pickIdle")}
          </p>
        </div>
        <DraftClockRing
          expiresAt={current?.clock_expires_at ?? null}
          paused={paused}
          totalSeconds={board.session.pick_time_seconds}
          accent={accent}
        />
      </div>
      {(blocked || paused) && (
        <p className="mt-4 text-sm font-medium" style={{ color: accentColor }}>
          {!blocked
            ? t("organizerPaused")
            : board.session.blocked_reason === "order_recalculated"
              ? t("orderRecalculatedPaused")
              : t("roleShortagePaused")}
        </p>
      )}
    </section>
  );
}
