import type { AdminRegistration } from "@/types/balancer-admin.types";
import type {
  DraftAutopickStrategy,
  DraftCaptainOrder,
  DraftFormat,
  DraftRole
} from "@/types/draft.types";

export interface DraftSetupConfig {
  teamSize: number;
  teamCount: number;
  pickTimeSeconds: number;
  format: DraftFormat;
  autopickStrategy: DraftAutopickStrategy;
  allowAdminOverride: boolean;
  roundRules: string[];
}

export interface DraftCaptainSetup {
  ids: number[];
  teamNames: Record<number, string>;
  order: DraftCaptainOrder;
  randomSeed: number;
}

export interface DraftRegistrationSummary {
  role: DraftRole;
  roles: DraftRole[];
  rank: number | null;
}

export function isInDraftPool(registration: AdminRegistration): boolean {
  return (
    registration.status === "approved" &&
    !registration.deleted_at &&
    !registration.exclude_from_balancer &&
    registration.balancer_status !== "not_in_balancer"
  );
}

export function summarizeRegistration(registration: AdminRegistration): DraftRegistrationSummary {
  const active = (registration.roles ?? [])
    .filter((entry) => entry.is_active)
    .sort((left, right) => left.priority - right.priority);
  const primary = active.find((entry) => entry.is_primary) ?? active[0];
  const ranks = active
    .map((entry) => entry.rank_value)
    .filter((value): value is number => value != null);
  const roles = Array.from(new Set(active.map((entry) => entry.role))) as DraftRole[];
  return {
    role: (primary?.role as DraftRole | undefined) ?? "dps",
    roles: roles.length > 0 ? roles : ["dps"],
    rank: primary?.rank_value ?? (ranks.length > 0 ? Math.max(...ranks) : null)
  };
}

export function registrationLabel(registration: AdminRegistration): string {
  return registration.battle_tag || registration.display_name || `#${registration.id}`;
}

