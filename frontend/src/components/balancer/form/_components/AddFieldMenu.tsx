"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import {
  BUILTIN_FIELD_KEYS,
  IDENTITY_PROVIDERS,
  builtinFixedVisibility,
  identityKey,
  identityProvider
} from "@/lib/forms/builtin-keys";
import { makeUniqueFieldKey } from "@/lib/forms/keys";
import type { FieldKind, FormField } from "@/types/forms.types";

/**
 * Every kind a custom question can take. `builtin` is deliberately absent: a
 * builtin is chosen by KEY, because the server owns its behaviour, and offering
 * "kind: builtin" with a free-text key would be an invitation to invent one.
 */
export const CUSTOM_FIELD_KINDS = [
  "text",
  "textarea",
  "number",
  "select",
  "multi_select",
  "checkbox",
  "url",
  "date",
  "role_ranks"
] as const satisfies readonly FieldKind[];

/** Builtins that are not an identity, in the order the catalog declares them. */
const STATIC_BUILTIN_KEYS = BUILTIN_FIELD_KEYS.filter((key) => identityProvider(key) === null);

const OPTION_KINDS: Record<string, true> = { select: true, multi_select: true };

export function newBuiltinField(key: string): FormField {
  return {
    key,
    kind: "builtin",
    required: false,
    // The catalog decides for most of them; where it does not, public is the
    // reading the registrant already expects from the rest of the form.
    visibility: builtinFixedVisibility(key) ?? "public",
    params: {},
    show_in_draft: false,
    // Matches the server default: a freshly added question is frozen at submit
    // until the organizer deliberately opens it.
    editable: false
  };
}

/**
 * A new custom question.
 *
 * The key is provisional and stays editable-by-label until the organizer has
 * named the field once; `RegistrationFormBuilder` locks it from there, because
 * the key is what every stored answer is filed under.
 */
export function newCustomField(kind: FieldKind, existingKeys: Iterable<string>): FormField {
  return {
    key: makeUniqueFieldKey("", existingKeys),
    kind,
    label: "",
    required: false,
    visibility: "public",
    // An empty list is a schema the server refuses, and it should: the field
    // editor flags it until two options exist, which is where the organizer is
    // already looking.
    options: OPTION_KINDS[kind] ? [] : null,
    params: {},
    show_in_draft: false,
    editable: false
  };
}

/**
 * "Add a question": the builtins this form does not already ask for, then the
 * eight custom kinds.
 *
 * A builtin appears at most once — its key is its storage — so an already
 * placed one is dropped from the list rather than shown disabled: there is
 * nothing the organizer could do about it here except find it in the rail.
 */
export function AddFieldMenu({
  usedKeys,
  onAddBuiltin,
  onAddCustom,
  disabled = false
}: Readonly<{
  usedKeys: ReadonlySet<string>;
  onAddBuiltin: (key: string) => void;
  onAddCustom: (kind: FieldKind) => void;
  disabled?: boolean;
}>) {
  const t = useTranslations("registrationFormAdmin.builder");
  const tKeys = useTranslations("registrationFormAdmin.builtins");
  const tKinds = useTranslations("registrationFormAdmin.kinds");

  const builtins = STATIC_BUILTIN_KEYS.filter((key) => !usedKeys.has(key));
  const identities = IDENTITY_PROVIDERS.map(identityKey).filter((key) => !usedKeys.has(key));

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled}>
          <Plus className="mr-1.5 size-3.5" aria-hidden />
          {t("addField")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        {builtins.length > 0 || identities.length > 0 ? (
          <>
            <DropdownMenuLabel>{t("builtinGroup")}</DropdownMenuLabel>
            {builtins.map((key) => (
              <DropdownMenuItem key={key} onSelect={() => onAddBuiltin(key)}>
                {tKeys(key)}
              </DropdownMenuItem>
            ))}
            {identities.length > 0 && (
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>{t("identityGroup")}</DropdownMenuSubTrigger>
                <DropdownMenuPortal>
                  <DropdownMenuSubContent>
                    {identities.map((key) => (
                      <DropdownMenuItem key={key} onSelect={() => onAddBuiltin(key)}>
                        {tKeys(key)}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuPortal>
              </DropdownMenuSub>
            )}
            <DropdownMenuSeparator />
          </>
        ) : null}

        <DropdownMenuLabel>{t("customGroup")}</DropdownMenuLabel>
        {CUSTOM_FIELD_KINDS.map((kind) => (
          <DropdownMenuItem key={kind} onSelect={() => onAddCustom(kind)}>
            {tKinds(kind)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
