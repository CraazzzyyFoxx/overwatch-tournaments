import * as React from "react";

import { controlSurfaceClass } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface TextareaProps extends React.ComponentProps<"textarea"> {
  /** The text of its row, like `Input`: `sm` 13px (a 32px-row form), `default` 14px. */
  size?: "sm" | "default";
}

// 16px below `sm`, like `Input`: iOS Safari zooms into anything smaller.
const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, size = "default", ...props }, ref) => {
    return (
      <textarea
        className={cn(
          controlSurfaceClass,
          "flex min-h-20 py-2 text-base",
          size === "sm" ? "sm:text-caption" : "sm:text-sm",
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Textarea.displayName = "Textarea";

export { Textarea };
