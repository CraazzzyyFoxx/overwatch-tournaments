"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";

import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * A link from a community's page into a workspace-scoped browse page
 * (`/tournaments`, `/statistics`). Those pages have no workspace in the URL:
 * they read the active workspace from the workspace cookie, so following the
 * link has to move the cookie first — the same move the workspace switcher
 * makes when you pick a community. On a tenant host the store is locked to the
 * host workspace and the switch is a no-op, which is correct: the host already
 * scopes every read.
 */
export function WorkspaceScopeLink({
  workspaceId,
  href,
  className,
  "aria-label": ariaLabel,
  children
}: Readonly<{
  workspaceId: number;
  href: string;
  className?: string;
  "aria-label"?: string;
  children: ReactNode;
}>) {
  const router = useRouter();
  const setCurrentWorkspace = useWorkspaceStore((state) => state.setCurrentWorkspace);
  const setStatsScope = useWorkspaceStore((state) => state.setStatsScope);

  return (
    <Link
      href={href}
      prefetch={false}
      className={className}
      aria-label={ariaLabel}
      onClick={(event) => {
        // Leave modified clicks (new tab/window) to the browser.
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        setCurrentWorkspace(workspaceId);
        setStatsScope("workspace");
        router.push(href);
      }}
    >
      {children}
    </Link>
  );
}

/**
 * The section exit ("Все турниры →") when the destination is workspace-scoped:
 * `MoreLink`'s look over `WorkspaceScopeLink`'s cookie switch.
 */
export function ScopedMoreLink({
  workspaceId,
  href,
  children
}: Readonly<{ workspaceId: number; href: string; children: ReactNode }>) {
  return (
    <WorkspaceScopeLink
      workspaceId={workspaceId}
      href={href}
      className="group/more inline-flex min-h-8 items-center gap-1.5 rounded-md font-[family-name:var(--aqt-data)] text-label font-semibold uppercase tracking-label text-[color:var(--aqt-teal)] hover:text-[color:color-mix(in_srgb,var(--aqt-teal)_78%,white)]"
    >
      {children}
      <ArrowRight
        className="size-3.5 transition-transform duration-150 group-hover/more:translate-x-0.5"
        aria-hidden
      />
    </WorkspaceScopeLink>
  );
}
