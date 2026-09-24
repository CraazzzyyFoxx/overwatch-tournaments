import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";

interface SpinnerProps {
  /** Overrides the default `size-4`; also carries margin/colour. */
  className?: string;
  /**
   * Announce the wait. Pass it when the spinner is the only loading indicator
   * of its region; leave it off when visible text already says "Saving…".
   */
  label?: string;
}

/**
 * The one loading spinner. Decorative by default — an icon inside a button
 * whose label already changed to "Saving…" must not be announced twice.
 */
export function Spinner({ className, label }: Readonly<SpinnerProps>) {
  const icon = <LoaderCircle aria-hidden className={cn("size-4 animate-spin", className)} />;

  if (!label) {
    return icon;
  }

  return (
    <span role="status" className="inline-flex items-center">
      {icon}
      <span className="sr-only">{label}</span>
    </span>
  );
}
