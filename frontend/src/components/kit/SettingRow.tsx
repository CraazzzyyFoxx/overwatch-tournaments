"use client";

import { useId, useLayoutEffect, useRef, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { cn } from "@/lib/utils";
import { useSettingsOutlineEntry } from "./SettingsOutline";

/** Id of the error line a `SettingRow` renders for the control `controlId`. */
export function settingErrorId(controlId: string): string {
  return `${controlId}-error`;
}

/** Id of the label a `SettingRow` renders for the control `controlId`. */
export function settingLabelId(controlId: string): string {
  return `${controlId}-label`;
}

/**
 * Id of the hint a `SettingRow` renders for the control `controlId`: a control
 * the label alone cannot explain (a switch) points `aria-describedby` at it.
 */
export function settingHintId(controlId: string): string {
  return `${controlId}-hint`;
}

/**
 * The control half of an inline error: spread on the control whose row gets
 * the same `error`, so the field is marked and names its message.
 */
export function invalidProps(controlId: string, error: string | undefined) {
  return error
    ? ({ "aria-invalid": true, "aria-describedby": settingErrorId(controlId) } as const)
    : {};
}

/** Characters used against a limit. `soft` is advice (search snippets), not a cap. */
export interface SettingRowCount {
  value: number;
  max: number;
  soft?: boolean;
}

/**
 * One setting: what it is and why on the left, the control on the right.
 *
 * `stacked` puts the control under its label at full width, for the values a
 * control column cannot hold: text a reader types, Markdown, a record table. A
 * group narrower than `@md` (28rem) stacks every row, from the same DOM. Beside
 * the label the control gets a 14rem column (more if its content needs it), so
 * a select in a wide card does not stretch to half the page.
 *
 * `error` renders under the control, with an icon and words (never colour
 * alone); pair it with `invalidProps(htmlFor, error)` on the control. `count`
 * sits at the end of the label line.
 *
 * Lived inside `RegistrationFormBuilder` until the registration policy moved
 * into the settings rail; every settings section now builds rows from it, and
 * a second copy of a 12-line layout primitive is how two settings pages start
 * drifting apart visually.
 */
export function SettingRow({
  htmlFor,
  label,
  hint,
  stacked = false,
  error,
  count,
  children
}: Readonly<{
  htmlFor?: string;
  label: string;
  hint?: ReactNode;
  stacked?: boolean;
  error?: string;
  count?: SettingRowCount;
  children: ReactNode;
}>) {
  const fallbackId = useId();
  const errorId = htmlFor ? settingErrorId(htmlFor) : fallbackId;
  const over = count ? count.value > count.max : false;

  return (
    <div
      className={cn(
        "grid gap-2 py-3 first:pt-0 last:pb-0",
        // The container, not the viewport, decides: a settings card is one
        // column of a `SettingsGrid`, and a dialog is narrower still.
        !stacked && "@md:grid-cols-[minmax(0,1fr)_minmax(auto,14rem)] @md:items-center @md:gap-6"
      )}
    >
      <div className="min-w-0">
        <div className="flex items-baseline justify-between gap-3">
          <Label
            id={htmlFor ? settingLabelId(htmlFor) : undefined}
            htmlFor={htmlFor}
            className="text-sm font-medium text-foreground"
          >
            {label}
          </Label>
          {count ? (
            <span
              className={cn(
                "aqt-tnum shrink-0 text-label",
                over ? (count.soft ? "text-warning" : "text-danger") : "text-muted-foreground"
              )}
            >
              {count.value} / {count.max}
            </span>
          ) : null}
        </div>
        {hint ? (
          <p id={htmlFor ? settingHintId(htmlFor) : undefined} className="mt-0.5 max-w-prose text-xs text-muted-foreground">
            {hint}
          </p>
        ) : null}
      </div>
      <div className="min-w-0">
        <div className={cn("flex min-w-0 items-center", !stacked && "@md:justify-end")}>
          {children}
        </div>
        {error ? (
          <p id={errorId} role="alert" className="mt-1.5 flex items-start gap-1.5 text-caption text-danger">
            <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            <span className="min-w-0 [overflow-wrap:anywhere]">{error}</span>
          </p>
        ) : null}
      </div>
    </div>
  );
}

/**
 * A titled group of rows, framed as one card: a settings page is a stack of
 * these, so each group reads as its own unit instead of a stretch of one long
 * form. Rows are separated by hairlines inside the card, never by another
 * frame (DESIGN §5, one level of framing). A hub body (T3) is the same stack.
 *
 * `id` is the group's anchor: stable and locale-free, because it is what a
 * `#fragment` link and the section rail's outline (`SettingsOutline`) point at.
 *
 * `summary` is a count or a verdict beside the title, in body case; `actions`
 * are the group's own controls, at the end of the title line.
 *
 * `immediate` marks a group whose controls act on their own (an upload, a
 * transfer, a DNS check) rather than through the page's save bar, so the two
 * save models never share a group without saying so.
 *
 * `flush` drops the body's padding and row hairlines for one block that runs
 * edge to edge: a table, which brings its own rules between rows.
 *
 * `wide` spans every column of the `SettingsGrid` it sits in, for a body that
 * needs the page's width (a document editor, a per-round table).
 *
 * `level` is the title's heading rank: 2 under a page `h1`, deeper inside a
 * dialog whose own title and section heading sit above the group.
 */
export function SettingGroup({
  id,
  title,
  summary,
  description,
  actions,
  immediate = false,
  flush = false,
  wide = false,
  level = 2,
  children
}: Readonly<{
  id: string;
  title: string;
  summary?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  immediate?: boolean;
  flush?: boolean;
  wide?: boolean;
  level?: 2 | 3 | 4;
  children: ReactNode;
}>) {
  const t = useTranslations("kit.settings");
  const titleId = useId();
  const ref = useRef<HTMLElement>(null);
  useSettingsOutlineEntry(id, title, ref);
  const Heading = `h${level}` as const;

  return (
    // `scroll-mt-16` keeps a jumped-to group clear of the admin top bar; a
    // flush body is clipped to the card's corners.
    <Card asChild className={cn("scroll-mt-16", flush && "overflow-hidden", wide && "col-span-full")}>
      <section id={id} ref={ref} aria-labelledby={titleId}>
        {/* `min-w-48`: past that the actions wrap under the title instead of squeezing it. */}
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
          <div className="min-w-48 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <Heading id={titleId} className="text-ui font-semibold text-foreground">
                {title}
                {summary != null && summary !== false ? (
                  <span className="ml-2 font-normal tabular-nums text-muted-foreground">{summary}</span>
                ) : null}
              </Heading>
              {immediate ? (
                <p className="text-xs text-muted-foreground">{t("appliesImmediately")}</p>
              ) : null}
            </div>
            {description ? (
              <p className="mt-0.5 max-w-prose text-xs text-muted-foreground">{description}</p>
            ) : null}
          </div>
          {/* Pulled into the header's padding, so a row of buttons does not
              make a group with actions taller than one without. */}
          {actions ? <div className="-my-1 flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </header>
        {/* `empty:hidden`: a collapsed group is its header alone. */}
        <div
          className={cn(
            "@container border-t border-border empty:hidden",
            !flush && "divide-y divide-border/60 px-5 py-3"
          )}
        >
          {children}
        </div>
      </section>
    </Card>
  );
}

/**
 * The page body that holds a section's `SettingGroup` cards: columns of at
 * least 26rem, at most three, and only as many as there are cards (empty
 * tracks collapse, so one card fills the width and two split it).
 *
 * Cards that all fit in one row are one row of equal height. More cards than
 * columns pack as masonry: in reading order, each into the column that ends
 * highest, so a short card never leaves a hole beside a tall one. A `wide`
 * group spans every column.
 *
 * Masonry by row spans: the rows are 1px and each card spans its own height
 * plus the gap, re-measured whenever a card resizes or the set of cards
 * changes. Until then (server render, first paint) it is a plain grid.
 *
 * Only cards go in here: a page note sits outside it. A save bar belongs to
 * the block it saves, inside one wrapper with its card.
 */
export function SettingsGrid({ children }: Readonly<{ children: ReactNode }>) {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const grid = ref.current;
    if (!grid) return;
    const place = () => {
      const items = Array.from(grid.children) as HTMLElement[];
      const style = getComputedStyle(grid);
      // Every auto-fit track, collapsed ones included: how many cards one row holds.
      const columns = style.gridTemplateColumns.split(" ").length;
      if (items.length <= columns) {
        grid.style.cssText = "align-items: stretch";
        for (const item of items) item.style.gridRowEnd = "";
        return;
      }
      // Measured at their own height first (`items-start`), then spanned: reads before writes.
      grid.style.cssText = "grid-auto-rows: 1px; row-gap: 0px";
      const gap = Number.parseFloat(style.columnGap) || 0;
      const spans = items.map((item) => Math.max(1, Math.ceil(item.getBoundingClientRect().height + gap)));
      items.forEach((item, index) => (item.style.gridRowEnd = `span ${spans[index]}`));
    };
    // Re-spanning a card never changes its height, and a stretched row stays one row, so this cannot feed back.
    const resize = new ResizeObserver(place);
    const watch = () => {
      resize.disconnect();
      for (const item of Array.from(grid.children)) resize.observe(item);
      place();
    };
    const mutation = new MutationObserver(watch);
    mutation.observe(grid, { childList: true });
    watch();
    return () => {
      resize.disconnect();
      mutation.disconnect();
      grid.style.cssText = "";
    };
  }, []);

  return (
    <div
      ref={ref}
      className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,max(26rem,calc((100%_-_2rem)/3))),1fr))] items-start gap-4"
    >
      {children}
    </div>
  );
}
