/**
 * The tournament header's SECONDARY action box: the same 36px height, radius and
 * type size as the teal register button standing beside it, in the muted
 * palette.
 *
 * One const rather than a copy per call site. The geometry is load-bearing —
 * `.meta-pill` (11.5px type, 24px tall) made these read as metadata that had
 * wandered into the action row — and three drifting copies of the string is how
 * that regression comes back.
 *
 * Deliberately not a `tournaments.css` rule like `.meta-pill`: these boxes are
 * Tailwind-sized, and a CSS class would express one look in two languages.
 */
const ACTION_BOX =
  "inline-flex items-center gap-2 rounded-lg border border-[color:var(--aqt-border-2)] " +
  "bg-[color:var(--aqt-overlay-2)] px-4 py-2 text-sm font-medium " +
  "text-[color:var(--aqt-fg-muted)]";

export const TOURNAMENT_ACTION_CLASS =
  ACTION_BOX +
  " no-underline outline-none transition-colors " +
  "hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] " +
  "focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-bg)]";

/**
 * A STATE, not a control: "registration closed" is a `<div>`, so it takes the
 * action box's geometry and palette without the hover affordance that would
 * promise a click nothing handles.
 */
export const TOURNAMENT_STATUS_BOX_CLASS = ACTION_BOX + " text-[color:var(--aqt-fg-dim)]";

export const TOURNAMENT_PRIMARY_ACTION_CLASS =
  "inline-flex items-center gap-2 rounded-lg bg-[color:var(--aqt-teal)] px-4 py-2 text-sm font-medium " +
  "text-[color:var(--aqt-bg)] outline-none transition-opacity hover:opacity-90 " +
  "focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-bg)]";

/** Header text action: same sentence as a stamp, not a 36px box beside one. */
export const TOURNAMENT_TEXT_ACTION_CLASS =
  "inline-flex items-center gap-1.5 border-0 bg-transparent p-0 text-caption font-semibold " +
  "text-[color:var(--aqt-teal)] no-underline outline-none transition-opacity " +
  "hover:opacity-80 focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-bg)]";
