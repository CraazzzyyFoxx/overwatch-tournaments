"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ArrowUpRight, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { DraftClock } from "@/components/draft/DraftClock";
import { useDraftFeasibilityQuery, useDraftRealtime } from "@/hooks/useDraftData";
import { Button } from "@/components/ui/button";
import { HeroCoord, HeroFrame } from "@/components/site/PageHero";
import type { DraftBoard } from "@/types/draft.types";

import { DraftHistoryPanel } from "./DraftHistoryPanel";
import { FeasibilityStatus } from "./FeasibilityStatus";
import { LifecycleControls } from "./LifecycleControls";
import { ResolveRoleConflictDialog } from "./ResolveRoleConflictDialog";

interface AdminControlRoomProps {
  tournamentId: number;
  board: DraftBoard;
}

const BLOCKED_REASONS = ["role_shortage", "order_recalculated"] as const;

/**
 * The organizer's control page for a live draft.
 *
 * Running the draft happens in the draft room itself (`/draft/{id}`), which
 * carries the admin dock: pause, resume, extra time, autopick and override sit
 * beside the board they act on. What stays here is what the room is NOT: the
 * session's state at a glance, feasibility, the destructive lifecycle actions
 * that end or rewind the session, and the tournament's draft history.
 */
export function AdminControlRoom({ tournamentId, board }: Readonly<AdminControlRoomProps>) {
  const t = useTranslations("draftAdmin.controlRoom");
  const [roleDialogOpen, setRoleDialogOpen] = useState(false);
  // Subscribed here too: the status, clock and feasibility below must follow
  // the picks made in the room without a manual reload.
  const { connectionState } = useDraftRealtime(tournamentId, board);
  const feasibilityQuery = useDraftFeasibilityQuery(board.session.id);
  const feasibility = feasibilityQuery.data ?? null;
  const session = board.session;
  const currentPick = board.current_pick;
  const currentTeam = currentPick
    ? board.teams.find((team) => team.id === currentPick.draft_team_id) ?? null
    : null;
  const shouldResolve = session.blocked_reason === "role_shortage" || feasibility?.is_feasible === false;
  // Only translate reasons the messages actually carry; anything else (a newer
  // backend than this build) falls back to the raw code.
  const blockedReason = BLOCKED_REASONS.find((reason) => reason === session.blocked_reason);

  return (
    <div className="space-y-5 text-[color:var(--aqt-fg)]">
      <HeroFrame>
        <div className="flex flex-col gap-6 px-5 py-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="min-w-0">
            <div className="flex flex-wrap gap-4">
              <HeroCoord>{t("adminCoordinate", { id: session.id })}</HeroCoord>
              <HeroCoord>{t(`status.${session.status}`)}</HeroCoord>
            </div>
            {/* The clock is deliberately outside the live region: it ticks four
                times a second and would re-announce the whole strip with it. */}
            <div role="status" className="mt-4">
              <p className="font-mono text-xs uppercase tracking-wider tabular-nums text-[color:var(--aqt-teal)]">
                {currentPick
                  ? t("onTheClock", {
                      round: currentPick.round_no,
                      pick: currentPick.overall_no,
                      total: board.picks.length
                    })
                  : t("currentPickEmpty")}
              </p>
              <h2 className="mt-2 font-onest text-2xl font-semibold tracking-tight sm:text-3xl">
                {currentTeam?.name ?? t("noCurrentPick")}
              </h2>
            </div>
            <p className="mt-3 text-sm text-[color:var(--aqt-fg-muted)]">
              {t(`connectionState.${connectionState}`)}
            </p>
          </div>
          <div className="flex shrink-0 flex-col gap-5 lg:items-end">
            <div className="lg:text-right">
              <HeroCoord>{t("clock")}</HeroCoord>
              <div className="mt-1 font-onest text-4xl font-semibold">
                {/* compact: at this size the long forms ("autopicking…") wrap
                    the strip on a phone, and PAUSE/AUTO say the same thing. */}
                <DraftClock
                  expiresAt={currentPick?.clock_expires_at ?? null}
                  paused={session.status === "paused"}
                  compact
                />
              </div>
            </div>
            {/* The primary action of this page is leaving it: everything that
                steers a live pick lives in the room's admin dock. */}
            <Button asChild size="lg">
              <Link href={`/draft/${tournamentId}`} target="_blank" rel="noreferrer">
                {t("openBoard")}
                <ArrowUpRight className="ml-2 h-4 w-4" aria-hidden />
              </Link>
            </Button>
            <LifecycleControls tournamentId={tournamentId} board={board} />
          </div>
        </div>
      </HeroFrame>

      {session.blocked_reason && (
        <div
          role="alert"
          className="flex items-start gap-3 border-y border-[color:var(--aqt-live)]/30 bg-[color:var(--aqt-live)]/8 px-4 py-3"
        >
          <ShieldAlert
            className="mt-0.5 h-5 w-5 shrink-0 text-[color:var(--aqt-live)]"
            aria-hidden
          />
          <div className="flex-1">
            <p className="font-medium">{t("systemPause")}</p>
            <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">
              {blockedReason ? t(`blockedReason.${blockedReason}`) : session.blocked_reason}
            </p>
          </div>
          {shouldResolve && (
            <Button onClick={() => setRoleDialogOpen(true)}>{t("resolveRoles")}</Button>
          )}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[7fr_3fr]">
        <main className="min-w-0 space-y-4">
          <FeasibilityStatus feasibility={feasibility} loading={feasibilityQuery.isLoading} />
          {!session.blocked_reason && shouldResolve && (
            <Button variant="outline" onClick={() => setRoleDialogOpen(true)}>
              <AlertTriangle className="mr-2 h-4 w-4" aria-hidden />
              {t("resolveRoles")}
            </Button>
          )}
        </main>
        <aside className="border-[color:var(--aqt-border)] lg:border-l lg:pl-6">
          {/* Deleting a session is refused while it is live, so the live one is
              listed as context; the terminal ones stay erasable from here. */}
          <DraftHistoryPanel tournamentId={tournamentId} onSessionDeleted={() => {}} />
        </aside>
      </div>

      <ResolveRoleConflictDialog
        open={roleDialogOpen}
        onOpenChange={setRoleDialogOpen}
        tournamentId={tournamentId}
        board={board}
        feasibility={feasibility}
      />
    </div>
  );
}
