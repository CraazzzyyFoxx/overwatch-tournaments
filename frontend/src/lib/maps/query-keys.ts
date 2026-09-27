/**
 * Map keys. Like heroes, the catalogue is one request for the whole app -- maps
 * are global reference rows, so the injected `workspace_id` narrows nothing.
 *
 * The gamemode variant is a separate cache entry because it is a different
 * payload, not a different view of one: without `entities: ["gamemode"]` the
 * server leaves every `MapRead.gamemode` null. Both sit under `["maps",
 * "catalog"]`, and that under `["maps"]`, so the catalogue editor's invalidation
 * still reaches them. Read them through `useMapsCatalog`.
 */
export const mapQueryKeys = {
  all: () => ["maps"] as const,
  catalog: (withGamemode = false) =>
    withGamemode ? (["maps", "catalog", "gamemode"] as const) : (["maps", "catalog"] as const),
  /** The id/name projection the match filters use. Under the same root as the
   *  catalogue so one alias edit drops both. */
  lookup: () => ["maps", "lookup"] as const,
  gamemodes: () => ["gamemodes"] as const,
};
