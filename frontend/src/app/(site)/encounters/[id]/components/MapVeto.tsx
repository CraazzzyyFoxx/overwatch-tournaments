"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import captainService from "@/services/captain.service";
import mapService from "@/services/map.service";
import type {
  EncounterMapPoolEntry,
  EncounterMapPoolState,
  MapPoolEntryStatus,
  MapVetoAction,
} from "@/types/tournament.types";

const STATUS_COLORS: Record<MapPoolEntryStatus, string> = {
  available: "bg-gray-200 text-gray-800 dark:bg-gray-700 dark:text-gray-200",
  picked: "bg-green-500 text-white",
  banned: "bg-red-500 text-white line-through",
  played: "bg-blue-500 text-white",
};

interface MapVetoProps {
  encounterId: number;
}

function getStepLabel(state: EncounterMapPoolState): string | null {
  if (state.is_complete) return "Completed";
  if (state.expected_action === "decider") return "Decider map is being resolved";
  if (!state.turn_side || !state.expected_action) return null;
  return `${state.turn_side} team to ${state.expected_action}`;
}

export function MapVeto({ encounterId }: MapVetoProps) {
  const [mapNames, setMapNames] = useState<Record<number, string>>({});
  const [vetoState, setVetoState] = useState<EncounterMapPoolState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isUnavailable, setIsUnavailable] = useState(false);
  const [pendingAction, setPendingAction] = useState<{
    mapId: number;
    action: MapVetoAction;
  } | null>(null);

  // Fetch the current map-pool state. The realtime hub only delivers a thin
  // "changed" signal; the authoritative pool is always pulled from this endpoint.
  const refetchState = useCallback(async () => {
    try {
      const state = await captainService.getMapPoolState(encounterId);
      if (state === null) {
        setIsUnavailable(true);
        setVetoState(null);
        setError(null);
      } else {
        setIsUnavailable(false);
        setVetoState(state);
        setError(null);
      }
    } catch {
      setError("Failed to load map veto");
    } finally {
      setIsLoading(false);
      setPendingAction(null);
    }
  }, [encounterId]);

  useEffect(() => {
    let cancelled = false;

    mapService
      .lookup()
      .then((items) => {
        if (cancelled) return;
        setMapNames(
          Object.fromEntries(items.map((item) => [item.id, item.name])),
        );
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, []);

  // Initial load (and reload when the encounter changes).
  useEffect(() => {
    setIsLoading(true);
    setIsUnavailable(false);
    void refetchState();
  }, [encounterId, refetchState]);

  // Live updates: any captain's committed veto publishes a signal on this topic;
  // every viewer refetches to converge on the new pool.
  useRealtimeTopic(
    `encounter:${encounterId}:map-veto`,
    () => {
      void refetchState();
    },
    [refetchState],
  );

  const availableMaps = useMemo(
    () =>
      vetoState?.pool.filter(
        (entry: EncounterMapPoolEntry) => entry.status === "available",
      ) ?? [],
    [vetoState],
  );

  const pickedMaps = useMemo(
    () =>
      (vetoState?.pool ?? [])
        .filter((entry: EncounterMapPoolEntry) => entry.status === "picked")
        .sort(
          (left: EncounterMapPoolEntry, right: EncounterMapPoolEntry) =>
            left.order - right.order,
        ),
    [vetoState],
  );

  const stepLabel = vetoState ? getStepLabel(vetoState) : null;

  const performAction = async (mapId: number, action: MapVetoAction) => {
    if (!vetoState?.allowed_actions.includes(action)) {
      return;
    }

    setPendingAction({ mapId, action });
    setError(null);
    try {
      await captainService.performVeto(encounterId, { map_id: mapId, action });
      // Optimistic refetch for the acting captain; other viewers converge via the
      // realtime "map_veto.updated" signal that this commit publishes.
      await refetchState();
    } catch {
      setError("Veto action failed");
      setPendingAction(null);
      // Resync to the server's authoritative state after a rejected action.
      await refetchState();
    }
  };

  if (!vetoState) {
    if (isUnavailable) {
      return null;
    }

    if (!isLoading && !error) {
      return null;
    }

    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Map Veto</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">
            {error ?? "Loading map veto..."}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between gap-3 text-base">
          <span>Map Veto</span>
          {stepLabel && <Badge variant="secondary">{stepLabel}</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5">
          {vetoState.pool.map((entry: EncounterMapPoolEntry) => (
            <div
              key={entry.id}
              className={`rounded-md p-2 text-center text-sm ${STATUS_COLORS[entry.status]}`}
            >
              <div className="font-medium">
                {mapNames[entry.map_id] ?? `Map #${entry.map_id}`}
              </div>
              {entry.picked_by && (
                <div className="text-xs opacity-75">{entry.picked_by}</div>
              )}
            </div>
          ))}
        </div>

        {vetoState.viewer_can_act && availableMaps.length > 0 && (
          <div className="space-y-2">
            <div className="text-sm font-medium">
              Your turn as {vetoState.viewer_side} captain
            </div>
            <div className="flex flex-wrap gap-2">
              {availableMaps.map((entry: EncounterMapPoolEntry) => (
                <Button
                  key={entry.id}
                  size="sm"
                  variant={
                    vetoState.allowed_actions[0] === "ban"
                      ? "destructive"
                      : "outline"
                  }
                  disabled={pendingAction !== null || isLoading}
                  onClick={() =>
                    void performAction(entry.map_id, vetoState.allowed_actions[0])
                  }
                >
                  {pendingAction?.mapId === entry.map_id
                    ? "Sending..."
                    : `${vetoState.allowed_actions[0] === "ban" ? "Ban" : "Pick"} ${mapNames[entry.map_id] ?? entry.map_id}`}
                </Button>
              ))}
            </div>
          </div>
        )}

        {pickedMaps.length > 0 && (
          <div>
            <div className="mb-1 text-sm font-medium">Map order</div>
            <div className="flex flex-wrap gap-2">
              {pickedMaps.map((entry: EncounterMapPoolEntry, index: number) => (
                <Badge key={entry.id} variant="secondary">
                  {index + 1}. {mapNames[entry.map_id] ?? entry.map_id}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {error && <div className="text-sm text-red-500">{error}</div>}
      </CardContent>
    </Card>
  );
}
