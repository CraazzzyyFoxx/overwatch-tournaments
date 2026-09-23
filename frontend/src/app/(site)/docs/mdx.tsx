import Link from "next/link";
import type { MDXComponents } from "mdx/types";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

import styles from "./docs.module.css";

function Callout({
  type = "note",
  children,
}: Readonly<{ type?: "note" | "warning"; children: ReactNode }>) {
  return (
    <div className={cn(styles.callout, type === "warning" && styles.calloutWarning)}>{children}</div>
  );
}

function Anchor({ href = "", ...props }: ComponentProps<"a">) {
  // `/api/*` is the gateway, not a Next route.
  if (href.startsWith("/") && !href.startsWith("/api/")) {
    return <Link href={href} {...props} />;
  }
  return <a href={href} rel={href.startsWith("http") ? "noreferrer" : undefined} {...props} />;
}

function Table(props: ComponentProps<"table">) {
  return (
    <div className={styles.tableWrap}>
      <table {...props} />
    </div>
  );
}

/** Everything an article may use. Anything else in an MDX file fails to render. */
export const mdxComponents: MDXComponents = { a: Anchor, table: Table, Callout };
