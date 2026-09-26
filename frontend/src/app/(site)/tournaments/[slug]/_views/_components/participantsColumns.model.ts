import type { ReactNode } from "react";
import type { useTranslations } from "next-intl";

import type { Registration } from "@/types/registration.types";
import type { FormField, RolesParams } from "@/types/forms.types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Translator = ReturnType<typeof useTranslations<never>>;

export interface ColumnDefinition {
  id: string;
  label: string;
  category: "meta" | "built_in" | "custom";
  defaultVisible: boolean;
  render: (reg: Registration, index: number) => ReactNode;
  searchValue?: (reg: Registration) => string | null;
  /** Breakpoint at which column becomes visible. "always" = never hidden. */
  responsive?: "always" | "sm" | "md" | "lg";
  /** Optional fixed width class for the column. */
  widthClass?: string;
  /**
   * Content class driving the desktop grid track minimum. Every row is its own
   * grid, so tracks must be sized from a declared content class instead of
   * `min-content`, which would resolve differently per row and misalign the
   * columns. Omitted = `"data"`.
   */
  width?: "icon" | "badge" | "data";
  /** Optional alignment override for header and cells. */
  align?: "left" | "center";
}

// ---------------------------------------------------------------------------
// Role helpers — icon-only, larger icons
// ---------------------------------------------------------------------------

export const ROLE_TO_ICON: Record<string, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support",
  flex: "Flex",
};

export function getRoleLabel(role: string, t: Translator): string {
  switch (role.toLowerCase()) {
    case "tank":
      return t("common.roles.tank");
    case "damage":
      return t("common.roles.damage");
    case "support":
      return t("common.roles.support");
    case "flex":
      return t("common.roles.flex");
    default:
      return role.charAt(0).toUpperCase() + role.slice(1);
  }
}

/**
 * The site's own name for a question the schema labels in the organizer's
 * words. A key with no entry here keeps whatever label the form carries.
 */
export function getLocalizedColumnLabel(t: Translator, key: string, fallback: string): string {
  switch (key) {
    case "battle_tag":
      return t("registration.accounts.battleTag");
    case "smurf_tags":
      return t("registration.accounts.smurfs");
    case "identity_discord":
      return t("registration.accounts.discord");
    case "identity_twitch":
      return t("registration.accounts.twitch");
    case "identity_boosty":
      return t("registration.accounts.boosty");
    case "identity_vk":
      return t("registration.accounts.vk");
    case "identity_youtube":
      return t("registration.accounts.youtube");
    case "roles":
      return t("common.rolesList");
    case "top_heroes":
      return t("tournamentDetail.topHeroes");
    case "stream_pov":
      return t("registration.details.streamPov");
    case "public_notes":
      return t("registration.details.notes");
    case "reserve":
      return t("registration.details.reserve");
    default:
      return fallback;
  }
}

/** Whether the `roles` question also asks for top heroes. */
export function asksTopHeroes(field: FormField): boolean {
  return (field.params as Partial<RolesParams>).top_heroes?.enabled === true;
}
