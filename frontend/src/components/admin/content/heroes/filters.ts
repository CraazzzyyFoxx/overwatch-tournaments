import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";

import { activeFilterDef } from "../shared";

/** The game's own character classes (`FilterBar` drops the chip when there are none), then active state. */
export function heroFilterDefs(
  classes: readonly string[],
  classLabel: (code: string) => string,
  t: (key: "filters.class" | "filters.status" | "columns.active" | "catalog.inactive") => string
): FilterDef[] {
  return [
    {
      key: "class",
      label: t("filters.class"),
      kind: "single",
      options: classes.map((code) => ({ value: code, label: classLabel(code) })),
    },
    activeFilterDef(t),
  ];
}
