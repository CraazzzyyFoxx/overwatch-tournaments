import type { useTranslations } from "next-intl";

import {
  AUDIT_ENTITY_TYPES,
  auditEntityLabel,
  describeAuditAction,
  formatAuditActor,
  type AuditTranslator
} from "@/components/kit/audit-log";
import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { AuditLogRead } from "@/types/admin.types";

import { SCOPE_PARAM } from "./model";

/** The `adminMatches.audit` translator of the browser that renders the chips. */
type AuditScreenTranslator = ReturnType<typeof useTranslations<"adminMatches.audit">>;

/**
 * The chips over the audit feed.
 *
 * `entityId`, `actor` and `action` are the raw URL params of the chips that have
 * no closed option list: they arrive from a link ("only this actor", the
 * per-entity trail's "see it in the feed") and are declared as filters only
 * while they are set, so the "+ Filter" picker never offers a control whose
 * values it cannot enumerate.
 */
export function auditFilterDefs({
  t,
  auditT,
  isSuperuser,
  entityId,
  actor,
  action,
  pageRows
}: Readonly<{
  t: AuditScreenTranslator;
  auditT: AuditTranslator;
  isSuperuser: boolean;
  entityId: string;
  actor: string;
  action: string;
  pageRows: AuditLogRead[];
}>): FilterDef[] {
  const list: FilterDef[] = [
    {
      key: "entity_type",
      label: t("entity"),
      kind: "single",
      options: AUDIT_ENTITY_TYPES.map((entityType) => ({
        value: entityType,
        label: auditEntityLabel(entityType, auditT) ?? entityType,
      })),
    },
  ];
  if (isSuperuser) {
    // Absent means "this workspace". A toggle, not a one-option list: the
    // FilterBar offers no list it cannot give a second choice in.
    list.push({ key: SCOPE_PARAM, label: t("everyWorkspacePlatform"), kind: "toggle" });
  }
  if (entityId) {
    list.push({
      key: "entity_id",
      label: t("record"),
      kind: "single",
      options: [{ value: entityId, label: `#${entityId}` }],
    });
  }
  if (actor) {
    // Named from the rows on screen when they can name them: every row in an
    // actor-filtered feed has that actor, and "#12" says nothing to the reader
    // who is about to argue about it.
    const named = pageRows.find((row) => String(row.actor_auth_user_id) === actor);
    list.push({
      key: "actor_user_id",
      label: t("actor"),
      kind: "single",
      options: [{ value: actor, label: named ? formatAuditActor(named, auditT) : `#${actor}` }],
    });
  }
  if (action) {
    list.push({
      key: "action",
      label: t("action"),
      kind: "single",
      options: [{ value: action, label: describeAuditAction(action, auditT).label }],
    });
  }
  return list;
}
