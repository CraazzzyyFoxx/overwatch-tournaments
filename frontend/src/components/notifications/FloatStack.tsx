"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CircleCheck, Megaphone, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import {
  NotificationActions,
  type ResolvedAction
} from "@/components/notifications/NotificationActions";
import { useBellSignal } from "@/components/notifications/bell-signal";
import { ACTIONABLE_RANK, KIND_FALLBACK, KIND_VISUAL } from "@/components/notifications/notification-kinds";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { useNotifications } from "@/hooks/useNotifications";
import { useFormatter } from "@/lib/datetime/client";
import {
  readDismissedAnnouncements,
  rememberDismissedAnnouncement
} from "@/lib/notifications/announcement-dismissed";
import { announcementHref, announcementText } from "@/lib/notifications/announcement-text";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import { isRosterSlotCode } from "@/lib/roster/shape";
import { cn } from "@/lib/utils";
import notificationService from "@/services/notification.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { NotificationItem } from "@/types/notification.types";

/** How long the confirmation card stays before the next pending thing (or nothing). */
const DONE_MS = 3500;
/** Hidden for this visit only: the item itself stays in the bell. */
const HIDDEN_KEY = "owt-urgent-hidden";

const CARD_CLASS =
  "pointer-events-auto relative rounded-[14px] border shadow-[0_18px_40px_-12px_rgb(0_0_0/0.65),0_2px_6px_rgb(0_0_0/0.3)] motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 sm:shadow-[0_14px_30px_-14px_rgb(0_0_0/0.7)] motion-safe:sm:slide-in-from-top-2";
const CLOSE_CLASS =
  "absolute right-1.5 top-1.5 size-8 text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] sm:top-1/2 sm:-translate-y-1/2";

interface FloatStackProps {
  /** The layout's server-side read, so the announcement paints with the first frame. */
  initialAnnouncements: NotificationItem[] | undefined;
  /** Set on a white-label host: the stack then only speaks for that community. */
  tenantWorkspaceId: number | null;
}

/**
 * The page's floating stack: the operator's announcement, and the one thing
 * that needs this person now.
 *
 * In the DOM right after the header, so a keyboard reader reaches an urgent
 * action before the page body rather than after the footer. Phones get fixed
 * cards within thumb reach at the bottom; from 640px they are slim bars that
 * sit in the flow at the top of the page and pin under the header plate once it
 * scrolls — they push the page down, never cover it.
 */
export function FloatStack({ initialAnnouncements, tenantWorkspaceId }: Readonly<FloatStackProps>) {
  const t = useTranslations("notifications");
  const { user } = useAuthProfile();

  const authUserId = user?.id ?? null;
  const announcement = <AnnouncementCard initial={initialAnnouncements} authUserId={authUserId} />;
  const urgent =
    authUserId == null ? null : (
      <UrgentCard authUserId={authUserId} tenantWorkspaceId={tenantWorkspaceId} />
    );

  return (
    <div
      aria-label={t("floatStack.label")}
      className={cn(
        // Always mounted, even with no card: the screen-reader status line for
        // "hidden until the next visit" lives inside and `display:none` would
        // silence it. With no card the grid has no height of its own.
        "pointer-events-none fixed bottom-[calc(12px+env(safe-area-inset-bottom))] left-3 right-3 z-40 grid grid-cols-[minmax(0,1fr)] gap-2.5",
        // From 640 the stack is in the flow, centred under the header plate.
        "sm:sticky sm:bottom-auto sm:left-auto sm:right-auto sm:top-[calc(10px+var(--aqt-header-h)+8px)] sm:mx-auto sm:mt-2.5 sm:w-[min(680px,calc(100%-2rem))] sm:gap-2 md:w-[min(680px,calc(100%-3rem))] xl:w-[min(680px,calc(100%-5rem))]"
      )}
    >
      {announcement}
      {/* Urgent first under the header, but within thumb reach on a phone. */}
      <div className="contents sm:[&>section]:order-first">{urgent}</div>
    </div>
  );
}

/**
 * The operator's notice. Dismissal is a read mark plus this browser's cookie:
 * `/announcements/active` is auth-optional, so once the access cookie lapses the
 * server answers as if anonymous and every dismissed notice would come back.
 */
function AnnouncementCard({
  initial,
  authUserId
}: Readonly<{ initial: NotificationItem[] | undefined; authUserId: number | null }>) {
  const t = useTranslations("notifications.banner");
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState<number[]>(() => readDismissedAnnouncements());

  const query = useQuery({
    queryKey: notificationQueryKeys.activeAnnouncements(),
    queryFn: () => notificationService.activeAnnouncements(),
    initialData: initial,
    // Nobody asked for this read: it runs on every page for every visitor,
    // including anonymous ones. A failure means no card, not an error toast
    // over whatever the visitor actually came to do.
    meta: { suppressErrorToast: true }
  });

  const markRead = useMutation({
    mutationFn: (ids: number[]) => notificationService.markRead(ids),
    onError: (_error, ids) => {
      setDismissed((current) => current.filter((id) => !ids.includes(id)));
    },
    onSuccess: (_result, ids) => {
      // Remembered only once the server has it, so a failed write restores the
      // notice instead of hiding an unsaved dismissal on this browser forever.
      for (const id of ids) rememberDismissedAnnouncement(id);
      // A read mark *is* the dismissal, and the bell counts the same rows.
      void queryClient.invalidateQueries({ queryKey: notificationQueryKeys.list() });
      void queryClient.invalidateQueries({ queryKey: notificationQueryKeys.activeAnnouncements() });
    }
  });

  // Newest wins, and the order is established here rather than trusted from the
  // response: two notices would double the stack's height, and showing the
  // older one is worse than showing none.
  const announcement = (query.data ?? [])
    .filter((item) => !item.is_read && !dismissed.includes(item.id))
    .reduce<NotificationItem | null>(
      (newest, item) => (newest && newest.published_at >= item.published_at ? newest : item),
      null
    );
  const text = announcement ? announcementText(announcement.payload, locale) : null;
  if (!announcement || !text?.title) return null;
  const href = announcementHref(announcement.payload);

  const onDismiss = () => {
    // Hide it locally either way: the mutation's refetch takes a round trip,
    // and a card that lingers after its close button reads as broken.
    setDismissed((ids) => [...ids, announcement.id]);
    if (authUserId != null) markRead.mutate([announcement.id]);
    else rememberDismissedAnnouncement(announcement.id);
    // This click unmounts the button that owns focus, and focus would land on
    // <body> — the next Tab would restart at the top of the document.
    const contentRoot =
      document.getElementById("main-content") ?? document.getElementById("admin-content");
    contentRoot?.focus({ preventScroll: true });
  };

  return (
    <section
      aria-label={t("label")}
      className={cn(
        CARD_CLASS,
        "grid min-h-11 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] py-1.5 pl-3 pr-10 sm:flex sm:gap-3 sm:pl-3.5 sm:pr-11"
      )}
    >
      <span className="inline-flex items-center gap-1.5 text-label font-bold uppercase leading-[1.25] tracking-label text-[color:var(--aqt-teal)]">
        <Megaphone className="size-3.5" aria-hidden />
        <span className="sr-only sm:not-sr-only">{t("eyebrow")}</span>
      </span>
      {href ? (
        <Link
          href={href}
          prefetch={false}
          className="min-w-0 truncate font-semibold text-[color:var(--aqt-fg)] underline-offset-[3px] hover:underline hover:decoration-[color:var(--aqt-border-3)] sm:flex-1"
        >
          {text.title}
        </Link>
      ) : (
        <span className="min-w-0 truncate font-semibold text-[color:var(--aqt-fg)] sm:flex-1">
          {text.title}
        </span>
      )}
      {href && (
        // The title above is the same link; this one repeats it for the eye only.
        <Link
          href={href}
          prefetch={false}
          aria-hidden
          tabIndex={-1}
          className="hidden min-h-7 shrink-0 items-center gap-1.5 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-teal)] sm:inline-flex"
        >
          {t("more")}
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      )}
      <Button
        static={false}
        variant="ghost"
        size="icon"
        className={CLOSE_CLASS}
        onClick={onDismiss}
      >
        <X className="size-3.5" aria-hidden />
        <span className="sr-only">{t("dismiss")}</span>
      </Button>
    </section>
  );
}

/**
 * The one thing that needs this person now: an open check-in first, then a
 * pending invite. On a community's page (or its own host) only that community's
 * items — elsewhere, anything.
 */
function UrgentCard({
  authUserId,
  tenantWorkspaceId
}: Readonly<{ authUserId: number; tenantWorkspaceId: number | null }>) {
  const t = useTranslations("notifications");
  const tSlot = useTranslations("rosterShape.slotCodes");
  const format = useFormatter();
  const pathname = usePathname();
  const setBellOpen = useBellSignal((state) => state.setOpen);
  const minute = useMinuteClock();
  const { items, markOneRead } = useNotifications(authUserId);
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);

  // `sessionStorage`, not a cookie: "this visit" is exactly a tab session. Read
  // in the initializer — the card never renders on the server (the inbox query
  // has no data there), so there is nothing for it to disagree with.
  const [hidden, setHidden] = useState(() => {
    try {
      return typeof window !== "undefined" && window.sessionStorage.getItem(HIDDEN_KEY) === "1";
    } catch {
      // Storage blocked: the card simply stays dismissible per visit.
      return false;
    }
  });
  const [resolved, setResolved] = useState<{ id: number; action: ResolvedAction } | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    if (workspaces.length === 0) void fetchWorkspaces();
  }, [workspaces.length, fetchWorkspaces]);

  // The confirmation holds the card for a few seconds, then the next pending
  // thing takes its place.
  useEffect(() => {
    if (!resolved) return;
    const timer = window.setTimeout(() => setResolved(null), DONE_MS);
    return () => window.clearTimeout(timer);
  }, [resolved]);

  const slug = pathname?.match(/^\/workspace\/([^/]+)/)?.[1];
  const scopeWorkspaceId =
    tenantWorkspaceId ??
    (slug ? (workspaces.find((workspace) => workspace.slug === slug)?.id ?? null) : null);

  const pending = items
    .filter((item) => {
      if (!ACTIONABLE_RANK[item.kind] || item.is_read) return false;
      if (scopeWorkspaceId != null && item.workspace_id !== scopeWorkspaceId) return false;
      // A check-in whose window has closed is no longer an action, only history.
      // The minute clock, not `Date.now()`: reading the clock in render is impure,
      // and this way a lapsed card leaves on its own.
      const closesAt = item.payload.closes_at;
      if (item.kind === "check_in.opened" && typeof closesAt === "string" && minute != null) {
        return new Date(closesAt).getTime() > minute;
      }
      return true;
    })
    .sort((a, b) => ACTIONABLE_RANK[a.kind] - ACTIONABLE_RANK[b.kind]);

  const doneItem = resolved ? items.find((item) => item.id === resolved.id) : undefined;
  if (resolved) {
    const name = doneItem?.payload.tournament_name;
    return (
      <>
        <Live message={announcement} />
        <section
          role="status"
          className={cn(
            CARD_CLASS,
            "flex items-center gap-2.5 border-[color:color-mix(in_srgb,var(--aqt-emerald)_34%,var(--aqt-border-2))] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_6%,var(--aqt-card-2))] p-2.5 pr-3.5 text-[color:var(--aqt-emerald)]"
          )}
        >
          <CircleCheck className="size-4 shrink-0" aria-hidden />
          <p className="text-body text-[color:var(--aqt-fg-muted)]">
            {t(`actions.${resolved.action}`)}
            {typeof name === "string" ? (
              <>
                {": "}
                <b className="font-semibold text-[color:var(--aqt-fg)]">{name}</b>
              </>
            ) : null}
          </p>
        </section>
      </>
    );
  }

  const item = pending[0];
  if (!item || hidden) return <Live message={announcement} />;

  const [Icon, tone] = KIND_VISUAL[item.kind] ?? KIND_FALLBACK;
  const workspace = workspaces.find((candidate) => candidate.id === item.workspace_id) ?? null;
  const tournamentName = item.payload.tournament_name;
  const teamName = item.payload.team_name;
  const closesAt = item.payload.closes_at;
  const slotCode = item.payload.slot_code;

  const meta: string[] = [];
  if (workspace) meta.push(workspace.name);
  if (item.kind === "check_in.opened") {
    if (typeof closesAt === "string") {
      const closes = new Date(closesAt);
      meta.push(
        t("urgent.until", { time: format.dateTime(closes, { dateStyle: "medium", timeStyle: "short" }) })
      );
      meta.push(format.relativeTime(closes));
    }
  } else if (typeof slotCode === "string") {
    // An unknown code from a newer server renders as itself: the label is
    // decoration, the slot is the offer.
    meta.push(t("urgent.slot", { slot: isRosterSlotCode(slotCode) ? tSlot(slotCode) : slotCode }));
  }

  const onHide = () => {
    setHidden(true);
    try {
      window.sessionStorage.setItem(HIDDEN_KEY, "1");
    } catch {
      // Storage blocked: hidden for this render, back on the next page load.
    }
    setAnnouncement(t("urgent.hidden"));
  };

  return (
    <>
      <Live message={announcement} />
      <section
        aria-label={t("urgent.label")}
        className={cn(
          CARD_CLASS,
          "grid grid-cols-[32px_minmax(0,1fr)] items-start gap-x-2.5 gap-y-2 p-2.5 pr-10 sm:grid-cols-[32px_minmax(0,1fr)_auto] sm:items-center sm:gap-x-3 sm:gap-y-1 sm:py-2 sm:pl-2.5 sm:pr-11"
        )}
        style={{
          borderColor: `color-mix(in srgb, ${tone} 40%, var(--aqt-border-2))`,
          background: `color-mix(in srgb, ${tone} 6%, var(--aqt-card-2))`
        }}
      >
        <span
          aria-hidden
          className="inline-flex size-8 items-center justify-center rounded-[9px]"
          style={{ color: tone, background: `color-mix(in srgb, ${tone} 14%, transparent)` }}
        >
          <Icon className="size-4" aria-hidden />
        </span>
        <p className="min-w-0 text-body">
          <b className="block font-semibold text-pretty text-[color:var(--aqt-fg)]">
            {item.kind === "check_in.opened"
              ? t("urgent.checkIn", { tournament: String(tournamentName ?? "") })
              : t("urgent.invite", {
                  team: String(teamName ?? ""),
                  tournament: String(tournamentName ?? "")
                })}
          </b>
          {meta.length > 0 && (
            <span className="mt-0.5 block text-caption text-[color:var(--aqt-fg-dim)]">
              {meta.join(" · ")}
            </span>
          )}
        </p>
        <Button
          static={false}
          variant="ghost"
          size="icon"
          className={CLOSE_CLASS}
          title={t("urgent.hideTitle")}
          onClick={onHide}
        >
          <X className="size-3.5" aria-hidden />
          <span className="sr-only">{t("urgent.hide")}</span>
        </Button>
        <div className="col-start-2 flex flex-wrap items-center gap-2 sm:col-start-3 sm:row-start-1 sm:flex-nowrap">
          <NotificationActions
            item={item}
            done={null}
            onResolved={(action) => {
              setResolved({ id: item.id, action });
              setAnnouncement(t(`actions.${action}`));
              markOneRead(item.id);
            }}
          />
          {pending.length > 1 && (
            <button
              type="button"
              onClick={() => setBellOpen(true)}
              className="min-h-9 shrink-0 rounded-lg px-2 text-caption font-medium text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("urgent.more", { count: pending.length - 1 })}
            </button>
          )}
        </div>
      </section>
    </>
  );
}

function Live({ message }: Readonly<{ message: string }>) {
  return (
    <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </p>
  );
}
