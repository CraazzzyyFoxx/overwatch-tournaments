import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { CatalogEntityRead } from "@/types/catalog.types";

import { activeFilterDef } from "../shared";

/** Mode and competitive pool where the game declares modes, then active state. */
export function mapFilterDefs({
  hasModes,
  modes,
  modeLabel,
  t,
}: Readonly<{
  hasModes: boolean;
  modes: readonly CatalogEntityRead[];
  modeLabel: string;
  t: (
    key:
      | "filters.mode"
      | "filters.modePool"
      | "filters.status"
      | "catalog.competitive"
      | "catalog.casual"
      | "catalog.inactive"
      | "columns.active",
    values?: { kind: string }
  ) => string;
}>): FilterDef[] {
  const modeDefs: FilterDef[] = hasModes
    ? [
        {
          key: "mode",
          label: t("filters.mode", { kind: modeLabel }),
          kind: "single",
          options: modes.map((mode) => ({ value: mode.id.toString(), label: mode.name })),
        },
        {
          key: "in_competitive",
          label: t("filters.modePool"),
          kind: "single",
          options: [
            { value: "true", label: t("catalog.competitive") },
            { value: "false", label: t("catalog.casual") },
          ],
        },
      ]
    : [];
  return [...modeDefs, activeFilterDef(t)];
}
