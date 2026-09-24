"use client";

import { Check, Hourglass } from "lucide-react";
import { useTranslations } from "next-intl";

import TeamName, { type TeamNameInput } from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import { Spinner } from "@/components/ui/spinner";

interface PregameReadinessProps {
  encounter: Encounter;
  readiness: { home: boolean; away: boolean };
  /** Null for a spectator: they watch the gate, they never confirm. */
  viewerSide: "home" | "away" | null;
  pending: boolean;
  onReady: () => void;
}

/**
 * The readiness gate as the room's own content, not a modal over placeholders.
 *
 * This used to be an `AlertDialog` floating over two `Skeleton` blocks, which
 * read as "the room is loading" — a shimmer that never resolves, because there
 * is genuinely nothing to load yet: the backend does not create either session
 * (`pick_ban_session.ensure_pick_ban_session`) until both captains confirm, so
 * the pool and the step sequence do not exist and cannot be rendered. Faking
 * them promised content that was not coming, and the modal's backdrop hid the
 * one thing that IS real in this state — the header's matchup and series
 * standing.
 *
 * So the room renders for real: header above, and this panel where the pool
 * will go, naming both sides and which of them the room is still waiting on.
 */
export function PregameReadiness({
  encounter,
  readiness,
  viewerSide,
  pending,
  onReady
}: Readonly<PregameReadinessProps>) {
  const t = useTranslations("pickBan.room");
  const viewerReady = viewerSide != null && readiness[viewerSide];

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-[color:var(--aqt-border)] p-4">
      <div className="flex flex-col gap-1">
        <h2 className="inline-flex items-center gap-2 font-onest text-lg font-semibold">
          <Hourglass className="h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]" aria-hidden />
          {t("notReadyTitle")}
        </h2>
        <p className="text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
          {t("notReadyHint")}
        </p>
      </div>

      <ul className="grid gap-2 sm:grid-cols-2">
        <ReadyRow
          team={encounter.home_team ?? null}
          fallbackName={t("side.home")}
          ready={readiness.home}
          accentVar="--aqt-teal"
        />
        <ReadyRow
          team={encounter.away_team ?? null}
          fallbackName={t("side.away")}
          ready={readiness.away}
          accentVar="--aqt-rose"
        />
      </ul>

      {viewerSide != null ? (
        viewerReady ? (
          <p className="text-sm text-[color:var(--aqt-support)]">
            {t("ready.confirmed")} · {t("ready.waitingOpponent")}
          </p>
        ) : (
          <div>
            <Button onClick={onReady} disabled={pending}>
              {pending ? <Spinner className="mr-2" /> : null}
              {pending ? t("ready.sending") : t("ready.button")}
            </Button>
          </div>
        )
      ) : null}
    </section>
  );
}

/** One side's readiness: logo, name, and a check or an hourglass. */
function ReadyRow({
  team,
  fallbackName,
  ready,
  accentVar
}: Readonly<{
  team: TeamNameInput | null;
  fallbackName: string;
  ready: boolean;
  accentVar: "--aqt-teal" | "--aqt-rose";
}>) {
  const t = useTranslations("pickBan.room");
  const StateIcon = ready ? Check : Hourglass;
  const stateLabel = ready ? t("ready.stateReady") : t("ready.statePending");

  return (
    <li
      className={cn(
        "flex min-w-0 items-center gap-2.5 rounded-lg border px-3 py-2.5",
        ready
          ? "border-[color:var(--aqt-support)]/35 bg-[color:var(--aqt-support)]/[0.06]"
          : "border-dashed border-[color:var(--aqt-border-2)]"
      )}
    >
      <TeamName
        team={team}
        fallback={fallbackName}
        size="md"
        className="flex-1 gap-2.5"
        nameClassName={cn(
          "text-sm font-semibold",
          accentVar === "--aqt-teal"
            ? "text-[color:var(--aqt-teal)]"
            : "text-[color:var(--aqt-rose)]"
        )}
      />
      <span
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 text-label uppercase tracking-label",
          ready ? "text-[color:var(--aqt-support)]" : "text-[color:var(--aqt-fg-faint)]"
        )}
      >
        <StateIcon className="h-3.5 w-3.5" aria-hidden />
        {stateLabel}
      </span>
    </li>
  );
}
