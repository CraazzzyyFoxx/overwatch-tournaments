import Link from "next/link";
import type { MDXComponents } from "mdx/types";
import type { ComponentProps, ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

/** Running text: paragraphs and list items. */
const TEXT = "text-body leading-relaxed text-[color:var(--aqt-fg-muted)]";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]";

/** A docs page's own h1 (an article's title comes from the registry, not the MDX). */
export const DOC_TITLE = "font-display text-title font-bold text-balance text-[color:var(--aqt-fg)]";

/** The grid of guide cards on the docs hub and on a guide's index. */
export const DOC_CARDS = "mt-6 grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3";

/**
 * A whole-card link to a guide or an article: the border turns teal under the
 * pointer. `external` for a page Next does not route (`/api/docs`, the gateway's).
 */
export function DocCard({
  href,
  external = false,
  title,
  description,
}: Readonly<{ href: string; external?: boolean; title: string; description?: string }>) {
  const body = (
    <>
      <CardTitle className="text-ui">{title}</CardTitle>
      {description ? <CardDescription className="mt-1 text-caption">{description}</CardDescription> : null}
    </>
  );
  return (
    <Card
      asChild
      className={cn("block px-4 py-3.5 transition-colors duration-150 hover:border-[color:var(--aqt-teal)]", FOCUS)}
    >
      {external ? <a href={href}>{body}</a> : <Link href={href}>{body}</Link>}
    </Card>
  );
}

/** A paragraph; the first one under the page's h1 is the lead. */
export function P({ className, ...props }: ComponentProps<"p">) {
  return <p className={cn("mt-2 [h1+&]:mt-3 [h1+&]:text-pretty", TEXT, className)} {...props} />;
}

export function H2(props: ComponentProps<"h2">) {
  return <h2 {...props} className="mt-10 text-ui font-semibold text-[color:var(--aqt-fg)]" />;
}

export function Anchor({ href = "", className, ...props }: ComponentProps<"a">) {
  const linkClass = cn("text-[color:var(--aqt-teal)]", FOCUS, className);
  // `/api/*` is the gateway, not a Next route.
  if (href.startsWith("/") && !href.startsWith("/api/")) {
    return <Link href={href} className={linkClass} {...props} />;
  }
  return (
    <a
      href={href}
      rel={href.startsWith("http") ? "noreferrer" : undefined}
      className={linkClass}
      {...props}
    />
  );
}

function Callout({
  type = "note",
  children,
}: Readonly<{ type?: "note" | "warning"; children: ReactNode }>) {
  return (
    <Alert tone={type === "warning" ? "warning" : "info"} className="mt-5 *:first:mt-0">
      {children}
    </Alert>
  );
}

/** Everything an article may use. Anything else in an MDX file fails to render. */
export const mdxComponents: MDXComponents = {
  h2: H2,
  h3: (props) => <h3 {...props} className="mt-7 text-body font-semibold text-[color:var(--aqt-fg)]" />,
  p: P,
  // Preflight strips markers; numbered steps must show their numbers.
  ul: (props) => <ul {...props} className="mt-2 list-disc pl-5 marker:text-[color:var(--aqt-fg-faint)]" />,
  ol: (props) => <ol {...props} className="mt-2 list-decimal pl-5 marker:text-[color:var(--aqt-fg-faint)]" />,
  // A loose list wraps each item in a `<p>`: the item's own margin is the gap.
  li: (props) => <li {...props} className={cn("mt-2", TEXT, "*:first:mt-0")} />,
  strong: (props) => <strong {...props} className="font-semibold text-[color:var(--aqt-fg)]" />,
  a: Anchor,
  code: ({ className, ...props }) => (
    <code
      {...props}
      className={cn(
        "rounded-lg bg-[color:var(--aqt-overlay-4)] px-1 py-px text-label text-[color:var(--aqt-fg)] wrap-anywhere",
        className
      )}
    />
  ),
  // A fenced block's `<code>` drops the inline chip and keeps the block's colour.
  pre: (props) => (
    <pre
      {...props}
      className="mt-3 overflow-x-auto rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-4 py-3 text-caption leading-relaxed [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-[color:var(--aqt-fg-muted)] [&_code]:wrap-normal"
    />
  ),
  // A column sizes to its widest unbreakable word; letting inline code break
  // anywhere there squeezed `subscribe` into `subscrib|e`. The wrapper scrolls instead.
  table: (props) => (
    <Table
      {...props}
      wrapperClassName="mt-3"
      className="text-[color:var(--aqt-fg-muted)] [&_code]:whitespace-nowrap [&_code]:wrap-normal"
    />
  ),
  thead: TableHeader,
  tbody: TableBody,
  tr: TableRow,
  th: TableHead,
  td: (props) => <TableCell {...props} className="align-top" />,
  Callout,
};
