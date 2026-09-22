"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, X } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import {
  readDismissedAnnouncements,
  rememberDismissedAnnouncement
} from "@/lib/notifications/announcement-dismissed";
import { announcementHref, announcementText } from "@/lib/notifications/announcement-text";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import notificationService from "@/services/notification.service";
import type { NotificationItem } from "@/types/notification.types";

interface AnnouncementBannerProps {
  /** The layout's server-side read, so the banner is painted with the first
   *  frame instead of popping in after hydration. */
  initial?: NotificationItem[];
}

interface AnnouncementContent {
  title: string;
  body: string | null;
  href: string | null;
}

/**
 * The banner's own reading of a row: the viewer's text (locale choice lives in
 * `announcementText`) plus the link, whose safety check `announcementHref`
 * owns for both readers of it.
 */
function announcementContent(
  payload: Record<string, unknown>,
  locale: string
): AnnouncementContent | null {
  const text = announcementText(payload, locale);
  if (!text?.title) return null;

  return { title: text.title, body: text.body ?? null, href: announcementHref(payload) };
}

/**
 * The platform-wide announcement, floating over the page under the sticky
 * header — on every page and for every visitor, since it is the only
 * notification surface an anonymous one has.
 *
 * Out of the document flow on purpose: in flow it displaced every page by its
 * own height, and the height depends on text an operator types, so the whole
 * site jumped by an unpredictable amount whenever a notice went up. As overlay
 * chrome it costs the layout nothing and matches the two surfaces that already
 * float here — `CookieConsent` and `TournamentBroadcastDock`.
 *
 * `z-[45]` is the slot between the page's own sticky rails (`z-40`: profile tab
 * strips, sidebars) and the header, dialogs and cookie notice (`z-50`): it must
 * cover in-page chrome, and must never cover the header or a modal.
 *
 * Vertical anchor is `--aqt-banner-top`, defaulting to the same
 * `--aqt-sticky-top` every in-page sticky rail uses, so it clears the site
 * header at both scroll positions (the header sits 24px down at scroll top and
 * pins to 0 after). The admin shell has a shorter header and sets its own.
 *
 * `role="status"`, not the `Alert` primitive's default `role="alert"`: an
 * operator notice is not urgent, so it is announced politely at the next pause
 * rather than interrupting a screen reader mid-sentence. Nothing is focused on
 * mount and nothing is trapped — and Escape deliberately does *not* close it,
 * because dismissal here is permanent and an accidental Escape would retire a
 * notice the visitor never read.
 */
const AnnouncementBanner = ({ initial }: AnnouncementBannerProps) => {
  const t = useTranslations<never>();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const { user } = useAuthProfile();
  const authUserId = user?.id ?? null;

  // This browser's dismissals: the server may answer as if anonymous (lapsed
  // access cookie), and these keep a closed notice closed regardless.
  const [dismissed, setDismissed] = useState<number[]>(() => readDismissedAnnouncements());

  const query = useQuery({
    queryKey: notificationQueryKeys.activeAnnouncements(),
    queryFn: () => notificationService.activeAnnouncements(),
    initialData: initial,
    // Nobody asked for this read: it runs on every page for every visitor,
    // including anonymous ones. A failure means no banner, not an error toast
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
      // A read mark *is* the dismissal, and the bell counts the same rows — so
      // closing the banner has to drop its badge too.
      void queryClient.invalidateQueries({ queryKey: notificationQueryKeys.list() });
      void queryClient.invalidateQueries({ queryKey: notificationQueryKeys.activeAnnouncements() });
    }
  });

  // Newest wins, and the order is established here rather than trusted from the
  // response: showing two notices would double the header's height, and showing
  // the older one is worse than showing none.
  const announcement = (query.data ?? [])
    .filter((item) => !item.is_read && !dismissed.includes(item.id))
    .reduce<NotificationItem | null>(
      (newest, item) => (newest && newest.published_at >= item.published_at ? newest : item),
      null
    );

  const content = announcement ? announcementContent(announcement.payload, locale) : null;
  if (!announcement || !content) {
    return null;
  }

  const onDismiss = () => {
    // Hide it locally either way: the mutation's refetch takes a round trip,
    // and a banner that lingers after its close button reads as broken.
    setDismissed((ids) => [...ids, announcement.id]);
    if (authUserId != null) {
      markRead.mutate([announcement.id]);
    } else {
      rememberDismissedAnnouncement(announcement.id);
    }
    // This click unmounts the button that owns focus, and focus would land on
    // <body> — the next Tab would then restart at the top of the document
    // instead of continuing where the visitor was. Both shells expose a
    // `tabIndex={-1}` content root, which is where reading resumes.
    const contentRoot =
      document.getElementById("main-content") ?? document.getElementById("admin-content");
    contentRoot?.focus({ preventScroll: true });
  };

  const hasBody = Boolean(content.body);

  return (
    // Centre the notice in the same content column as both page shells.
    // `pointer-events-none` on the rail so the strip across the top of every
    // page does not eat clicks the card itself is not under.
    <div className="pointer-events-none fixed inset-x-0 top-[var(--aqt-banner-top,calc(var(--aqt-sticky-top)+0.75rem))] z-[45] mx-auto flex w-full max-w-screen-3xl justify-center px-4 md:px-6 xl:px-10">
      {hasBody ? (
        <Alert
          role="status"
          aria-label={t("notifications.banner.label")}
          className="pointer-events-auto relative flex w-full flex-col rounded-2xl border border-border/60 bg-background/85 p-3 shadow-sm backdrop-blur-md transition-all duration-150 animate-in fade-in slide-in-from-top-1 motion-reduce:animate-none sm:w-auto sm:min-w-[320px] sm:max-w-md [&>svg]:static [&>svg~*]:pl-0"
        >
          <div className="flex items-start justify-between gap-2.5">
            <div className="flex min-w-0 flex-1 items-start gap-2">
              <span className="mt-0.5 inline-flex shrink-0 text-muted-foreground">
                <Info className="size-4" aria-hidden />
              </span>
              <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                <AlertTitle className="mb-0 text-xs font-medium leading-snug text-foreground text-pretty sm:text-sm">
                  {content.title}
                </AlertTitle>
                <AlertDescription className="mt-1 text-xs leading-relaxed text-muted-foreground text-pretty">
                  {content.body}
                </AlertDescription>
                {content.href && (
                  <div className="mt-2">
                    <Link
                      href={content.href}
                      // The visible label stays short; the accessible name carries the
                      // destination, so the link still makes sense in a screen reader's
                      // link list (and contains its visible text, per label-in-name).
                      aria-label={`${t("notifications.banner.more")}: ${content.title}`}
                      className="inline-flex items-center gap-0.5 text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
                    >
                      <span>{t("notifications.banner.more")}</span>
                      <span aria-hidden>→</span>
                    </Link>
                  </div>
                )}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              static={false}
              className="-mr-1 -mt-0.5 size-6 shrink-0 rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-3"
              aria-label={t("notifications.banner.dismiss")}
              onClick={onDismiss}
            >
              <X aria-hidden />
            </Button>
          </div>
        </Alert>
      ) : (
        <Alert
          role="status"
          aria-label={t("notifications.banner.label")}
          className="pointer-events-auto relative flex w-auto max-w-[calc(100vw-2rem)] items-center gap-2 rounded-full border border-border/60 bg-background/85 px-3 py-1.5 shadow-sm backdrop-blur-md transition-all duration-150 animate-in fade-in slide-in-from-top-1 motion-reduce:animate-none sm:gap-2.5 [&>svg]:static [&>svg~*]:pl-0"
        >
          <span className="inline-flex shrink-0 text-muted-foreground">
            <Info className="size-3.5" aria-hidden />
          </span>

          <div className="min-w-0 [overflow-wrap:anywhere]">
            <AlertTitle className="mb-0 max-w-[280px] truncate text-xs font-medium leading-normal text-foreground sm:max-w-md md:max-w-lg sm:text-sm sm:leading-none">
              {content.title}
            </AlertTitle>
          </div>

          {content.href && (
            <Link
              href={content.href}
              // The visible label stays short; the accessible name carries the
              // destination, so the link still makes sense in a screen reader's
              // link list (and contains its visible text, per label-in-name).
              aria-label={`${t("notifications.banner.more")}: ${content.title}`}
              className="inline-flex shrink-0 items-center gap-0.5 text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
            >
              <span>{t("notifications.banner.more")}</span>
              <span aria-hidden>→</span>
            </Link>
          )}

          <Button
            variant="ghost"
            size="icon"
            static={false}
            className="-mr-1 size-6 shrink-0 rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-3"
            aria-label={t("notifications.banner.dismiss")}
            onClick={onDismiss}
          >
            <X aria-hidden />
          </Button>
        </Alert>
      )}
    </div>
  );
};

export default AnnouncementBanner;
