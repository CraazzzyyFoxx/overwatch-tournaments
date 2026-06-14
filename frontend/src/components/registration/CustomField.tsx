"use client";

import { useEffect } from "react";
import type { CustomFieldDefinition } from "@/types/registration.types";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import FieldLabel from "./FieldLabel";
import { getCustomFieldValidationError } from "./validation";

interface CustomFieldProps {
  definition: CustomFieldDefinition;
  value: string;
  onChange: (v: string) => void;
  onValidationChange?: (error: string | null) => void;
}

export default function CustomField({
  definition,
  value,
  onChange,
  onValidationChange,
}: CustomFieldProps) {
  const inputType = definition.type === "number" ? "number" : definition.type === "url" ? "url" : "text";
  const validationError = getCustomFieldValidationError(definition, value);

  useEffect(() => {
    onValidationChange?.(validationError);
  }, [onValidationChange, validationError]);

  if (definition.type === "select" && definition.options) {
    return (
      <div className="space-y-1.5">
        <FieldLabel label={definition.label} required={definition.required} />
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-full rounded-lg border border-white/10 bg-white/3 px-3 text-sm text-white outline-none"
        >
          <option value="">Select...</option>
          {definition.options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </div>
    );
  }

  if (definition.type === "checkbox") {
    return (
      <div className="space-y-2">
        <label className="flex items-center gap-3">
          <Switch
            checked={value === "true"}
            onCheckedChange={(checked) => onChange(checked ? "true" : "false")}
          />
          <FieldLabel label={definition.label} required={definition.required} />
        </label>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <FieldLabel label={definition.label} required={definition.required} />
      <input
        type={inputType}
        placeholder={definition.placeholder ?? ""}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "h-9 w-full rounded-lg border border-white/10 bg-white/3 px-3 text-sm text-white placeholder-white/30 outline-none transition-colors focus:border-white/20",
          validationError && "border-red-500/70 text-red-100 placeholder:text-red-200/60 focus:border-red-500/70",
        )}
      />
      {validationError && (
        <p className="text-xs text-red-400">{validationError}</p>
      )}
    </div>
  );
}
