"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { RoomChat } from "@/components/chat/RoomChat";
import { BackLink } from "@/components/site/BackLink";
import TeamName from "@/components/TeamName";
import { Card, CardContent } from "@craazzzyyfoxx/admin-kit/ui/card";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { encounterChatRoom } from "@/lib/realtime/chat-rooms";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import ffaService from "@/services/ffa.service";
import type { Encounter } from "@/types/encounter.types";

/**
 * The pre-game room of an FFA lobby: who is in it, and the chat.
 *
 * A lobby has no veto, no hero bans and no readiness gate — there are no two
 * sides to take turns, and the organizer enters every game's result — so the
 * duel room's whole phase machine is absent here rather than rendered as a
 * string of empty states. What is left is the one thing the room exists for:
 * the private channel where the lobby code and the rules are posted, on the
 * same `encounter:{id}:chat` topic the duel room uses.
 */
export function FfaPregameRoom({ encounter }: Readonly<{ encounter: Encounter }>) {
  const t = useTranslations();
  const lobbyQuery = useQuery({
    queryKey: tournamentQueryKeys.ffaLobby(encounter.tournament_id, encounter.id),
    queryFn: () => ffaService.getLobby(encounter.id)
  });
  const lobby = lobbyQuery.data ?? null;

  return (
    <>
      <div className="space-y-4">
        <BackLink href={`/encounters/${encounter.id}`}>{t("ffa.backToLobby")}</BackLink>

        <Card>
          <CardContent className="space-y-4 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h1 className="text-lg font-semibold text-[color:var(--aqt-fg)]">
                {lobby?.name ?? encounter.name}
              </h1>
              <Eyebrow tone="dim">
                {t("ffa.gamesPerLobby")}: {lobby?.best_of ?? encounter.best_of}
              </Eyebrow>
            </div>

            <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("ffa.roomHint")}</p>

            <div className="space-y-2">
              <Eyebrow as="h2">
                {t("ffa.roomParticipants")}
              </Eyebrow>
              {lobbyQuery.isPending ? (
                <Skeleton className="h-24 w-full rounded-lg" />
              ) : lobby == null || lobby.rows.length === 0 ? (
                <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("ffa.lobbyEmpty")}</p>
              ) : (
                <ul className="grid gap-2 sm:grid-cols-2">
                  {[...lobby.rows]
                    .sort((left, right) => left.slot - right.slot)
                    .map((row) => (
                      <li
                        key={row.team_id}
                        className="flex items-center gap-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-3 py-2"
                      >
                        <span className="aqt-tnum w-6 shrink-0 text-label text-[color:var(--aqt-fg-faint)]">
                          {row.slot}
                        </span>
                        <TeamName
                          team={{ name: row.team_name, image_url: row.team_image_url }}
                          size="xs"
                        />
                      </li>
                    ))}
                </ul>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <RoomChat room={encounterChatRoom(encounter.id)} />
    </>
  );
}
