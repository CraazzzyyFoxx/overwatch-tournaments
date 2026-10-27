"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import MatchLogIndicator, { RawLogStatus } from "@/components/match/MatchLogIndicator";
import { SectionHead } from "@/components/match/EncounterAtoms";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Match } from "@/types/encounter.types";
import { mapWithModeName } from "@/lib/catalog/mode";

export default function EncounterHistory({ matches }: Readonly<{ matches: Match[] }>) {
  const t = useTranslations();
  const history = matches.filter((match) => match.map_index == null);
  if (history.length === 0) return null;

  return (
    <section aria-label={t("encounters.history.title")}>
      <SectionHead title={t("encounters.history.title")} />
      <p className="mb-3 text-sm text-[color:var(--aqt-fg-muted)]">
        {t("encounters.history.description")}
      </p>
      <Card asChild className="overflow-hidden divide-y divide-[color:var(--aqt-border)]">
        <ul>
          {history.map((match) => (
            <li key={match.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
              <div className="min-w-0 space-y-1">
                <Button variant="accent" size="sm" asChild>
                  <Link href={`/matches/${match.id}`}>
                    {mapWithModeName(match.map, match.mode) ?? t("encounters.match.mapAlt")} · #{match.id}
                  </Link>
                </Button>
                <p className="text-sm text-[color:var(--aqt-fg-muted)]">
                  {t("encounters.history.unconfirmed")}
                </p>
                <p className="text-label text-[color:var(--aqt-fg-muted)]">
                  <RawLogStatus raw_status={match.raw_status} raw_available={match.raw_available} />
                </p>
              </div>
              <MatchLogIndicator
                hasLogs
                logs={[{
                  matchId: match.id,
                  label: `${mapWithModeName(match.map, match.mode) ?? t("encounters.match.mapAlt")} · #${match.id}`,
                  rawAvailable: match.raw_available
                }]}
              />
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}
