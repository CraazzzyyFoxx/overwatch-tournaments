"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Ban, CalendarOff, Loader2, ShieldAlert, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import captainService from "@/services/captain.service";
import encounterService from "@/services/encounter.service";
import mapService from "@/services/map.service";
import type { MapRead } from "@/types/map.types";
import type { MapVetoAction } from "@/types/tournament.types";

import type { VetoSide } from "./veto-model";
import { VetoAdminControls } from "./VetoAdminControls";
import { VetoHero } from "./VetoHero";
import { VetoMapGrid } from "./VetoMapGrid";
import { VetoStepTimeline } from "./VetoStepTimeline";

interface VetoRoomProps {
  encounterId: number;
}

export function VetoRoom({ encounterId }: VetoRoomProps) {
  const t = useTranslations("encounters.veto.room");
  const queryClient = useQueryClient();
  const { isSuperuser, isWorkspaceAdmin, hasWorkspacePermission } = usePermissions();

  const stateQuery = useQuery({
    queryKey: ["encounter-veto-state", encounterId],
    queryFn: () => captainService.getMapPoolState(encounterId),
    enabled: Number.isFinite(encounterId) && encounterId > 0,
  });
  const encounterQuery = useQuery({
    queryKey: ["encounter-detail", encounterId],
    queryFn: () => encounterService.getEncounter(encounterId),
    enabled: Number.isFinite(encounterId) && encounterId > 0,
  });
  const mapsQuery = useQuery({
    queryKey: ["maps-all"],
    queryFn: () => mapService.getAll({ perPage: -1 }),
    staleTime: 5 * 60 * 1000,
  });

  // The hub only delivers a thin "changed" signal on every mutation (actions,
  // session create, reset) — the authoritative state is always refetched.
  useRealtimeTopic(`encounter:${encounterId}:map-veto`, () => {
    void queryClient.invalidateQueries({ queryKey: ["encounter-veto-state", encounterId] });
  });

  const state = stateQuery.data ?? null;
  const encounter = encounterQuery.data ?? null;

  const mapsById = useMemo(() => {
    const byId: Record<number, MapRead | undefined> = {};
    for (const map of mapsQuery.data?.results ?? []) byId[map.id] = map;
    return byId;
  }, [mapsQuery.data]);

  const [selectedMapId, setSelectedMapId] = useState<number | null>(null);

  // A committed step (ours or the opponent's, incl. an admin reset) can strand
  // the selection on a map that is no longer available — drop it.
  useEffect(() => {
    if (selectedMapId == null || !state) return;
    const entry = state.pool.find((candidate) => candidate.map_id === selectedMapId);
    if (!entry || entry.status !== "available") setSelectedMapId(null);
  }, [state, selectedMapId]);

  const vetoMutation = useMutation({
    mutationFn: (input: { map_id: number; action: MapVetoAction }) =>
      captainService.performVeto(encounterId, input),
    onSuccess: () => setSelectedMapId(null),
    onError: (error) => notify.apiError(error, { title: t("captain.actionFailed") }),
    // Refetch on failure too: a concurrent-move 400 means our view is stale.
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["encounter-veto-state", encounterId] }),
  });

  const workspaceId = encounter?.tournament?.workspace_id ?? null;
  const isAdmin =
    workspaceId != null &&
    (isSuperuser ||
      isWorkspaceAdmin(workspaceId) ||
      hasWorkspacePermission(workspaceId, "match.update"));

  if (stateQuery.isPending || encounterQuery.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-40 w-full rounded-xl" />
        <div className="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_2fr]">
          <Skeleton className="h-72 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  if (stateQuery.isError || state === null || !encounter) {
    return (
      <EmptyRoomCard
        icon={<ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" aria-hidden />}
        title={t("loadError")}
        action={
          <Button
            onClick={() => {
              void stateQuery.refetch();
              void encounterQuery.refetch();
            }}
          >
            {t("retry")}
          </Button>
        }
        encounterId={encounterId}
      />
    );
  }

  if (!state.session) {
    const teamsUnknown = state.reason === "teams_unknown";
    return (
      <EmptyRoomCard
        icon={
          teamsUnknown ? (
            <Users className="h-6 w-6 text-[color:var(--aqt-teal)]" aria-hidden />
          ) : (
            <CalendarOff className="h-6 w-6 text-[color:var(--aqt-amber)]" aria-hidden />
          )
        }
        title={teamsUnknown ? t("empty.teamsUnknownTitle") : t("empty.notConfiguredTitle")}
        hint={teamsUnknown ? t("empty.teamsUnknownHint") : t("empty.notConfiguredHint")}
        encounterId={encounterId}
      />
    );
  }

  const session = state.session;
  const sideName = (side: VetoSide) =>
    side === "home"
      ? encounter.home_team?.name ?? t("side.home")
      : encounter.away_team?.name ?? t("side.away");

  const turnBanner = state.is_complete
    ? t("completedBanner")
    : state.expected_action === "decider"
      ? t("deciderResolving")
      : state.turn_side && state.expected_action
        ? t("turn", {
            side: sideName(state.turn_side),
            action: t(`action.${state.expected_action}`),
          })
        : null;

  const captainAction: MapVetoAction | null =
    state.viewer_can_act && state.allowed_actions.length > 0 ? state.allowed_actions[0] : null;
  const canSelectMaps =
    session.status === "active" && !state.is_complete && (captainAction !== null || isAdmin);
  const selectedMapName =
    selectedMapId != null
      ? mapsById[selectedMapId]?.name ?? t("maps.mapNumber", { id: selectedMapId })
      : null;

  return (
    <div className="flex flex-col gap-4">
      <VetoHero encounter={encounter} state={state} session={session} />

      {turnBanner ? (
        <div
          role="status"
          aria-live="polite"
          className="rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card-2)]/50 px-4 py-2.5 text-sm font-medium"
        >
          {turnBanner}
        </div>
      ) : null}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(260px,1fr)_2fr]">
        <VetoStepTimeline
          sequence={state.sequence}
          pool={state.pool}
          currentStepIndex={state.current_step_index}
          isComplete={state.is_complete}
          mapsById={mapsById}
          sideName={sideName}
        />
        <div className="flex flex-col gap-4">
          <VetoMapGrid
            pool={state.pool}
            mapsById={mapsById}
            selectedMapId={selectedMapId}
            canSelect={canSelectMaps}
            onSelect={(mapId) =>
              setSelectedMapId((current) => (current === mapId ? null : mapId))
            }
          />

          {captainAction !== null && session.status === "active" && !state.is_complete ? (
            <CaptainActionBar
              action={captainAction}
              selectedMapId={selectedMapId}
              selectedMapName={selectedMapName}
              pending={vetoMutation.isPending}
              onConfirm={(mapId) => vetoMutation.mutate({ map_id: mapId, action: captainAction })}
              onCancel={() => setSelectedMapId(null)}
            />
          ) : null}

          {isAdmin ? (
            <VetoAdminControls
              encounterId={encounterId}
              state={state}
              selectedMapId={selectedMapId}
              selectedMapName={selectedMapName}
              onMutated={() => {
                setSelectedMapId(null);
                void queryClient.invalidateQueries({
                  queryKey: ["encounter-veto-state", encounterId],
                });
              }}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}

/**
 * Two-step confirmation: the captain first selects a map in the grid, then
 * explicitly confirms the ban/pick here — no single-click commits.
 */
function CaptainActionBar({
  action,
  selectedMapId,
  selectedMapName,
  pending,
  onConfirm,
  onCancel,
}: {
  action: MapVetoAction;
  selectedMapId: number | null;
  selectedMapName: string | null;
  pending: boolean;
  onConfirm: (mapId: number) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("encounters.veto.room");

  return (
    <section
      aria-label={t("captain.yourTurn")}
      className="flex flex-wrap items-center gap-3 rounded-xl border border-[color:var(--aqt-teal)]/45 bg-[color:var(--aqt-teal)]/8 px-4 py-3"
    >
      <span className="inline-flex items-center gap-2 text-sm font-semibold text-[color:var(--aqt-teal)]">
        {action === "ban" ? <Ban className="h-4 w-4" aria-hidden /> : null}
        {t("captain.yourTurn")}
      </span>
      <span className="text-sm text-[color:var(--aqt-fg-muted)]">
        {selectedMapName ?? t("captain.selectHint")}
      </span>
      <div className="ml-auto flex items-center gap-2">
        {selectedMapId != null ? (
          <Button size="sm" variant="ghost" disabled={pending} onClick={onCancel}>
            {t("captain.cancel")}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant={action === "ban" ? "destructive" : "default"}
          disabled={selectedMapId == null || pending}
          onClick={() => {
            if (selectedMapId != null) onConfirm(selectedMapId);
          }}
        >
          {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : null}
          {pending
            ? t("captain.sending")
            : action === "ban"
              ? t("captain.confirmBan", { map: selectedMapName ?? "—" })
              : t("captain.confirmPick", { map: selectedMapName ?? "—" })}
        </Button>
      </div>
    </section>
  );
}

function EmptyRoomCard({
  icon,
  title,
  hint,
  action,
  encounterId,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
  encounterId: number;
}) {
  const t = useTranslations("encounters.veto.room");

  return (
    <Card>
      <CardContent className="flex min-h-[40svh] flex-col items-center justify-center gap-3 p-8 text-center">
        {icon}
        <h1 className="font-onest text-xl font-semibold">{title}</h1>
        {hint ? (
          <p className="max-w-lg text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
            {hint}
          </p>
        ) : null}
        <div className="mt-2 flex items-center gap-2">
          {action}
          <Button variant="outline" asChild>
            <Link href={`/encounters/${encounterId}`}>
              <ArrowLeft className="mr-2 h-4 w-4" aria-hidden />
              {t("back")}
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
