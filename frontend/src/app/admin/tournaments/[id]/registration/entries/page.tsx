"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { tabFallback } from "../../hubQueries";

// D25: the registrations table lives in a neutral place and is rendered by both
// the hub tab (tournament from the path) and the legacy balancer route
// (tournament from the query) until T14 retires the latter.
const RegistrationsTable = dynamic(
  () => import("@/components/balancer/registrations/RegistrationsTable"),
  { loading: () => tabFallback }
);

/**
 * The individual registrations of one tournament.
 *
 * Registered TEAMS are the sibling `teams` section, not a switcher inside this
 * one: the admin has a single tab implementation (`AdminTabs`, owned by the
 * layout), and a Radix `Tabs` pair here made the teams view unlinkable.
 */
export default function RegistrationEntriesPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const validTournamentId =
    Number.isFinite(tournamentId) && tournamentId > 0 ? tournamentId : null;

  return <RegistrationsTable tournamentId={validTournamentId} />;
}
