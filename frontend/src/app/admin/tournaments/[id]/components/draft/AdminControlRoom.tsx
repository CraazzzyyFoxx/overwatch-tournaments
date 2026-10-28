"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { DraftClock } from "@/components/draft/DraftClock";
import { useDraftFeasibilityQuery, useDraftRealtime } from "@/hooks/useDraftData";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { StatusPill } from "@/components/kit/StatusPill";
import { type Tone } from "@/components/ui/tone";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/status-dot";
import { HeroCoord, HeroFrame } from "@/components/site/PageHero";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
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

const CONNECTION_TONE: Record<string, Tone> = {
  connected: "success",
  connecting: "warning",
  reconnecting: "warning"
};

/**
 * The organizer's control page for a live draft.
 *
 * Running the draft happens in the draft room itself (`/draft/{id}`), which
 * carries the admin dock: extra time, autopick and override sit beside the
 * board they act on. What stays here: the session's state at a glance,
 * feasibility, pause/resume (the system-pause copy sends the admin here to
 * resume), the lifecycle actions that end or rewind the session, and the
 * tournament's draft history.
 */
export function AdminControlRoom({ tournamentId, board }: Readonly<AdminControlRoomProps>) {
  const t = useTranslations("draftAdmin.controlRoom");
  const tDraft = useTranslations("draftAdmin");
  const [roleDialogOpen, setRoleDialogOpen] = useState(false);
  // Subscribed here too: the status, clock and feasibility below must follow
  // the picks made in the room without a manual reload.
  const { connectionState } = useDraftRealtime(tournamentQueryKeys.draftBoard(tournamentId), board);
  const feasibilityQuery = useDraftFeasibilityQuery(board.session.id);
  // The session's own owner scope: the draft's roles are the tournament game's, whatever game is being browsed.
  const ontology = useDisciplineMetadata(board.session.workspace_id, board.session.discipline).data ?? null;
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
    <div className="space-y-5">
      <HeroFrame>
        <div className="flex flex-col gap-6 px-5 py-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="min-w-0">
            <StatusPill tone={session.status === "paused" ? "warning" : "info"} dot={session.status === "live"}>
              {tDraft(`statuses.${session.status}`)}
            </StatusPill>
            {/* The clock is deliberately outside the live region: it ticks four
                times a second and would re-announce the whole strip with it. */}
            <div role="status" className="mt-4">
              <p className={`${eyebrowClass("muted")} tabular-nums`}>
                {currentPick
                  ? t("onTheClock", {
                      round: currentPick.round_no,
                      pick: currentPick.overall_no,
                      total: board.picks.length
                    })
                  : t("currentPickEmpty")}
              </p>
              <h2 className="mt-2 font-onest text-2xl font-semibold sm:text-3xl">
                {currentTeam?.name ?? t("noCurrentPick")}
              </h2>
            </div>
            <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
              <StatusDot tone={CONNECTION_TONE[connectionState] ?? "neutral"} />
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
            {/* Leaving for the room is the primary action while live; while
                paused, Resume below is the next step and takes the lead. */}
            <Button asChild size="lg" variant={session.status === "paused" ? "outline" : "default"}>
              <Link href={`/draft/${tournamentId}`} target="_blank" rel="noreferrer">
                {t("openBoard")}
                <ArrowUpRight className="ml-2 h-4 w-4" aria-hidden />
              </Link>
            </Button>
            <LifecycleControls
              tournamentId={tournamentId}
              board={board}
              resumeBlocked={feasibility?.is_feasible === false}
            />
          </div>
        </div>
      </HeroFrame>

      {session.blocked_reason && (
        <Alert tone="danger">
          <ShieldAlert className="size-4" aria-hidden />
          <AlertTitle>{t("systemPause")}</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-muted-foreground">
              {blockedReason ? t(`blockedReason.${blockedReason}`) : session.blocked_reason}
            </span>
            {shouldResolve && (
              <Button size="sm" onClick={() => setRoleDialogOpen(true)}>
                {t("resolveRoles")}
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-[7fr_3fr]">
        <div className="min-w-0 space-y-4">
          {!session.blocked_reason && shouldResolve && (
            <Button variant="outline" onClick={() => setRoleDialogOpen(true)}>
              {t("resolveRoles")}
            </Button>
          )}
          {/* Deleting a session is refused while it is live, so the live one is
              listed as context; the terminal ones stay erasable from here. */}
          <DraftHistoryPanel tournamentId={tournamentId} />
        </div>
        <aside className="lg:border-l lg:border-border lg:pl-6">
          <FeasibilityStatus feasibility={feasibility} loading={feasibilityQuery.isLoading} ontology={ontology} />
        </aside>
      </div>

      <ResolveRoleConflictDialog
        open={roleDialogOpen}
        onOpenChange={setRoleDialogOpen}
        tournamentId={tournamentId}
        board={board}
        feasibility={feasibility}
        ontology={ontology}
      />
    </div>
  );
}
