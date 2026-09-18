"use client";

import { Plus } from "lucide-react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import type { BalancerApplication, BalancerRoleCode } from "@/types/balancer-admin.types";
import { ROLE_LABELS, buildApplicationSearchIndex } from "@/app/balancer/components/workspace-helpers";

type PoolAvailableListProps = {
  applications: BalancerApplication[];
  /** Already trimmed and lower-cased by the sidebar so one input drives every view. */
  searchQuery: string;
  onAddFromApplication: (application: BalancerApplication) => void;
  disabled?: boolean;
};

/** Applications carry free-form role strings; players carry `BalancerRoleCode`. */
function normalizeApplicationRole(role: string | null | undefined): BalancerRoleCode | null {
  switch (role?.trim().toLowerCase()) {
    case "tank":
      return "tank";
    case "damage":
      return "damage";
    case "support":
      return "support";
    default:
      return null;
  }
}

/**
 * The Available view of the Balancing Pool: approved registrations that are not in the pool yet.
 */
export function PoolAvailableList({
  applications,
  searchQuery,
  onAddFromApplication,
  disabled = false,
}: Readonly<PoolAvailableListProps>) {
  const matches = searchQuery
    ? applications.filter((application) => buildApplicationSearchIndex(application).includes(searchQuery))
    : applications;

  if (matches.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-[color:var(--aqt-border-2)] px-4 py-8 text-center">
        <div className="space-y-1.5">
          <p className="text-caption font-medium text-[color:var(--aqt-fg)]">
            {searchQuery ? "No available registrations match this search" : "No available registrations"}
          </p>
          <p className="text-xs text-[color:var(--aqt-fg-dim)]">
            {searchQuery
              ? "Try another BattleTag or role."
              : "Every approved registration is already in the Balancing Pool."}
          </p>
        </div>
      </div>
    );
  }

  return (
    // Same containment as the pool list: below `xl` the shell has no definite height, so an
    // uncapped scroller would grow to its content and push a scrollbar onto the document.
    <div className="min-h-0 max-h-[calc(100svh-16rem)] flex-1 overflow-y-auto overflow-x-hidden pr-2">
      <div className="space-y-1.5">
        {matches.map((application) => {
          const roleCodes = [application.primary_role, ...application.additional_roles_json]
            .map(normalizeApplicationRole)
            .filter((roleCode, index, all): roleCode is BalancerRoleCode =>
              roleCode !== null && all.indexOf(roleCode) === index,
            );

          return (
            <button
              key={application.id}
              type="button"
              disabled={disabled}
              onClick={() => onAddFromApplication(application)}
              className="flex w-full items-center gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-2.5 py-2 text-left transition-colors hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-3)] disabled:opacity-50"
            >
              {roleCodes.length > 0 ? (
                <span className="flex items-center gap-1">
                  {roleCodes.map((roleCode) => (
                    <span key={roleCode} title={ROLE_LABELS[roleCode]} className="opacity-95">
                      <PlayerRoleIcon role={ROLE_LABELS[roleCode]} size={15} />
                    </span>
                  ))}
                </span>
              ) : (
                <span className="text-label text-[color:var(--aqt-fg-dim)]">No roles</span>
              )}
              <span
                className="min-w-0 flex-1 truncate text-caption font-medium text-[color:var(--aqt-fg)]"
                title={application.battle_tag}
              >
                {application.battle_tag}
              </span>
              <span className="flex shrink-0 items-center gap-1 text-label font-medium text-[color:var(--aqt-fg-dim)]">
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                Include
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
