"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CircleCheck, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState, type ReactNode } from "react";

import {
  NotificationActions,
  type ResolvedAction
} from "@/components/notifications/NotificationActions";
import { useBellSignal } from "@/components/notifications/bell-signal";
import { ACTIONABLE_RANK, KIND_FALLBACK, KIND_VISUAL } from "@/components/notifications/notification-kinds";
import { Button } from "@/components/ui/button";
import { GameMark } from "@/components/workspace/GameMark";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { useNotifications } from "@/hooks/useNotifications";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { useTournamentQuery } from "@/hooks/useTournamentClientData";
import { rememberReleaseSeen, type Release } from "@/lib/changelog/releases";
import { useFormatter } from "@/lib/datetime/client";
import {
  readDismissedAnnouncements,
  rememberDismissedAnnouncement
} from "@/lib/notifications/announcement-dismissed";
import { announcementHref, announcementText } from "@/lib/notifications/announcement-text";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import { cn } from "@/lib/utils";
import notificationService from "@/services/notification.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { AnnouncementLocaleText, NotificationItem } from "@/types/notification.types";

/** How long a resolved row says so before it leaves. */
const DONE_MS = 3500;
/** Urgent items hidden for this visit, by id. The items themselves stay in the bell. */
const HIDDEN_KEY = "owt-urgent-hidden-ids";
/** A check-in closing sooner than this counts down in red. */
const SOON_MS = 30 * 60_000;
/** Rows the tray shows before the rest folds into "N more": three from 640px, two on a phone. */
const TRAY_ROWS = 3;
const PHONE_ROWS = 2;

const CONTAINER_CLASS = cn(
  // Always mounted, even with nothing to show: the screen-reader status line
  // lives inside and `display:none` would silence it. Empty, it has no height.
  "pointer-events-none fixed inset-x-0 bottom-0 z-40 grid grid-cols-[minmax(0,1fr)]",
  // From 640 a card pinned under the header plate, over the page rather than in
  // its flow: nothing moves when it comes or goes. `z-[45]` keeps it above the
  // pages' own z-40 sticky tab bars that pin into the same strip, and under the
  // header and modals (z-50).
  "sm:bottom-auto sm:top-[calc(10px+var(--aqt-header-h)+8px)] sm:z-[45] sm:mx-auto sm:w-[min(680px,calc(100%-2rem))]"
);
const SURFACE_CLASS =
  "pointer-events-auto relative overflow-hidden border shadow-[0_18px_40px_-12px_rgb(0_0_0/0.65),0_2px_6px_rgb(0_0_0/0.3)] motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 sm:rounded-[14px] sm:shadow-[0_14px_30px_-14px_rgb(0_0_0/0.7)] motion-safe:sm:slide-in-from-top-2";
// A phone gets a sheet along the bottom edge, within thumb reach.
const TRAY_CLASS = cn(
  SURFACE_CLASS,
  "rounded-t-[20px] border-x-0 border-b-0 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)] pb-[env(safe-area-inset-bottom)] sm:border-x sm:border-b sm:pb-0"
);
const EVENT_CLASS = cn(
  SURFACE_CLASS,
  "mx-3 mb-[calc(12px+env(safe-area-inset-bottom))] grid grid-cols-[minmax(0,1fr)] gap-3 rounded-[14px] border-[color:color-mix(in_srgb,var(--aqt-teal)_28%,var(--aqt-border-2))] p-3.5 pr-11 sm:mx-0 sm:mb-0 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-center sm:gap-4"
);
const EVENT_BACKGROUND =
  "radial-gradient(70% 150% at 0% 0%, color-mix(in srgb, var(--aqt-teal) 13%, transparent), transparent 62%), var(--aqt-card-2)";
const ROW_CLASS =
  "relative grid grid-cols-[32px_minmax(0,1fr)] items-start gap-x-3 gap-y-2 py-2.5 pl-3 pr-11 sm:grid-cols-[32px_minmax(0,1fr)_auto] sm:items-center";
const CLOSE_CLASS =
  "absolute right-1.5 top-1.5 text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] sm:top-1/2 sm:-translate-y-1/2";

interface FloatStackProps {
  /** The layout's server-side read, so the announcement paints with the first frame. */
  initialAnnouncements: NotificationItem[] | undefined;
  /** Set on a white-label host: the stack then only speaks for that community. */
  tenantWorkspaceId: number | null;
  /** The release this browser has not seen, still within its card window; the layout's call, `null` on a tenant host. */
  release: Release | null;
}

type Row =
  | { key: string; type: "done"; action: ResolvedAction; name: string | null }
  | { key: string; type: "urgent"; item: NotificationItem }
  | { key: string; type: "announcement"; text: AnnouncementLocaleText; href: string | null }
  | { key: string; type: "release"; release: Release };

/**
 * The page's floating stack: what needs this person now, the operator's
 * announcement and the release news, as one tray of rows. Urgent rows come
 * first (check-in, then invites), then the announcement, then the release.
 * A release alone on the screen is an event card instead of a row.
 *
 * In the DOM right after the header, so a keyboard reader reaches an urgent
 * action before the page body rather than after the footer. Phones get a sheet
 * along the bottom edge, from 640px a card pinned under the header plate: both
 * float over the page and never push it down.
 */
export function FloatStack({ initialAnnouncements, tenantWorkspaceId, release }: Readonly<FloatStackProps>) {
  const t = useTranslations("notifications");
  const pathname = usePathname();
  const { user } = useAuthProfile();
  const authUserId = user?.id ?? null;
  const setBellOpen = useBellSignal((state) => state.setOpen);
  const [status, setStatus] = useState("");

  const announcement = useActiveAnnouncement(initialAnnouncements, authUserId);
  const urgent = useUrgentItems(authUserId, tenantWorkspaceId, setStatus);

  const onChangelog = pathname === "/changelog";
  const [releaseClosed, setReleaseClosed] = useState(false);
  const shownRelease = release && !releaseClosed && !onChangelog ? release : null;
  // Opening the page is reading the release.
  useEffect(() => {
    if (release && onChangelog) rememberReleaseSeen(release.version);
  }, [release, onChangelog]);

  const rows: Row[] = [];
  if (urgent.done) rows.push(urgent.done);
  for (const item of urgent.pending) rows.push({ key: `urgent-${item.id}`, type: "urgent", item });
  if (announcement) {
    rows.push({ key: `announcement-${announcement.id}`, type: "announcement", text: announcement.text, href: announcement.href });
  }
  const crowded = rows.length > 0;

  // Beside anything else the release is a row; alone, the event card. Once a
  // row on this page it stays one, so answering the check-in above it does not
  // make the stack jump. The next page decides afresh.
  const [rowOnPath, setRowOnPath] = useState<string | null>(null);
  if (shownRelease && crowded && rowOnPath !== pathname) setRowOnPath(pathname);
  const releaseAsEvent = shownRelease != null && !crowded && rowOnPath !== pathname;
  if (shownRelease && !releaseAsEvent) rows.push({ key: "release", type: "release", release: shownRelease });

  const closeRelease = () => {
    if (!shownRelease) return;
    setReleaseClosed(true);
    rememberReleaseSeen(shownRelease.version);
    focusContent();
  };

  // The release has no row in the bell, so it never counts towards "N more":
  // without room it simply waits for a later page.
  const listed = rows.filter((row) => row.type !== "release").length;
  const moreFromDesktop = Math.max(0, listed - TRAY_ROWS);
  const moreOnPhone = Math.max(0, listed - PHONE_ROWS);

  const renderRow = (row: Row) => {
    switch (row.type) {
      case "done":
        return <DoneRow action={row.action} name={row.name} />;
      case "urgent":
        return (
          <UrgentRow
            item={row.item}
            minute={urgent.minute}
            workspaceName={urgent.workspaces.find((workspace) => workspace.id === row.item.workspace_id)?.name ?? null}
            onResolved={(action) => urgent.resolve(row.item, action)}
            onHide={() => {
              urgent.hide(row.item.id);
              focusContent();
            }}
          />
        );
      case "announcement":
        return (
          <AnnouncementRow
            text={row.text}
            href={row.href}
            onDismiss={() => {
              announcement?.dismiss();
              focusContent();
            }}
          />
        );
      case "release":
        return <ReleaseRow release={row.release} onClose={closeRelease} />;
    }
  };

  return (
    <div className={CONTAINER_CLASS}>
      <Live message={status} />
      {releaseAsEvent && shownRelease ? (
        <ReleaseEvent release={shownRelease} onClose={closeRelease} />
      ) : rows.length > 0 ? (
        <section aria-label={t("floatStack.label")} className={TRAY_CLASS}>
          <ul className="divide-y divide-[color:var(--aqt-border)]">
            {rows.slice(0, TRAY_ROWS).map((row, index) => (
              <li key={row.key} className={cn(index >= PHONE_ROWS && "max-sm:hidden")}>
                {renderRow(row)}
              </li>
            ))}
          </ul>
          {moreOnPhone > 0 && <MoreRow count={moreOnPhone} onOpen={() => setBellOpen(true)} className="sm:hidden" />}
          {moreFromDesktop > 0 && (
            <MoreRow count={moreFromDesktop} onOpen={() => setBellOpen(true)} className="max-sm:hidden" />
          )}
        </section>
      ) : null}
    </div>
  );
}

/**
 * The operator's notice: the newest one this viewer has not closed. Dismissal is
 * a read mark plus this browser's cookie: `/announcements/active` is
 * auth-optional, so once the access cookie lapses the server answers as if
 * anonymous and every dismissed notice would come back.
 */
function useActiveAnnouncement(initial: NotificationItem[] | undefined, authUserId: number | null) {
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState<number[]>(() => readDismissedAnnouncements());

  const query = useQuery({
    queryKey: notificationQueryKeys.activeAnnouncements(),
    queryFn: () => notificationService.activeAnnouncements(),
    initialData: initial,
    // Nobody asked for this read: it runs on every page for every visitor,
    // including anonymous ones. A failure means no row, not an error toast
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
  // response: two notices would double the row count for one operator.
  const item = (query.data ?? [])
    .filter((candidate) => !candidate.is_read && !dismissed.includes(candidate.id))
    .reduce<NotificationItem | null>(
      (newest, candidate) => (newest && newest.published_at >= candidate.published_at ? newest : candidate),
      null
    );
  const text = item ? announcementText(item.payload, locale) : null;
  if (!item || !text?.title) return null;

  return {
    id: item.id,
    text,
    href: announcementHref(item.payload),
    dismiss: () => {
      // Hidden locally either way: the mutation's refetch takes a round trip,
      // and a row that lingers after its close button reads as broken.
      setDismissed((ids) => [...ids, item.id]);
      if (authUserId != null) markRead.mutate([item.id]);
      else rememberDismissedAnnouncement(item.id);
    }
  };
}

/**
 * What needs this person now: open check-ins first, then pending invites. On a
 * community's page (or its own host) only that community's items, elsewhere
 * anything.
 */
function useUrgentItems(
  authUserId: number | null,
  tenantWorkspaceId: number | null,
  announce: (message: string) => void
) {
  const t = useTranslations("notifications");
  const pathname = usePathname();
  const minute = useMinuteClock();
  const { items, markOneRead } = useNotifications(authUserId);
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const fetchWorkspaces = useWorkspaceStore((state) => state.fetchWorkspaces);
  // Read in the initializer: urgent rows never render on the server (the inbox
  // has no data there), so there is nothing for it to disagree with.
  const [hidden, setHidden] = useState(readHiddenIds);
  const [resolved, setResolved] = useState<{ id: number; action: ResolvedAction; name: string | null } | null>(null);

  useEffect(() => {
    if (authUserId != null && workspaces.length === 0) void fetchWorkspaces();
  }, [authUserId, workspaces.length, fetchWorkspaces]);

  // The confirmation holds its row for a few seconds, then the row leaves.
  useEffect(() => {
    if (!resolved) return;
    const timer = window.setTimeout(() => setResolved(null), DONE_MS);
    return () => window.clearTimeout(timer);
  }, [resolved]);

  const slug = pathname?.match(/^\/workspace\/([^/]+)/)?.[1];
  const scopeWorkspaceId =
    tenantWorkspaceId ?? (slug ? (workspaces.find((workspace) => workspace.slug === slug)?.id ?? null) : null);

  const pending = items
    .filter((item) => {
      if (!ACTIONABLE_RANK[item.kind] || item.is_read) return false;
      if (hidden.includes(item.id) || item.id === resolved?.id) return false;
      if (scopeWorkspaceId != null && item.workspace_id !== scopeWorkspaceId) return false;
      // A check-in whose window has closed is no longer an action, only history.
      // The minute clock, not `Date.now()`: reading the clock in render is impure,
      // and this way a lapsed row leaves on its own.
      const closesAt = item.payload.closes_at;
      if (item.kind === "check_in.opened" && typeof closesAt === "string" && minute != null) {
        return new Date(closesAt).getTime() > minute;
      }
      return true;
    })
    .sort((a, b) => ACTIONABLE_RANK[a.kind] - ACTIONABLE_RANK[b.kind]);

  return {
    pending,
    minute,
    done: resolved
      ? { key: `done-${resolved.id}`, type: "done" as const, action: resolved.action, name: resolved.name }
      : null,
    workspaces,
    hide: (id: number) => {
      const next = [...hidden, id];
      setHidden(next);
      try {
        window.sessionStorage.setItem(HIDDEN_KEY, next.join("."));
      } catch {
        // Storage blocked: hidden for this render, back on the next page load.
      }
      announce(t("urgent.hidden"));
    },
    resolve: (item: NotificationItem, action: ResolvedAction) => {
      const name = item.payload.tournament_name;
      setResolved({ id: item.id, action, name: typeof name === "string" ? name : null });
      announce(t(`actions.${action}`));
      markOneRead(item.id);
    }
  };
}

/** `sessionStorage`, not a cookie: "this visit" is exactly a tab session. */
function readHiddenIds(): number[] {
  try {
    const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem(HIDDEN_KEY);
    return raw ? raw.split(".").map(Number).filter((id) => Number.isSafeInteger(id) && id > 0) : [];
  } catch {
    // Storage blocked: rows stay hideable per page load.
    return [];
  }
}

/** A close button unmounts with its row: focus would drop to <body> and the next Tab restart at the top. */
function focusContent() {
  document.getElementById("main-content")?.focus({ preventScroll: true });
}

/** `"2.0.0"` reads as "2.0" in a sentence; the full tag stays on the chip. */
function shortVersion(version: string): string {
  return version.split(".").slice(0, 2).join(".");
}

function UrgentRow({
  item,
  minute,
  workspaceName,
  onResolved,
  onHide
}: Readonly<{
  item: NotificationItem;
  minute: number | null;
  workspaceName: string | null;
  onResolved: (action: ResolvedAction) => void;
  onHide: () => void;
}>) {
  const t = useTranslations("notifications");
  const format = useFormatter();
  const slotLabel = useOfferedSlotLabel(item);
  const [Icon, tone] = KIND_VISUAL[item.kind] ?? KIND_FALLBACK;
  const tournament = String(item.payload.tournament_name ?? "");
  const closesAt = item.payload.closes_at;
  const slotCode = item.payload.slot_code;

  const meta: ReactNode[] = [];
  if (workspaceName) meta.push(workspaceName);
  let bar: ReactNode = null;
  if (item.kind === "check_in.opened" && typeof closesAt === "string" && minute != null) {
    // Time left first: it is what decides whether to act now.
    const closes = new Date(closesAt);
    const left = closes.getTime() - minute;
    const soon = left < SOON_MS;
    meta.push(
      <span
        key="left"
        className={cn("font-medium", soon ? "text-[color:var(--aqt-rose-text)]" : "text-[color:var(--aqt-amber)]")}
      >
        {t("urgent.closesIn", { relative: format.relativeTime(closes, minute) })}
      </span>
    );
    const sameDay = format.dateTime(closes, { dateStyle: "short" }) === format.dateTime(minute, { dateStyle: "short" });
    meta.push(
      sameDay
        ? t("urgent.at", { time: format.dateTime(closes, { timeStyle: "short" }) })
        : format.dateTime(closes, { dateStyle: "medium", timeStyle: "short" })
    );
    // What is left of the window, from the moment it opened.
    const span = closes.getTime() - Date.parse(item.published_at);
    if (span > 0) {
      bar = (
        <span
          aria-hidden
          className="absolute bottom-0 left-0 h-0.5 rounded-r-full"
          style={{
            width: `${Math.min(1, Math.max(0, left / span)) * 100}%`,
            background: soon ? "var(--aqt-rose)" : "var(--aqt-amber)"
          }}
        />
      );
    }
  } else if (typeof slotCode === "string") {
    // An unknown code from a newer server renders as itself: the label is
    // decoration, the slot is the offer.
    meta.push(t("urgent.slot", { slot: slotLabel(slotCode) }));
  }

  return (
    <div
      className={ROW_CLASS}
      style={{ background: `linear-gradient(90deg, color-mix(in srgb, ${tone} 9%, transparent), transparent 62%)` }}
    >
      <Tile tone={tone}>
        <Icon className="size-4" />
      </Tile>
      <RowText
        title={
          item.kind === "check_in.opened"
            ? t("urgent.checkIn", { tournament })
            : t("urgent.invite", { team: String(item.payload.team_name ?? ""), tournament })
        }
        meta={meta.length > 0 ? meta.flatMap((part, index) => (index > 0 ? [" · ", part] : [part])) : null}
      />
      <div className="col-start-2 flex flex-wrap items-center gap-2 sm:col-start-3 sm:row-start-1 sm:flex-nowrap">
        <NotificationActions item={item} done={null} onResolved={onResolved} />
      </div>
      <CloseButton label={t("urgent.hide")} title={t("urgent.hideTitle")} onClick={onHide} />
      {bar}
    </div>
  );
}

/**
 * An invite names a slot of the TOURNAMENT's own game: its scoped ontology
 * localizes it (the notification carries no game of its own), and a code that
 * dictionary does not know renders as itself.
 */
function useOfferedSlotLabel(item: NotificationItem) {
  const tournamentId =
    typeof item.payload.slot_code === "string" && typeof item.payload.tournament_id === "number"
      ? item.payload.tournament_id
      : null;
  const tournament = useTournamentQuery(tournamentId === null ? "" : String(tournamentId)).data;
  const ontology = useDisciplineMetadata(tournament?.workspace_id ?? "all", tournament?.discipline ?? null).data;
  return useSlotLabel(ontology ?? null);
}

function AnnouncementRow({
  text,
  href,
  onDismiss
}: Readonly<{ text: AnnouncementLocaleText; href: string | null; onDismiss: () => void }>) {
  const t = useTranslations("notifications.banner");
  const [Icon, tone] = KIND_VISUAL["announcement.published"] ?? KIND_FALLBACK;
  return (
    <div className={ROW_CLASS}>
      <Tile tone={tone}>
        <Icon className="size-4" />
      </Tile>
      {/* The operator's text, cut at two lines: the form says so beside the field. */}
      <RowText title={text.title} meta={text.body || null} clamp />
      {href ? (
        <div className="col-start-2 sm:col-start-3 sm:row-start-1">
          <Button asChild variant="outline" size="sm">
            <Link href={href} prefetch={false}>
              {t("more")}
            </Link>
          </Button>
        </div>
      ) : null}
      <CloseButton label={t("dismiss")} onClick={onDismiss} />
    </div>
  );
}

function ReleaseRow({ release, onClose }: Readonly<{ release: Release; onClose: () => void }>) {
  const t = useTranslations("notifications.release");
  return (
    <div className="relative grid grid-cols-[32px_minmax(0,1fr)_auto] items-center gap-x-3 py-2.5 pl-3 pr-11">
      <Tile tone="var(--aqt-teal)">
        <Sparkles className="size-4" />
      </Tile>
      <p className="min-w-0 truncate text-body font-semibold text-[color:var(--aqt-fg)]">
        {t("kicker", { version: shortVersion(release.version) })}
      </p>
      <Button asChild variant="link" size="inline" className="font-semibold">
        <Link href={`/changelog#v${release.version}`} prefetch={false}>
          {t("cta")}
        </Link>
      </Button>
      <CloseButton label={t("hide")} onClick={onClose} className="top-1/2 -translate-y-1/2" />
    </div>
  );
}

/** The release alone on the screen: the games it brings, its headline and a way to read it. */
function ReleaseEvent({ release, onClose }: Readonly<{ release: Release; onClose: () => void }>) {
  const t = useTranslations("notifications.release");
  const locale = useLocale();
  const games = useGameDescriptors();
  const marks = (release.games ?? []).flatMap((code) => {
    const game = games.get(code);
    return game ? [game] : [];
  });

  return (
    <section aria-label={t("label")} className={EVENT_CLASS} style={{ background: EVENT_BACKGROUND }}>
      {marks.length > 0 ? (
        <span aria-hidden className="grid w-fit grid-cols-[repeat(4,26px)] gap-1.5 sm:grid-cols-[repeat(2,28px)]">
          {marks.map((game) => (
            <span
              key={game.code}
              className="inline-flex size-[26px] items-center justify-center rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] sm:size-7"
            >
              <GameMark discipline={game} size={16} decorative />
            </span>
          ))}
        </span>
      ) : (
        <Tile tone="var(--aqt-teal)">
          <Sparkles className="size-4" />
        </Tile>
      )}
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-caption font-semibold text-[color:var(--aqt-teal)]">
          {t("kicker", { version: shortVersion(release.version) })}
          <span className="rounded-[5px] border border-[color:var(--aqt-border-2)] px-1.5 py-px text-label tabular-nums text-[color:var(--aqt-fg-dim)]">
            v{release.version}
          </span>
        </p>
        <p className="mt-1 text-pretty font-display text-ui font-bold leading-snug text-[color:var(--aqt-fg)]">
          {release.title[locale === "en" ? "en" : "ru"]}
        </p>
      </div>
      <Button asChild size="sm" className="max-sm:w-full">
        <Link href={`/changelog#v${release.version}`} prefetch={false}>
          {t("cta")}
          <ArrowRight aria-hidden />
        </Link>
      </Button>
      <CloseButton label={t("hide")} onClick={onClose} />
    </section>
  );
}

function DoneRow({ action, name }: Readonly<{ action: ResolvedAction; name: string | null }>) {
  const t = useTranslations("notifications.actions");
  return (
    <div
      className="relative grid grid-cols-[32px_minmax(0,1fr)] items-center gap-x-3 py-2.5 pl-3 pr-3.5"
      style={{
        background: "linear-gradient(90deg, color-mix(in srgb, var(--aqt-emerald) 9%, transparent), transparent 62%)"
      }}
    >
      <Tile tone="var(--aqt-emerald)">
        <CircleCheck className="size-4" />
      </Tile>
      <p className="text-body text-[color:var(--aqt-fg-muted)]">
        {t(action)}
        {name ? (
          <>
            {": "}
            <b className="font-semibold text-[color:var(--aqt-fg)]">{name}</b>
          </>
        ) : null}
      </p>
    </div>
  );
}

function MoreRow({ count, onOpen, className }: Readonly<{ count: number; onOpen: () => void; className: string }>) {
  const t = useTranslations("notifications.floatStack");
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onOpen}
      className={cn(
        "h-9 w-full rounded-none border-t border-[color:var(--aqt-border)] font-medium text-[color:var(--aqt-fg-muted)]",
        className
      )}
    >
      {t("more", { count })}
      <ArrowRight aria-hidden />
    </Button>
  );
}

function Tile({ tone, children }: Readonly<{ tone: string; children: ReactNode }>) {
  return (
    <span
      aria-hidden
      className="inline-flex size-8 items-center justify-center rounded-[9px]"
      style={{ color: tone, background: `color-mix(in srgb, ${tone} 14%, transparent)` }}
    >
      {children}
    </span>
  );
}

function RowText({ title, meta, clamp = false }: Readonly<{ title: ReactNode; meta: ReactNode; clamp?: boolean }>) {
  return (
    <p className="min-w-0 text-body">
      <b className="block text-pretty font-semibold text-[color:var(--aqt-fg)]">{title}</b>
      {meta ? (
        <span className={cn("mt-0.5 block text-caption text-[color:var(--aqt-fg-dim)]", clamp && "line-clamp-2")}>
          {meta}
        </span>
      ) : null}
    </p>
  );
}

function CloseButton({
  label,
  title,
  onClick,
  className
}: Readonly<{ label: string; title?: string; onClick: () => void; className?: string }>) {
  return (
    <Button variant="ghost" size="icon-sm" className={cn(CLOSE_CLASS, className)} title={title} onClick={onClick}>
      <X aria-hidden />
      <span className="sr-only">{label}</span>
    </Button>
  );
}

function Live({ message }: Readonly<{ message: string }>) {
  return (
    <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </p>
  );
}
