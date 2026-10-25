"use client";

import { useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Swords } from "lucide-react";

import { DataTable } from "@/components/data-table";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters } from "@/components/kit/useFilters";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import adminService from "@/services/admin.service";
import type { PregameRoomRow } from "@/types/admin.types";
import { seatsBySlot } from "@/lib/encounter/seats";

import { pregameRoomFilterDefs } from "./filters";
import { PHASE_LABEL, PREGAME_ROOMS_REFETCH_MS } from "./model";
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
  const t = useTranslations("adminMatches.pregame");
  const roomsQuery = useQuery({
    queryKey: adminQueryKeys.pregameRooms(tournamentId),
    queryFn: () => adminService.getPregameRooms(tournamentId),
    // The live update: see `PREGAME_ROOMS_REFETCH_MS`. Nothing pushes the set
    // of rooms, so without this the screen is a snapshot that lies within
    // seconds of a captain pressing anything.
    refetchInterval: PREGAME_ROOMS_REFETCH_MS
  });

  // Newest first. The server answers in bracket order (stage, round, id);
  // reversed, that is the tie-break of every column sort (see
  // `sortByKickoff`) and the order a cleared sort falls back to.
  const rooms = useMemo(() => [...(roomsQuery.data?.rooms ?? [])].reverse(), [roomsQuery.data]);

  const defs = useMemo(() => pregameRoomFilterDefs(rooms, (key) => t(key as Parameters<typeof t>[0])), [rooms, t]);
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

  if (roomsQuery.isError) {
    return <PageStateCard state="error" onAction={() => void roomsQuery.refetch()} />;
  }

  if (!roomsQuery.isLoading && rooms.length === 0) {
    return (
      <EmptyNote
        title={t("noRooms")}
        icon={Swords}
        action={
          <Button asChild size="sm" variant="outline">
            <Link href={`/admin/tournaments/${tournamentId}/settings/pre-game`}>
              {t("setup")}
            </Link>
          </Button>
        }
      >
        {t("setupText")}
      </EmptyNote>
    );
  }

  return (
    <div className="space-y-3">
      <DataTable<PregameRoomRow>
        rows={visible}
        isLoading={roomsQuery.isLoading}
        columns={columns}
        filterKey={filters.filterKey}
        initialPageSize={PAGE_SIZE}
        initialSort={{ field: "scheduled_at", dir: "desc" }}
        columnsStorageKey="pregame-rooms-table-columns"
        searchPlaceholder={t("search")}
        getRowId={(row) => String(row.encounter_id)}
        toolbar={<FilterBar defs={defs} filters={filters} />}
        emptyMessage={t("empty")}
        renderMobileCard={(row) => (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{row.original.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {seatsBySlot(row.original.teams).map((seat) => seat.name).join(` ${t("vs")} `) || t("tbd")}
            </p>
            <p className="text-xs text-muted-foreground">
              {t(PHASE_LABEL[row.original.phase] as Parameters<typeof t>[0])}
              {row.original.attention.length > 0 ? ` · ${t("attentionColumn")}` : ""}
            </p>
          </div>
        )}
      />
    </div>
  );
}
