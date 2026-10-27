import * as React from "react";

import { TONE_CLASS, type Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  /** The tint (`TONE_CLASS`). Only `danger` interrupts a screen reader (`role="alert"`); the rest are `status`. */
  tone?: Tone;
}

/**
 * A notice block with an optional leading icon. The block's radius is the
 * card's (12px); a leading `<svg>` is placed on the first line of text.
 */
const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, tone = "neutral", ...props }, ref) => (
    <div
      ref={ref}
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "relative w-full rounded-xl border px-4 py-3 text-body [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-3.5 [&>svg]:size-4 [&>svg~*]:pl-7",
        TONE_CLASS[tone],
        className
      )}
      {...props}
    />
  )
);
Alert.displayName = "Alert";

/** The alert's lead line. A `<p>`, not a heading: the alert sits inside a section that already has one. */
const AlertTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p ref={ref} className={cn("mb-1 font-semibold", className)} {...props} />
));
AlertTitle.displayName = "AlertTitle";

const AlertDescription = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("[&_p]:leading-relaxed", className)} {...props} />
  )
);
AlertDescription.displayName = "AlertDescription";

export { Alert, AlertTitle, AlertDescription };
