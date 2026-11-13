import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { CatalogAliasMissKind } from "@/types/admin.types";

import { MISS_KINDS } from "./model";

/** `?type=` and `?resolved=`: the chip row is the only store of either, so a link to "just the maps" opens on them. */
export function unresolvedFilterDefs(
  t: (key: "filters.type" | "filters.includeResolved" | `catalog.kinds.${CatalogAliasMissKind}`) => string
): FilterDef[] {
  return [
    {
      key: "type",
      label: t("filters.type"),
      kind: "single",
      options: MISS_KINDS.map((kind) => ({
        value: kind,
        label: t(`catalog.kinds.${kind}`),
      })),
    },
    { key: "resolved", label: t("filters.includeResolved"), kind: "toggle" },
  ];
}
