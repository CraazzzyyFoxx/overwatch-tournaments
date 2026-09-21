"use client";

import { ArrowDownIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { useCallback } from "react";
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";

import { Button } from "@/components/ui/button";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { cn } from "@/lib/utils";

/**
 * The stick-to-bottom transcript scroller, vendored from the `@ai-elements`
 * registry and then fixed where the upstream copy is wrong for a human chat.
 *
 * shadcn's newer `message-scroller` covers the same ground with turn anchoring
 * and an animated jump button, but it is a NEW dependency (`@shadcn/react`,
 * still 0.x) plus five utilities this stylesheet does not define; the three
 * defects that actually reached users are fixable here:
 *
 * 1. The scroll container was not reachable by keyboard. `StickToBottom.Content`
 *    scrolls an unclassed `div` with no tabindex, so in a read-only room (a
 *    spectator, a muted viewer — no buttons inside the log) there was no key
 *    that moved the transcript at all. The content block takes `tabIndex={0}`,
 *    which makes the scrollport focusable and arrow keys work.
 * 2. Scroll chaining escaped to the page; `overscroll-contain` keeps it inside.
 * 3. The spring scroll ran regardless of `prefers-reduced-motion`. The library
 *    never reads the query (no `matchMedia` in its dist), so the preference has
 *    to be turned into its `"instant"` behaviour here.
 */
export type ConversationProps = ComponentProps<typeof StickToBottom>;

export const Conversation = ({ className, initial, resize, ...props }: ConversationProps) => {
  const reduced = usePrefersReducedMotion();
  return (
    <StickToBottom
      className={cn("relative min-h-0 flex-1 overflow-y-hidden", className)}
      initial={initial ?? (reduced ? "instant" : "smooth")}
      resize={resize ?? (reduced ? "instant" : "smooth")}
      role="log"
      {...props}
    />
  );
};

export type ConversationContentProps = ComponentProps<typeof StickToBottom.Content>;

export const ConversationContent = ({
  className,
  scrollClassName,
  ...props
}: ConversationContentProps) => (
  <StickToBottom.Content
    scrollClassName={cn("overscroll-contain", scrollClassName)}
    tabIndex={0}
    className={cn(
      "flex flex-col gap-8 p-4 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
      className
    )}
    {...props}
  />
);

export type ConversationEmptyStateProps = ComponentProps<"div"> & {
  title?: string;
  description?: string;
  icon?: ReactNode;
};

export const ConversationEmptyState = ({
  className,
  title = "No messages yet",
  description,
  icon,
  children,
  ...props
}: ConversationEmptyStateProps) => (
  <div
    className={cn(
      "flex size-full flex-col items-center justify-center gap-3 p-8 text-center",
      className
    )}
    {...props}
  >
    {children ?? (
      <>
        {icon ? (
          <div className="flex size-10 items-center justify-center rounded-lg border bg-muted/40 text-muted-foreground">
            {icon}
          </div>
        ) : null}
        <div className="space-y-1">
          <h3 className="text-sm font-medium">{title}</h3>
          {description ? (
            <p className="max-w-[24ch] text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
      </>
    )}
  </div>
);

/**
 * Jump back to the live edge. Mounted only while the reader has scrolled away,
 * so it never sits in the tab order when it would do nothing — and it carries a
 * name: an icon-only button with no `aria-label` announced as "button".
 */
export type ConversationScrollButtonProps = ComponentProps<typeof Button>;

export const ConversationScrollButton = ({
  className,
  ...props
}: ConversationScrollButtonProps) => {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();

  const handleScrollToBottom = useCallback(() => {
    scrollToBottom();
  }, [scrollToBottom]);

  return (
    !isAtBottom && (
      <Button
        className={cn(
          "absolute bottom-3 left-1/2 size-8 -translate-x-1/2 rounded-full shadow-md",
          className
        )}
        onClick={handleScrollToBottom}
        size="icon"
        type="button"
        variant="secondary"
        {...props}
      >
        <ArrowDownIcon className="size-4" aria-hidden />
      </Button>
    )
  );
};
