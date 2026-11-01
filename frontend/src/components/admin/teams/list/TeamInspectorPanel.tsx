"use client";

import { useTranslations } from "next-intl";

import { InspectorField, InspectorSection } from "@/components/kit/InspectorField";
import { PersonLabel } from "@/components/PlayerName";
import { roleOf } from "@/lib/roster/role-ref";
import type { Player, Team } from "@/types/team.types";

function RosterList({ players }: Readonly<{ players: Player[] }>) {
  return (
    <ul className="space-y-1 text-sm">
      {players.map((player) => (
        <li key={player.id} className="flex items-center justify-between gap-2">
          <PersonLabel display={player.display} showCanonical />
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {roleOf(player.role)}
            {" · "}
            {player.rank ?? "—"}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** What the inspector shows for a roster, before opening the editor page. */
export function TeamInspectorPanel({ team }: Readonly<{ team: Team }>) {
  const t = useTranslations("adminPeople.teams");
  const players = team.players ?? [];
  const starters = players.filter((player) => !player.is_substitution);
  const substitutes = players.filter((player) => player.is_substitution);
  // The captain is a roster row, so their name comes from it; a captain inherited from before that rule can sit
  // off the roster.
  const captain = players.find((player) => player.user_id === team.captain_id);
  const captainName = captain ? (
    <PersonLabel display={captain.display} showCanonical />
  ) : team.captain_id > 0 ? (
    t("userId", { id: team.captain_id })
  ) : null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <InspectorField label={t("labels.captain")}>{captainName}</InspectorField>
        <InspectorField label={t("labels.averageSr")}>
          <span className="tabular-nums">{team.avg_sr.toFixed(0)}</span>
        </InspectorField>
        <InspectorField label={t("labels.totalSr")}>
          <span className="tabular-nums">{team.total_sr}</span>
        </InspectorField>
        <InspectorField label={t("labels.group")}>{team.group?.name}</InspectorField>
        <InspectorField label={t("labels.placement")}>
          {team.placement != null ? <span className="tabular-nums">#{team.placement}</span> : null}
        </InspectorField>
      </div>

      {starters.length > 0 ? (
        <InspectorSection title={t("startersTitle")}>
          <RosterList players={starters} />
        </InspectorSection>
      ) : null}

      {substitutes.length > 0 ? (
        <InspectorSection title={t("substitutes")}>
          <RosterList players={substitutes} />
        </InspectorSection>
      ) : null}
    </div>
  );
}
