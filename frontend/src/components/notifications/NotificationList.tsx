"use client";

import {
  AlertTriangle,
  Bell,
  Check,
  CheckCheck,
  CheckCircle2,
  Megaphone,
  Trash2,
  UserPlus,
  XCircle
} from "lucide-react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { PopoverClose } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { announcementText } from "@/lib/announcement-text";
import { notificationHref } from "@/lib/notification-href";
import { cn } from "@/lib/utils";
import type { NotificationItem } from "@/types/notification.types";

type KindMessageKey = `notifications.kinds.${
  | "team_invite.received"
  | "team_invite.answered"
  | "registration.approved"
  | "registration.rejected"
  | "encounter.report_disputed"
  | "announcement.published"
  | "team.kicked"
  | "team.rejected"
  | "team.disbanded"}`;

interface NotificationListProps {
  headingId: string;
  items: NotificationItem[];
  unreadCount: number | null;
  isLoading: boolean;
  hasData: boolean;
  isError: boolean;
  isFetching: boolean;
  retry: () => void;
  isMarkingRead: boolean;
  markingId: number | null;
  markReadStatus: "idle" | "pending" | "error" | "success";
  markAllRead: () => void;
  markOneRead: (id: number) => void;
  retryMarkRead: () => void;
  hasMore: boolean;
  isLoadingMore: boolean;
  isLoadMoreError: boolean;
  loadMore: () => void;
  deleteOne: (id: number) => void;
  clearRead: () => void;
  isDeleting: boolean;
  deletingId: number | null;
  deleteStatus: "idle" | "pending" | "error" | "success";
  retryDelete: () => void;
}

/** Only scalar payload values are valid ICU interpolation arguments. */
function messageValues(payload: Record<string, unknown>): Record<string, string | number> {
  const values: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value === "string" || typeof value === "number") {
      values[key] = value;
    }
  }
  return values;
}

/** Visual iconography and status colors per notification kind. */
function getKindConfig(kind: string) {
  switch (kind) {
    case "team_invite.received":
    case "team_invite.answered":
      return {
        icon: UserPlus,
        className: "bg-blue-500/10 text-blue-400 border-blue-500/20"
      };
    case "registration.approved":
      return {
        icon: CheckCircle2,
        className: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
      };
    case "registration.rejected":
    case "team.kicked":
    case "team.rejected":
    case "team.disbanded":
      return {
        icon: XCircle,
        className: "bg-rose-500/10 text-rose-400 border-rose-500/20"
      };
    case "encounter.report_disputed":
      return {
        icon: AlertTriangle,
        className: "bg-amber-500/10 text-amber-400 border-amber-500/20"
      };
    case "announcement.published":
      return {
        icon: Megaphone,
        className: "bg-primary/10 text-primary border-primary/20"
      };
    default:
      return {
        icon: Bell,
        className: "bg-muted text-muted-foreground border-border"
      };
  }
}

const NotificationList = ({
  headingId,
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
}: NotificationListProps) => {
  const t = useTranslations<never>();
  const locale = useLocale();
  const format = useFormatter();

  const notificationText = (item: NotificationItem): string => {
    if (item.kind === "announcement.published") {
      const title = announcementText(item.payload, locale)?.title;
      if (title) return title;
    }
    const key = `notifications.kinds.${item.kind}` as KindMessageKey;
    if (!t.has(key)) return t("notifications.unknownKind");
    return t(key, messageValues(item.payload));
  };
  // One mutation at a time: read-marking and deleting both rewrite the same
  // rows, and the list is refetched rather than patched, so overlapping them
  // would race two invalidations against one another.
  const busy = isMarkingRead || isDeleting;
  const markAllUnavailable = unreadCount == null || unreadCount === 0 || busy;
  // Read rows are the only ones "clear read" can take, so with none loaded the
  // button would be a request that deletes nothing.
  const clearReadUnavailable = busy || !items.some((item) => item.is_read);
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
  const statusMessage = deleteStatusText || readStatus;

  return (
    <div className="flex min-h-0 max-h-[min(70dvh,var(--radix-popover-content-available-height))] flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 px-4 pb-2.5 pt-3.5">
        <div className="flex items-center gap-2">
          <h2 id={headingId} className="text-sm font-semibold tracking-tight text-foreground">
            {t("notifications.title")}
          </h2>
          {unreadCount != null && unreadCount > 0 && (
            <span className="rounded-full border border-primary/25 bg-primary/15 px-2 py-0.5 text-label font-semibold tabular-nums text-primary">
              {t("notifications.newCount", { count: unreadCount })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          <Button
            static={false}
            variant="ghost"
            size="sm"
            className="h-auto min-h-8 gap-1.5 px-2 text-xs text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground aria-disabled:pointer-events-none aria-disabled:opacity-50"
            onClick={() => {
              if (!markAllUnavailable) markAllRead();
            }}
            aria-label={t("notifications.markAllRead")}
            aria-disabled={markAllUnavailable}
            aria-busy={isMarkingRead && markingId == null}
          >
            <CheckCheck className="size-3.5 shrink-0" aria-hidden />
            <span>
              {t(
                isMarkingRead && markingId == null
                  ? "notifications.markingAllRead"
                  : "notifications.markAllRead"
              )}
            </span>
          </Button>
          <Button
            static={false}
            variant="ghost"
            size="sm"
            className="h-auto min-h-8 gap-1.5 px-2 text-xs text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive aria-disabled:pointer-events-none aria-disabled:opacity-50"
            onClick={() => {
              if (!clearReadUnavailable) clearRead();
            }}
            aria-label={t("notifications.clearRead")}
            aria-disabled={clearReadUnavailable}
            aria-busy={isDeleting && deletingId == null}
          >
            <Trash2 className="size-3.5 shrink-0" aria-hidden />
            <span>
              {t(
                isDeleting && deletingId == null
                  ? "notifications.clearingRead"
                  : "notifications.clearRead"
              )}
            </span>
          </Button>
        </div>
      </div>

      <div
        tabIndex={0}
        aria-label={t("notifications.title")}
        className="min-h-0 overflow-y-auto overscroll-contain outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        {isError && (
          <div className="space-y-2 px-3 py-4">
            <p role="status" className="text-sm">
              {t(hasData ? "notifications.refreshError" : "notifications.loadError")}
            </p>
            <Button
              static={false}
              variant="outline"
              size="sm"
              onClick={retry}
              disabled={isFetching}
            >
              {t(isFetching ? "common.loading" : "notifications.retry")}
            </Button>
          </div>
        )}
        {isLoading ? (
          <div
            aria-busy="true"
            aria-label={t("notifications.loading")}
            className="space-y-5 px-3 py-4"
          >
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
          <div className="px-3 py-6 text-center">
            <p className="text-sm font-medium">{t("notifications.empty")}</p>
            <p className="mt-1 text-pretty text-sm text-muted-foreground">
              {t("notifications.emptyHint")}
            </p>
          </div>
        ) : items.length > 0 ? (
          <ul className="divide-y divide-border/40">
            {items.map((item) => {
              const href = notificationHref(item);
              const text = notificationText(item);
              const isPending = isMarkingRead && (markingId == null || markingId === item.id);
              const isDeletePending = isDeleting && (deletingId == null || deletingId === item.id);
              const unavailable = item.is_read || busy;
              const kindConfig = getKindConfig(item.kind);
              const KindIcon = kindConfig.icon;

              return (
                <li
                  key={item.id}
                  className={cn(
                    "group relative flex items-start gap-3 px-4 py-3 text-sm transition-colors hover:bg-muted/30",
                    !item.is_read && "bg-muted/20"
                  )}
                >
                  <div className="relative mt-0.5 shrink-0">
                    <div
                      className={cn(
                        "flex size-8 items-center justify-center rounded-full border",
                        kindConfig.className
                      )}
                    >
                      <KindIcon className="size-4" aria-hidden />
                    </div>
                    {!item.is_read && (
                      <span
                        aria-hidden="true"
                        className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full bg-primary ring-2 ring-card"
                      />
                    )}
                  </div>

                  <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                    {!item.is_read && (
                      <span className="sr-only">{t("notifications.unread")} </span>
                    )}
                    {href ? (
                      <PopoverClose asChild>
                        <Link
                          href={href}
                          className="line-clamp-2 text-sm font-medium leading-snug text-foreground hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                        >
                          {text}
                        </Link>
                      </PopoverClose>
                    ) : (
                      <p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
                        {text}
                      </p>
                    )}
                    <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                      <time dateTime={item.published_at}>
                        {format.relativeTime(new Date(item.published_at))}
                      </time>
                    </div>
                  </div>

                  <Button
                    static={false}
                    variant="ghost"
                    size="icon"
                    className={cn(
                      "size-7 shrink-0 rounded-md text-muted-foreground transition-opacity hover:bg-accent hover:text-foreground",
                      item.is_read
                        ? "pointer-events-none opacity-0"
                        : "opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                    )}
                    aria-label={t(
                      item.is_read ? "notifications.readFor" : "notifications.markReadFor",
                      { notification: text }
                    )}
                    aria-disabled={unavailable}
                    aria-busy={isPending}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (!unavailable) markOneRead(item.id);
                    }}
                  >
                    <Check className="size-3.5" aria-hidden />
                    <span className="sr-only">
                      {t(
                        isPending
                          ? "notifications.markingRead"
                          : item.is_read
                            ? "notifications.read"
                            : "notifications.markRead"
                      )}
                    </span>
                  </Button>

                  <Button
                    static={false}
                    variant="ghost"
                    size="icon"
                    className="size-7 shrink-0 rounded-md text-muted-foreground opacity-100 transition-opacity hover:bg-destructive/10 hover:text-destructive sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                    aria-label={t("notifications.deleteFor", { notification: text })}
                    aria-disabled={busy}
                    aria-busy={isDeletePending}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (!busy) deleteOne(item.id);
                    }}
                  >
                    <Trash2 className="size-3.5" aria-hidden />
                    <span className="sr-only">
                      {t(isDeletePending ? "notifications.deleting" : "notifications.delete")}
                    </span>
                  </Button>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>

      <div className="shrink-0">
        <p
          role="status"
          aria-atomic="true"
          className={cn("text-sm", statusMessage ? "border-t px-3 py-2" : "sr-only")}
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
        {hasMore && (
          <div className="border-t p-2">
            <p role="status" className={cn("text-sm", isLoadMoreError ? "px-1 pb-2" : "sr-only")}>
              {isLoadMoreError
                ? t("notifications.loadMoreError")
                : isLoadingMore
                  ? t("notifications.loadingMore")
                  : ""}
            </p>
            <Button
              static={false}
              variant="ghost"
              size="sm"
              className="h-auto min-h-10 w-full whitespace-normal text-xs sm:min-h-8"
              onClick={loadMore}
              disabled={isFetching || busy}
            >
              {t(
                isLoadingMore
                  ? "notifications.loadingMore"
                  : isLoadMoreError
                    ? "notifications.retryLoadMore"
                    : "notifications.loadMore"
              )}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};

export default NotificationList;
