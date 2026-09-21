"use client";

import { useTranslations } from "next-intl";

import type { FieldRendererProps } from "@/components/forms/types";

import AccountCombobox from "../AccountCombobox";
import VerifiedAccountSelect from "../VerifiedAccountSelect";

/**
 * The `battle_tag` builtin: the roster's identity, so it gets its own grammar
 * and its own control rather than riding the identity catalog.
 */
export default function BattleTagField({
  field,
  value,
  onChange,
  error,
  context,
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const current = typeof value === "string" ? value : "";
  const label = field.label || t("registration.accounts.battleTag");

  // Server-enforced; here it only picks the control, and only for the
  // registrant — an organizer editing somebody else's row is unconstrained.
  if (context.mode === "public" && field.params.require_verified === true) {
    return (
      <VerifiedAccountSelect
        label={label}
        provider="battlenet"
        accounts={context.accounts}
        value={current}
        onChange={onChange}
        required={field.required}
        error={error}
      />
    );
  }

  return (
    <AccountCombobox
      label={label}
      placeholder={field.placeholder || "Player#1234"}
      value={current}
      onChange={onChange}
      suggestions={context.accounts
        .filter((account) => account.provider === "battlenet")
        .map((account) => account.username)}
      icon="/battlenet.svg"
      required={field.required}
      field={field}
      error={error}
    />
  );
}
