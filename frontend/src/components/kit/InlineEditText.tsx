"use client";

import { useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import { Check, Pencil, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";

interface InlineEditTextProps {
  value: string;
  /**
   * Persists the trimmed draft. Pass a promise (e.g. `mutation.mutateAsync`) so the
   * editor stays open with the draft intact when saving fails.
   */
  onSave: (next: string) => void | Promise<unknown>;
  /** Accessible name of the field, e.g. "Group name". */
  label: string;
  canEdit?: boolean;
  /** `false` lets a blank draft save as `""` (a clear) instead of erroring. */
  required?: boolean;
  /** Shown in the input and, muted, in place of an empty value. */
  placeholder?: string;
  maxLength?: number;
  className?: string;
  textClassName?: string;
  inputClassName?: string;
}

/** Read-only text with a pencil affordance that swaps in an input plus save/cancel. */
export function InlineEditText({
  value,
  onSave,
  label,
  canEdit = true,
  required = true,
  placeholder,
  maxLength,
  className,
  textClassName,
  inputClassName
}: Readonly<InlineEditTextProps>) {
  const t = useTranslations("kit.inlineEdit");
  const [draft, setDraft] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const commit = async () => {
    const next = draft?.trim() ?? "";
    if (!next && required) {
      setError(t("required", { label: label.toLowerCase() }));
      return;
    }
    if (next === value) {
      setDraft(null);
      setError(null);
      return;
    }
    setError(null);
    setIsSaving(true);
    try {
      await onSave(next);
      setDraft(null);
    } catch {
      // Caller reports the failure; keep the draft so it can be retried.
    } finally {
      setIsSaving(false);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void commit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      setDraft(null);
      setError(null);
    }
  };

  if (draft === null) {
    return (
      <div className={cn("flex min-w-0 items-center gap-1", className)}>
        <span className={cn("truncate", textClassName, !value && "text-muted-foreground")}>{value || placeholder}</span>
        {canEdit ? (
          <Button
            size="icon-sm"
            variant="ghost"
            className="shrink-0 text-muted-foreground"
            aria-label={t("edit", { label })}
            title={t("edit", { label })}
            onClick={() => setDraft(value)}
          >
            <Pencil aria-hidden />
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className={cn("flex min-w-0 items-center gap-1", className)}>
      <Input
        autoFocus
        aria-label={label}
        aria-invalid={error ? true : undefined}
        value={draft}
        placeholder={placeholder}
        maxLength={maxLength}
        disabled={isSaving}
        size="sm"
        className={cn("h-7", inputClassName)}
        onChange={(event) => {
          setDraft(event.target.value);
          setError(null);
        }}
        onKeyDown={handleKeyDown}
      />
      <Button
        size="icon-sm"
        variant="ghost"
        className="shrink-0"
        aria-label={t("save", { label })}
        disabled={isSaving}
        onClick={() => void commit()}
      >
        {isSaving ? <Spinner /> : <Check aria-hidden />}
      </Button>
      <Button
        size="icon-sm"
        variant="ghost"
        className="shrink-0 text-muted-foreground"
        aria-label={t("cancel", { label })}
        disabled={isSaving}
        onClick={() => {
          setDraft(null);
          setError(null);
        }}
      >
        <X aria-hidden />
      </Button>
      {error ? (
        <span role="alert" className="sr-only">
          {error}
        </span>
      ) : null}
    </div>
  );
}
