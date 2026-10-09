"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, Check, ChevronsUpDown, Globe, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Workspace } from "@/types/workspace.types";

/** Saved viewing filter and the opened object's owner are independent. */
export function useActiveWorkspace() {
  const pathname = usePathname() ?? "";
  const {
    workspaces, currentWorkspaceId, hostLockedWorkspaceId, entityWorkspaceId,
    statsScope, setStatsScope
  } = useWorkspaceStore();
  const pageSlug = /^\/workspace\/([^/]+)/.exec(pathname)?.[1];
  const pinned = workspaces.find((w) => w.id === hostLockedWorkspaceId);
  const workspace = pinned ??
    (statsScope === "all" ? undefined : workspaces.find((w) => w.id === currentWorkspaceId));
  const entityWorkspace = workspaces.find((w) => w.id === entityWorkspaceId) ??
    workspaces.find((w) => w.slug === pageSlug);

  return { workspaces, workspace, entityWorkspace, allScope: !pinned && statsScope === "all", setStatsScope };
}

const MENU_ITEM_CLASS =
  "flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-body " +
  "text-[color:var(--aqt-fg)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] " +
  "focus-visible:bg-[color:var(--aqt-overlay-3)] focus-visible:shadow-[inset_0_0_0_2px_var(--aqt-teal)] " +
  "aria-[pressed=true]:bg-[color:var(--aqt-overlay-2)]";

/** Changes the viewing filter in place. Navigation is an explicit link. */
export default function WorkspaceSwitcher() {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  const setCurrentWorkspace = useWorkspaceStore((s) => s.setCurrentWorkspace);
  const { workspaces, workspace, entityWorkspace, allScope, setStatsScope } = useActiveWorkspace();

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  if (workspaces.length === 0) return null;

  const pickWorkspace = (next: Workspace) => {
    setCurrentWorkspace(next.id);
    setStatsScope("workspace");
    setOpen(false);
  };

  const pickAll = () => {
    setStatsScope("all");
    setOpen(false);
  };

  return (
    <div className="relative min-w-0">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            // The visible name leads the accessible one (label-in-name).
            aria-label={`${workspace?.name ?? t("nav.allWorkspaces")} — ${t("nav.switchWorkspace")}`}
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
            {t("nav.viewingScope")}
          </p>
          <button
            type="button"
            onClick={pickAll}
            aria-pressed={allScope}
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
                aria-pressed={isCurrent}
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
          {entityWorkspace ? (
            <p className="px-2.5 py-1.5 text-caption text-[color:var(--aqt-fg-dim)]">
              {t("nav.entityCommunity", { name: entityWorkspace.name })}
            </p>
          ) : null}
          {workspace ? (
            <Link
              href={`/workspace/${workspace.slug}`}
              prefetch={false}
              onClick={() => setOpen(false)}
              className={MENU_ITEM_CLASS}
            >
              <ArrowUpRight className="size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1">{t("nav.openWorkspace")}</span>
            </Link>
          ) : null}
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
