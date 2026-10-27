"use client";

import { useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";

import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { roleChoices, type RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import { formatSubRoleLabel } from "@/lib/player";

const NO_SUB_ROLE = "none";

/**
 * Text/number field that keeps a local draft and persists on blur or Enter.
 * Escape restores the saved value. Used instead of the pencil-reveal
 * `InlineEditText` because this whole table is an editor: one click on the
 * value, type, tab away.
 */
export function CommitField({
  value,
  onCommit,
  label,
  disabled,
  className,
  inputMode
}: Readonly<{
  value: string;
  onCommit: (next: string) => void;
  /** Accessible name, e.g. `Rank of Nickname`. */
  label: string;
  disabled?: boolean;
  className?: string;
  inputMode?: "numeric";
}>) {
  const [draft, setDraft] = useState<string | null>(null);

  const commit = () => {
    if (draft === null) return;
    const next = draft.trim();
    setDraft(null);
    if (next !== value) {
      onCommit(next);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.blur();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setDraft(null);
    }
  };

  return (
    <Input
      aria-label={label}
      value={draft ?? value}
      disabled={disabled}
      inputMode={inputMode}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={handleKeyDown}
      size="sm"
      className={className}
    />
  );
}

/**
 * Role picker whose trigger is the same glyph the rest of the site shows.
 *
 * The accessible name carries the field *and* the current value, because an
 * `aria-label` on a Radix trigger overrides the value it renders — an icon-only
 * trigger labelled just "Role of X" would never announce which role is set.
 */
export function RoleSelect({
  value,
  onChange,
  label,
  disabled,
  ontology
}: Readonly<{
  /** A role code of the owner game's rated dimension, or `OPEN_SLOT_CODE` for none assigned. */
  value: string;
  onChange: (role: string) => void;
  /** Field name, e.g. `Role of Nickname`. */
  label: string;
  disabled?: boolean;
  ontology: RoleOntology | null;
}>) {
  const slotLabel = useSlotLabel(ontology);
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled || !ontology}>
      <SelectTrigger aria-label={[label, slotLabel(value)].join(": ")} size="sm" className="w-[4.5rem] gap-1 px-2">
        <SelectValue>
          <RosterSlotGlyph code={value} ontology={ontology} size={18} decorative />
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {roleChoices(ontology, value).map((code) => (
          <SelectItem key={code} value={code}>
            <span className="flex items-center gap-2">
              <RosterSlotGlyph code={code} ontology={ontology} size={16} decorative />
              {slotLabel(code)}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function SubRoleSelect({
  value,
  options,
  onChange,
  label,
  disabled,
  describedBy
}: Readonly<{
  value: string;
  options: Array<{ slug: string; label: string }>;
  onChange: (subRole: string) => void;
  /** Field name, e.g. `Sub-role of Nickname`. */
  label: string;
  disabled?: boolean;
  describedBy?: string;
}>) {
  const t = useTranslations("adminPeople.roster");
  // A saved sub-role missing from the catalog (renamed, deactivated) still needs
  // an option, or Radix renders the trigger empty.
  const items =
    !value || options.some((option) => option.slug === value)
      ? options
      : [...options, { slug: value, label: formatSubRoleLabel(value) ?? value }];
  const selectedLabel = items.find((option) => option.slug === value)?.label ?? t("noSubRole");

  return (
    <Select
      value={value || NO_SUB_ROLE}
      onValueChange={(next) => onChange(next === NO_SUB_ROLE ? "" : next)}
      disabled={disabled}
    >
      <SelectTrigger aria-label={[label, selectedLabel].join(": ")} aria-describedby={describedBy} size="sm" className="w-[9.5rem] px-2">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_SUB_ROLE}>{t("noSubRole")}</SelectItem>
        {items.map((option) => (
          <SelectItem key={option.slug} value={option.slug}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function FlagToggle({
  active,
  label,
  icon: Icon,
  onToggle,
  disabled
}: Readonly<{
  active: boolean;
  label: string;
  icon: typeof Sparkles;
  onToggle: () => void;
  disabled?: boolean;
}>) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={cn("size-7", active ? "text-warning" : "text-muted-foreground/70")}
          aria-label={label}
          aria-pressed={active}
          disabled={disabled}
          onClick={onToggle}
        >
          <Icon aria-hidden className="size-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}
