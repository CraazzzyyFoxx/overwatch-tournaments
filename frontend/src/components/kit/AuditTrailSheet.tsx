"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, History } from "lucide-react";

import { AuditTrailBody } from "@/components/kit/AuditTrail";
import {
  AUDIT_TRAIL_PARAM,
  auditEntityLabel,
  auditTrailCountQuery,
  encodeAuditTrailScope,
  parseAuditTrailScope,
  sameAuditTrailScope,
  type AuditTrailScope,
} from "@/components/kit/audit-log";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { usePermissions } from "@/hooks/usePermissions";
import { cn } from "@/lib/utils";

/**
 * The per-entity audit trail, as one right-hand drawer for the whole admin panel.
 *
 * One mounted `Sheet` behind a context rather than one per call site: the trail
 * used to sit inline at the bottom of three screens, which fetched history
 * nobody had asked to read and — on the registration editor — nested a scrolling
 * card inside an already-scrolling dialog. A single drawer fetches on open,
 * scales to a trigger per table row, and cannot nest inside itself.
 *
 * Scope lives in the URL (`?history=tournament:12:3`) so a trail can be linked
 * to and survives a reload. `replaceState`, not `pushState`, for the same reason
 * `AdminDataTable` uses it for filters: only a change of place earns a history
 * entry, and peeking at a drawer is not one.
 */

interface AuditTrailContextValue {
  scope: AuditTrailScope | null;
  open: (scope: AuditTrailScope) => void;
  close: () => void;
}

const AuditTrailContext = createContext<AuditTrailContextValue | null>(null);

function readScopeFromUrl(): AuditTrailScope | null {
  if (typeof window === "undefined") return null;
  return parseAuditTrailScope(
    new URLSearchParams(window.location.search).get(AUDIT_TRAIL_PARAM),
  );
}

function writeScopeToUrl(scope: AuditTrailScope | null): void {
  const params = new URLSearchParams(window.location.search);
  if (scope) params.set(AUDIT_TRAIL_PARAM, encodeAuditTrailScope(scope));
  else params.delete(AUDIT_TRAIL_PARAM);

  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    query ? `${window.location.pathname}?${query}` : window.location.pathname,
  );
}

export function AuditTrailProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [scope, setScope] = useState<AuditTrailScope | null>(null);

  // The server render has no location, so a deep link is adopted on mount
  // rather than during render; `popstate` keeps back/forward honest afterwards.
  useEffect(() => {
    const sync = () =>
      setScope((current) => {
        const next = readScopeFromUrl();
        return sameAuditTrailScope(current, next) ? current : next;
      });

    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  const open = useCallback((next: AuditTrailScope) => {
    setScope(next);
    writeScopeToUrl(next);
  }, []);

  const close = useCallback(() => {
    setScope(null);
    writeScopeToUrl(null);
  }, []);

  const value = useMemo(() => ({ scope, open, close }), [scope, open, close]);

  return (
    <AuditTrailContext.Provider value={value}>
      {children}
      <AuditTrailSheet scope={scope} onClose={close} />
    </AuditTrailContext.Provider>
  );
}

export function useAuditTrail(): AuditTrailContextValue {
  const value = useContext(AuditTrailContext);
  if (!value) {
    throw new Error("useAuditTrail must be used inside <AuditTrailProvider>.");
  }
  return value;
}

/** `Tournament #12` — everything a scope alone can honestly name. */
function describeScope(scope: AuditTrailScope): string {
  return `${auditEntityLabel(scope.entityType) ?? "Record"} #${scope.entityId}`;
}

function AuditTrailSheet({
  scope,
  onClose,
}: Readonly<{ scope: AuditTrailScope | null; onClose: () => void }>) {
  // The closing scope is held for the exit animation: dropping the content the
  // moment `scope` clears would blank the drawer out instead of sliding it away.
  // Adjusted during render rather than in an effect, which would paint the
  // emptied drawer for a frame before catching up.
  const [lastScope, setLastScope] = useState<AuditTrailScope | null>(scope);
  if (scope && scope !== lastScope) setLastScope(scope);

  const shown = scope ?? lastScope;
  if (!shown) return null;

  const feedHref = `/admin/audit?entity_type=${encodeURIComponent(shown.entityType)}&entity_id=${shown.entityId}`;
  const noun = (auditEntityLabel(shown.entityType) ?? "record").toLowerCase();

  return (
    <Sheet open={scope != null} onOpenChange={(next) => (next ? undefined : onClose())}>
      <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="space-y-1 border-b border-border/50 px-5 py-4 text-left">
          <SheetTitle className="flex items-center gap-2 text-base">
            <History aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            Change history
          </SheetTitle>
          <SheetDescription>
            Every admin action recorded for {describeScope(shown)}, newest first.
          </SheetDescription>
        </SheetHeader>

        {/* `overscroll-contain` keeps a flick at the end of the trail from
            scrolling the page underneath the drawer. */}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
          <AuditTrailBody key={encodeAuditTrailScope(shown)} scope={shown} />
        </div>

        <div className="border-t border-border/50 px-5 py-3">
          <Link
            href={feedHref}
            className="inline-flex items-center gap-1.5 text-sm text-primary underline-offset-2 hover:underline"
          >
            <ExternalLink aria-hidden className="size-3.5" />
            Search and filter this {noun} in the audit log
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export interface AuditTrailButtonProps {
  scope: AuditTrailScope;
  /**
   * Names the entity in the accessible name, so the control still says what it
   * opens when read out of context. Falls back to what the scope alone can name.
   */
  target?: string;
  /**
   * Costs one `per_page=1` request per mounted button, so it is opt-in: worth it
   * beside a single entity, not multiplied down a table. A table row opens the
   * drawer from its own action menu with `useAuditTrail` instead.
   */
  showCount?: boolean;
  className?: string;
}

/**
 * Opens the trail for one entity, or renders nothing without `audit.read` in
 * that entity's workspace — a button that only ever opens a refusal is worse
 * than no button.
 */
export function AuditTrailButton({
  scope,
  target,
  showCount = false,
  className,
}: Readonly<AuditTrailButtonProps>) {
  const { open } = useAuditTrail();
  const { canAccessPermission } = usePermissions();
  const allowed = canAccessPermission("audit.read", scope.workspaceId);

  const countQuery = useQuery({
    ...auditTrailCountQuery(scope),
    enabled: allowed && showCount,
  });

  if (!allowed) return null;

  // Zero is deliberately badge-less: "0" next to the trigger reads as "nothing
  // ever happened here", which the drawer's own empty states exist to avoid
  // claiming. An absent badge promises nothing.
  const count = countQuery.data ?? 0;

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => open(scope)}
      className={cn("transition-transform active:scale-[0.96]", className)}
    >
      <History aria-hidden className="size-4" />
      <span>Change history</span>
      <span className="sr-only">{` for ${target ?? describeScope(scope)}`}</span>
      {count > 0 ? (
        <Badge variant="secondary" className="ms-0.5 px-1.5 font-normal tabular-nums">
          {count}
        </Badge>
      ) : null}
    </Button>
  );
}
