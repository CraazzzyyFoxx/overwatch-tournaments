import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { MouseEventHandler, ReactNode } from "react";

import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { cn } from "@/lib/utils";

/** "← Back to …": the eyebrow-voiced text link above a detail page's title. */
export function BackLink({
  href,
  children,
  className,
  onClick
}: Readonly<{
  href: string;
  children: ReactNode;
  className?: string;
  /** Runs before the navigation; `preventDefault()` takes it over (the mix room animates its way out). */
  onClick?: MouseEventHandler<HTMLAnchorElement>;
}>) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        eyebrowClass(),
        "inline-flex items-center gap-1.5 transition-colors hover:text-[color:var(--aqt-teal)]",
        className
      )}
    >
      <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
      {children}
    </Link>
  );
}
