"use client";

import Link from "next/link";
import { ListChecks } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { usePermissions } from "@/hooks/usePermissions";
import { useMyEncounterRole } from "@/hooks/useMyEncounterRole";
import pickBanService from "@/services/pickBan.service";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

interface PregameRoomLinkProps {
  encounterId: number;
  tournamentId: number;
  /** The encounter's workspace and game: a game that files matches by id has a room even without a pick-ban. */
  workspaceId: number;
  discipline: string;
  /** Positions of the series not cancelled: an import-only room needs one to file a match for. */
  liveGames: number;
}

/**
 * Link to the unified pre-game room (map veto + hero bans). Rendered whenever
 * EITHER kind applies to this encounter — a room reachable only once its
 * session exists would hide the very room captains need to open to confirm
 * readiness in the first place (backend: `EncounterReadiness` gates session
 * creation, not room existence). Replaces the retired `VetoRoomLink` /
 * `HeroBanRoomLink` pair. With neither kind configured, a game that files its
 * matches by id (`capabilities.match_fetch`) still has an import-only room, linked
 * for the readers who may file there: a captain of the encounter or an organizer.
 */
export function PregameRoomLink({
  encounterId,
  tournamentId,
  workspaceId,
  discipline,
  liveGames
}: Readonly<PregameRoomLinkProps>) {
  const t = useTranslations();
  const { hasWorkspacePermission } = usePermissions();
  const mapQuery = useQuery({
    queryKey: encounterQueryKeys.pregameMapState(encounterId),
    queryFn: () => pickBanService.getPickBanState("map", encounterId)
  });
  const heroQuery = useQuery({
    queryKey: encounterQueryKeys.pregameHeroState(encounterId),
    queryFn: () => pickBanService.getPickBanState("hero", encounterId)
  });
  const metadata = useDisciplineMetadata(workspaceId, discipline);

  const applies = (state: typeof mapQuery.data) =>
    state != null && (state.reason !== "not_configured" || state.session != null);
  const configured = applies(mapQuery.data) || applies(heroQuery.data);
  const importOnly =
    !configured &&
    mapQuery.data != null &&
    heroQuery.data != null &&
    liveGames > 0 &&
    metadata.data?.discipline.capabilities.match_fetch === true;
  // The room files as an organizer only with `match.result` (the organizer route's gate); anyone else must captain.
  const organizer = hasWorkspacePermission(workspaceId, "match.result");
  const roleQuery = useMyEncounterRole(encounterId, importOnly && !organizer);
  const canImport = organizer || roleQuery.data?.encounter_team_id != null;
  if (!configured && !(importOnly && canImport)) {
    return null;
  }

  return (
    <Button variant="outline" size="sm" asChild>
      <Link href={`/tournaments/${tournamentId}/pregame/${encounterId}`}>
        <ListChecks aria-hidden />
        {t("encounters.detail.pregameRoom")}
      </Link>
    </Button>
  );
}
