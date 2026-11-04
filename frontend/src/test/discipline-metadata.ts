import type { DisciplineDescriptor, DisciplineMetadata, OntologyRole } from "@/types/discipline.types";

/**
 * Scoped metadata fixtures for the installed games, shaped like `GET /disciplines/{code}/metadata`:
 * Overwatch's three roots in the `player_role` dimension, League's five positions in `position`, Deadlock's one
 * `agent` (no Full flex). Component tests mock `@/services/discipline.service` with {@link disciplineServiceMock}
 * so a form or roster resolves the same owner scope it would in production; its list holds Overwatch and League only.
 */
function role(
  id: number,
  dimension: string,
  code: string,
  name: string,
  extra: Partial<OntologyRole> = {}
): OntologyRole {
  return {
    id,
    dimension,
    code,
    name,
    parent_id: null,
    workspace_id: null,
    active: true,
    selectable: true,
    sort_order: id,
    attrs: {},
    ...extra
  };
}

function descriptor(code: string, name: string, provider: string): DisciplineDescriptor {
  return {
    code,
    name,
    short_name: code === "lol" ? "LoL" : code === "deadlock" ? "Deadlock" : "OW",
    icon: null,
    enabled: true,
    kinds: { character: code === "lol" ? "Champion" : "Hero", map: "Map" },
    character_classes: [],
    identity_provider: provider,
    // Deadlock alone has no open slot and no Full flex player (`DisciplineSpec.flex`).
    flex: code !== "deadlock",
    capabilities: {
      catalog_sync: true,
      native_rank_collection: true,
      native_ladder: true,
      achievement_conditions: code === "overwatch",
      analytics: code === "overwatch",
      match_fetch: false,
      match_search: false,
      log_upload: code === "overwatch"
    }
  } as DisciplineDescriptor;
}

function metadata(
  code: string,
  name: string,
  provider: string,
  dimension: string,
  roles: OntologyRole[]
): DisciplineMetadata {
  return {
    discipline: descriptor(code, name, provider),
    workspace_id: null,
    dimensions: [
      { id: 1, code: dimension, name: dimension, selection_mode: "single", rated: true, active: true, sort_order: 0 }
    ],
    roles,
    stat_defs: [],
    team_format_presets: [],
    native_ladder: []
  } as unknown as DisciplineMetadata;
}

export const OW_METADATA = metadata("overwatch", "Overwatch", "battlenet", "player_role", [
  role(1, "player_role", "tank", "Tank", { attrs: { color: "#0ea5e9", icon: "/test-roles/tank.svg" } }),
  role(2, "player_role", "damage", "Damage", { attrs: { color: "#f97316", icon: "/test-roles/damage.svg" } }),
  role(3, "player_role", "support", "Support", { attrs: { color: "#10b981", icon: "/test-roles/support.svg" } })
]);

export const LOL_METADATA = metadata("lol", "League of Legends", "riot", "position", [
  role(11, "position", "top", "Top", { attrs: { icon: "/test-roles/top.svg" } }),
  role(12, "position", "jungle", "Jungle", { attrs: { icon: "/test-roles/jungle.svg" } }),
  role(13, "position", "mid", "Mid", { attrs: { icon: "/test-roles/mid.svg" } }),
  role(14, "position", "bot", "Bot", { attrs: { icon: "/test-roles/bot.svg" } }),
  role(15, "position", "support", "Support", { attrs: { icon: "/test-roles/support.svg" } })
]);

export const DEADLOCK_METADATA = metadata("deadlock", "Deadlock", "steam", "agent", [
  role(21, "agent", "agent", "Agent")
]);

const ALL = [OW_METADATA, LOL_METADATA];
/** Every game the metadata read resolves; the installed-games list stays Overwatch and League. */
const RESOLVABLE = [...ALL, DEADLOCK_METADATA];

/** The `vi.mock("@/services/discipline.service", …)` factory result. */
export const disciplineServiceMock = {
  default: {
    list: async () => ALL.map((entry) => entry.discipline),
    metadata: async (_axis: unknown, code: string) => {
      const found = RESOLVABLE.find((entry) => entry.discipline.code === code);
      if (!found) throw new Error(`discipline_not_installed: ${code}`);
      return found;
    }
  }
};
