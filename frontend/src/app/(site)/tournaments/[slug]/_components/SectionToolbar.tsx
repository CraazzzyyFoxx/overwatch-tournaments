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
 * The one toolbar shape every public tournament section uses: a single card
 * panel, chips on the start, controls on the end, wrapping under itself on
 * narrow screens. The leading group scrolls sideways in place rather than
 * wrapping. Hairlines split adjacent labelled chip groups (stage | role) and,
 * from `sm`, the chips from the end controls. With nothing in it, the panel
 * hides rather than draw an empty box.
 */
export function SectionToolbar({ children, end, label, className }: Readonly<SectionToolbarProps>) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-xl border bg-card p-1.5 has-[>:only-child:empty]:hidden sm:gap-3",
        className
      )}
    >
      <div className="peer flex min-w-0 max-w-full basis-full gap-1.75 overflow-x-auto overflow-y-hidden overscroll-x-contain py-0.5 [scrollbar-width:thin] empty:hidden *:flex-none sm:flex-1 sm:basis-auto [&>[role=group]+[role=group]]:border-s [&>[role=group]+[role=group]]:ps-1.75">
        {children}
      </div>
      {end ? (
        <div className="flex basis-full flex-wrap items-center gap-2 sm:ml-auto sm:basis-auto sm:peer-empty:ml-0 sm:peer-[:not(:empty)]:border-s sm:peer-[:not(:empty)]:ps-3">
          {end}
        </div>
      ) : null}
    </div>
  );
}
