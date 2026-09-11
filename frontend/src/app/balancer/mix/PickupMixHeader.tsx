"use client";

import Link from "next/link";
import { ArrowLeft, Settings2, Trash2, UserCog, UserPlus } from "lucide-react";

import { PANEL_CLASS } from "@/app/balancer/components/balancer-page-helpers";
import { EYEBROW_CLASS } from "@/app/balancer/pickup/pickup-chrome";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CustomGame } from "@/services/custom-game.service";

type PickupMixHeaderProps = {
  /** Host or co-host, and not-terminal -- gates every write action in this header. */
  canWrite: boolean;
  game: CustomGame | undefined;
  gameLoading: boolean;
  onOpenPool: () => void;
  onOpenSettings: () => void;
  onOpenAccess: () => void;
  /** Workspace admin (or superuser) -- gates the irreversible hard delete,
   * a stronger grant than the host-or-co-host `canWrite` above. */
  canDelete?: boolean;
  deleting?: boolean;
  onDeleteMix?: () => void;
};

/**
 * The mix this screen is open on: the way back to the list, its name and id,
 * and the one write a host does before touching a lineup -- pull more
 * players in. One line instead of three: the back link, the identity and the
 * write used to stack as separate rows and read as three unrelated pieces of
 * chrome instead of one header.
 *
 * Boxed in the same `PANEL_CLASS` card every other block on this screen
 * uses (the verdict pills, the team card, the record-result bar) -- bare, it
 * was the only unbordered row on the page, so the gap `Add players` leaves
 * between itself and the title read as an accident instead of a header's own
 * padding.
 *
 * Which mix this is comes from the route, not from state this header owns --
 * switching to another one, or starting a new one, happens on the list at
 * `/balancer/pickup`. This is the only place the mix's name and number sit
 * together.
 */
export function PickupMixHeader({
  canWrite,
  game,
  gameLoading,
  onOpenPool,
  onOpenSettings,
  onOpenAccess,
  canDelete = false,
  deleting = false,
  onDeleteMix,
}: Readonly<PickupMixHeaderProps>) {
  return (
    <div className={cn(PANEL_CLASS, "flex flex-wrap items-center gap-3 px-4 py-3")}>
      <Link
        href="/balancer/pickup"
        className="flex shrink-0 items-center gap-1.5 text-caption text-[color:var(--aqt-fg-dim)] transition-colors hover:text-[color:var(--aqt-fg-muted)]"
      >
        <ArrowLeft className="size-3.5" aria-hidden="true" />
        Mixes
      </Link>

      <span aria-hidden="true" className="h-5 w-px shrink-0 bg-[color:var(--aqt-border)]" />

      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <span className={EYEBROW_CLASS}>Mix</span>
        <h1 className="min-w-0 truncate font-display text-xl font-bold tracking-[-0.01em] text-[color:var(--aqt-fg)]">
          {game?.name ?? (gameLoading ? "\u2026" : "No mix yet")}
        </h1>
        {game ? (
          <span className="shrink-0 text-caption font-semibold text-[color:var(--aqt-fg-dim)]">
            {`#${game.id}`}
          </span>
        ) : null}
      </div>

      {canWrite ? (
        <Button
          type="button"
          variant="outline"
          className="h-9 shrink-0"
          disabled={game == null}
          onClick={onOpenPool}
        >
          <UserPlus className="mr-1.5 size-3.5" aria-hidden="true" />
          Add players
        </Button>
      ) : null}

      {canWrite ? (
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-9 w-9 shrink-0"
          disabled={game == null}
          onClick={onOpenSettings}
          aria-label="Team composition"
        >
          <Settings2 className="size-3.5" aria-hidden="true" />
        </Button>
      ) : null}
      {canWrite ? (
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-9 w-9 shrink-0"
          disabled={game == null}
          onClick={onOpenAccess}
          aria-label="Manage access"
        >
          <UserCog className="size-3.5" aria-hidden="true" />
        </Button>
      ) : null}

      {canDelete && onDeleteMix ? (
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className="h-9 w-9 shrink-0 text-[color:var(--aqt-fg-muted)] hover:border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)] hover:text-rose-200"
              disabled={game == null || deleting}
              aria-label="Delete mix"
            >
              <Trash2 className="size-3.5" aria-hidden="true" />
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete this mix?</AlertDialogTitle>
              <AlertDialogDescription>
                Permanently removes {game?.name ?? "this mix"} and every match it recorded. This
                cannot be undone -- unlike Close, there is no way back to it afterwards.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep it</AlertDialogCancel>
              <AlertDialogAction onClick={onDeleteMix}>Delete permanently</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      ) : null}
    </div>
  );
}
