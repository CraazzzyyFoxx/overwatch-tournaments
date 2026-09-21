import { isValidElement, type ReactNode } from "react";

/**
 * Table of contents for a stored Markdown document.
 *
 * Two levels only: `##` is a section and `###` is a subsection under it. `#` is
 * the document's own title (the page already names the tab, so it is not a
 * navigation target) and `####` and deeper are detail inside a subsection —
 * listing them turns the rail into a second copy of the document.
 */
export type TocEntry = {
  /** Anchor target — the same value `Markdown` puts on the rendered heading. */
  id: string;
  text: string;
  level: 2 | 3;
};

const FENCE = /^\s{0,3}(?:```|~~~)/;
const HEADING = /^\s{0,3}(#{2,3})\s+(.+?)\s*#*\s*$/;

/**
 * Inline Markdown the RENDERED heading will not contain. The rail's link text
 * and the heading's id are both derived from source lines, and the heading
 * element's own text comes from React children, so the two disagree unless the
 * syntax characters come off here: `## **Чек-ин**` renders as `Чек-ин`.
 */
function stripInlineMarkdown(text: string): string {
  return text
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_`~]/g, "")
    .trim();
}

/**
 * Anchor id for a heading.
 *
 * ponytail: two headings with the same text produce the same id, and the
 * browser scrolls to the first one. Suffixing the duplicates would mean the
 * renderer and this parser both tracking occurrence order — the renderer sees
 * one heading at a time — and a regulation with two identically named sections
 * is a document problem before it is a navigation one. Number the sections if
 * it ever matters.
 */
export function slugifyHeading(text: string): string {
  const slug = stripInlineMarkdown(text)
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "section";
}

/** Flattens a rendered heading's children to the text the slug is built from. */
export function headingText(children: ReactNode): string {
  if (children === null || children === undefined || typeof children === "boolean") return "";
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(headingText).join("");
  // `isValidElement<P>` is a type predicate, so the element's props are checked
  // against the shape rather than asserted into it.
  if (isValidElement<{ children?: ReactNode }>(children)) {
    return headingText(children.props.children);
  }
  return "";
}

/**
 * Reads the section headings out of a Markdown source.
 *
 * Fenced code is skipped: a shell comment (`# rm -rf`) inside a block is not a
 * section, and a document that pasted one would otherwise get it in the rail.
 */
export function extractToc(source: string): TocEntry[] {
  const entries: TocEntry[] = [];
  let inFence = false;

  for (const line of source.split("\n")) {
    if (FENCE.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;

    const match = HEADING.exec(line);
    if (!match) continue;

    const text = stripInlineMarkdown(match[2]);
    if (!text) continue;
    entries.push({ id: slugifyHeading(match[2]), text, level: match[1].length as 2 | 3 });
  }

  return entries;
}
