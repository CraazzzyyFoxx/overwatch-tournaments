import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";

export function statusFilterDefs(
  t: (key: "columns.scope" | "scope.registration" | "scope.balancer") => string
): FilterDef[] {
  return [
    {
      key: "scope",
      label: t("columns.scope"),
      kind: "single",
      options: [
        { value: "registration", label: t("scope.registration") },
        { value: "balancer", label: t("scope.balancer") }
      ]
    }
  ];
}
