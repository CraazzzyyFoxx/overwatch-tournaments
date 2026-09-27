"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, ChevronsUpDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn, initials } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { Workspace } from "@/types/workspace.types";

/**
 * Deterministic initials-tile accent. These were raw Tailwind palette classes
 * paired with a hardcoded on-accent foreground, which sits outside the token
 * system and carried no contrast guarantee; the `--aqt-*` accents are all
 * designed to take `--aqt-bg` as their on-accent text.
 */
const FALLBACK_ACCENTS = [
  "var(--aqt-violet)",
  "var(--aqt-blue)",
  "var(--aqt-emerald)",
  "var(--aqt-amber)",
  "var(--aqt-rose)",
  "var(--aqt-teal)",
  "var(--aqt-gold)"
];

function WorkspaceAvatar({
  workspace,
  size = "sm"
}: Readonly<{ workspace: Workspace; size?: "sm" | "md" | "header" }>) {
  const sizeClass = size === "sm" ? "size-5" : "size-7";
  const textSize = size === "sm" ? "text-label" : "text-xs";

  return (
    <Avatar key={workspace.id} className={cn(sizeClass, "rounded-md")}>
      {workspace.icon_url ? <AvatarImage src={workspace.icon_url} alt="" /> : null}
      <AvatarFallback
        className={cn("rounded-md font-semibold", textSize)}
        style={{
          background: FALLBACK_ACCENTS[workspace.id % FALLBACK_ACCENTS.length],
          color: "var(--aqt-bg)"
        }}
      >
        {initials(workspace.name)}
      </AvatarFallback>
    </Avatar>
  );
}

export default function WorkspaceSwitcher() {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const { workspaces, currentWorkspaceId, fetchWorkspaces, setCurrentWorkspace } =
    useWorkspaceStore();

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);

  if (workspaces.length === 0) return null;

  return (
    <>
      {/* Reads as "platform / workspace" beside the header's home logo, and
        hides with it below `sm`. Rendered here rather than in the header so it
        never outlives the switcher, which renders nothing until the workspaces
        have loaded. */}
      <span
        aria-hidden
        className="hidden h-5 w-px rotate-[18deg] bg-[color:var(--aqt-border-3)] sm:block"
      />
      <Popover open={open} onOpenChange={setOpen}>
        {/* Click-only: one real button is the whole control, no hover intent. */}
        <PopoverTrigger asChild>
          <button
            type="button"
            // The visible name leads the accessible one (label-in-name).
            aria-label={
              currentWorkspace
                ? `${currentWorkspace.name} — ${t("nav.switchWorkspace")}`
                : t("nav.switchWorkspace")
            }
            className={cn(
              "flex h-9 shrink-0 items-center gap-1 rounded-lg px-1",
              "transition-colors hover:bg-accent",
              "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            )}
          >
            {currentWorkspace ? (
              <>
                <WorkspaceAvatar workspace={currentWorkspace} size="header" />
                <span className="ml-1 hidden max-w-40 truncate text-sm font-medium text-[color:var(--aqt-fg-muted)] lg:inline">
                  {currentWorkspace.name}
                </span>
              </>
            ) : (
              <span className="text-sm text-muted-foreground">WS</span>
            )}
            <ChevronsUpDown className="size-4 text-muted-foreground" aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-64 p-1" sideOffset={8}>
          <div className="px-2 py-1.5">
            <p className="text-xs font-medium text-muted-foreground">{t("nav.workspaces")}</p>
          </div>
          <div className="flex flex-col gap-0.5">
            {workspaces.map((workspace) => {
              const isActive = workspace.id === currentWorkspaceId;
              return (
                <button
                  key={workspace.id}
                  type="button"
                  aria-pressed={isActive}
                  onClick={() => {
                    setCurrentWorkspace(workspace.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm",
                    "transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    isActive ? "bg-accent text-accent-foreground" : "hover:bg-accent/50"
                  )}
                >
                  <WorkspaceAvatar workspace={workspace} size="sm" />
                  <div className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{workspace.name}</span>
                  </div>
                  {isActive && <Check className="size-4 shrink-0 text-foreground" aria-hidden />}
                </button>
              );
            })}
          </div>
          {/* The workspace page used to be reachable only by clicking the avatar
            itself, which is now the popover trigger. */}
          {currentWorkspace ? (
            <>
              <div className="my-1 h-px bg-border" />
              <Link
                href={`/workspace/${currentWorkspace.slug}`}
                onClick={() => setOpen(false)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground",
                  "transition-colors hover:bg-accent/50 hover:text-foreground",
                  "outline-none focus-visible:ring-2 focus-visible:ring-ring"
                )}
              >
                <ArrowUpRight className="size-4 shrink-0" aria-hidden />
                <span className="truncate">
                  {t("nav.openWorkspace", { name: currentWorkspace.name })}
                </span>
              </Link>
            </>
          ) : null}
        </PopoverContent>
      </Popover>
    </>
  );
}

export { WorkspaceAvatar };
