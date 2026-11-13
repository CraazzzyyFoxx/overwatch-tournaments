import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { AdminSessionStatus } from "@/types/rbac.types";

import { SESSION_STATUSES } from "./model";

/** `t` is the `adminAccess.common` translator of the browser that renders the chips. */
export function sessionFilterDefs(t: (key: "status" | AdminSessionStatus) => string): FilterDef[] {
  return [
    {
      key: "status",
      label: t("status"),
      kind: "single",
      options: SESSION_STATUSES.map((status) => ({ value: status, label: t(status) }))
    }
  ];
}
