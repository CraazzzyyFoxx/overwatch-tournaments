import { useId, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Heading style of one group inside an account-settings tab; exported for the disclosure summary that cannot be a SettingsGroup. */
export const SETTINGS_GROUP_HEADING_CLASS = "text-ui font-semibold text-[color:var(--aqt-fg)]";

/**
 * One titled group inside an account-settings tab (`h4` under the tab's `h3`).
 * Every tab used to style these headings its own way — muted 14px, uppercase
 * 12px, destructive — so the same level read as three different ranks.
 */
export function SettingsGroup({
  title,
  description,
  aside,
  tone,
  children
}: Readonly<{
  title: string;
  description?: ReactNode;
  /** Trailing slot on the heading row: a status line or a group-wide action. */
  aside?: ReactNode;
  tone?: "danger";
  children: ReactNode;
}>) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
        <div className="min-w-0 space-y-0.5">
          <h4
            id={id}
            className={cn(SETTINGS_GROUP_HEADING_CLASS, tone === "danger" && "text-destructive")}
          >
            {title}
          </h4>
          {description ? (
            <p className="text-caption text-pretty text-[color:var(--aqt-fg-muted)]">{description}</p>
          ) : null}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}
