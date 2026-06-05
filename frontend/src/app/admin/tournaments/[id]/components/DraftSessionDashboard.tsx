"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useToast } from "@/hooks/use-toast";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getTierForRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENTS } from "@/lib/roles";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import balancerAdminService from "@/services/balancer-admin.service";
import draftService from "@/services/draft.service";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftAutopickStrategy, DraftCaptainOrder } from "@/types/draft.types";

interface DraftSessionDashboardProps {
  tournamentId: number;
  canManage: boolean;
}

const STATUS_LABEL: Record<string, string> = {
  setup: "Setup",
  ready: "Ready",
  live: "Live",
  paused: "Paused",
  completed: "Completed",
  cancelled: "Cancelled",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

/** A registration is in the balancer pool (mirrors isRegistrationIncludedInBalancer). */
function isInBalancerPool(r: AdminRegistration): boolean {
  return (
    r.status === "approved" &&
    !r.deleted_at &&
    !r.exclude_from_balancer &&
    r.balancer_status !== "not_in_balancer"
  );
}

/** Primary role + rank from a registration's active roles (priority order, prefer primary). */
function registrationSummary(r: AdminRegistration): { role: string; rank: number | null } {
  const active = (r.roles ?? []).filter((e) => e.is_active).sort((a, b) => a.priority - b.priority);
  const primary = active.find((e) => e.is_primary) ?? active[0];
  const ranks = active.map((e) => e.rank_value).filter((v): v is number => v != null);
  return {
    role: primary?.role ?? "dps",
    rank: primary?.rank_value ?? (ranks.length ? Math.max(...ranks) : null),
  };
}

function registrationLabel(r: AdminRegistration): string {
  return r.battle_tag || r.display_name || `#${r.id}`;
}

export function DraftSessionDashboard({ tournamentId, canManage }: DraftSessionDashboardProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const boardKey = tournamentQueryKeys.draftBoard(tournamentId);

  const boardQuery = useQuery({
    queryKey: boardKey,
    queryFn: () => draftService.getTournamentBoard(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: boardKey });
  const onError = (error: unknown) =>
    toast({ title: "Draft error", description: errorMessage(error), variant: "destructive" });

  // --- create session config ---
  const [rounds, setRounds] = useState(4);
  const [pickTime, setPickTime] = useState(45);
  const [teamSize, setTeamSize] = useState(5);
  const [autopick, setAutopick] = useState<DraftAutopickStrategy>("best_fit");

  const createMutation = useMutation({
    mutationFn: () =>
      draftService.createSession(tournamentId, {
        pool_source: "balancer_balance",
        format: "snake",
        rounds,
        pick_time_seconds: pickTime,
        team_size: teamSize,
        autopick_strategy: autopick,
      }),
    onSuccess: () => {
      toast({ title: "Draft session created" });
      invalidate();
    },
    onError,
  });

  // --- seed from the existing balancer pool ---
  const [captainIds, setCaptainIds] = useState<number[]>([]); // ordered = seed order
  const [teamNames, setTeamNames] = useState<Record<number, string>>({});
  const [captainOrder, setCaptainOrder] = useState<DraftCaptainOrder>("weakest_first");

  const seedMutation = useMutation({
    mutationFn: (sessionId: number) =>
      draftService.seed(tournamentId, sessionId, {
        captain_order: captainOrder,
        pool_captains: captainIds.map((id) => ({
          registration_id: id,
          name: teamNames[id]?.trim() || null,
        })),
      }),
    onSuccess: () => {
      toast({ title: "Draft seeded from balancer pool" });
      invalidate();
    },
    onError,
  });

  const lifecycleMutation = useMutation({
    mutationFn: (vars: {
      sessionId: number;
      action: "start" | "pause" | "resume" | "cancel" | "export";
    }) => draftService.lifecycle(tournamentId, vars.sessionId, vars.action),
    onSuccess: (_data, vars) => {
      toast({ title: `Draft ${vars.action}` });
      invalidate();
    },
    onError,
  });

  const board = boardQuery.data ?? null;
  const session = board?.session ?? null;
  const lifecyclePending = lifecycleMutation.isPending;
  // Only a non-terminal session blocks creating a new draft. A cancelled or
  // completed session is kept for read-only views but must NOT trap the admin.
  const isActiveSession =
    !!session && ["setup", "ready", "live", "paused"].includes(session.status);

  const teamCount = board?.teams.length ?? 0;
  const totalPicks = useMemo(
    () => (session ? session.rounds * teamCount : 0),
    [session, teamCount]
  );
  const completedPicks =
    board?.picks.filter(
      (p) => p.status === "completed" || p.status === "autopicked" || p.status === "skipped"
    ).length ?? 0;

  if (boardQuery.isLoading) {
    return <p className="text-muted-foreground">Loading draft…</p>;
  }

  if (!canManage) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Live Draft</CardTitle>
          <CardDescription>
            You do not have permission to manage the draft for this tournament.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  // ---- no active session (none, or a terminal cancelled/completed one): create form ----
  if (!isActiveSession) {
    const previous = session; // terminal session, if any
    return (
      <div className="space-y-4">
        {previous && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Previous draft
                <Badge variant="secondary">
                  {STATUS_LABEL[previous.status] ?? previous.status}
                </Badge>
              </CardTitle>
              <CardDescription>
                {previous.status === "cancelled"
                  ? "The previous draft was cancelled. You can create a new one below."
                  : "The previous draft is complete. You can export it or create a new one below."}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Link
                href={`/tournaments/${tournamentId}/draft`}
                className="text-sm text-primary underline"
                target="_blank"
              >
                Open board ↗
              </Link>
              {previous.status === "completed" && (
                <Button
                  size="sm"
                  disabled={lifecyclePending}
                  onClick={() =>
                    lifecycleMutation.mutate({ sessionId: previous.id, action: "export" })
                  }
                >
                  Export to teams
                </Button>
              )}
            </CardContent>
          </Card>
        )}
        <Card>
          <CardHeader>
            <CardTitle>Create draft session</CardTitle>
            <CardDescription>
              {previous
                ? "Configure and create a new draft session."
                : "No draft session exists yet. Configure and create one to begin."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div>
              <Label htmlFor="draft-rounds">Rounds</Label>
              <Input
                id="draft-rounds"
                type="number"
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value) || 1)}
              />
            </div>
            <div>
              <Label htmlFor="draft-pick-time">Pick time (s)</Label>
              <Input
                id="draft-pick-time"
                type="number"
                value={pickTime}
                onChange={(e) => setPickTime(Number(e.target.value) || 45)}
              />
            </div>
            <div>
              <Label htmlFor="draft-team-size">Team size</Label>
              <Input
                id="draft-team-size"
                type="number"
                value={teamSize}
                onChange={(e) => setTeamSize(Number(e.target.value) || 5)}
              />
            </div>
            <div>
              <Label htmlFor="draft-autopick">Autopick</Label>
              <Select
                value={autopick}
                onValueChange={(v) => setAutopick(v as DraftAutopickStrategy)}
              >
                <SelectTrigger id="draft-autopick">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="best_fit">Best fit</SelectItem>
                  <SelectItem value="role_need">Role need</SelectItem>
                  <SelectItem value="best_available">Best available</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
            <Button disabled={createMutation.isPending} onClick={() => createMutation.mutate()}>
              Create session
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!session) return null; // unreachable (isActiveSession implies non-null); narrows for TS

  const statusBadge = (
    <Badge variant={session.status === "live" ? "default" : "secondary"}>
      {STATUS_LABEL[session.status] ?? session.status}
    </Badge>
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2">Live Draft {statusBadge}</CardTitle>
            <Link
              href={`/tournaments/${tournamentId}/draft`}
              className="text-sm text-primary underline"
              target="_blank"
            >
              Open live board ↗
            </Link>
          </div>
          <CardDescription>
            {session.rounds} rounds · {session.pick_time_seconds}s/pick · team size{" "}
            {session.team_size} · autopick {session.autopick_strategy} · picks {completedPicks}/
            {totalPicks}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {(session.status === "setup" || session.status === "ready") && (
            <Button
              size="sm"
              disabled={lifecyclePending || session.status !== "ready"}
              onClick={() => lifecycleMutation.mutate({ sessionId: session.id, action: "start" })}
            >
              Start draft
            </Button>
          )}
          {session.status === "live" && (
            <Button
              size="sm"
              variant="secondary"
              disabled={lifecyclePending}
              onClick={() => lifecycleMutation.mutate({ sessionId: session.id, action: "pause" })}
            >
              Pause
            </Button>
          )}
          {session.status === "paused" && (
            <Button
              size="sm"
              disabled={lifecyclePending}
              onClick={() => lifecycleMutation.mutate({ sessionId: session.id, action: "resume" })}
            >
              Resume
            </Button>
          )}
          {(session.status === "live" ||
            session.status === "paused" ||
            session.status === "ready") && (
            <Button
              size="sm"
              variant="destructive"
              disabled={lifecyclePending}
              onClick={() => lifecycleMutation.mutate({ sessionId: session.id, action: "cancel" })}
            >
              Cancel draft
            </Button>
          )}
          {session.status === "completed" && (
            <Button
              size="sm"
              disabled={lifecyclePending}
              onClick={() => lifecycleMutation.mutate({ sessionId: session.id, action: "export" })}
            >
              Export to teams
            </Button>
          )}
        </CardContent>
      </Card>

      {(session.status === "setup" || session.status === "ready") && (
        <PoolSeedForm
          tournamentId={tournamentId}
          captainIds={captainIds}
          teamNames={teamNames}
          onToggleCaptain={(id) =>
            setCaptainIds((prev) =>
              prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
            )
          }
          onTeamName={(id, name) => setTeamNames((prev) => ({ ...prev, [id]: name }))}
          captainOrder={captainOrder}
          onCaptainOrder={setCaptainOrder}
          pending={seedMutation.isPending}
          alreadySeeded={session.status === "ready"}
          onSeed={() => seedMutation.mutate(session.id)}
        />
      )}
    </div>
  );
}

interface PoolSeedFormProps {
  tournamentId: number;
  captainIds: number[];
  teamNames: Record<number, string>;
  onToggleCaptain: (id: number) => void;
  onTeamName: (id: number, name: string) => void;
  captainOrder: DraftCaptainOrder;
  onCaptainOrder: (order: DraftCaptainOrder) => void;
  pending: boolean;
  alreadySeeded: boolean;
  onSeed: () => void;
}

function PoolSeedForm({
  tournamentId,
  captainIds,
  teamNames,
  onToggleCaptain,
  onTeamName,
  captainOrder,
  onCaptainOrder,
  pending,
  alreadySeeded,
  onSeed,
}: PoolSeedFormProps) {
  const divisionGrid = useDivisionGrid();

  const poolQuery = useQuery({
    queryKey: ["balancer", "draft-pool", tournamentId],
    queryFn: () => balancerAdminService.listRegistrations(tournamentId, { status_filter: "approved" }),
  });

  const pool = useMemo(() => {
    const data = (poolQuery.data ?? []).filter(isInBalancerPool);
    return [...data].sort((a, b) => {
      const rankA = registrationSummary(a).rank ?? -1;
      const rankB = registrationSummary(b).rank ?? -1;
      return rankB - rankA;
    });
  }, [poolQuery.data]);

  const captainSeat = (id: number) => captainIds.indexOf(id);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Seed from balancer pool</CardTitle>
        <CardDescription>
          Captains are chosen from the existing balancer pool — every other in-pool player becomes
          available. Roles and ranks come from the balancer. Draft order controls who picks first
          (snake then alternates each round); &quot;weakest picks first&quot; seats the lowest-rated
          captain at the top.
          {alreadySeeded ? " Re-seeding will rebuild teams and picks." : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {poolQuery.isLoading ? (
          <p className="text-muted-foreground">Loading pool…</p>
        ) : poolQuery.isError ? (
          <p className="text-destructive">Failed to load the balancer pool. Try again.</p>
        ) : pool.length === 0 ? (
          <p className="text-muted-foreground">
            No approved players in the balancer pool yet. Approve registrations in the{" "}
            <Link href="/balancer" className="text-primary underline">
              balancer panel
            </Link>{" "}
            first.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-muted-foreground">
                {captainIds.length} captain(s) selected · {pool.length} players in pool
              </div>
              <div className="flex items-center gap-2">
                <Label htmlFor="captain-order" className="text-xs text-muted-foreground">
                  Draft order
                </Label>
                <Select value={captainOrder} onValueChange={(v) => onCaptainOrder(v as DraftCaptainOrder)}>
                  <SelectTrigger id="captain-order" className="h-8 w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="weakest_first">Weakest picks first</SelectItem>
                    <SelectItem value="strongest_first">Strongest picks first</SelectItem>
                    <SelectItem value="manual">Selection order</SelectItem>
                    <SelectItem value="random">Random</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="max-h-[55vh] divide-y divide-border/40 overflow-auto rounded-md border border-border/40">
              {pool.map((reg) => {
                const { role, rank } = registrationSummary(reg);
                const label = registrationLabel(reg);
                const isCaptain = captainIds.includes(reg.id);
                const order = captainSeat(reg.id);
                const tier = rank != null ? getTierForRank(divisionGrid, rank) : null;
                return (
                  <div key={reg.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                    <input
                      type="checkbox"
                      checked={isCaptain}
                      onChange={() => onToggleCaptain(reg.id)}
                      aria-label={`Captain ${label}`}
                    />
                    <span className="w-6 text-center text-muted-foreground">
                      {isCaptain ? order + 1 : ""}
                    </span>
                    <span className="flex-1 truncate">{label}</span>
                    <div
                      className={cn(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border/10",
                        ROLE_ACCENTS[role]?.tile
                      )}
                      title={role.toUpperCase()}
                    >
                      <PlayerRoleIcon role={getRoleIconName(role)} size={14} color="currentColor" />
                    </div>
                    <div className="flex items-center gap-2 min-w-[140px] justify-end">
                      {rank != null ? (
                        <>
                          {tier && (
                            <>
                              <Image
                                src={tier.icon_url}
                                alt={tier.name}
                                width={20}
                                height={20}
                                className="shrink-0 object-contain"
                              />
                              <span className="text-xs text-muted-foreground truncate font-medium">
                                {tier.name}
                              </span>
                            </>
                          )}
                          <span className="font-mono text-xs text-muted-foreground/60 tabular-nums">
                            ({rank})
                          </span>
                        </>
                      ) : (
                        <span className="text-xs text-muted-foreground/40">—</span>
                      )}
                    </div>
                    {isCaptain ? (
                      <Input
                        placeholder="Team name (optional)"
                        value={teamNames[reg.id] ?? ""}
                        onChange={(e) => onTeamName(reg.id, e.target.value)}
                        className="h-8 w-48"
                      />
                    ) : (
                      <span className="w-48" />
                    )}
                  </div>
                );
              })}
            </div>
            <Button disabled={pending || captainIds.length === 0} onClick={onSeed}>
              {alreadySeeded ? "Re-seed" : "Seed"} & make ready ({captainIds.length} teams)
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
