"use client";

import TournamentRulesPage from "../_views/TournamentRulesPage";
import { useTournamentSlug } from "../_hooks/useTournamentId";

export default function TournamentRulesRoutePage() {
  const slug = useTournamentSlug();
  return <TournamentRulesPage slug={slug} />;
}
