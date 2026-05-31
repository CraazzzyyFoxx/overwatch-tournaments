import React from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { getPlayerSlug, getPlayerType } from "@/utils/player";

/**
 * Minimal player-like shape accepted by `PlayerName`. Compatible with
 * `Player`, `User`, and `TeamRosterPlayer` / `UserTournamentPlayer`.
 */
interface PlayerNameInput {
  name: string;
  role?: string | null;
  sub_role?: string | null;
}

const PlayerName = ({
  player,
  includeSpecialization,
  excludeBadge
}: {
  player: PlayerNameInput;
  includeSpecialization: boolean;
  excludeBadge?: boolean;
}) => {
  const name = player.name.split("#")[0];
  const tag = player.name.split("#")[1];
  const playerRoleInfo =
    "role" in player && player.role !== undefined
      ? { role: player.role ?? null, sub_role: player.sub_role ?? null }
      : null;

  return (
    <div className="flex flex-col">
      <div className="flex flex-row gap-1 items-center">
        <Link href={`/users/${getPlayerSlug(player.name)}`}>
          <h4 className="text-base font-semibold">{name}</h4>
        </Link>
        {tag && !excludeBadge && (
          <Badge variant="secondary" className="px-1 text-xs">
            <p className="text-muted-foreground">{`#${tag}`}</p>
          </Badge>
        )}
      </div>
      <div>
        {includeSpecialization && playerRoleInfo && (
          <p className="text-xs text-muted-foreground">{getPlayerType(playerRoleInfo)}</p>
        )}
      </div>
    </div>
  );
};

export default PlayerName;
