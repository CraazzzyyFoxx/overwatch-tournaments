import type { FilterValue } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { AuditSortField } from "@/types/admin.types";

/**
 * `sort` is a closed whitelist server-side — anything else is a 422 — so every
 * sortable column id has to BE one of these strings. Columns outside the set
 * (the target label, the change summary) declare `enableSorting: false`.
 */
export const SORTABLE: Record<string, AuditSortField> = {
  created_at: "created_at",
  action: "action",
  source: "source",
  actor_label: "actor_label",
  entity_type: "entity_type",
};

export const SCOPE_PARAM = "scope";
/** The scope toggle chip's URL value: `?scope=1` widens the feed to every workspace. */
export const ALL_WORKSPACES = "1";
/** What links said before the scope became a toggle chip; still read, rewritten to `1`. */
export const LEGACY_ALL_WORKSPACES = "all";

/** The chip values that narrow which rows are in the feed, as `listAudit` takes them. */
export function auditFeedFilters(values: Record<string, FilterValue>) {
  return {
    entityType: String(values.entity_type ?? "") || null,
    // `|| null` on the parse, not a guard function: `NaN || null` is `null`, so a
    // truncated or non-numeric param drops the filter rather than sending garbage.
    entityId: Number.parseInt(String(values.entity_id ?? ""), 10) || null,
    actorUserId: Number.parseInt(String(values.actor_user_id ?? ""), 10) || null,
    action: String(values.action ?? "") || null,
  };
}
