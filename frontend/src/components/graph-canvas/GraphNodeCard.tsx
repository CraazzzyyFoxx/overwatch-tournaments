import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The one node card every canvas draws: an accent-coloured frame, a caption line (a tree path, a node kind), a title
 * row with the node's actions on its right, then the node's own body. Handles go in `handles`, outside the body, so
 * they position against the node rather than a row.
 */
export function GraphNodeCard({
  accent,
  selected,
  eyebrow,
  title,
  actions,
  handles,
  className,
  children,
  "aria-label": ariaLabel
}: Readonly<{
  /** A colour token for the frame (and the minimap swatch, through `data.accent`); the neutral border without one. */
  accent?: string;
  selected?: boolean;
  eyebrow?: ReactNode;
  title: ReactNode;
  actions?: ReactNode;
  handles?: ReactNode;
  className?: string;
  children?: ReactNode;
  "aria-label"?: string;
}>) {
  const style: CSSProperties | undefined = accent ? { borderColor: accent } : undefined;
  return (
    <div
      aria-label={ariaLabel}
      className={cn(
        "rounded-lg border-2 bg-card px-3 py-2 shadow-md",
        selected && "ring-2 ring-ring ring-offset-2 ring-offset-background",
        className
      )}
      style={style}
    >
      {handles}
      {eyebrow ? <div className="text-label tabular-nums text-muted-foreground">{eyebrow}</div> : null}
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1 text-caption font-semibold">{title}</div>
        {actions ? <div className="flex shrink-0 items-center gap-0.5">{actions}</div> : null}
      </div>
      {children ? <div className="mt-2">{children}</div> : null}
    </div>
  );
}
