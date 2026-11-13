import type { FilterDef, FilterValue } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { GameMark } from "@/components/workspace/GameMark";
import { DISCIPLINE_PARAM } from "@/lib/site/discipline-scope";
import type { DisciplineDescriptor } from "@/types/discipline.types";

/**
 * The admin's game filter: a `FilterBar` chip on `?discipline=` (the param `useGameScope` reads) over the
 * community's enabled games, in their order. None where the community runs one game. `resets` names the
 * params a game change makes meaningless (a game's maps, roles, divisions). `inlineAllLabel` draws it as a
 * visible select instead of a chip, for pages whose actions need a game picked.
 */
export function gameFilterDefs(
  games: readonly DisciplineDescriptor[] | undefined,
  label: string,
  resets?: (next: FilterValue | null) => readonly string[],
  inlineAllLabel?: string
): FilterDef[] {
  const enabled = (games ?? []).filter((game) => game.enabled);
  if (enabled.length < 2) return [];
  return [
    {
      key: DISCIPLINE_PARAM,
      label,
      kind: "single",
      options: enabled.map((game) => ({
        value: game.code,
        label: game.name,
        icon: <GameMark discipline={game} size={16} decorative />
      })),
      resets,
      inline: inlineAllLabel === undefined ? undefined : { allLabel: inlineAllLabel }
    }
  ];
}
