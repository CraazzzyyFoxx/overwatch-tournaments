"use client";

import Link from "next/link";
import { useState } from "react";
import { Loader2, Plus } from "lucide-react";

import { PANEL_CLASS } from "@/app/balancer/components/balancer-page-helpers";
import {
  CAPTION_CLASS,
  EYEBROW_CLASS,
  METRIC_PILL_CLASS,
  MIX_STATUS_CLASS,
} from "@/app/balancer/pickup/pickup-chrome";
import { formatDate, formatRelative } from "@/components/admin/format-time";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { CustomGame, CustomGameStatus } from "@/services/custom-game.service";

/** How far back the "lineup from" picker reaches — a host clones last night's mix, not last season's. */
const CLONE_SOURCE_LIMIT = 5;

/** The picker's "start from nothing" option; anything else is a source mix id. */
const EMPTY_SOURCE = "empty";

type PickupMixListProps = {
  canEdit: boolean;
  games: CustomGame[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  creating: boolean;
  onCreateGame: (name: string, cloneFromGameId: number | null) => void;
};

/**
 * Every mix this workspace has run, newest first: who hosted it, when, and
 * its current status — the picker a host used to reach past to get to the one
 * they were already running.
 *
 * Opening a mix, or starting a new one, both happen here now. The mix screen
 * itself (`/balancer/pickup/[gameId]`) only ever reads and edits the one
 * already picked, so this is the one place that names every mix at once.
 */
export function PickupMixList({
  canEdit,
  games,
  loading,
  error,
  onRetry,
  creating,
  onCreateGame,
}: Readonly<PickupMixListProps>) {
  const [newName, setNewName] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  // `null` means "untouched", so the default can follow the list as it loads.
  const [pickedSource, setPickedSource] = useState<string | null>(null);
  // The last name this component filled in itself -- anything else in the
  // field is the host's own wording and a source change must not overwrite it.
  const [suggestedName, setSuggestedName] = useState("");

  const sources = games.slice(0, CLONE_SOURCE_LIMIT);
  // Cloning last night's mix is the common case, so it is what the form offers
  // first; an empty workspace has nothing to clone and falls back to Empty.
  const source = pickedSource ?? (sources[0] ? String(sources[0].id) : EMPTY_SOURCE);
  const cloneFromGameId = source === EMPTY_SOURCE ? null : Number(source);

  const resetForm = () => {
    setNewName("");
    setPickedSource(null);
    setSuggestedName("");
  };

  const pickSource = (value: string) => {
    setPickedSource(value);
    const picked = games.find((item) => String(item.id) === value);
    if (picked && (newName === "" || newName === suggestedName)) {
      setNewName(picked.name);
      setSuggestedName(picked.name);
    }
  };

  return (
    <div className="flex flex-1 flex-col gap-5">
      <div className="flex flex-wrap items-end gap-x-5 gap-y-3 border-b border-[color:var(--aqt-border)] pb-4">
        <div className="min-w-0">
          <div className={EYEBROW_CLASS}>Balancer</div>
          <h1 className="mt-1.5 font-display text-headline/[1.1] font-bold tracking-[-0.01em] text-[color:var(--aqt-fg)]">
            Mixes
          </h1>
        </div>

        {canEdit ? (
          <div className="ml-auto flex items-center gap-2">
            <Popover
              open={isCreateOpen}
              onOpenChange={(open) => {
                setIsCreateOpen(open);
                if (!open) resetForm();
                // The default source is last night's mix, so its name is the
                // default name too -- one click recreates it, a keystroke renames.
                else if (sources[0]) {
                  setNewName(sources[0].name);
                  setSuggestedName(sources[0].name);
                }
              }}
            >
              <PopoverTrigger asChild>
                <Button type="button" className="h-9">
                  <Plus className="mr-1.5 size-3.5" aria-hidden="true" />
                  New mix
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-72 p-3">
                <form
                  className="space-y-1.5"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const name = newName.trim();
                    if (!name) return;
                    onCreateGame(name, cloneFromGameId);
                    resetForm();
                    setIsCreateOpen(false);
                  }}
                >
                  <label htmlFor="pickup-new-mix" className={cn(EYEBROW_CLASS, "block")}>
                    New mix
                  </label>
                  <div className="flex gap-1.5">
                    <Input
                      id="pickup-new-mix"
                      value={newName}
                      onChange={(event) => setNewName(event.target.value)}
                      placeholder="Thursday scrim"
                      autoComplete="off"
                      className="h-9 min-w-0 rounded-lg border-[color:var(--aqt-border-2)] bg-black/15 text-sm"
                    />
                    <Button
                      type="submit"
                      size="sm"
                      className="h-9 shrink-0 px-3"
                      disabled={creating || !newName.trim()}
                    >
                      {creating ? (
                        <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden="true" />
                      ) : null}
                      Create
                    </Button>
                  </div>
                  <label htmlFor="pickup-clone-from" className={cn(EYEBROW_CLASS, "block pt-1")}>
                    Lineup from
                  </label>
                  <Select value={source} onValueChange={pickSource}>
                    <SelectTrigger
                      id="pickup-clone-from"
                      className="h-9 rounded-lg border-[color:var(--aqt-border-2)] bg-black/15 text-sm"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={EMPTY_SOURCE}>Empty</SelectItem>
                      {sources.map((item) => (
                        <SelectItem key={item.id} value={String(item.id)}>
                          {`${item.name} · #${item.id}`}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-label text-[color:var(--aqt-fg-dim)]">
                    {cloneFromGameId == null
                      ? "Starts empty — fill it from the workspace player pool."
                      : "Copies the lineup and settings; benched players come back to the pool."}
                  </p>
                </form>
              </PopoverContent>
            </Popover>
          </div>
        ) : null}
      </div>

      {error ? (
        <PageStateCard
          state="error"
          title="Unable to load mixes"
          description="Check your connection and try again."
          actionLabel="Retry"
          onAction={onRetry}
          className={cn(PANEL_CLASS, "px-4 py-16")}
        />
      ) : loading ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : games.length === 0 ? (
        <PageStateCard
          state="empty"
          title="No mixes yet"
          description={
            canEdit
              ? "Create a mix to start filling its lineup."
              : "A host has not created a mix in this workspace yet."
          }
          className={cn(PANEL_CLASS, "px-4 py-16")}
        />
      ) : (
        <ul
          aria-label="Mixes"
          className={cn(PANEL_CLASS, "flex flex-col divide-y divide-[color:var(--aqt-border)]")}
        >
          {games.map((game) => (
            <PickupMixRow key={game.id} game={game} />
          ))}
        </ul>
      )}
    </div>
  );
}

function PickupMixRow({ game }: Readonly<{ game: CustomGame }>) {
  const status = game.status as CustomGameStatus;
  return (
    <li>
      <Link
        href={`/balancer/pickup/${game.id}`}
        className="flex items-center gap-3.5 px-4 py-3.5 transition-colors hover:bg-white/[0.025]"
      >
        <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
          <span className="truncate text-body font-semibold text-[color:var(--aqt-fg)]">
            {game.name}
          </span>
          <span className="shrink-0 text-xs text-[color:var(--aqt-fg-faint)]">
            {`#${game.id}`}
          </span>
        </span>

        <span className={cn(CAPTION_CLASS, "w-40 shrink-0 truncate text-left")}>
          {game.host_display_name ?? `#${game.host_user_id}`}
        </span>

        <span className={cn(CAPTION_CLASS, "w-44 shrink-0 truncate text-left")}>
          {game.matches_count > 0 ? (
            `${game.matches_count} map${game.matches_count === 1 ? "" : "s"} · ${formatRelative(game.last_match_at)}`
          ) : (
            <span className="text-[color:var(--aqt-fg-faint)]">No matches</span>
          )}
        </span>

        <span className={cn(CAPTION_CLASS, "w-36 shrink-0 text-left")}>
          {formatDate(game.created_at)}
        </span>

        <span
          className={cn(
            METRIC_PILL_CLASS,
            MIX_STATUS_CLASS[status] ?? MIX_STATUS_CLASS.draft,
            "w-24 shrink-0 justify-center capitalize",
          )}
        >
          {game.status}
        </span>
      </Link>
    </li>
  );
}
