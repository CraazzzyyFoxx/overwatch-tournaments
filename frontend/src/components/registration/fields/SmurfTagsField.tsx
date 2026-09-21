"use client";

import { useTranslations } from "next-intl";

import type { FieldRendererProps } from "@/components/forms/types";

import SmurfTagsInput from "../SmurfTagsInput";

/** The `smurf_tags` builtin: a list of BattleTags beside the main one. */
export default function SmurfTagsField({
  field,
  value,
  onChange,
  error,
  context,
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const tags = Array.isArray(value) ? (value as unknown[]).map(String) : [];

  return (
    <SmurfTagsInput
      tags={tags}
      onChange={onChange}
      label={field.label || t("registration.accounts.smurfs")}
      // The registrant's own Battle.net handles; the input hides the ones
      // already added.
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
