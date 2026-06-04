"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
import { useToast } from "@/hooks/use-toast";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import draftService from "@/services/draft.service";
import type {
  DraftAutopickStrategy,
  DraftRole,
  DraftSeedCaptainInput,
  DraftSeedPlayerInput,
} from "@/types/draft.types";

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
        pool_source: "manual",
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

  // --- seed inputs ---
  const [captains, setCaptains] = useState<DraftSeedCaptainInput[]>([
    { name: "", draft_position: 1, battle_tag: "" },
  ]);
  const [players, setPlayers] = useState<DraftSeedPlayerInput[]>([
    { battle_tag: "", primary_role: "dps", rank_value: 3000 },
  ]);

  const seedMutation = useMutation({
    mutationFn: (sessionId: number) =>
      draftService.seed(tournamentId, sessionId, {
        captains: captains
          .filter((c) => c.name.trim())
          .map((c, i) => ({ ...c, draft_position: i + 1, battle_tag: c.battle_tag || null })),
        players: players
          .filter((p) => (p.battle_tag ?? "").trim())
          .map((p) => ({ ...p })),
      }),
    onSuccess: () => {
      toast({ title: "Draft seeded" });
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

  // ---- no session: create form ----
  if (!session) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Create draft session</CardTitle>
          <CardDescription>
            No draft session exists yet. Configure and create one to begin.
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
    );
  }

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

      {session.status === "setup" && (
        <SeedForm
          captains={captains}
          players={players}
          onCaptainsChange={setCaptains}
          onPlayersChange={setPlayers}
          pending={seedMutation.isPending}
          onSeed={() => seedMutation.mutate(session.id)}
        />
      )}
    </div>
  );
}

interface SeedFormProps {
  captains: DraftSeedCaptainInput[];
  players: DraftSeedPlayerInput[];
  onCaptainsChange: (next: DraftSeedCaptainInput[]) => void;
  onPlayersChange: (next: DraftSeedPlayerInput[]) => void;
  pending: boolean;
  onSeed: () => void;
}

function SeedForm({
  captains,
  players,
  onCaptainsChange,
  onPlayersChange,
  pending,
  onSeed,
}: SeedFormProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Seed teams & pool</CardTitle>
        <CardDescription>
          Add captains (one per team, in seed order) and the available player pool, then start the
          draft. Balance-derived seeding is coming later.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Captains</Label>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                onCaptainsChange([
                  ...captains,
                  { name: "", draft_position: captains.length + 1, battle_tag: "" },
                ])
              }
            >
              + Captain
            </Button>
          </div>
          {captains.map((c, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
              <Input
                placeholder="Team name"
                value={c.name}
                onChange={(e) => {
                  const next = [...captains];
                  next[i] = { ...c, name: e.target.value };
                  onCaptainsChange(next);
                }}
              />
              <Input
                placeholder="Captain BattleTag#1234"
                value={c.battle_tag ?? ""}
                onChange={(e) => {
                  const next = [...captains];
                  next[i] = { ...c, battle_tag: e.target.value };
                  onCaptainsChange(next);
                }}
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onCaptainsChange(captains.filter((_, j) => j !== i))}
              >
                ✕
              </Button>
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Player pool</Label>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                onPlayersChange([
                  ...players,
                  { battle_tag: "", primary_role: "dps", rank_value: 3000 },
                ])
              }
            >
              + Player
            </Button>
          </div>
          {players.map((p, i) => (
            <div key={i} className="grid grid-cols-[1fr_120px_120px_auto] gap-2">
              <Input
                placeholder="BattleTag#1234"
                value={p.battle_tag ?? ""}
                onChange={(e) => {
                  const next = [...players];
                  next[i] = { ...p, battle_tag: e.target.value };
                  onPlayersChange(next);
                }}
              />
              <Select
                value={p.primary_role}
                onValueChange={(v) => {
                  const next = [...players];
                  next[i] = { ...p, primary_role: v as DraftRole };
                  onPlayersChange(next);
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tank">Tank</SelectItem>
                  <SelectItem value="dps">DPS</SelectItem>
                  <SelectItem value="support">Support</SelectItem>
                </SelectContent>
              </Select>
              <Input
                type="number"
                placeholder="Rank"
                value={p.rank_value ?? ""}
                onChange={(e) => {
                  const next = [...players];
                  next[i] = { ...p, rank_value: e.target.value ? Number(e.target.value) : null };
                  onPlayersChange(next);
                }}
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onPlayersChange(players.filter((_, j) => j !== i))}
              >
                ✕
              </Button>
            </div>
          ))}
        </div>

        <Button disabled={pending} onClick={onSeed}>
          Seed & make ready
        </Button>
      </CardContent>
    </Card>
  );
}
