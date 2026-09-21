"use client";

import { BadgeInfo } from "lucide-react";
import { useTranslations } from "next-intl";

import type { FieldRendererProps } from "@/components/forms/types";

import FormField from "../FormField";

/**
 * `public_notes` and `organizer_notes` — the same control, told apart by the
 * key. `organizer_notes` is fixed to `organizers` visibility server-side, so it
 * simply never reaches a public read and needs no gate here beyond its glyph.
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
      placeholder={
        field.placeholder ??
        (internal ? "Internal notes, never shown to the player" : t("registration.details.notesPlaceholder"))
      }
      value={typeof value === "string" ? value : ""}
      onChange={onChange}
      error={error}
    />
  );
}
