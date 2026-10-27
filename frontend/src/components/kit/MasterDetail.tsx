"use client";

import type { CSSProperties, ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { RowButton } from "@/components/ui/row-button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

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
  const t = useTranslations("kit.actions");
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
        {t("backToList")}
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

export interface MasterListItem<K extends string | number> {
  key: K;
  label: string;
  /** Decorative mark before the label, e.g. a role icon. */
  icon?: ReactNode;
}

/**
 * The plain T4 list column: one frame of named rows, the selected one marked
 * with `aria-current`. Selecting is navigation, so `onSelect` writes the
 * caller's query param (with `mode: "push"`, see `MasterDetail`). Lists with a
 * toolbar of their own (search, per-row actions) keep their own component.
 */
export function MasterList<K extends string | number>({
  label,
  items,
  selectedKey,
  onSelect
}: Readonly<{
  /** Accessible name of the `<nav>`. */
  label: string;
  items: readonly MasterListItem<K>[];
  selectedKey: K | null | undefined;
  onSelect: (key: K) => void;
}>) {
  return (
    <Card asChild className="p-2">
      <nav aria-label={label}>
        <ul className="flex flex-col gap-0.5">
          {items.map((item) => {
            const isSelected = item.key === selectedKey;
            return (
              <li key={item.key}>
                <RowButton
                  aria-current={isSelected ? "true" : undefined}
                  onClick={() => onSelect(item.key)}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-muted-foreground hover:text-foreground aria-[current=true]:text-foreground"
                >
                  {item.icon}
                  <span className={cn("min-w-0 flex-1 truncate text-sm", isSelected && "font-medium")}>
                    {item.label}
                  </span>
                </RowButton>
              </li>
            );
          })}
        </ul>
      </nav>
    </Card>
  );
}

/** `MasterList` while its rows load: the same frame with placeholder rows. */
export function MasterListSkeleton() {
  return (
    <Card aria-hidden className="flex flex-col gap-0.5 p-2">
      {[0, 1, 2, 3].map((row) => (
        <Skeleton key={row} className="h-8 w-full rounded-md" />
      ))}
    </Card>
  );
}
