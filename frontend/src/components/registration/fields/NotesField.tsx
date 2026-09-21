"use client";

import { BadgeInfo } from "lucide-react";
import { useTranslations } from "next-intl";

import type { FieldRendererProps } from "@/components/forms/types";

import FormField from "../FormField";

/**
 * `public_notes` and `organizer_notes` — the same control, told apart by the
 * key. The PLAYER writes both; `organizer_notes` is fixed to `organizers`
 * visibility server-side, which strips it from public reads only. So there is
 * no gate here, just the glyph.
 */
export default function NotesField({
  field,
  value,
  onChange,
  error,
}: Readonly<FieldRendererProps>) {
  const t = useTranslations();
  const internal = field.key === "organizer_notes";

  return (
    <FormField
      multiline
      label={field.label || (internal ? "Organizer Notes" : t("registration.details.notes"))}
      required={field.required}
      icon={internal ? <BadgeInfo className="size-3.5 opacity-50" /> : undefined}
      // The registrant writes this one too — only the READER differs — so the
      // placeholder must not read as an organizer's private scratchpad.
      // `SchemaForm` states the audience beneath the control.
      placeholder={
        field.placeholder ??
        (internal ? "" : t("registration.details.notesPlaceholder"))
      }
      value={typeof value === "string" ? value : ""}
      onChange={onChange}
      error={error}
    />
  );
}
