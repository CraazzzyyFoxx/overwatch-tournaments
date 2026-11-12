"use client";

import { Copy, Files } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator
} from "@craazzzyyfoxx/admin-kit/ui/context-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@craazzzyyfoxx/admin-kit/ui/dropdown-menu";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { formatHandlesForClipboard } from "@/components/balancer/balancer-page-helpers";

type HandleCopyButtonProps = {
  handle: string;
  className?: string;
};

type AdditionalHandleStripProps = {
  additionalHandles: string[];
  className?: string;
};

type HandleMenuItemsProps = {
  /** The row's primary handle first, its extra accounts after. */
  handles: string[];
};

/** What a copy put on the clipboard: names it in the confirmation toast. */
type CopiedKind = "handle" | "altHandle" | "altHandles" | "allHandles";

function useHandleClipboard() {
  const t = useTranslations("balancerTool.pool.handles");
  return async (value: string, kind: CopiedKind) => {
    try {
      await navigator.clipboard.writeText(value);
      notify.success(t("copied", { kind }));
    } catch {
      notify.error(t("copyFailed", { kind }));
    }
  };
}

export function HandleCopyButton({
  handle,
  className
}: Readonly<HandleCopyButtonProps>) {
  const t = useTranslations("balancerTool.pool.handles");
  const copyHandle = useHandleClipboard();

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className={cn(
        "h-7 w-7 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-cyan-100",
        className
      )}
      title={t("copy")}
      onClick={() => copyHandle(handle, "handle")}
    >
      <Copy className="h-3.5 w-3.5" />
      <span className="sr-only">{t("copy")}</span>
    </Button>
  );
}

/** A row's extra accounts behind one collapsed chip: copy one or all of them. */
export function AdditionalHandleStrip({ additionalHandles, className }: Readonly<AdditionalHandleStripProps>) {
  const t = useTranslations("balancerTool.pool.handles");
  const copyHandle = useHandleClipboard();

  if (additionalHandles.length === 0) {
    return null;
  }

  return (
    // `data-card-action`: the clickable pool and roster rows skip this subtree,
    // so opening the alt menu never opens the player sheet behind it.
    <div data-card-action className={cn("flex shrink-0 items-center gap-1", className)}>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="xs"
            className="rounded-full border-cyan-300/15 bg-cyan-500/8 text-cyan-100/62 hover:border-cyan-300/30 hover:bg-cyan-500/14 hover:text-cyan-50"
            title={t("showAlts")}
          >
            {t("altCount", { count: additionalHandles.length })}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          <DropdownMenuLabel>{t("alts")}</DropdownMenuLabel>
          {additionalHandles.length > 1 ? (
            <>
              <DropdownMenuItem
                onClick={() => copyHandle(formatHandlesForClipboard(additionalHandles), "altHandles")}
              >
                <Files className="h-4 w-4" />
                {t("copyAllAlts")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          ) : null}
          {additionalHandles.map((handle) => (
            <DropdownMenuItem key={handle} onClick={() => copyHandle(handle, "altHandle")}>
              <Copy className="h-4 w-4" />
              <span className="truncate">{handle}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function HandleContextMenuItems({ handles }: Readonly<HandleMenuItemsProps>) {
  const t = useTranslations("balancerTool.pool.handles");
  const copyHandle = useHandleClipboard();
  const [primaryHandle, ...additionalHandles] = handles;

  if (!primaryHandle) {
    return null;
  }

  return (
    <>
      <ContextMenuSeparator />
      <ContextMenuLabel>{t("menuLabel")}</ContextMenuLabel>
      <ContextMenuItem onClick={() => copyHandle(primaryHandle, "handle")}>
        <Copy className="h-4 w-4" />
        {t("copyMain")}
      </ContextMenuItem>
      {handles.length > 1 ? (
        <ContextMenuItem
          onClick={() => copyHandle(formatHandlesForClipboard(handles), "allHandles")}
        >
          <Files className="h-4 w-4" />
          {t("copyAll")}
        </ContextMenuItem>
      ) : null}
      {additionalHandles.length > 0 ? <ContextMenuSeparator /> : null}
      {additionalHandles.map((handle) => (
        <ContextMenuItem key={handle} onClick={() => copyHandle(handle, "altHandle")}>
          <Copy className="h-4 w-4" />
          {handle}
        </ContextMenuItem>
      ))}
    </>
  );
}
