"use client";

import Link from "next/link";
import { ListChecks } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import pickBanService from "@/services/pickBan.service";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

interface PregameRoomLinkProps {
  encounterId: number;
  tournamentId: number;
  /**
   * Button styling, supplied by the caller. The link used to hardcode a shadcn
   * `<Button variant="outline">`, which resolves against the shadcn theme
   * variables and therefore read a shade off — and a size off — next to the
   * `--aqt-*` controls it sits beside.
   */
  className?: string;
}

/**
 * Link to the unified pre-game room (map veto + hero bans). Rendered whenever
 * EITHER kind applies to this encounter — a room reachable only once its
 * session exists would hide the very room captains need to open to confirm
 * readiness in the first place (backend: `EncounterReadiness` gates session
 * creation, not room existence). Replaces the retired `VetoRoomLink` /
 * `HeroBanRoomLink` pair.
 */
export function PregameRoomLink({ encounterId, tournamentId, className }: Readonly<PregameRoomLinkProps>) {
  const t = useTranslations();
  const mapQuery = useQuery({
    queryKey: encounterQueryKeys.pregameMapState(encounterId),
    queryFn: () => pickBanService.getPickBanState("map", encounterId)
  });
  const heroQuery = useQuery({
    queryKey: encounterQueryKeys.pregameHeroState(encounterId),
    queryFn: () => pickBanService.getPickBanState("hero", encounterId)
  });

  const applies = (state: typeof mapQuery.data) =>
    state != null && (state.reason !== "not_configured" || state.session != null);
  if (!applies(mapQuery.data) && !applies(heroQuery.data)) {
    return null;
  }

  return (
    <Link href={`/tournaments/${tournamentId}/pregame/${encounterId}`} className={cn(className)}>
      <ListChecks className="h-4 w-4" aria-hidden />
      {t("encounters.detail.pregameRoom")}
    </Link>
  );
}
