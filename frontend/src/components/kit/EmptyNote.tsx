import type { ElementType, ReactNode } from "react";

import { TONE_TEXT, type Tone } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

export interface EmptyNoteProps {
  children: ReactNode;
  /** Bold first line above the body; switches to the centered layout. */
  title?: string;
  icon?: ElementType;
  /** A single next action (button or link), rendered under the text. */
  action?: ReactNode;
  /** `sm` is the one-line hint inside a form or list; default is a block. */
  size?: "sm" | "md";
  /** Border colour only — the copy stays muted so the note never shouts. */
  tone?: Extract<Tone, "neutral" | "warning" | "danger">;
  className?: string;
}

const BORDER: Record<NonNullable<EmptyNoteProps["tone"]>, string> = {
  neutral: "border-border/70",
  warning: "border-warning/40 bg-warning/5",
  danger: "border-danger/40 bg-danger/5"
};

/**
 * The admin's one dashed note: "nothing here yet", "pick a workspace first",
 * "this needs X to be enabled". It is NOT `PageStateCard` — that is a whole
 * screen's state; this sits inside a card, a table cell or a form.
 *
 * Before this, 32 sites drew their own dashed box with nine different padding
 * and radius combinations. Two sizes exist because two jobs exist: `md` is the
 * empty body of a list, `sm` is a hint beside a control.
 */
export function EmptyNote({
  children,
  title,
  icon: Icon,
  action,
  size = "md",
  tone = "neutral",
  className
}: Readonly<EmptyNoteProps>) {
  const centered = Boolean(title || Icon);
  return (
    <div
      className={cn(
        "rounded-lg border border-dashed text-muted-foreground",
        BORDER[tone],
        size === "sm" ? "px-3 py-2 text-xs" : "px-4 py-6 text-sm",
        centered && "flex flex-col items-center text-center",
        className
      )}
    >
      {Icon ? (
        <Icon
          className={cn("size-6", tone === "neutral" ? "text-muted-foreground" : TONE_TEXT[tone])}
          aria-hidden
        />
      ) : null}
      {title ? <p className={cn("font-medium text-foreground", Icon && "mt-3")}>{title}</p> : null}
      <div className={cn(title && "mt-1", centered && "max-w-prose")}>{children}</div>
      {action ? <div className={cn("mt-4", !centered && "flex")}>{action}</div> : null}
    </div>
  );
}
