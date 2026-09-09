"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { useInvalidation } from "@/hooks/useInvalidation";
import { notificationQueryKeys } from "@/lib/notification-query-keys";
import notificationService from "@/services/notification.service";
import type { NotificationItem } from "@/types/notification.types";

interface UseNotificationsResult {
  items: NotificationItem[];
  unreadCount: number | null;
  isLoading: boolean;
  hasData: boolean;
  isError: boolean;
  isFetching: boolean;
  retry: () => void;
  markAllRead: () => void;
  markOneRead: (id: number) => void;
  isMarkingRead: boolean;
  markingId: number | null;
  markReadStatus: "idle" | "pending" | "error" | "success";
  retryMarkRead: () => void;
  /** Another page exists behind `next_cursor`. */
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
  isLoadMoreError: boolean;
  /** Drop one row from this inbox. The server row survives — see the service. */
  deleteOne: (id: number) => void;
  /** Drop every row already marked read. Never touches an unread one. */
  clearRead: () => void;
  isDeleting: boolean;
  deletingId: number | null;
  deleteStatus: "idle" | "pending" | "error" | "success";
  retryDelete: () => void;
}

/**
 * The inbox behind the bell: one query for the page *and* the badge count, and
 * the personal realtime topic that tells it to refetch.
 *
 * `authUserId` is the identity's own id and nothing else — the gateway ACL for
 * `user:<id>:notifications` has no superuser bypass, so a wrong id is a
 * subscription that is rejected on every reconnect. `null` (anonymous) means no
 * request and no subscription at all.
 */
export function useNotifications(authUserId: number | null | undefined): UseNotificationsResult {
  const queryClient = useQueryClient();
  const enabled = authUserId != null;

  // Paged, not a single read: the server answers 20 rows and an opaque
  // `next_cursor`, so a plain query would make everything older than the 20th
  // notification unreachable — there is no other surface it exists on.
  const query = useInfiniteQuery({
    queryKey: notificationQueryKeys.list(),
    queryFn: ({ pageParam }) => notificationService.list({ cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    meta: { suppressErrorToast: true },
    enabled
  });

  // The inbox is refetched by the shared invalidation consumer: the event names
  // `user.notifications` and nothing else, and going through it also buys the
  // coalescing this hook never had — a burst of announcements used to cost one
  // full inbox read each.
  useInvalidation({ scopeKind: "user", scopeId: authUserId });

  const markRead = useMutation({
    mutationFn: (ids?: number[]) => notificationService.markRead(ids),
    meta: { suppressErrorToast: true },
    onSuccess: async () => {
      // Stay pending until both surfaces reflect the dismissal. A failed
      // refresh must not announce success against stale unread rows.
      const results = await Promise.allSettled([
        queryClient.invalidateQueries(
          { queryKey: notificationQueryKeys.list() },
          { throwOnError: true }
        ),
        queryClient.invalidateQueries(
          { queryKey: notificationQueryKeys.activeAnnouncements() },
          { throwOnError: true }
        )
      ]);
      for (const result of results) {
        if (result.status === "rejected") throw result.reason;
      }
    }
  });

  // Deleting is per viewer, so the same two surfaces have to be re-read: a
  // dismissed announcement leaves the banner as well as the list. No optimistic
  // patch — `markRead` above answers the same question by refetching, and one
  // invalidation path is easier to keep honest than two cache writers.
  const remove = useMutation({
    mutationFn: (variables: { ids?: number[]; onlyRead?: boolean }) =>
      notificationService.remove(variables),
    meta: { suppressErrorToast: true },
    onSuccess: async () => {
      const results = await Promise.allSettled([
        queryClient.invalidateQueries(
          { queryKey: notificationQueryKeys.list() },
          { throwOnError: true }
        ),
        queryClient.invalidateQueries(
          { queryKey: notificationQueryKeys.activeAnnouncements() },
          { throwOnError: true }
        )
      ]);
      for (const result of results) {
        if (result.status === "rejected") throw result.reason;
      }
    }
  });

  return {
    // Pages arrive newest-first and keyset-paginated, so concatenation is the
    // order — no re-sort, and no row can appear twice.
    items: query.data?.pages.flatMap((page) => page.items) ?? [],
    // The badge counts the whole inbox, not the loaded prefix: every page
    // carries the same total, so the first one answers it.
    unreadCount: query.data?.pages[0]?.unread_count ?? null,
    isLoading: enabled && query.isPending,
    hasData: query.data !== undefined,
    isError: query.isError && !query.isFetchNextPageError,
    isFetching: query.isFetching,
    retry: () => {
      if (!query.isFetching) void query.refetch();
    },
    markAllRead: () => {
      if (!markRead.isPending) markRead.mutate(undefined);
    },
    markOneRead: (id) => {
      if (!markRead.isPending) markRead.mutate([id]);
    },
    isMarkingRead: markRead.isPending,
    markingId: markRead.variables?.[0] ?? null,
    markReadStatus: markRead.status,
    retryMarkRead: () => {
      if (!markRead.isPending) markRead.mutate(markRead.variables);
    },
    hasMore: query.hasNextPage,
    loadMore: () => {
      if (query.hasNextPage && !query.isFetching && !markRead.isPending && !remove.isPending) {
        void query.fetchNextPage({ cancelRefetch: false });
      }
    },
    isLoadingMore: query.isFetchingNextPage,
    isLoadMoreError: query.isFetchNextPageError,
    deleteOne: (id) => {
      if (!remove.isPending) remove.mutate({ ids: [id] });
    },
    clearRead: () => {
      if (!remove.isPending) remove.mutate({ onlyRead: true });
    },
    isDeleting: remove.isPending,
    // `null` while the bulk "clear read" runs — the row-level spinner has no
    // single row to sit on, exactly like `markingId`.
    deletingId: remove.variables?.ids?.[0] ?? null,
    deleteStatus: remove.status,
    retryDelete: () => {
      if (!remove.isPending && remove.variables) remove.mutate(remove.variables);
    }
  };
}
