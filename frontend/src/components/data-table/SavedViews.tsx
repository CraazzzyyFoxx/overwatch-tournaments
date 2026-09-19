"use client";

import { Bookmark, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface SavedView {
  name: string;
  /** `window.location.search` at save time — the table mirrors its whole state there. */
  search: string;
  extra?: unknown;
}

export interface SavedViewsExtra {
  get: () => unknown;
  apply: (value: unknown) => void;
}

const suffix = ":views";

export function loadViews(storageKey: string): SavedView[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(`${storageKey}${suffix}`) ?? "null");
    return Array.isArray(parsed) ? (parsed as SavedView[]) : [];
  } catch {
    return [];
  }
}

export function saveViews(storageKey: string, views: SavedView[]) {
  try {
    localStorage.setItem(`${storageKey}${suffix}`, JSON.stringify(views));
  } catch {
    // localStorage full or unavailable — the views just do not survive the tab
  }
}

export function applyView(view: SavedView, extra?: SavedViewsExtra) {
  window.history.replaceState(null, "", `${window.location.pathname}${view.search}`);
  // The state MUST be null: Next's router ignores a popstate it did not push,
  // so only the table's own listener wakes up and re-reads the URL.
  window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
  if (view.extra !== undefined) extra?.apply(view.extra);
}

export function AdminSavedViews({
  storageKey,
  extra
}: {
  storageKey: string;
  extra?: SavedViewsExtra;
}) {
  const [views, setViews] = useState<SavedView[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");

  // localStorage is client-only, so the first render has to match the server's.
  useEffect(() => {
    setViews(loadViews(storageKey));
  }, [storageKey]);

  function commit(next: SavedView[]) {
    setViews(next);
    saveViews(storageKey, next);
  }

  function save() {
    const trimmed = name.trim();
    if (!trimmed) return;
    const view: SavedView = {
      name: trimmed,
      search: window.location.search,
      ...(extra ? { extra: extra.get() } : {})
    };
    commit(
      views.some((existing) => existing.name === trimmed)
        ? views.map((existing) => (existing.name === trimmed ? view : existing))
        : [...views, view]
    );
    setName("");
    setSaving(false);
  }

  return (
    <>
      <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="h-8">
            <Bookmark className="h-4 w-4" aria-hidden />
            Views
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          {views.map((view) => (
            <DropdownMenuItem
              key={view.name}
              className="justify-between gap-2"
              onSelect={() => applyView(view, extra)}
            >
              <span className="truncate">{view.name}</span>
              <button
                type="button"
                aria-label={`Delete view ${view.name}`}
                className="shrink-0 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
                // Only the click is stopped: swallowing pointerdown too would make
                // Radix synthesize a select on pointerup.
                onClick={(event) => {
                  event.stopPropagation();
                  commit(views.filter((existing) => existing.name !== view.name));
                }}
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </DropdownMenuItem>
          ))}
          {views.length > 0 ? <DropdownMenuSeparator /> : null}
          <DropdownMenuItem onSelect={() => setSaving(true)}>Save current view…</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {/* A Dialog rather than a Popover: the menu hands focus back to its
          trigger as it closes, which a Popover reads as "focus left" and shuts
          itself again before the name can be typed. Mounted only while open:
          `DialogContent` reads translations, which the table's hosts do not
          all provide. */}
      {saving ? (
      <Dialog open onOpenChange={setSaving}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Save current view</DialogTitle>
          </DialogHeader>
          <Label htmlFor="admin-saved-view-name">View name</Label>
          <Input
            id="admin-saved-view-name"
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                save();
              }
            }}
          />
          <Button size="sm" disabled={name.trim() === ""} onClick={save}>
            Save
          </Button>
        </DialogContent>
      </Dialog>
      ) : null}
    </>
  );
}
