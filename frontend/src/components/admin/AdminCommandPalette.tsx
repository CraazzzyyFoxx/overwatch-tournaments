"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useCommandState } from "cmdk";
import { useRouter } from "next/navigation";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@craazzzyyfoxx/admin-kit/ui/command";
import {
  adminNavItemSearchValue,
  adminRouteAccessOptions,
  type AdminNavGroup,
} from "@/components/admin/admin-navigation";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";

interface AdminCommandPaletteProps {
  groups: AdminNavGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Announces how many pages the current query matched. cmdk filters internally,
 * so the count only exists in command state — without this, a screen reader
 * hears nothing when the visible list shrinks to two entries.
 */
function ResultCountAnnouncer() {
  const t = useTranslations("adminShell.commandPalette");
  const count = useCommandState((state) => state.filtered.count);
  const search = useCommandState((state) => state.search);

  return (
    <div role="status" aria-live="polite" className="sr-only">
      {search ? t("resultCount", { count, search }) : t("available", { count })}
    </div>
  );
}

export function AdminCommandPalette({ groups, open, onOpenChange }: Readonly<AdminCommandPaletteProps>) {
  const t = useTranslations("adminShell");
  const tUi = useTranslations("kit.ui");
  const router = useRouter();
  const { canAccessAdminRoute } = usePermissions();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const handleSelect = useCallback(
    (href: string) => {
      onOpenChange(false);
      router.push(href);
    },
    [router, onOpenChange],
  );

  // A view is a route of its own, and one entry's views can carry different
  // gates than the entry (Access mixes global-RBAC, workspace-admin and
  // superuser-only sections). Gating each against the same route table the
  // layout guard reads keeps the palette from offering an Unauthorized wall.
  const viewEntries = groups.flatMap((group) =>
    group.items.flatMap((item) =>
      (item.views ?? [])
        .filter((view) =>
          canAccessAdminRoute(
            adminRouteAccessOptions(view.href.split("?")[0], currentWorkspaceId),
          ),
        )
        .map((view) => ({ item, view })),
    ),
  );

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title={tUi("commandPalette")}
      description={t("commandPalette.search")}
      showCloseButton={false}
    >
      <CommandInput aria-label={t("commandPalette.search")} placeholder={t("commandPalette.searchPlaceholder")} />
      <ResultCountAnnouncer />
      <CommandList>
        <CommandEmpty>{t("commandPalette.noMatch")}</CommandEmpty>
        {groups.map((group) => (
          <CommandGroup key={group.title || "primary"} heading={group.title ? t(group.title as never) : t("nav.overview")}>
            {group.items.map((item) => (
              <CommandItem
                key={item.href}
                value={adminNavItemSearchValue(t(item.title as never), item)}
                onSelect={() => handleSelect(item.href)}
              >
                <item.icon aria-hidden className="size-4 text-muted-foreground" />
                <span>{t(item.title as never)}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
        {/* Views of the multi-view screens. Collapsing five sidebar entries
            into one browser would otherwise make "standings" unfindable: the
            page it lives on is called Matches. */}
        {viewEntries.length > 0 ? (
          <CommandGroup heading={t("commandPalette.views")}>
            {viewEntries.map(({ item, view }) => (
              <CommandItem
                key={view.href}
                value={`${t(item.title as never)} ${t(view.label as never)}`}
                onSelect={() => handleSelect(view.href)}
              >
                <item.icon aria-hidden className="size-4 text-muted-foreground" />
                <span>
                  {t(item.title as never)}
                  <span aria-hidden className="text-muted-foreground"> · </span>
                  {t(view.label as never)}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}
      </CommandList>
    </CommandDialog>
  );
}

export function useCommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // "/" when not focused on an input
      if (
        e.key === "/" &&
        !e.metaKey &&
        !e.ctrlKey &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLTextAreaElement) &&
        !(e.target as HTMLElement)?.isContentEditable
      ) {
        e.preventDefault();
        setOpen(true);
      }

      // Ctrl+K / Cmd+K
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return { open, setOpen };
}
