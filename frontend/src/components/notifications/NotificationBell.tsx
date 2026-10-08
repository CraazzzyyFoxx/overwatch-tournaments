"use client";

import { Bell, Check, CheckCheck, CircleAlert, Settings2, Trash2, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useState, type ReactNode } from "react";

import {
  NotificationActions,
  type ResolvedAction
} from "@/components/notifications/NotificationActions";
import { useBellSignal } from "@/components/notifications/bell-signal";
import { KIND_FALLBACK, KIND_VISUAL } from "@/components/notifications/notification-kinds";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { SITE_NAME } from "@/config/site";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useNotifications, type UseNotificationsResult } from "@/hooks/useNotifications";
import { type Formatter } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";
import { announcementText } from "@/lib/notifications/announcement-text";
import { notificationHref } from "@/lib/notifications/href";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { NotificationItem } from "@/types/notification.types";

/**
 * Payload fields holding an ISO stamp. ICU has no argument type that formats
 * one, so they are rendered before interpolation — otherwise the message would
 * read `2026-09-25T18:00:00Z` in both locales.
 */
const DATE_FIELDS = ["scheduled_at", "closes_at"] as const;

/** Below this the panel is the whole screen rather than a popover. */
const PHONE_QUERY = "(max-width: 639px)";

/**
 * The inbox lives behind its own control in the header — not inside the account
 * menu, where a `role="menu"` could not legally hold a row made of a link, two
 * tool buttons and an inline action.
 *
 * Renders nothing for a signed-out visitor: the inbox is per account, and the
 * one notification an anonymous reader can receive (a platform announcement)
 * has its own card in the floating stack.
 */
export function NotificationBell() {
  const { user } = useAuthProfile();
  if (user?.id == null) return null;
  return <SignedInBell authUserId={user.id} />;
}

function SignedInBell({ authUserId }: Readonly<{ authUserId: number }>) {
  const t = useTranslations();
  const inbox = useNotifications(authUserId);
  // Shared: the floating stack's "Ещё N" opens this same panel.
  const open = useBellSignal((state) => state.open);
  const setOpen = useBellSignal((state) => state.setOpen);
  const [isPhone, setIsPhone] = useState(false);

  useEffect(() => {
    const query = window.matchMedia(PHONE_QUERY);
    const sync = () => setIsPhone(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  const unread = inbox.unreadCount ?? 0;
  const trigger = (
    <button
      type="button"
      aria-label={unread > 0 ? t("notifications.bellLabel", { count: unread }) : t("notifications.title")}
      className="relative inline-flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-[var(--aqt-radius-sm)] border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] text-[color:var(--aqt-fg-muted)] transition-colors hover:border-[color:var(--aqt-border-3)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-expanded:text-[color:var(--aqt-fg)]"
    >
      <Bell className="size-4" aria-hidden />
      {unread > 0 && (
        <span
          aria-hidden
          className="absolute -right-1.5 -top-[7px] inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full border-2 border-[color:var(--aqt-card)] bg-[color:var(--aqt-rose)] px-[5px] text-label font-bold leading-[14px] tabular-nums text-[color:var(--aqt-bg)]"
        >
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </button>
  );

  if (isPhone) {
    return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>{trigger}</SheetTrigger>
        {/* Full screen, not a bottom drawer: a phone has no room for a panel
            that is also a popover, and the list is the whole task. */}
        <SheetContent
          side="bottom"
          closeButton={false}
          className="inset-0 flex h-dvh max-h-none w-auto flex-col gap-0 overflow-hidden rounded-none border-0 bg-[color:var(--aqt-card-2)] p-0"
        >
          <Panel inbox={inbox} isPhone onClose={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        collisionPadding={16}
        animate={false}
        className="flex max-h-[min(640px,calc(100dvh-96px))] w-[400px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-xl border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] p-0 shadow-[0_18px_50px_rgb(0_0_0/0.5)]"
        onOpenAutoFocus={(event) => {
          // Land on the heading, not the first tool: focusing a tool pops its
          // tooltip on every open.
          event.preventDefault();
          (event.currentTarget as HTMLElement).querySelector<HTMLElement>("h2")?.focus();
        }}
      >
        <Panel inbox={inbox} isPhone={false} onClose={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  );
}

const TOOL_CLASS =
  "size-9 text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] aria-disabled:pointer-events-none aria-disabled:opacity-50";
const FOOT_LINK_CLASS =
  "min-h-9 rounded-lg px-2 text-caption font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50";

function Panel({
  inbox,
  isPhone,
  onClose
}: Readonly<{ inbox: UseNotificationsResult; isPhone: boolean; onClose: () => void }>) {
  const t = useTranslations();
  const locale = useLocale();
  const format = useFormatter();
  // The settings deep link stays on the page the reader is on, the way the
  // OAuth return link does, rather than bouncing home.
  const pathname = usePathname();
  const headingId = useId();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);
  const tenantWorkspaceId = useWorkspaceStore((state) => state.hostLockedWorkspaceId);
  // A row names the community it came from, so the panel needs the directory.
  // Only once it is open: nothing else here asks for the list.
  useEffect(() => {
    if (workspaces.length === 0) void fetchWorkspaces();
  }, [workspaces.length, fetchWorkspaces]);

  const [resolved, setResolved] = useState<Record<number, ResolvedAction>>({});
  const [actionMessage, setActionMessage] = useState("");

  const {
    items,
    unreadCount,
    isLoading,
    hasData,
    isError,
    isFetching,
    retry,
    isMarkingRead,
    markingId,
    markReadStatus,
    markAllRead,
    markOneRead,
    retryMarkRead,
    hasMore,
    isLoadingMore,
    isLoadMoreError,
    loadMore,
    deleteOne,
    clearRead,
    isDeleting,
    deletingId,
    deleteStatus,
    retryDelete
  } = inbox;

  // One mutation at a time: read-marking and deleting both rewrite the same
  // rows, and the list is refetched rather than patched, so overlapping them
  // would race two invalidations against one another.
  const busy = isMarkingRead || isDeleting;
  const markAllUnavailable = !unreadCount || busy;
  const readStatus = isMarkingRead
    ? t(markingId == null ? "notifications.markingAllRead" : "notifications.markingRead")
    : markReadStatus === "error"
      ? t("notifications.markReadError")
      : markReadStatus === "success"
        ? t(markingId == null ? "notifications.markedAllRead" : "notifications.markedRead")
        : "";
  const deleteStatusText = isDeleting
    ? t(deletingId == null ? "notifications.clearingRead" : "notifications.deleting")
    : deleteStatus === "error"
      ? t("notifications.deleteError")
      : deleteStatus === "success"
        ? t(deletingId == null ? "notifications.clearedRead" : "notifications.deleted")
        : "";
  // The delete message wins a tie: it is the newer verb whenever both have run,
  // and two live regions announcing at once is worse than one stale line.
  const statusMessage = actionMessage || deleteStatusText || readStatus;
  const statusIsError = deleteStatusText ? deleteStatus === "error" : markReadStatus === "error";

  const heading = (
    <h2
      id={headingId}
      tabIndex={-1}
      className="font-display text-ui font-bold leading-[1.3] text-[color:var(--aqt-fg)] outline-none"
    >
      {t("notifications.title")}
    </h2>
  );

  return (
    <>
      <div className="flex shrink-0 items-center gap-2.5 border-b border-[color:var(--aqt-border)] py-3 pl-4 pr-2.5">
        {isPhone ? <SheetTitle asChild>{heading}</SheetTitle> : heading}
        {unreadCount != null && unreadCount > 0 && (
          <span className="rounded-full bg-[color:color-mix(in_srgb,var(--aqt-rose)_14%,transparent)] px-[7px] py-1 text-label font-semibold leading-none tabular-nums text-[color:var(--aqt-rose-text)]">
            {t("notifications.newCount", { count: unreadCount })}
          </span>
        )}
        <TooltipProvider delayDuration={200}>
          <div className="ml-auto flex items-center gap-0.5">
            {unreadCount != null && unreadCount > 0 && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-flex">
                    <Button
                      static={false}
                      variant="ghost"
                      size="icon"
                      className={TOOL_CLASS}
                      onClick={() => {
                        if (!markAllUnavailable) markAllRead();
                      }}
                      aria-disabled={markAllUnavailable}
                      aria-busy={isMarkingRead && markingId == null}
                    >
                      <CheckCheck aria-hidden />
                      <span className="sr-only">{t("notifications.markAllRead")}</span>
                    </Button>
                  </span>
                </TooltipTrigger>
                <TooltipContent>{t("notifications.markAllRead")}</TooltipContent>
              </Tooltip>
            )}
            {/* The one place a reader can turn Discord copies off. The modal owns
                `?settings=`, so this is a plain link on the current page rather
                than a second way to open it. */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  href={`${pathname ?? "/"}?settings=notifications`}
                  onClick={onClose}
                  className="inline-flex size-9 items-center justify-center rounded-md text-[color:var(--aqt-fg-dim)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <Settings2 className="size-4" aria-hidden />
                  <span className="sr-only">{t("notifications.configure")}</span>
                </Link>
              </TooltipTrigger>
              <TooltipContent>{t("notifications.configure")}</TooltipContent>
            </Tooltip>
            {isPhone && (
              <Button
                static={false}
                variant="ghost"
                size="icon"
                className={TOOL_CLASS}
                onClick={onClose}
              >
                <X aria-hidden />
                <span className="sr-only">{t("notifications.close")}</span>
              </Button>
            )}
          </div>
        </TooltipProvider>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {isError && (
          <div className="flex items-start gap-3 p-[18px] text-body text-[color:var(--aqt-fg-muted)]">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-[color:var(--aqt-rose)]" aria-hidden />
            <div>
              <b className="mb-0.5 block font-semibold text-[color:var(--aqt-fg)]">
                {t(hasData ? "notifications.refreshError" : "notifications.loadErrorTitle")}
              </b>
              {!hasData && t("notifications.loadErrorHint")}
              <div className="mt-2.5">
                <Button
                  static={false}
                  variant="outline"
                  size="sm"
                  className="h-8 border-[color:var(--aqt-border-2)] px-3 text-caption"
                  onClick={retry}
                  disabled={isFetching}
                >
                  {t(isFetching ? "common.loading" : "notifications.retry")}
                </Button>
              </div>
            </div>
          </div>
        )}
        {isLoading ? (
          <div aria-busy="true" className="space-y-5 px-4 py-4">
            <span role="status" className="sr-only">
              {t("notifications.loading")}
            </span>
            {[0, 1, 2].map((row) => (
              <div key={row} aria-hidden="true" className="space-y-2">
                <Skeleton className="h-4 w-full motion-reduce:animate-none" />
                <Skeleton className="h-4 w-3/4 motion-reduce:animate-none" />
                <Skeleton className="h-3 w-1/3 motion-reduce:animate-none" />
              </div>
            ))}
          </div>
        ) : hasData && items.length === 0 && !isError ? (
          <div className="grid justify-items-center gap-1.5 px-6 py-10 text-center text-[color:var(--aqt-fg-dim)]">
            <Bell className="mb-1 size-7 text-[color:var(--aqt-fg-faint)]" aria-hidden />
            <b className="font-semibold text-[color:var(--aqt-fg)]">{t("notifications.empty")}</b>
            <p className="max-w-[26ch] text-caption">{t("notifications.emptyHint")}</p>
          </div>
        ) : items.length > 0 ? (
          <ol>
            {items.map((item) => (
              <Row
                key={item.id}
                item={item}
                busy={busy}
                isMarkingRead={isMarkingRead}
                markingId={markingId}
                isDeleting={isDeleting}
                deletingId={deletingId}
                markOneRead={markOneRead}
                deleteOne={deleteOne}
                onClose={onClose}
                resolved={resolved[item.id] ?? null}
                onResolved={(action) => {
                  setResolved((current) => ({ ...current, [item.id]: action }));
                  setActionMessage(t(`notifications.actions.${action}`));
                  if (!item.is_read) markOneRead(item.id);
                }}
                workspace={workspaces.find((workspace) => workspace.id === item.workspace_id) ?? null}
                tenantWorkspaceId={tenantWorkspaceId}
                locale={locale}
                format={format}
              />
            ))}
          </ol>
        ) : null}
      </div>

      <div className="shrink-0">
        <p
          role="status"
          aria-atomic="true"
          aria-live="polite"
          className={cn(
            "text-caption",
            statusIsError
              ? "border-t border-[color:var(--aqt-border)] px-3 py-2 text-[color:var(--aqt-rose-text)]"
              : "sr-only"
          )}
        >
          {statusMessage}
        </p>
        {markReadStatus === "error" && (
          <div className="px-3 pb-2">
            <Button static={false} variant="outline" size="sm" onClick={retryMarkRead}>
              {t("notifications.retryMarkRead")}
            </Button>
          </div>
        )}
        {deleteStatus === "error" && (
          <div className="px-3 pb-2">
            <Button static={false} variant="outline" size="sm" onClick={retryDelete}>
              {t("notifications.retryDelete")}
            </Button>
          </div>
        )}
        {isLoadMoreError && (
          <p role="status" className="px-3 pb-2 text-caption text-[color:var(--aqt-rose-text)]">
            {t("notifications.loadMoreError")}
          </p>
        )}
        {items.length > 0 && (
          <div className="flex justify-between gap-3 border-t border-[color:var(--aqt-border)] px-2 py-1.5">
            {items.some((item) => item.is_read) ? (
              <button
                type="button"
                className={FOOT_LINK_CLASS}
                onClick={clearRead}
                disabled={busy}
                aria-busy={isDeleting && deletingId == null}
              >
                {t("notifications.clearRead")}
              </button>
            ) : (
              <span />
            )}
            {hasMore && (
              <button
                type="button"
                className={FOOT_LINK_CLASS}
                onClick={loadMore}
                disabled={isFetching || busy}
                aria-busy={isLoadingMore}
              >
                {t(
                  isLoadingMore
                    ? "notifications.loadingMore"
                    : isLoadMoreError
                      ? "notifications.retryLoadMore"
                      : "notifications.loadMore"
                )}
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
}

interface RowProps {
  item: NotificationItem;
  busy: boolean;
  isMarkingRead: boolean;
  markingId: number | null;
  isDeleting: boolean;
  deletingId: number | null;
  markOneRead: (id: number) => void;
  deleteOne: (id: number) => void;
  onClose: () => void;
  resolved: ResolvedAction | null;
  onResolved: (action: ResolvedAction) => void;
  workspace: { id: number; name: string; icon_url: string | null } | null;
  tenantWorkspaceId: number | null;
  locale: string;
  format: Formatter;
}

function Row({
  item,
  busy,
  isMarkingRead,
  markingId,
  isDeleting,
  deletingId,
  markOneRead,
  deleteOne,
  onClose,
  resolved,
  onResolved,
  workspace,
  tenantWorkspaceId,
  locale,
  format
}: Readonly<RowProps>) {
  const t = useTranslations();
  const [Icon, tone] = KIND_VISUAL[item.kind] ?? KIND_FALLBACK;
  const href = notificationHref(item);
  const published = new Date(item.published_at);
  const absolute = format.dateTime(published, { dateStyle: "medium", timeStyle: "short" });

  let body: ReactNode;
  if (item.kind === "announcement.published") {
    const title = announcementText(item.payload, locale)?.title;
    body = title
      ? t.rich("notifications.announcementText", { title, b: (chunks) => <b>{chunks}</b> })
      : t("notifications.unknownKind");
  } else {
    const key = `notifications.kinds.${item.kind}`;
    if (!t.has(key as Parameters<typeof t.has>[0])) {
      body = t("notifications.unknownKind");
    } else {
      const values: Record<string, string | number> = {};
      for (const [field, value] of Object.entries(item.payload)) {
        if (typeof value === "string" || typeof value === "number") values[field] = value;
      }
      for (const field of DATE_FIELDS) {
        const raw = values[field];
        if (typeof raw === "string") {
          values[field] = format.dateTime(new Date(raw), { dateStyle: "medium", timeStyle: "short" });
        }
      }
      // A phase with no end carries no `closes_at`, and a match whose time is not
      // fixed yet carries no `scheduled_at`; an ICU `select` needs its argument in
      // every case, so the message branches on this sentinel.
      if (item.kind === "registration.opened" || item.kind === "check_in.opened") {
        values.closes_at ??= "none";
      }
      if (item.kind === "encounter.scheduled") values.scheduled_at ??= "none";
      // The key is only known at runtime, so the typed translator cannot
      // narrow it — every kind message takes the same `<b>` tag and scalars.
      const translate = t.rich as (key: string, values: Record<string, unknown>) => ReactNode;
      body = translate(key, { ...values, b: (chunks: ReactNode) => <b>{chunks}</b> });
    }
  }

  // On a community's own host its own rows drop the source: everything here is
  // that community's, and repeating the name on every row says nothing.
  const showSource = !(workspace && workspace.id === tenantWorkspaceId);
  const isPending = isMarkingRead && (markingId == null || markingId === item.id);
  const isDeletePending = isDeleting && (deletingId == null || deletingId === item.id);

  const text = (
    <>
      {!item.is_read && <span className="sr-only">{t("notifications.unread")} </span>}
      {body}
    </>
  );

  return (
    <li
      className={cn(
        "group relative grid grid-cols-[32px_minmax(0,1fr)_auto] gap-3 border-b border-[color:var(--aqt-border)] py-3.5 pl-4 pr-2.5 last:border-b-0",
        !item.is_read &&
          "bg-[color:color-mix(in_srgb,var(--aqt-teal)_4%,transparent)] before:absolute before:left-[5px] before:top-[26px] before:size-1.5 before:rounded-full before:bg-[color:var(--aqt-teal)] before:content-['']"
      )}
    >
      <span
        aria-hidden
        className="inline-flex size-8 items-center justify-center rounded-[8px] border"
        style={{
          color: tone,
          background: `color-mix(in srgb, ${tone} 12%, transparent)`,
          borderColor: `color-mix(in srgb, ${tone} 24%, transparent)`
        }}
      >
        <Icon className="size-4" aria-hidden />
      </span>

      <div className="min-w-0">
        {href ? (
          <Link
            href={href}
            onClick={() => {
              if (!item.is_read && !busy) markOneRead(item.id);
              onClose();
            }}
            className={cn(
              "block text-body leading-[1.45] text-pretty hover:underline hover:decoration-[color:var(--aqt-border-3)] hover:underline-offset-[3px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring [&_b]:font-semibold [&_b]:text-[color:var(--aqt-fg)]",
              item.is_read ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg)]"
            )}
          >
            {text}
          </Link>
        ) : (
          <p
            className={cn(
              "text-body leading-[1.45] text-pretty [&_b]:font-semibold [&_b]:text-[color:var(--aqt-fg)]",
              item.is_read ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg)]"
            )}
          >
            {text}
          </p>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-caption text-[color:var(--aqt-fg-dim)]">
          {showSource &&
            (workspace ? (
              <>
                <WorkspaceAvatar workspace={workspace} size={16} className="rounded-[4px]" />
                <span>{workspace.name}</span>
                <span aria-hidden>·</span>
              </>
            ) : item.workspace_id == null ? (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/brand-mark.svg" alt="" width={16} height={16} className="rounded-[4px]" />
                <span>{SITE_NAME}</span>
                <span aria-hidden>·</span>
              </>
            ) : null)}
          <time dateTime={item.published_at} title={absolute}>
            {format.relativeTime(published)}
          </time>
        </div>
        <NotificationActions
          item={item}
          done={resolved}
          onResolved={onResolved}
          className="mt-2.5"
        />
      </div>

      <div className="flex flex-col gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
        {!item.is_read && (
          <Button
            static={false}
            variant="ghost"
            size="icon"
            className="size-8 text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] aria-disabled:pointer-events-none aria-disabled:opacity-50"
            title={t("notifications.markRead")}
            aria-label={t("notifications.markRead")}
            aria-disabled={busy}
            aria-busy={isPending}
            onClick={() => {
              if (!busy) markOneRead(item.id);
            }}
          >
            <Check className="size-3.5" aria-hidden />
          </Button>
        )}
        <Button
          static={false}
          variant="ghost"
          size="icon"
          className="size-8 text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] aria-disabled:pointer-events-none aria-disabled:opacity-50"
          title={t("notifications.delete")}
          aria-label={t("notifications.delete")}
          aria-disabled={busy}
          aria-busy={isDeletePending}
          onClick={() => {
            if (!busy) deleteOne(item.id);
          }}
        >
          <Trash2 className="size-3.5" aria-hidden />
        </Button>
      </div>
    </li>
  );
}
