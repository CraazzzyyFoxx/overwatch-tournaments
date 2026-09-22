"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

interface FieldLabelProps {
  label: string;
  /**
   * `id` of the control this labels. Required for real inputs — without it the
   * field has no programmatic label and a screen reader announces a bare edit
   * box. Omit it only when the label sits inside a `<fieldset>`/composite
   * widget that carries its own `aria-label`.
   */
  htmlFor?: string;
  required?: boolean;
  icon?: ReactNode;
  className?: string;
}

/**
 * Registration field label. This used to render a `<span>`, which meant every
 * field in the public registration flow was visually labelled and
 * programmatically anonymous.
 */
export default function FieldLabel({
  label,
  htmlFor,
  required = false,
  icon,
  className,
}: Readonly<FieldLabelProps>) {
  const t = useTranslations();
  const Tag = htmlFor ? "label" : "span";
  return (
    <Tag htmlFor={htmlFor} className={cn("inline-flex items-center gap-2", className)}>
      {icon ? <span className="flex shrink-0 items-center justify-center">{icon}</span> : null}
      <span className="text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
        {label}
        {required && (
          <span className="ml-0.5 text-destructive">
            <span aria-hidden="true">*</span>
            <span className="sr-only">{t("common.required")}</span>
          </span>
        )}
      </span>
    </Tag>
  );
}
