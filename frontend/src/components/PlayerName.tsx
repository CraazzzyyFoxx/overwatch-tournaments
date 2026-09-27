import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { getPlayerSlug, getPlayerType } from "@/lib/player";

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
    <div className="flex min-w-0 flex-col">
      <div className="flex min-w-0 flex-row items-center gap-1">
        <Link href={`/users/${getPlayerSlug(player.name)}`} className="min-w-0">
          <span className="block truncate text-base font-semibold" title={name}>
            {name}
          </span>
        </Link>
        {tag && !excludeBadge && (
          <Badge variant="secondary" className="shrink-0 px-1 text-xs">
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
