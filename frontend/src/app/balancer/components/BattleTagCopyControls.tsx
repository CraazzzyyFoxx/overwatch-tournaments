"use client";

import { Copy, Files } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator
} from "@/components/ui/context-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { formatBattleTagsForClipboard, formatSmurfCount } from "./balancer-page-helpers";

type BattleTagCopyButtonProps = {
  battleTag: string;
  label?: string;
  className?: string;
};

type SmurfTagStripProps = {
  smurfTags: string[];
  className?: string;
  compact?: boolean;
};

type BattleTagMenuItemsProps = {
  battleTags: string[];
};

function useBattleTagClipboard() {
  return async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      notify.success(`${label} copied`);
    } catch {
      notify.error(`Unable to copy the ${label}. Your browser blocked clipboard access — select the text and copy it manually.`);
    }
  };
}

export function BattleTagCopyButton({
  battleTag,
  label = "BattleTag",
  className
}: Readonly<BattleTagCopyButtonProps>) {
  const copyBattleTag = useBattleTagClipboard();

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className={cn(
        "h-7 w-7 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-cyan-100",
        className
      )}
      title={`Copy ${label}`}
      onClick={() => copyBattleTag(battleTag, label)}
    >
      <Copy className="h-3.5 w-3.5" />
      <span className="sr-only">Copy {label}</span>
    </Button>
  );
}

export function SmurfTagStrip({ smurfTags, className, compact = false }: Readonly<SmurfTagStripProps>) {
  const copyBattleTag = useBattleTagClipboard();

  if (smurfTags.length === 0) {
    return null;
  }

  return (
    <div
      className={cn("flex shrink-0 items-center gap-1", className)}
      onDoubleClick={(event) => event.stopPropagation()}
    >
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1 rounded-full border border-cyan-300/15 bg-cyan-500/8 font-semibold text-cyan-100/62 transition hover:border-cyan-300/30 hover:bg-cyan-500/14 hover:text-cyan-50",
              compact ? "px-1.5 py-0.5 text-label" : "px-2 py-0.5 text-label"
            )}
            title="Show smurf BattleTags"
          >
            {formatSmurfCount(smurfTags.length)}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          <DropdownMenuLabel>Smurf BattleTags</DropdownMenuLabel>
          {smurfTags.length > 1 ? (
            <>
              <DropdownMenuItem
                onClick={() =>
                  copyBattleTag(formatBattleTagsForClipboard(smurfTags), "Smurf BattleTags")
                }
              >
                <Files className="h-4 w-4" />
                Copy all smurfs
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          ) : null}
          {smurfTags.map((smurfTag) => (
            <DropdownMenuItem
              key={smurfTag}
              onClick={() => copyBattleTag(smurfTag, "Smurf BattleTag")}
            >
              <Copy className="h-4 w-4" />
              <span className="truncate">{smurfTag}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function BattleTagContextMenuItems({ battleTags }: Readonly<BattleTagMenuItemsProps>) {
  const copyBattleTag = useBattleTagClipboard();
  const [primaryBattleTag, ...smurfTags] = battleTags;

  if (!primaryBattleTag) {
    return null;
  }

  return (
    <>
      <ContextMenuSeparator />
      <ContextMenuLabel>BattleTags</ContextMenuLabel>
      <ContextMenuItem onClick={() => copyBattleTag(primaryBattleTag, "BattleTag")}>
        <Copy className="h-4 w-4" />
        Copy main BattleTag
      </ContextMenuItem>
      {battleTags.length > 1 ? (
        <ContextMenuItem
          onClick={() => copyBattleTag(formatBattleTagsForClipboard(battleTags), "All BattleTags")}
        >
          <Files className="h-4 w-4" />
          Copy all BattleTags
        </ContextMenuItem>
      ) : null}
      {smurfTags.length > 0 ? <ContextMenuSeparator /> : null}
      {smurfTags.map((smurfTag) => (
        <ContextMenuItem key={smurfTag} onClick={() => copyBattleTag(smurfTag, "Smurf BattleTag")}>
          <Copy className="h-4 w-4" />
          {smurfTag}
        </ContextMenuItem>
      ))}
    </>
  );
}
