"use client";

import type { CSSProperties, ReactNode } from "react";
import { ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";

export interface MasterDetailProps {
  list: ReactNode;
  /**
   * The editor for the selected row, or `null`/`undefined` when nothing is
   * selected — which is also what switches the narrow layout back to the list.
   */
  detail: ReactNode;
  listWidth?: number;
  emptyDetail?: ReactNode;
}

/**
 * The T4 layout: a list on the left, an editor on the right.
 *
 * Replaces the "one screen, seven dialogs" shape of `StageManager` and the
 * pre-game scope selector: selecting is navigation, editing is a panel, and
 * neither is a modal.
 *
 * Below `md` there is no room for both, so it shows one at a time. The
 * caller MUST write its selection with `mode: "push"` — the Back button steps
 * the history entry back, which is the only way to return to the list without
 * this component knowing the caller's query-param name.
 */
export function MasterDetail({
  list,
  detail,
  listWidth = 280,
  emptyDetail
}: Readonly<MasterDetailProps>) {
  const hasSelection = detail !== null && detail !== undefined && detail !== false;

  return (
    <div
      className="grid gap-4 md:[grid-template-columns:var(--admin-master-width)_minmax(0,1fr)]"
      style={{ "--admin-master-width": `${listWidth}px` } as CSSProperties}
    >
      <div className={hasSelection ? "hidden md:block" : "block"}>{list}</div>
      <div className={hasSelection ? "block min-w-0" : "hidden min-w-0 md:block"}>
        {hasSelection ? (
          <>
            <div className="mb-3 md:hidden">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => window.history.back()}
              >
                <ChevronLeft aria-hidden className="size-4" />
                Back to list
              </Button>
            </div>
            {detail}
          </>
        ) : (
          emptyDetail
        )}
      </div>
    </div>
  );
}
