"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import Cookies from "js-cookie";
import { Check, ChevronsUpDown, Globe, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { STATS_SCOPE_COOKIE } from "@/lib/site/stats-scope";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Workspace } from "@/types/workspace.types";

/**
 * Which community the chrome is currently about, and whether the visitor asked
 * for the cross-community ("all") scope. Shared by the switcher and the active
 * events popover so both agree on one answer.
 *
 * Precedence: the host lock (tenant host) beats the community page the reader
 * is on, which beats the stored selection. The platform home is the "all
 * communities" page itself, so there the switcher reads "Все сообщества"
 * whatever is stored; elsewhere the all-scope preference only shows through
 * where nothing pins a community.
 */
export function useActiveWorkspace(): {
  workspaces: Workspace[];
  workspace: Workspace | undefined;
  /** Set only where the location itself fixes the community, never by preference. */
  pinned: Workspace | undefined;
  allScope: boolean;
  setAllScope: (next: boolean) => void;
} {
  const pathname = usePathname() ?? "";
  const { workspaces, currentWorkspaceId, hostLockedWorkspaceId } = useWorkspaceStore();
  // Read at mount, not on the server: every caller renders nothing until the
  // client-side workspace list arrives, so this cannot mismatch the SSR HTML.
  const [allScope, setAllScope] = useState(
    () => typeof document !== "undefined" && Cookies.get(STATS_SCOPE_COOKIE) === "all"
  );

  const pageSlug = /^\/workspace\/([^/]+)/.exec(pathname)?.[1];
  const pinned = hostLockedWorkspaceId
    ? workspaces.find((w) => w.id === hostLockedWorkspaceId)
    : pageSlug
      ? workspaces.find((w) => w.slug === pageSlug)
      : undefined;
  const onPlatformHome = !hostLockedWorkspaceId && pathname === "/";
  const workspace =
    pinned ??
    (allScope || onPlatformHome ? undefined : workspaces.find((w) => w.id === currentWorkspaceId));

  return {
    workspaces,
    workspace,
    pinned,
    allScope: (allScope || onPlatformHome) && !workspace,
    setAllScope
  };
}

const MENU_ITEM_CLASS =
  "flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-body " +
  "text-[color:var(--aqt-fg)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] " +
  "focus-visible:bg-[color:var(--aqt-overlay-3)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)] " +
  "aria-[current=page]:bg-[color:var(--aqt-overlay-2)]";

/**
 * The community switcher: the platform apex's "which community am I looking
 * at" control. Picking one scopes the site to it and opens its page; "all
 * communities" lifts the scope and returns to the platform home.
 */
export default function WorkspaceSwitcher() {
  const t = useTranslations();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  const setCurrentWorkspace = useWorkspaceStore((s) => s.setCurrentWorkspace);
  const { workspaces, workspace, allScope, setAllScope } = useActiveWorkspace();

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  if (workspaces.length === 0) return null;

  const pickWorkspace = (next: Workspace) => {
    setCurrentWorkspace(next.id);
    Cookies.remove(STATS_SCOPE_COOKIE);
    setAllScope(false);
    setOpen(false);
    router.push(`/workspace/${next.slug}`);
  };

  const pickAll = () => {
    Cookies.set(STATS_SCOPE_COOKIE, "all", { sameSite: "lax", expires: 365 });
    setAllScope(true);
    setOpen(false);
    router.push("/");
  };

  return (
    <div className="relative min-w-0">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            // The visible name leads the accessible one (label-in-name).
            aria-label={
              workspace
                ? `${workspace.name} — ${t("nav.switchWorkspace")}`
                : t("nav.switchWorkspace")
            }
            className={cn(
              "flex h-9 w-full min-w-0 max-w-[220px] items-center gap-2 rounded-[9px] py-0 pl-1.5 pr-2",
              "border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)]",
              "text-caption font-semibold text-[color:var(--aqt-fg)] transition-colors",
              "hover:bg-[color:var(--aqt-overlay-3)] data-[state=open]:bg-[color:var(--aqt-overlay-3)]",
              "outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
          >
            {workspace ? (
              <WorkspaceAvatar workspace={workspace} size={24} />
            ) : (
              <span
                aria-hidden
                className="inline-flex size-6 shrink-0 items-center justify-center rounded-md border border-[color:color-mix(in_srgb,var(--aqt-teal)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,var(--aqt-card))] text-[color:var(--aqt-teal)]"
              >
                <Globe className="size-3.5" />
              </span>
            )}
            <span className="min-w-0 flex-1 truncate text-left">
              {workspace ? workspace.name : t("nav.allWorkspaces")}
            </span>
            <ChevronsUpDown className="size-3.5 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          sideOffset={8}
          collisionPadding={12}
          aria-label={t("nav.workspaces")}
          className="w-[280px] max-w-[calc(100vw-24px)] rounded-xl border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] p-1.5 shadow-[0_18px_50px_rgb(0_0_0/0.5)]"
        >
          <p className="px-2.5 pb-1.5 pt-2 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
            {t("nav.workspaces")}
          </p>
          <button
            type="button"
            onClick={pickAll}
            aria-current={allScope ? "page" : undefined}
            className={MENU_ITEM_CLASS}
          >
            <span
              aria-hidden
              className="inline-flex size-6 shrink-0 items-center justify-center rounded-md border border-[color:color-mix(in_srgb,var(--aqt-teal)_28%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,var(--aqt-card))] text-[color:var(--aqt-teal)]"
            >
              <Globe className="size-3.5" />
            </span>
            <span className="min-w-0 flex-1 truncate">{t("nav.allWorkspaces")}</span>
            {allScope ? <Check className="size-4 shrink-0" aria-hidden /> : null}
          </button>
          {workspaces.map((item) => {
            const isCurrent = item.id === workspace?.id;
            // The address shown to people: a verified custom domain only.
            // Platform subdomains are plumbing and are never displayed.
            const host =
              item.custom_domain && item.custom_domain_verified_at ? item.custom_domain : null;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => pickWorkspace(item)}
                aria-current={isCurrent ? "page" : undefined}
                className={MENU_ITEM_CLASS}
              >
                <WorkspaceAvatar workspace={item} size={24} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{item.name}</span>
                  {host ? (
                    <span className="block truncate text-caption text-[color:var(--aqt-fg-dim)]">
                      {host}
                    </span>
                  ) : null}
                </span>
                {isCurrent ? <Check className="size-4 shrink-0" aria-hidden /> : null}
              </button>
            );
          })}
          <div className="my-1.5 h-px bg-[color:var(--aqt-border)]" />
          <Link
            href="/get-workspace"
            onClick={() => setOpen(false)}
            className={cn(MENU_ITEM_CLASS, "text-[color:var(--aqt-fg-muted)]")}
          >
            <Plus className="size-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1 truncate">{t("nav.createWorkspace")}</span>
          </Link>
        </PopoverContent>
      </Popover>
    </div>
  );
}
