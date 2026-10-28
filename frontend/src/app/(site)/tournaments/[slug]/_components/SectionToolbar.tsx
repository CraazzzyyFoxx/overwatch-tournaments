import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SectionToolbarProps = {
  /** Filter chips, stage switchers — the leading group. */
  children: ReactNode;
  /** Search, sort, view segment — the trailing group, pushed to the end. */
  end?: ReactNode;
  label: string;
  className?: string;
};

/**
 * The one toolbar shape every public tournament section uses: chips on the
 * start, controls on the end, wrapping under itself on narrow screens. The
 * leading group scrolls sideways in place rather than wrapping.
 */
export function SectionToolbar({ children, end, label, className }: Readonly<SectionToolbarProps>) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn("flex flex-wrap items-center gap-2 sm:gap-3", className)}
    >
      <div className="flex min-w-0 max-w-full basis-full gap-1.75 overflow-x-auto overflow-y-hidden overscroll-x-contain py-0.5 [scrollbar-width:thin] *:flex-none sm:flex-1 sm:basis-auto">
        {children}
      </div>
      {end ? (
        <div className="flex basis-full flex-wrap items-center gap-2 sm:ml-auto sm:basis-auto">
          {end}
        </div>
      ) : null}
    </div>
  );
}
