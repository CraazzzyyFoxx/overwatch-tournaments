import type { ReactNode, Ref } from "react";

import { cn } from "@/lib/utils";

const VARIANT = {
  /** A card panel of its own. */
  panel: "rounded-xl border bg-card p-1.5",
  /** The header strip of the card it sits in (a table's filters): a rule beneath. */
  inset: "border-b px-4.5 py-3",
  /** No surface: the controls sit on the page above a stack of cards. */
  plain: ""
} as const;

export type SectionToolbarProps = {
  /** Filter chips, stage switchers — the leading group. */
  children: ReactNode;
  /** Search, sort, pickers — the trailing group, pushed to the end. */
  end?: ReactNode;
  /** The view switch, pinned to the far end whether or not there are chips. */
  view?: ReactNode;
  label: string;
  variant?: keyof typeof VARIANT;
  className?: string;
  ref?: Ref<HTMLDivElement>;
};

/**
 * The one toolbar shape every public tournament section uses: chips on the
 * start, controls on the end and the view switch last, wrapping under itself
 * on narrow screens. The leading group scrolls sideways in place rather than
 * wrapping. Hairlines split adjacent labelled chip groups (stage | role) and,
 * from `sm`, the chips from the end controls; with no chips the end controls
 * take the start and the view switch stays at the far end. With nothing in it,
 * the toolbar hides rather than draw an empty box; below `sm`, so does a
 * leading group holding only mobile-hidden controls, rather than leave an
 * empty row.
 */
export function SectionToolbar({
  children,
  end,
  view,
  label,
  variant = "panel",
  className,
  ref
}: Readonly<SectionToolbarProps>) {
  return (
    <div
      ref={ref}
      role="group"
      aria-label={label}
      className={cn(
        "flex flex-wrap items-center gap-2 has-[>:only-child:empty]:hidden sm:gap-3",
        VARIANT[variant],
        className
      )}
    >
      <div className="peer flex min-w-0 max-w-full basis-full gap-1.75 overflow-x-auto overflow-y-hidden overscroll-x-contain py-0.5 [scrollbar-width:thin] empty:hidden max-sm:[&:not(:has(>:not(.hidden)))]:hidden *:flex-none sm:flex-1 sm:basis-auto [&>[role=group]+[role=group]]:border-s [&>[role=group]+[role=group]]:ps-1.75">
        {children}
      </div>
      {end || view ? (
        <div className="flex basis-full flex-wrap items-center gap-2 sm:ml-auto sm:basis-auto sm:peer-empty:ml-0 sm:peer-empty:flex-1 sm:peer-[:not(:empty)]:border-s sm:peer-[:not(:empty)]:ps-3">
          {end}
          {view ? <div className="ms-auto">{view}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
