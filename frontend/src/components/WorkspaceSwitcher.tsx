"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, ChevronsUpDown } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Popover, PopoverAnchor, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { Workspace } from "@/types/workspace.types";

function getInitials(name: string): string {
  return name
    .split(/[\s-]+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

const FALLBACK_COLORS = [
  "bg-violet-600",
  "bg-blue-600",
  "bg-emerald-600",
  "bg-amber-600",
  "bg-rose-600",
  "bg-cyan-600",
  "bg-indigo-600",
  "bg-pink-600",
];

function getColorForWorkspace(id: number): string {
  return FALLBACK_COLORS[id % FALLBACK_COLORS.length];
}

function WorkspaceAvatar({ workspace, size = "sm" }: { workspace: Workspace; size?: "sm" | "md" | "header" }) {
  const sizeClass = size === "sm" ? "size-5" : "size-7";
  const textSize = size === "sm" ? "text-[10px]" : "text-xs";

  return (
    <Avatar key={workspace.id} className={cn(sizeClass, "rounded-md")}>
      {workspace.icon_url ? (
        <AvatarImage src={workspace.icon_url} alt={workspace.name} />
      ) : null}
      <AvatarFallback
        className={cn(
          "rounded-md text-white font-semibold",
          textSize,
          getColorForWorkspace(workspace.id)
        )}
      >
        {getInitials(workspace.name)}
      </AvatarFallback>
    </Avatar>
  );
}

export default function WorkspaceSwitcher() {
  const [open, setOpen] = useState(false);
  const hoverTimeout = useRef<ReturnType<typeof setTimeout>>(null);
  const router = useRouter();
  const { workspaces, currentWorkspaceId, fetchWorkspaces, setCurrentWorkspace } =
    useWorkspaceStore();

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  const handleMouseEnter = useCallback(() => {
    clearTimeout(hoverTimeout.current ?? undefined);
    hoverTimeout.current = setTimeout(() => setOpen(true), 200);
  }, []);

  const handleMouseLeave = useCallback(() => {
    clearTimeout(hoverTimeout.current ?? undefined);
    hoverTimeout.current = setTimeout(() => setOpen(false), 300);
  }, []);

  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);

  if (workspaces.length === 0) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
      <div
        className="flex items-center gap-0.5"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        <Link
          href={currentWorkspace ? `/workspace/${currentWorkspace.slug}` : "/"}
          className={cn(
            "rounded-lg",
            "hover:opacity-80 transition-opacity",
            "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          )}
          onClick={() => setOpen(false)}
        >
          {currentWorkspace ? (
            <WorkspaceAvatar workspace={currentWorkspace} size="header" />
          ) : (
            <span className="text-muted-foreground text-sm">WS</span>
          )}
        </Link>
        <PopoverTrigger asChild>
          <button
            className={cn(
              "rounded p-0.5",
              "hover:bg-accent transition-colors",
              "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            )}
            aria-label="Switch workspace"
          >
            <ChevronsUpDown className="size-3.5 text-muted-foreground" />
          </button>
        </PopoverTrigger>
      </div>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        className="w-64 p-1"
        sideOffset={8}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        <div className="px-2 py-1.5">
          <p className="text-xs font-medium text-muted-foreground">Workspaces</p>
        </div>
        <div className="flex flex-col gap-0.5">
          {workspaces.map((workspace) => {
            const isActive = workspace.id === currentWorkspaceId;
            return (
              <button
                key={workspace.id}
                onClick={() => {
                  setCurrentWorkspace(workspace.id);
                  setOpen(false);
                  router.push(`/workspace/${workspace.slug}`);
                }}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm w-full text-left",
                  "transition-colors outline-none",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-accent/50"
                )}
              >
                <WorkspaceAvatar workspace={workspace} size="sm" />
                <div className="flex-1 min-w-0">
                  <span className="truncate block font-medium text-sm">
                    {workspace.name}
                  </span>
                </div>
                {isActive && (
                  <Check className="size-4 text-foreground shrink-0" />
                )}
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}

export { WorkspaceAvatar };
