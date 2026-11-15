"use client";

import { useTranslations } from "next-intl";

import { Card } from "@craazzzyyfoxx/admin-kit/ui/card";
import type { Tournament } from "@/types/tournament.types";

import { registrationCardNodes } from "./registrationCards.model";
import TournamentRegisterButton from "./TournamentRegisterButton";

/** A register card per open registration node ("Register for Day 3"); nothing for a single-intake tournament. */
export function RegistrationNodeCards({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("tournamentDetail.registerCards");
  const nodes = registrationCardNodes(tournament);
  if (nodes.length === 0) return null;

  return (
    <section aria-label={t("title")} className="grid gap-3 sm:grid-cols-2">
      {nodes.map((node) => (
        <Card key={node.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
          <h2 className="font-display text-title font-bold">
            {t("registerFor", { name: node.name })}
          </h2>
          <TournamentRegisterButton tournament={tournament} registrationNodeId={node.id} />
        </Card>
      ))}
    </section>
  );
}
