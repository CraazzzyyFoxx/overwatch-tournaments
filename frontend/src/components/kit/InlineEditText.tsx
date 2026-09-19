"use client";

import { useState, type KeyboardEvent } from "react";
import { Check, Loader2, Pencil, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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
  className,
  textClassName,
  inputClassName
}: Readonly<InlineEditTextProps>) {
  const [draft, setDraft] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const commit = async () => {
    const next = draft?.trim() ?? "";
    if (!next) {
      setError(`Enter a ${label.toLowerCase()}.`);
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
        <span className={cn("truncate", textClassName)}>{value}</span>
        {canEdit ? (
          <Button
            size="icon"
            variant="ghost"
            className="size-7 shrink-0 text-muted-foreground [&_svg]:size-3.5"
            aria-label={`Edit ${label}`}
            title={`Edit ${label}`}
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
        disabled={isSaving}
        className={cn("h-7 aria-invalid:border-destructive", inputClassName)}
        onChange={(event) => {
          setDraft(event.target.value);
          setError(null);
        }}
        onKeyDown={handleKeyDown}
      />
      <Button
        size="icon"
        variant="ghost"
        className="size-7 shrink-0 [&_svg]:size-3.5"
        aria-label={`Save ${label}`}
        disabled={isSaving}
        onClick={() => void commit()}
      >
        {isSaving ? <Loader2 aria-hidden className="animate-spin" /> : <Check aria-hidden />}
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="size-7 shrink-0 text-muted-foreground [&_svg]:size-3.5"
        aria-label={`Cancel ${label} edit`}
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
