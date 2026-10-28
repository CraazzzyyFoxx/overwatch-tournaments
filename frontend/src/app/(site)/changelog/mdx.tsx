import { ArrowRight } from "lucide-react";
import type { MDXComponents } from "mdx/types";
import Link from "next/link";
import type { ReactNode } from "react";

import Image from "@/components/ui/image";
import { cn } from "@/lib/utils";

import { mdxComponents } from "../docs/mdx";

/** A topic inside an entry (markdown `###`), and the round-up's title. */
const H3 = "font-display text-title font-semibold text-[color:var(--aqt-fg)]";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-[color:var(--aqt-teal)]";

/** The entry's opening paragraph, a size above the body. */
function Lead({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <p className="mt-4 max-w-[60ch] text-ui leading-relaxed text-[color:var(--aqt-fg-muted)] md:text-reading">
      {children}
    </p>
  );
}

/** "Learn more" into the docs. */
function More({ href, children }: Readonly<{ href: string; children: ReactNode }>) {
  return (
    <Link
      href={href}
      prefetch={false}
      className={cn(
        "group mt-3.5 inline-flex items-center gap-1.5 rounded-sm text-caption font-semibold text-[color:var(--aqt-teal)] underline-offset-3 hover:underline",
        FOCUS
      )}
    >
      {children}
      <ArrowRight
        size={14}
        aria-hidden
        className="transition-transform duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-x-0.5 motion-reduce:transition-none"
      />
    </Link>
  );
}

/**
 * A screenshot; it opens full size in a new tab. 20px under a paragraph, 24px
 * under anything else, and the paragraph after it starts 28px down.
 */
function Shot({
  src,
  width,
  height,
  alt,
  priority
}: Readonly<{ src: string; width: number; height: number; alt: string; priority?: boolean }>) {
  return (
    <figure className="mt-6 [p+&]:mt-5 [&+p]:mt-7">
      <a href={src} target="_blank" rel="noreferrer" className={cn("block rounded-[var(--aqt-radius)]", FOCUS)}>
        <Image
          src={src}
          width={width}
          height={height}
          alt={alt}
          sizes="(min-width: 1024px) 880px, 100vw"
          // `priority` in the MDX, `preload` in Next 16: the old name is deprecated.
          preload={priority}
          className="block h-auto w-full rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)]"
        />
      </a>
    </figure>
  );
}

/** Text beside a screenshot on a wide screen. */
function Split({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="grid grid-cols-1 items-start lg:grid-cols-[minmax(0,4fr)_minmax(0,7fr)] lg:gap-10 [&_figure]:mt-5">
      {children}
    </div>
  );
}

/** The closing round-up: a title over two columns of short items. */
function Also({ title, children }: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <section className="mt-22 border-t border-[color:var(--aqt-border)] pt-10">
      {/* The markdown h3 look, without its section gap: the border above is the gap. */}
      <h3 className={H3}>{title}</h3>
      <div className="mt-5.5 grid grid-cols-1 gap-7 md:grid-cols-2 md:gap-x-12 md:gap-y-4">{children}</div>
    </section>
  );
}

/** Everything a changelog entry may use. Anything else in an MDX file fails to render. */
export const changelogComponents: MDXComponents = {
  ...mdxComponents,
  h3: (props) => <h3 {...props} className={cn(H3, "mt-14 md:mt-20")} />,
  h4: (props) => <h4 {...props} className="text-ui font-semibold text-[color:var(--aqt-fg)]" />,
  p: (props) => (
    <p {...props} className="mt-3 max-w-[64ch] text-ui leading-relaxed text-[color:var(--aqt-fg-muted)]" />
  ),
  ul: (props) => <ul {...props} className="mt-3 list-disc pl-4.5 marker:text-[color:var(--aqt-fg-faint)]" />,
  Lead,
  More,
  Shot,
  Split,
  Also
};
