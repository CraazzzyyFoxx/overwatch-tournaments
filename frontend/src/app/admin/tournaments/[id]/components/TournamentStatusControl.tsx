"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { usePermissions } from "@/hooks/usePermissions";
import adminService from "@/services/admin.service";
import type { Tournament, TournamentStatus } from "@/types/tournament.types";

const STATUS_CONFIG: Record<
  TournamentStatus,
  { label: string; color: string; next: TournamentStatus[] }
> = {
  registration: {
    label: "Registration",
    color: "bg-blue-500",
    next: ["draft"]
  },
  draft: {
    label: "Draft",
    color: "bg-yellow-500",
    next: ["check_in", "live"]
  },
  check_in: {
    label: "Check-in",
    color: "bg-orange-500",
    next: ["live"]
  },
  live: {
    label: "Live",
    color: "bg-green-500",
    next: ["playoffs", "completed"]
  },
  playoffs: {
    label: "Playoffs",
    color: "bg-purple-500",
    next: ["completed"]
  },
  completed: {
    label: "Completed",
    color: "bg-gray-500",
    next: ["archived"]
  },
  archived: {
    label: "Archived",
    color: "bg-gray-700",
    next: ["completed"]
  }
};

interface TournamentStatusControlProps {
  tournament: Tournament;
}

export function TournamentStatusControl({ tournament }: TournamentStatusControlProps) {
  const queryClient = useQueryClient();
  const { isSuperuser } = usePermissions();
  const config = STATUS_CONFIG[tournament.status];
  const [overrideStatus, setOverrideStatus] = useState<TournamentStatus | null>(null);

  const mutation = useMutation({
    mutationFn: ({ status, force = false }: { status: TournamentStatus; force?: boolean }) =>
      adminService.transitionTournamentStatus(tournament.id, { status, force }),
    onSuccess: () => {
      setOverrideStatus(null);
      queryClient.invalidateQueries({
        queryKey: ["admin", "tournament", tournament.id]
      });
    }
  });

  return (
    <div className="flex items-center gap-3">
      <Badge className={`${config.color} text-white`}>{config.label}</Badge>

      {config.next.length > 0 && (
        <div className="flex gap-2">
          {config.next.map((nextStatus) => {
            const nextConfig = STATUS_CONFIG[nextStatus];
            return (
              <Button
                key={nextStatus}
                size="sm"
                variant="outline"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate({ status: nextStatus })}
              >
                {mutation.isPending ? "..." : `\u2192 ${nextConfig.label}`}
              </Button>
            );
          })}
        </div>
      )}

      {isSuperuser ? (
        <div className="flex items-center gap-2">
          <Select
            value={overrideStatus ?? tournament.status}
            onValueChange={(value) => setOverrideStatus(value as TournamentStatus)}
          >
            <SelectTrigger className="h-8 w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(STATUS_CONFIG).map(([value, statusConfig]) => (
                <SelectItem key={value} value={value}>
                  {statusConfig.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="secondary"
            disabled={mutation.isPending || !overrideStatus || overrideStatus === tournament.status}
            onClick={() => {
              if (!overrideStatus || overrideStatus === tournament.status) return;
              mutation.mutate({ status: overrideStatus, force: true });
            }}
          >
            {mutation.isPending ? "..." : "Set status"}
          </Button>
        </div>
      ) : null}

      {mutation.isError && (
        <span className="text-sm text-red-500">{(mutation.error as Error).message}</span>
      )}
    </div>
  );
}
