"use client";

import { useTranslations } from "next-intl";

import { CAPTION_CLASS, lobbyLetter, teamAccent } from "@/app/balancer/mix/pickup-chrome";
import { cn } from "@/lib/utils";
import type { CustomGameLobby } from "@/services/custom-game.service";
import type { MapRead } from "@/types/map.types";

type PickupLobbyTabsProps = {
  /** The mix's lobbies, ordered by `lobby_index`. One of them renders nothing. */
  lobbies: CustomGameLobby[];
  activeLobby: number;
  /** The OW catalogue, so a tab can name the map its lobby is about to play. */
  maps: MapRead[];
  onSelect: (lobbyIndex: number) => void;
};

/**
 * The only way a host reaches any lobby past A. Tabs rather than matchups side
 * by side because the matchup column is capped at 1180px next to a 568px lineup
 * (see `[gameId]/page.tsx`) -- two do not fit, and half a matchup is worse than
 * one whole one. Six tabs wrap onto a second line rather than shrink to nothing.
 *
 * Each tab carries what a host decides on without opening it: which game that
 * lobby is on, whether the lineup currently on its screen has been recorded,
 * and what it is about to play. A mix running one lobby renders nothing at all:
 * a tab bar with a single tab is chrome describing itself.
 */
export function PickupLobbyTabs({
  lobbies,
  activeLobby,
  maps,
  onSelect
}: Readonly<PickupLobbyTabsProps>) {
  const t = useTranslations("mixes.lobbies");

  if (lobbies.length < 2) {
    return null;
  }

  return (
    <div
      role="tablist"
      aria-label={t("tabsLabel")}
      className="flex flex-wrap gap-1.5 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-1"
    >
      {lobbies.map((lobby) => {
        const selected = lobby.lobby_index === activeLobby;
        const accent = teamAccent(lobby.lobby_index);
        return (
          <button
            key={lobby.lobby_index}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => {
              if (!selected) onSelect(lobby.lobby_index);
            }}
            className={cn(
              "flex min-w-[8.5rem] flex-1 flex-col items-start gap-0.5 rounded-lg border px-3 py-2 text-left transition-colors",
              selected
                ? "border-[color:var(--aqt-border-3)] bg-[color:var(--aqt-overlay-3)]"
                : "border-transparent hover:bg-[color:var(--aqt-overlay-2)]"
            )}
          >
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className={cn("h-3 w-[3px] shrink-0 rounded-sm", accent.bar)} />
              <span
                className={cn(
                  "font-display text-sm font-bold tracking-[0.01em]",
                  selected ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-muted)]"
                )}
              >
                {t("tab", { letter: lobbyLetter(lobby.lobby_index) })}
              </span>
            </span>
            <span className={cn(CAPTION_CLASS, "truncate")}>
              <LobbyStatus lobby={lobby} maps={maps} />
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * One lobby's line, in the order a host reads it: how far along it is, whether
 * the lineup on its screen is still unplayed-and-unrecorded, and what it plays
 * next. A lobby that has never been balanced says so instead of claiming
 * "game 1": nothing has been set up to play yet.
 *
 * A component rather than a helper the tab passes its translator to: the
 * namespace is typed per call site, so handing `t` down would mean naming a
 * type next-intl does not export.
 */
function LobbyStatus({
  lobby,
  maps
}: Readonly<{ lobby: CustomGameLobby; maps: MapRead[] }>) {
  const t = useTranslations("mixes.lobbies");
  const parts: string[] = [];
  if (lobby.balanced_at == null) {
    parts.push(t("notBalanced"));
  } else {
    parts.push(t("game", { number: (lobby.matches_count ?? 0) + 1 }));
    if (lobby.lineup_recorded === false) {
      parts.push(t("notRecorded"));
    }
  }
  const map = lobby.next_map_id == null ? null : maps.find((entry) => entry.id === lobby.next_map_id);
  if (map) {
    parts.push(map.name);
  }
  return parts.join(" \u00B7 ");
}
