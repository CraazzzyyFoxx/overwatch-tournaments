import type { components } from "@/types/api.generated";

export type { components, operations, paths } from "@/types/api.generated";

/** Schema by OpenAPI component name, e.g. `Schema<"app.AchievementRead">`. */
export type Schema<K extends keyof components["schemas"]> = components["schemas"][K];
