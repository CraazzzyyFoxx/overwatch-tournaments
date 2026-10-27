"use client";

import { AlertTriangle } from "lucide-react";

import { ColorSwatch } from "@/components/ui/color-swatch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { invalidProps, settingErrorId } from "@/components/kit/SettingRow";

/**
 * One brand colour: a swatch that opens the picker and the hex it writes,
 * kept in step. Shared by the Branding section and the workspace wizard.
 *
 * Blank is a real value ("derive it"), so it shows as `fallback` behind a
 * dashed swatch and `placeholder` text, never as black.
 */
export function BrandColorField({
  id,
  label,
  value,
  onChange,
  fallback,
  placeholder,
  error,
  onBlur
}: Readonly<{
  id: string;
  label: string;
  value: string | null | undefined;
  onChange: (value: string) => void;
  /** What a blank field resolves to, as a CSS colour. */
  fallback?: string;
  /** What a blank field means, in words: "Auto", "Platform default". */
  placeholder?: string;
  error?: string;
  onBlur?: () => void;
}>) {
  const hex = value ?? "";
  return (
    <div className="min-w-0">
      <Label htmlFor={id}>{label}</Label>
      <div className="mt-1 flex items-center gap-2">
        <ColorSwatch value={hex} fallback={fallback} label={label} onValueChange={onChange} />
        <Input
          id={id}
          value={hex}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          placeholder={placeholder}
          spellCheck={false}
          // The hex is an identifier; the blank-state words are UI copy.
          className="font-mono placeholder:font-sans"
          {...invalidProps(id, error)}
        />
      </div>
      {error ? (
        <p
          id={settingErrorId(id)}
          role="alert"
          className="mt-1.5 flex items-start gap-1.5 text-caption text-danger"
        >
          <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {error}
        </p>
      ) : null}
    </div>
  );
}
