// No "use client": Server Components import these strings too. Through a
// client module they would arrive as a reference proxy, not a string.

/**
 * The trailing chevron of a select-like trigger: it turns over while the panel
 * is open, read off the `aria-expanded` of the trigger marked `group/trigger`
 * (named, so an expanded ancestor never turns it). A named group rather than a
 * `[[aria-expanded=true]>&]` selector: happy-dom keeps the `&gt;` that selector
 * serializes to inside an SVG class, and every hydration test would mismatch.
 */
export const triggerChevronClass =
  "size-4 shrink-0 opacity-50 transition-transform duration-150 group-aria-expanded/trigger:rotate-180";

/**
 * The chevron in a native `<details>`'s `<summary>`, `triggerChevronClass`'s
 * twin: it turns over while the `<details>` marked `group/disclosure` is open.
 * Its own group name, so a picker inside an open disclosure keeps its chevron
 * still. A `<details>` nested in another turns with the outer one: give the
 * inner one a Radix `Collapsible` instead.
 */
export const disclosureChevronClass =
  "size-4 shrink-0 opacity-50 transition-transform duration-150 group-open/disclosure:rotate-180";
