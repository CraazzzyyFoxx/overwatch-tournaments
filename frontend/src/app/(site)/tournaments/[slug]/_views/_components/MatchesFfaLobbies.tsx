"use client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { lobbyGamePositions } from "@/components/ffa/FfaLobbyTable";
import { isEncounterCompleted } from "@/lib/encounter/status";
import type { FfaLobby } from "@/types/ffa.types";
import type { Tournament } from "@/types/tournament.types";

/** Confirmed games of a lobby, by position — `FfaStagePanel`'s count. */
function playedGames(lobby: FfaLobby): number {
  return new Set(
    lobby.rows.flatMap((row) =>
      row.games.filter((game) => game.state === "confirmed").map((game) => game.position)
    )
  ).size;
}

/** First place once the standings job ranked the group, else the most points. */
function leaderOf(lobby: FfaLobby): string | null {
  const ranked = lobby.rows.find((row) => row.position === 1);
  if (ranked) return ranked.team_name;
  const played = lobby.rows.filter((row) => row.games_played > 0);
  if (played.length === 0) return null;
  return played.reduce((best, row) => (row.points > best.points ? row : best)).team_name;
}

/**
 * The FFA lobbies of the Matches tab, one block per stage. A lobby has no two
 * sides and no score, so it is not a `MatchRow`: it reads as its progress and
 * its current leader, and opens the lobby page where the full table lives.
 */
export function MatchesFfaLobbies({
  tournament,
  lobbies,
  headingClassName
}: Readonly<{
  tournament: Tournament;
  lobbies: readonly FfaLobby[];
  headingClassName: string;
}>) {
  const t = useTranslations();

  return tournament.stages
    .filter((stage) => lobbies.some((lobby) => lobby.stage_id === stage.id))
    .map((stage) => {
      const heading = t("ffa.stageLobbiesHeading", { stage: stage.name });
      return (
        <section key={`ffa-${stage.id}`} aria-label={heading}>
          <h2 className={headingClassName}>{heading}</h2>
          <div className="border-t border-[color:var(--aqt-border)]">
            {lobbies
              .filter((lobby) => lobby.stage_id === stage.id)
              .map((lobby) => {
                const played = playedGames(lobby);
                const leader = played > 0 ? leaderOf(lobby) : null;
                const state = isEncounterCompleted(lobby)
                  ? t("ffa.lobbyCompleted")
                  : played > 0
                    ? t("encounters.state.live")
                    : t("encounters.state.open");
                return (
                  <HoverPrefetchLink
                    key={lobby.encounter_id}
                    href={`/encounters/${lobby.encounter_id}`}
                    className="grid grid-cols-[minmax(5rem,auto)_minmax(0,1fr)_auto] items-center gap-2 border-b border-[color:var(--aqt-border)]/60 px-2 py-2.5 text-ui hover:text-[color:var(--aqt-teal)] sm:grid-cols-[minmax(5rem,auto)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:gap-3"
                  >
                    <span className="text-label text-[color:var(--aqt-fg-faint)]">{state}</span>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{lobby.name}</span>
                      <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">
                        {t("ffa.gamesProgress", {
                          played,
                          total: lobbyGamePositions(lobby).length
                        })}
                      </span>
                    </span>
                    <span className="hidden truncate text-label text-[color:var(--aqt-fg-muted)] sm:inline">
                      {leader ? t("ffa.lobbyLeader", { team: leader }) : null}
                    </span>
                    <ChevronRight className="size-3.5 text-[color:var(--aqt-fg-faint)]" aria-hidden />
                  </HoverPrefetchLink>
                );
              })}
          </div>
        </section>
      );
    });
}
