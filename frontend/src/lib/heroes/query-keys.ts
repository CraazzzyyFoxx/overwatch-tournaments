import type { KeyPart } from "@/lib/query-keys";

/**
 * Hero keys. The catalogue is ONE key for the whole app: `GET /api/v1/heroes`
 * answers the same full, name-sorted list to every caller (a hero row carries no
 * workspace column, so the injected `workspace_id` narrows nothing), and it used
 * to be cached three times over as `heroes-all`, `heroes-select-options` and
 * `["heroes", "all"]`. Read it through `useHeroesCatalog`.
 *
 * Everything sits under the `heroes` root so the catalogue editor's
 * `invalidateQueries({ queryKey: ["heroes"] })` still reaches it.
 */
export const heroQueryKeys = {
  all: () => ["heroes"] as const,
  catalog: () => ["heroes", "catalog"] as const,
  leaderboard: (heroId: KeyPart, tournamentId: KeyPart) =>
    ["hero-leaderboard", heroId, tournamentId] as const,
};
