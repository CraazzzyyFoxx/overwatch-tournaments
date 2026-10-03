"use client";

import { useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, Gavel, Hourglass, Swords } from "lucide-react";

import { DataTable } from "@/components/data-table";
import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters } from "@/components/kit/useFilters";
import { Button } from "@/components/ui/button";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import adminService from "@/services/admin.service";
import type { PregameRoomRow } from "@/types/admin.types";

import { pregameRoomFilterDefs } from "./filters";
import { PHASE_LABEL, PREGAME_ROOMS_REFETCH_MS, sortRooms } from "./model";
import { useRoomColumns } from "./useRoomColumns";

const PAGE_SIZE = 25;

/**
 * Every pre-game room of one tournament on one screen.
 *
 * The organizer's view of the rooms used to be "open each encounter and look",
 * which is fine for one match and useless on a round of sixteen. This answers
 * the only question that matters between matches — which room is stuck, and on
 * whom — and links straight into the one that is.
 *
 * Chips live in the URL through `FilterBar`, so "everything still waiting on
 * readiness" can be pasted to whoever is chasing the captains.
 */
export function PregameRoomsBrowser({ tournamentId }: Readonly<{ tournamentId: number }>) {
  const pathname = usePathname();
  const roomsQuery = useQuery({
    queryKey: adminQueryKeys.pregameRooms(tournamentId),
    queryFn: () => adminService.getPregameRooms(tournamentId),
    // The live update: see `PREGAME_ROOMS_REFETCH_MS`. Nothing pushes the set
    // of rooms, so without this the screen is a snapshot that lies within
    // seconds of a captain pressing anything.
    refetchInterval: PREGAME_ROOMS_REFETCH_MS
  });

  const rooms = useMemo(() => sortRooms(roomsQuery.data?.rooms ?? []), [roomsQuery.data]);

  const defs = useMemo(() => pregameRoomFilterDefs(rooms), [rooms]);
  const filters = useFilters(defs);
  const attentionOnly = filters.values.attention === true;
  // Joined rather than kept as an array: `filters.values` is rebuilt every
  // render, so only a primitive can key the memo below.
  const phaseKey = Array.isArray(filters.values.phase) ? filters.values.phase.join(",") : "";
  const stageFilter = String(filters.values.stage ?? "");

  const visible = useMemo(() => {
    const phases = phaseKey ? phaseKey.split(",") : [];
    return rooms.filter((room) => {
      if (attentionOnly && room.attention.length === 0) return false;
      if (phases.length > 0 && !phases.includes(room.phase)) return false;
      if (stageFilter) {
        return (room.stage_id == null ? "none" : String(room.stage_id)) === stageFilter;
      }
      return true;
    });
  }, [rooms, attentionOnly, phaseKey, stageFilter]);

  // The room sends the organizer back to the list they left, filters and all.
  const columns = useRoomColumns({
    tournamentId,
    returnTo: pathname ?? `/admin/tournaments/${tournamentId}/matches/rooms`
  });

  if (!roomsQuery.isLoading && rooms.length === 0) {
    return (
      <EmptyNote
        title="No pre-game rooms"
        icon={Swords}
        action={
          <Button asChild size="sm" variant="outline">
            <Link href={`/admin/tournaments/${tournamentId}/settings/pre-game`}>
              Set up the pre-game phase
            </Link>
          </Button>
        }
      >
        A room opens only where a map-veto or hero-ban rule set with a non-empty pool applies.
        Nothing in this tournament has one yet.
      </EmptyNote>
    );
  }

  return (
    <div className="space-y-3">
      <StatTileGrid className="xl:grid-cols-5">
        <StatTile
          label="Needs attention"
          value={rooms.filter((room) => room.attention.length > 0).length}
          detail="Disputed, overdue or waiting on a choice"
          icon={AlertTriangle}
          tone="danger"
        />
        <StatTile
          label="Waiting on readiness"
          value={rooms.filter((room) => room.phase === "readiness").length}
          detail="A captain has not confirmed"
          icon={Hourglass}
          tone="warning"
        />
        <StatTile
          label="Veto / bans live"
          value={rooms.filter((room) => room.phase === "map" || room.phase === "hero").length}
          icon={Swords}
          tone="accent"
        />
        <StatTile
          label="Reporting"
          value={rooms.filter((room) => room.phase === "report").length}
          detail="A played map has no agreed result"
          icon={Gavel}
          tone="info"
        />
        <StatTile
          label="Done"
          value={rooms.filter((room) => room.phase === "done").length}
          icon={ClipboardCheck}
          tone="success"
        />
      </StatTileGrid>

      <p className="text-sm text-muted-foreground">
        Refreshes every {PREGAME_ROOMS_REFETCH_MS / 1000} seconds while this tab is open.
      </p>

      <DataTable<PregameRoomRow>
        rows={visible}
        isLoading={roomsQuery.isLoading}
        columns={columns}
        filterKey={filters.filterKey}
        initialPageSize={PAGE_SIZE}
        columnsStorageKey="pregame-rooms-table-columns"
        searchPlaceholder="Search match or team"
        getRowId={(row) => String(row.encounter_id)}
        toolbar={<FilterBar defs={defs} filters={filters} />}
        emptyMessage="No room matches this filter."
        renderMobileCard={(row) => (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{row.original.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {row.original.home_team?.name ?? "TBD"} vs {row.original.away_team?.name ?? "TBD"}
            </p>
            <p className="text-xs text-muted-foreground">
              {PHASE_LABEL[row.original.phase]}
              {row.original.attention.length > 0 ? ` · needs attention` : ""}
            </p>
          </div>
        )}
      />
    </div>
  );
}
