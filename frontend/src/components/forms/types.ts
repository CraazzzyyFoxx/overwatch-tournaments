/**
 * The renderer contract `SchemaForm` drives.
 *
 * A schema field is rendered by whichever component the registry names for its
 * KEY (a builtin: `battle_tag`, `roles`, `identity_discord`, …) or, failing
 * that, for its KIND (`text`, `select`, …). Every renderer takes the same four
 * props plus a shared context, so the form never has to know which of the two
 * it dispatched on — that is the whole point of one field model for builtins
 * and custom questions alike.
 */

import type { ComponentType } from "react";

import type { Translate } from "@/lib/forms/form-errors";
import type { RoleCode } from "@/lib/roles";
import type { FormField } from "@/types/forms.types";
import type { Hero } from "@/types/hero.types";
import type { SubroleCatalog, SubscriptionStatus } from "@/types/registration.types";
import type { SocialAccount } from "@/types/user.types";

/** Everything a builtin renderer needs that is not the field itself. */
export interface FieldRendererContext {
  mode: "public" | "admin";
  /**
   * The registrant's own social accounts, or `[]` while an organizer edits
   * somebody else's row. Feeds the handle suggestions AND the verified-account
   * picker, which filters to `is_verified` itself — `require_verified` is a
   * server rule now, so nothing here re-derives it.
   */
  accounts: SocialAccount[];
  subroleCatalog: SubroleCatalog;
  /** Roster for the top-heroes pickers; empty until the query resolves. */
  heroes: Hero[];
  lockedRole: RoleCode | null;
  /**
   * The roles the `roles` answer declares, injected by `SchemaForm`. Optional:
   * a host builds the rest of this context, and only the per-role rank block
   * reads it — to mark exactly those roles' ranks required.
   */
  declaredRoles?: readonly string[];
  /** Server-resolved subscription standing, or `null` when it does not apply.
   *  Read-only: proving a subscription is a check-in step, not a signup step. */
  subscription: SubscriptionStatus | null;
  /** Opens profile settings so the registrant can link an account. Absent in
   *  admin mode, where the accounts are somebody else's. */
  onLinkAccounts?: () => void;
  /** Translator scoped to `forms.errors`. */
  t: Translate;
}

export interface FieldRendererProps {
  field: FormField;
  value: unknown;
  onChange: (value: unknown) => void;
  error: string | null;
  /**
   * Render read-only: this viewer may look at the answer but not change it.
   *
   * Set by `SchemaForm` from the host's lock map — in practice the server's
   * `edit_writable_keys` allowlist, or a value the schedule forced (a late
   * sign-up's `reserve`). The form ALSO wraps a locked field in a disabled
   * `<fieldset>`, so a renderer that ignores this prop is still read-only;
   * honouring it is about saying so visibly.
   */
  disabled?: boolean;
  context: FieldRendererContext;
}

export type FieldRenderer = ComponentType<FieldRendererProps>;

/** Keyed by builtin field key first, then by {@link FormField.kind}. */
export type RendererRegistry = Partial<Record<string, FieldRenderer>>;
