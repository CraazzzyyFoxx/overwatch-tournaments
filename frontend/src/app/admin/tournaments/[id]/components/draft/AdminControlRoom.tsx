"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ArrowUpRight, Clock3, Radio, ShieldAlert, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { DraftClock } from "@/app/(site)/tournaments/[id]/draft/_components/DraftClock";
import {
  useDraftFeasibilityQuery,
  useDraftPickOptionsQuery,
  useDraftRealtime
} from "@/app/(site)/tournaments/[id]/draft/_hooks/useDraftData";
import { Button } from "@/components/ui/button";
import { HeroCoord, HeroFrame, HeroStat, HeroStamp } from "@/components/site/PageHero";
import type { DraftBoard } from "@/types/draft.types";

import { CaptainPresence } from "./CaptainPresence";
import { FeasibilityStatus } from "./FeasibilityStatus";
import { LifecycleControls } from "./LifecycleControls";
import { ResolveRoleConflictDialog } from "./ResolveRoleConflictDialog";

interface AdminControlRoomProps {
  tournamentId: number;
  board: DraftBoard;
}

export function AdminControlRoom({ tournamentId, board }: AdminControlRoomProps) {
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

  return (
    <div className="space-y-5 text-[color:var(--aqt-fg)]">
      <HeroFrame>
        <div className="grid gap-8 px-6 py-7 lg:grid-cols-[1.35fr_1fr] lg:items-end lg:px-9">
          <div>
            <div className="flex flex-wrap gap-4">
              <HeroCoord>{t("adminCoordinate", { id: session.id })}</HeroCoord>
              <HeroCoord>{t(`status.${session.status}`)}</HeroCoord>
            </div>
            <h2 className="mt-4 font-onest text-3xl font-semibold tracking-tight sm:text-4xl">
              {t("title")}
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
              {t("description")}
            </p>
            <div className="mt-6 flex flex-wrap gap-7">
              <HeroStamp label={t("format")} value={session.format} />
              <HeroStamp label={t("teamSize")} value={session.team_size} />
              <HeroStamp label={t("connection")} value={t(`connectionState.${connectionState}`)} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-5 border-t border-[color:var(--aqt-border)] pt-5 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
            <HeroStat label={t("pickProgress")} value={`${completed}/${board.picks.length}`} />
            <HeroStat label={t("round")} value={currentPick?.round_no ?? "—"} />
            <HeroStat
              label={t("clock")}
              value={
                <DraftClock
                  expiresAt={currentPick?.clock_expires_at ?? null}
                  paused={session.status === "paused"}
                  compact
                />
              }
            />
          </div>
        </div>
      </HeroFrame>

      {session.blocked_reason && (
        <div className="flex items-start gap-3 border-y border-[color:var(--aqt-live)]/30 bg-[color:var(--aqt-live)]/8 px-4 py-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-[color:var(--aqt-live)]" />
          <div className="flex-1">
            <p className="font-medium">{t("systemPause")}</p>
            <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">
              {session.blocked_reason === "role_shortage"
                ? t("blockedReason.role_shortage")
                : session.blocked_reason}
            </p>
          </div>
          {shouldResolve && (
            <Button onClick={() => setRoleDialogOpen(true)}>{t("resolveRoles")}</Button>
          )}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]">
        <main className="space-y-5">
          <section className="border-b border-[color:var(--aqt-border)] pb-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <HeroCoord>{t("currentPick")}</HeroCoord>
                <h3 className="mt-2 font-onest text-2xl font-semibold">
                  {currentTeam?.name ?? t("noCurrentPick")}
                </h3>
                <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">
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
                <Link href={`/tournaments/${tournamentId}/draft`} target="_blank">
                  {t("openBoard")}<ArrowUpRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
            </div>
            <div className="mt-5">
              <LifecycleControls
                tournamentId={tournamentId}
                board={board}
                options={optionsQuery.data ?? null}
              />
            </div>
          </section>

          <section className="grid gap-5 sm:grid-cols-3">
            <AdminMetric icon={Users} label={t("teams")} value={board.teams.length} />
            <AdminMetric icon={Clock3} label={t("availablePlayers")} value={board.players.filter((player) => player.status === "available").length} />
            <AdminMetric icon={Radio} label={t("viewers")} value={presence.anonymous_viewer_count} />
          </section>
        </main>
        <aside className="space-y-6 border-t border-[color:var(--aqt-border)] pt-5 xl:border-l xl:border-t-0 xl:pl-6 xl:pt-0">
          <FeasibilityStatus feasibility={feasibility} loading={feasibilityQuery.isLoading} />
          {!session.blocked_reason && shouldResolve && (
            <Button variant="outline" className="w-full" onClick={() => setRoleDialogOpen(true)}>
              <AlertTriangle className="mr-2 h-4 w-4" />{t("resolveRoles")}
            </Button>
          )}
          <CaptainPresence teams={board.teams} presence={presence} />
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

function AdminMetric({ icon: Icon, label, value }: { icon: typeof Users; label: string; value: number }) {
  return (
    <div className="flex items-center gap-3 border-t border-[color:var(--aqt-border)] pt-3">
      <Icon className="h-4 w-4 text-[color:var(--aqt-teal)]" />
      <span className="flex-1 text-sm text-[color:var(--aqt-fg-muted)]">{label}</span>
      <strong className="font-mono tabular-nums">{value}</strong>
    </div>
  );
}
