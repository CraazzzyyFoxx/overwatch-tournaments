"use client";

import Link from "next/link";
import { ListChecks } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import captainService from "@/services/captain.service";

interface VetoRoomLinkProps {
  encounterId: number;
  tournamentId: number;
}

/**
 * Hero link to the dedicated veto room. Rendered only when a veto session
 * exists for the encounter — `session: null` (not configured / teams unknown)
 * keeps the link hidden.
 */
export function VetoRoomLink({ encounterId, tournamentId }: VetoRoomLinkProps) {
  const t = useTranslations();
  const stateQuery = useQuery({
    queryKey: ["encounter-veto-state", encounterId],
    queryFn: () => captainService.getMapPoolState(encounterId),
  });

  if (!stateQuery.data?.session) {
    return null;
  }

  return (
    <Button variant="outline" asChild>
      <Link href={`/tournaments/${tournamentId}/veto/${encounterId}`}>
        <ListChecks className="mr-2 h-4 w-4" aria-hidden />
        {t("encounters.detail.vetoRoom")}
      </Link>
    </Button>
  );
}
