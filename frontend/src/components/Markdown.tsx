import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/**
 * GFM on top of CommonMark: tables, task lists, strikethrough and autolinks —
 * exactly what an organizer's regulations document reaches for (a tiebreaker
 * table, a checklist of requirements).
 *
 * Exported because the admin editor's preview pane renders through the SAME
 * pipeline and the same component map: a preview that parses differently from
 * the public page is a preview that lies about what will be published.
 */
export const MARKDOWN_REMARK_PLUGINS = [remarkGfm];

/**
 * No sanitizer, and none is needed: `react-markdown` renders to React elements
 * rather than to an HTML string, and raw HTML in the source is passed through as
 * text unless `rehype-raw` is added (it is not). `dangerouslySetInnerHTML` never
 * appears on this path. Link protocols are filtered by react-markdown's default
 * `urlTransform`, which keeps http/https/mailto/tel and relative URLs and drops
 * everything else — a `javascript:` href renders as a link to nothing.
 */
const MARKDOWN_COMPONENTS: Components = {
  // The PAGE owns `h1` (the tournament's name), so a document's own top level
  // starts one step down. Levels are shifted rather than styled in place, which
  // keeps the heading outline of the page legal for a screen reader no matter
  // which level the author started at.
  h1: ({ node: _node, ...props }) => (
    <h2
      {...props}
      className="text-balance font-display text-headline font-semibold text-foreground"
    />
  ),
  h2: ({ node: _node, ...props }) => (
    <h3 {...props} className="text-balance font-display text-title font-semibold text-foreground" />
  ),
  // The bottom of the heading ladder sits AT the body size, never under it: a
  // heading smaller than the text it introduces reads as a caption. h3..h6
  // separate themselves by weight and foreground colour instead.
  h3: ({ node: _node, ...props }) => (
    <h4 {...props} className="text-reading font-semibold text-foreground" />
  ),
  h4: ({ node: _node, ...props }) => (
    <h5 {...props} className="text-reading font-semibold text-foreground" />
  ),
  h5: ({ node: _node, ...props }) => (
    <h6 {...props} className="text-reading font-semibold text-foreground" />
  ),
  h6: ({ node: _node, ...props }) => (
    <h6 {...props} className="text-reading font-semibold text-foreground" />
  ),
  p: ({ node: _node, ...props }) => <p {...props} className="text-pretty leading-relaxed" />,
  strong: ({ node: _node, ...props }) => (
    <strong {...props} className="font-semibold text-foreground" />
  ),
  a: ({ node: _node, ...props }) => (
    <a
      {...props}
      // Author-supplied destinations are third-party by definition: `noreferrer`
      // keeps the tournament page out of their referrer log and `noopener`
      // denies the opened tab a handle on this one.
      target="_blank"
      rel="noreferrer noopener"
      className="font-medium text-primary underline underline-offset-2 hover:no-underline"
    />
  ),
  ul: ({ node: _node, ...props }) => (
    <ul {...props} className="list-disc space-y-1 pl-5 leading-relaxed" />
  ),
  ol: ({ node: _node, ...props }) => (
    <ol {...props} className="list-decimal space-y-1 pl-5 leading-relaxed" />
  ),
  // A GFM task list carries its own checkbox and bullet-less layout; the class
  // is applied by react-markdown's `className` prop on the `<li>`.
  li: ({ node: _node, className, ...props }) => (
    <li {...props} className={cn("marker:text-muted-foreground", className)} />
  ),
  blockquote: ({ node: _node, ...props }) => (
    <blockquote {...props} className="border-l-2 border-primary/40 pl-4 text-muted-foreground" />
  ),
  hr: ({ node: _node, ...props }) => <hr {...props} className="border-border" />,
  code: ({ node: _node, className, ...props }) => (
    // A fenced block arrives as `<pre><code class="language-x">`; only the
    // inline form needs its own chip, so the fenced one keeps `pre`'s styling.
    <code
      {...props}
      className={cn(
        className,
        className?.includes("language-")
          ? "font-mono text-ui"
          : "rounded bg-muted px-1 py-0.5 font-mono text-ui text-foreground"
      )}
    />
  ),
  pre: ({ node: _node, ...props }) => (
    <pre
      {...props}
      className="overflow-x-auto rounded-lg border border-border bg-muted/40 p-3 text-ui"
    />
  ),
  // Tables get the scroll region the design system requires of every table, so
  // a wide tiebreaker grid scrolls instead of stretching the page on a phone.
  table: ({ node: _node, ...props }) => (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table {...props} className="w-full border-collapse text-ui" />
    </div>
  ),
  th: ({ node: _node, ...props }) => (
    <th
      {...props}
      className="border-b border-border bg-muted/40 px-3 py-2 text-left text-label font-semibold uppercase tracking-label text-muted-foreground"
    />
  ),
  td: ({ node: _node, ...props }) => (
    <td {...props} className="border-b border-border/60 px-3 py-2 align-top" />
  ),
  img: ({ node: _node, ...props }) => (
    // Author-supplied URL of unknown size and host: `next/image` needs
    // intrinsic dimensions or a sized parent, and `images.unoptimized` is on,
    // so it would buy nothing here.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      {...props}
      alt={props.alt ?? ""}
      loading="lazy"
      className="max-w-full rounded-lg border border-border"
    />
  )
};

type MarkdownProps = {
  /** Markdown source, stored verbatim server-side. */
  source: string;
  className?: string;
};

/**
 * Renders stored Markdown with the platform's type roles and tokens.
 *
 * Vertical rhythm lives on the wrapper (`space-y-*`) rather than on each block:
 * `react-markdown` renders its blocks as direct children here, so one rule
 * spaces headings, paragraphs, lists and tables consistently — and the
 * component map above never has to carry a margin that would double up when
 * two blocks of the same kind follow each other.
 *
 * The base size is `text-reading`, not the `text-body` every UI surface uses:
 * a stored document is read in paragraphs, and 14px is the density of a table
 * row. Everything smaller here (code, tables) is one rung down from it, not
 * three.
 */
export function Markdown({ source, className }: Readonly<MarkdownProps>) {
  return (
    <div className={cn("space-y-4 text-reading text-muted-foreground", className)}>
      <ReactMarkdown remarkPlugins={MARKDOWN_REMARK_PLUGINS} components={MARKDOWN_COMPONENTS}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
