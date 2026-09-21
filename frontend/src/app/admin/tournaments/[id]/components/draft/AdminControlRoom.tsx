"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ArrowUpRight, Radio, ShieldAlert, UserRound, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { DraftClock } from "@/components/draft/DraftClock";
import { RoomChat } from "@/components/chat/RoomChat";
import {
  useDraftFeasibilityQuery,
  useDraftPickOptionsQuery,
  useDraftRealtime
} from "@/hooks/useDraftData";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { HeroCoord, HeroFrame, HeroStamp } from "@/components/site/PageHero";
import { draftChatRoom } from "@/lib/chat-rooms";
import type { DraftBoard } from "@/types/draft.types";

import { captainPresenceRows } from "./admin-control-model";
import { CaptainPresence } from "./CaptainPresence";
import { FeasibilityStatus } from "./FeasibilityStatus";
import { LifecycleControls } from "./LifecycleControls";
import { ResolveRoleConflictDialog } from "./ResolveRoleConflictDialog";

interface AdminControlRoomProps {
  tournamentId: number;
  board: DraftBoard;
}

const BLOCKED_REASONS = ["role_shortage", "order_recalculated"] as const;

/**
 * Live draft control room (F6).
 *
 * One status strip carries everything the organizer running the draft needs at
 * a glance — who is on the clock, how long they have, who is connected, and
 * the lifecycle actions — because that set was previously spread over a hero,
 * a metric column and a section further down the page. Below it: the pick
 * detail on the left, observation (feasibility, presence) on the right, which
 * collapses under the main area on a narrow screen (F18).
 */
export function AdminControlRoom({ tournamentId, board }: Readonly<AdminControlRoomProps>) {
  const t = useTranslations("draftAdmin.controlRoom");
  const [roleDialogOpen, setRoleDialogOpen] = useState(false);
  const { presence, connectionState } = useDraftRealtime(tournamentId, board);
  const feasibilityQuery = useDraftFeasibilityQuery(board.session.id);
  const optionsQuery = useDraftPickOptionsQuery(board.current_pick?.id ?? null, board.current_pick != null);
  const feasibility = feasibilityQuery.data ?? null;
  const session = board.session;
  const currentPick = board.current_pick;
  const currentTeam = currentPick
    ? board.teams.find((team) => team.id === currentPick.draft_team_id) ?? null
    : null;
  const completed = board.picks.filter((pick) =>
    ["completed", "autopicked", "skipped"].includes(pick.status)
  ).length;
  const shouldResolve = session.blocked_reason === "role_shortage" || feasibility?.is_feasible === false;
  // Only translate reasons the messages actually carry; anything else (a newer
  // backend than this build) falls back to the raw code.
  const blockedReason = BLOCKED_REASONS.find((reason) => reason === session.blocked_reason);
  const captains = captainPresenceRows(board.teams, presence);
  const captainsOnline = captains.filter((captain) => captain.connected).length;

  // Rendered twice by the responsive split below (only one is ever visible, so
  // only one is in the accessibility tree). Both are presentational: the
  // queries and the realtime subscription live here, not in them.
  const watch = (
    <>
      <FeasibilityStatus feasibility={feasibility} loading={feasibilityQuery.isLoading} />
      {!session.blocked_reason && shouldResolve && (
        <Button variant="outline" className="w-full" onClick={() => setRoleDialogOpen(true)}>
          <AlertTriangle className="mr-2 h-4 w-4" aria-hidden />
          {t("resolveRoles")}
        </Button>
      )}
      <CaptainPresence teams={board.teams} presence={presence} />
    </>
  );

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
            <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-[color:var(--aqt-fg-muted)]">
              <span>{t(`connectionState.${connectionState}`)}</span>
              <span aria-hidden>·</span>
              <span className="tabular-nums">
                {t("captainPresenceCount", { online: captainsOnline, total: captains.length })}
              </span>
              <span aria-hidden>·</span>
              <span className="tabular-nums">
                {presence.anonymous_viewer_count} {t("viewers")}
              </span>
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
            <LifecycleControls
              tournamentId={tournamentId}
              board={board}
              options={optionsQuery.data ?? null}
            />
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
        <main className="min-w-0 space-y-5">
          <section className="border-b border-[color:var(--aqt-border)] pb-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <HeroCoord>{t("currentPick")}</HeroCoord>
                <p className="mt-2 text-sm tabular-nums text-[color:var(--aqt-fg-muted)]">
                  {currentPick
                    ? t("currentPickMeta", {
                        pick: currentPick.overall_no,
                        round: currentPick.round_no,
                        version: currentPick.version
                      })
                    : t("currentPickEmpty")}
                </p>
              </div>
              <Button asChild variant="outline">
                <Link href={`/draft/${tournamentId}`} target="_blank" rel="noreferrer">
                  {t("openBoard")}
                  <ArrowUpRight className="ml-2 h-4 w-4" aria-hidden />
                </Link>
              </Button>
            </div>
            <div className="mt-5 flex flex-wrap gap-7">
              <HeroStamp label={t("format")} value={session.format} />
              <HeroStamp label={t("teamSize")} value={session.roster_shape.team_size} />
              <HeroStamp label={t("pickProgress")} value={`${completed}/${board.picks.length}`} />
              <HeroStamp label={t("round")} value={currentPick?.round_no ?? "—"} />
            </div>
          </section>

          {/* No role="status": the viewer count ticks on its own and would
              re-announce the team and player metrics with it. */}
          <section className="grid gap-5 sm:grid-cols-3">
            <AdminMetric icon={Users} label={t("teams")} value={board.teams.length} />
            <AdminMetric
              icon={UserRound}
              label={t("availablePlayers")}
              value={board.players.filter((player) => player.status === "available").length}
            />
            <AdminMetric icon={Radio} label={t("viewers")} value={presence.anonymous_viewer_count} />
          </section>

          {/* The organizer's side of the room, where they are already running
              the draft — same room and same session id the public board
              mounts, so a message sent here lands in the captains' panel. */}
          <RoomChat room={draftChatRoom(session.id)} />

          <Accordion type="single" collapsible className="lg:hidden">
            <AccordionItem value="watch" className="border-t border-[color:var(--aqt-border)]">
              <AccordionTrigger>{t("watchPanel")}</AccordionTrigger>
              <AccordionContent className="space-y-6">{watch}</AccordionContent>
            </AccordionItem>
          </Accordion>
        </main>
        <aside className="hidden space-y-6 border-[color:var(--aqt-border)] lg:block lg:border-l lg:pl-6">
          {watch}
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
function AdminMetric({
  icon: Icon,
  label,
  value
}: Readonly<{
  icon: typeof Users;
  label: string;
  value: number;
}>) {
  return (
    <div className="flex items-center gap-3 border-t border-[color:var(--aqt-border)] pt-3">
      <Icon className="h-4 w-4 text-[color:var(--aqt-teal)]" aria-hidden />
      <span className="flex-1 text-sm text-[color:var(--aqt-fg-muted)]">{label}</span>
      <strong className="font-mono tabular-nums">{value}</strong>
    </div>
  );
}
