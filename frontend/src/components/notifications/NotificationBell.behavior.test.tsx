// @vitest-environment happy-dom
//
// The bell is the only surface an in-app notification exists on: nothing else
// tells a user that an invite arrived, that their registration was decided or
// that a report they filed is disputed. So these tests pin the four claims that
// make it a working inbox rather than an icon — the unread count is *announced*,
// the realtime signal actually refetches, "mark all read" clears the badge, and
// an anonymous visitor gets nothing at all — plus the one message that cannot be
// written as a plain interpolation: a disputed report with no pick-ban session
// carries `map_index: 0`, and "map 0" is not a thing that exists.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import type { NotificationInbox, NotificationItem } from "@/types/notification.types";

import NotificationBell from "./NotificationBell";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const list = vi.fn();
const markRead = vi.fn();
const remove = vi.fn();
let authUser: unknown = { id: 1, username: "alice" };
const mounted: { root: Root; client: QueryClient }[] = [];

// Topic -> the invalidation consumer's callbacks, so a test can fire the push
// the server would send. Mocked one level below `useInvalidation` (its own test
// covers the coalescing timings), leaving the resource vocabulary real.
type InvalidationConsumer = {
  onEvent: (event: { data?: { resources?: string[] } }, schedule: () => void) => void;
  onFlush: () => void;
};
const realtimeHandlers = new Map<string, InvalidationConsumer>();

vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({ status: authUser ? "authenticated" : "anonymous", user: authUser })
}));
vi.mock("@/hooks/useRealtimeCoalescedRefetch", () => ({
  useRealtimeCoalescedRefetch: (topic: string | null | undefined, options: InvalidationConsumer) => {
    if (topic) realtimeHandlers.set(topic, options);
  }
}));
vi.mock("@/services/notification.service", () => ({
  default: {
    list: (...args: unknown[]) => list(...args),
    markRead: (...args: unknown[]) => markRead(...args),
    remove: (...args: unknown[]) => remove(...args)
  }
}));

const MESSAGES = { en, ru } as const;

const PUBLISHED = "2026-09-07T10:00:00Z";

function item(
  overrides: Partial<NotificationItem> & Pick<NotificationItem, "id" | "kind">
): NotificationItem {
  return {
    audience: "user",
    payload: {},
    workspace_id: null,
    published_at: PUBLISHED,
    expires_at: null,
    is_read: false,
    ...overrides
  } as NotificationItem;
}

const INVITE = item({
  id: 11,
  kind: "team_invite.received",
  payload: {
    team_id: 7,
    team_name: "Alpha",
    tournament_id: 5,
    tournament_name: "Autumn Cup",
    slot_code: "dps",
    is_substitute: false,
    invite_id: 42
  }
});

const DISPUTED_WITH_MAP = item({
  id: 12,
  kind: "encounter.report_disputed",
  payload: { encounter_id: 9, tournament_id: 5, map_id: 3, map_index: 2 }
});

// The encounter had no pick-ban session, so there is no map ordinal at all.
const DISPUTED_NO_MAP = item({
  id: 13,
  kind: "encounter.report_disputed",
  payload: { encounter_id: 9, tournament_id: 5, map_id: 0, map_index: 0 }
});

// The one kind whose text is operator-written, and the one that carries a link.
const ANNOUNCEMENT = item({
  id: 14,
  kind: "announcement.published",
  audience: "global",
  payload: {
    default_locale: "en",
    href: "/changelog",
    locales: { en: { title: "Maintenance window" } }
  }
});

function inbox(items: NotificationItem[], unreadCount = items.length): NotificationInbox {
  return { items, unread_count: unreadCount, next_cursor: null };
}

async function flush(): Promise<void> {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

/** The push the server would send on the signed-in user's invalidation topic. */
function fireInvalidation(resources: string[] = ["user.notifications"]): void {
  const consumer = realtimeHandlers.get("user:1:invalidation");
  if (!consumer) throw new Error("the bell did not subscribe to the caller's own topic");
  consumer.onEvent({ data: { resources } }, () => {});
  consumer.onFlush();
}

async function mount(locale: "en" | "ru" = "en"): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  mounted.push({ root, client });

  await act(async () => {
    root.render(
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
        <QueryClientProvider client={client}>
          <NotificationBell />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await flush();
  return container;
}

function click(element: Element): Promise<void> {
  return act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

/** The popover is portalled to `document.body`, not into the mount container. */
function openPanel(): Promise<void> {
  const trigger = document.body.querySelector("button");
  if (!trigger) throw new Error("the bell rendered no trigger");
  return click(trigger);
}

function buttonNamed(name: string): HTMLButtonElement {
  const button = [...document.body.querySelectorAll("button")].find(
    (candidate) => candidate.textContent?.trim() === name
  );
  if (!button) throw new Error(`Missing button: ${name}`);
  return button;
}

afterEach(async () => {
  await act(async () => {
    for (const { root, client } of mounted.splice(0)) {
      root.unmount();
      client.clear();
    }
  });
  document.body.innerHTML = "";
});

beforeEach(() => {
  authUser = { id: 1, username: "alice" };
  realtimeHandlers.clear();
  list.mockReset().mockResolvedValue(inbox([INVITE, DISPUTED_WITH_MAP]));
  markRead.mockReset().mockResolvedValue({ marked: 2, unread_count: 0 });
  remove.mockReset().mockResolvedValue({ deleted: 1, unread_count: 1 });
  document.body.innerHTML = "";
});

describe("notification bell", () => {
  it("announces the unread count instead of only colouring a dot", async () => {
    const container = await mount();
    const trigger = container.querySelector("button");

    expect(trigger).not.toBeNull();
    // The number is in the accessible name: a badge a screen reader cannot
    // reach is the same as no badge at all.
    expect(trigger?.getAttribute("aria-label")).toContain("2");
    expect(container.textContent).toContain("2");
  });

  it("caps the visual badge without losing the accessible count", async () => {
    list.mockResolvedValue(inbox([INVITE], 120));
    const container = await mount();
    expect(container.querySelector("button")?.getAttribute("aria-label")).toContain("120");
    expect(container.textContent).toContain("99+");
  });

  it("does not claim an empty or all-read inbox before loading, and recovers from an initial error", async () => {
    const request = Promise.withResolvers<NotificationInbox>();
    list.mockReturnValueOnce(request.promise);
    const container = await mount();
    await openPanel();
    expect(container.querySelector("button")?.getAttribute("aria-label")).toBe(
      en.notifications.title
    );
    expect(document.body.textContent).not.toContain(en.notifications.empty);
    expect(document.body.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(buttonNamed(en.notifications.markAllRead).getAttribute("aria-disabled")).toBe("true");

    await act(async () => request.reject(new Error("offline")));
    await flush();
    expect(document.body.textContent).toContain(en.notifications.loadError);
    expect(document.body.textContent).not.toContain(en.notifications.empty);
    expect(container.querySelector("button")?.getAttribute("aria-label")).toBe(
      en.notifications.title
    );

    list.mockResolvedValue(inbox([], 0));
    await click(buttonNamed(en.notifications.retry));
    await flush();
    expect(document.body.textContent).toContain(en.notifications.empty);
    expect(document.body.textContent).not.toContain(en.notifications.loadError);
  });

  it("retains cached rows when a refresh fails and retries without replacing them with empty state", async () => {
    await mount();
    await openPanel();
    list.mockRejectedValue(new Error("offline"));
    await act(async () => fireInvalidation());
    await flush();
    expect(document.body.textContent).toContain("Alpha");
    expect(document.body.textContent).toContain(en.notifications.refreshError);
    expect(document.body.textContent).not.toContain(en.notifications.empty);

    list.mockResolvedValue(inbox([INVITE, DISPUTED_WITH_MAP, DISPUTED_NO_MAP]));
    await click(buttonNamed(en.notifications.retry));
    await flush();
    expect(document.body.querySelectorAll("li")).toHaveLength(3);
    expect(document.body.textContent).not.toContain(en.notifications.refreshError);
  });

  it("refetches when its own inbox is named stale, and ignores an event that names something else", async () => {
    await mount();

    expect(list).toHaveBeenCalledTimes(1);
    list.mockResolvedValue(inbox([INVITE, DISPUTED_WITH_MAP, DISPUTED_NO_MAP]));

    await act(async () => fireInvalidation(["workspace.logs"]));
    await flush();
    expect(list).toHaveBeenCalledTimes(1);

    await act(async () => fireInvalidation());
    await flush();
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("renders each row from its kind and payload, never from server text", async () => {
    list.mockResolvedValue(inbox([INVITE]));
    await mount();
    await openPanel();
    await flush();

    const panel = document.body.textContent ?? "";
    expect(panel).toContain("Alpha");
    expect(panel).toContain("Autumn Cup");
    // A raw key path here means the kind has no message in this dictionary.
    expect(panel).not.toContain("notifications.kinds");
  });

  it("does not invent a map number for a dispute with no pick-ban session", async () => {
    list.mockResolvedValue(inbox([DISPUTED_WITH_MAP, DISPUTED_NO_MAP]));
    await mount();
    await openPanel();
    await flush();

    const panel = document.body.textContent ?? "";
    // The ordinal is rendered when there is one...
    expect(panel).toContain("map 2");
    // ...and the zero row falls back to a form with no ordinal at all, rather
    // than claiming a "map 0" the encounter never had.
    expect(panel).toContain("A report in your match is disputed");
    expect(panel).not.toMatch(/\bmap\s*(#\s*)?0\b/i);
  });

  it("does not invent a map number in Russian either", async () => {
    list.mockResolvedValue(inbox([DISPUTED_NO_MAP]));
    await mount("ru");
    await openPanel();
    await flush();

    const panel = document.body.textContent ?? "";
    expect(panel).not.toContain("notifications.kinds");
    expect(panel).toContain("Отчёт по вашему матчу оспорен");
    expect(panel).not.toMatch(/карт\S*\s*0\b/i);
  });

  it("keeps mark-all pending through refetch and only then clears the badge and announces success", async () => {
    const container = await mount();
    await openPanel();
    const markAll = buttonNamed(en.notifications.markAllRead);
    const refresh = Promise.withResolvers<NotificationInbox>();
    list.mockReturnValueOnce(refresh.promise);
    await click(markAll);
    await flush();
    expect(markRead).toHaveBeenCalledWith(undefined);
    expect(markAll.getAttribute("aria-busy")).toBe("true");
    expect(document.body.textContent).not.toContain(en.notifications.markedAllRead);
    expect(container.querySelector("button")?.getAttribute("aria-label")).toContain("2");

    await act(async () => refresh.resolve(inbox([{ ...INVITE, is_read: true }], 0)));
    await flush();
    expect(markAll.isConnected).toBe(true);
    expect(markAll.getAttribute("aria-busy")).toBe("false");
    expect(container.querySelector("button")?.getAttribute("aria-label")).not.toContain("2");
    expect(document.body.querySelector('[role="status"]')?.textContent).toContain(
      en.notifications.markedAllRead
    );
  });

  it("marks only the chosen row and retains its focused control on completion", async () => {
    await mount();
    await openPanel();
    const markOne = [...document.body.querySelectorAll("button")].find((button) =>
      button.getAttribute("aria-label")?.includes("Alpha")
    )!;
    markOne.focus();
    list.mockResolvedValue(inbox([{ ...INVITE, is_read: true }, DISPUTED_WITH_MAP], 1));
    await click(markOne);
    await flush();
    expect(markRead).toHaveBeenCalledWith([INVITE.id]);
    expect(document.activeElement).toBe(markOne);
    expect(markOne.isConnected).toBe(true);
    expect(markOne.getAttribute("aria-disabled")).toBe("true");
    expect(buttonNamed(en.notifications.markRead).getAttribute("aria-disabled")).toBe("false");
    expect(document.body.textContent).toContain(en.notifications.markedRead);
  });

  it("keeps read failures in the panel and retries the same row without claiming success", async () => {
    await mount();
    await openPanel();
    markRead.mockRejectedValueOnce(new Error("offline"));
    const markOne = [...document.body.querySelectorAll("button")].find((button) =>
      button.getAttribute("aria-label")?.includes("Alpha")
    )!;
    await click(markOne);
    await flush();
    expect(document.body.textContent).toContain(en.notifications.markReadError);
    expect(document.body.textContent).not.toContain(en.notifications.markedRead);
    expect(markOne.getAttribute("aria-disabled")).toBe("false");

    list.mockResolvedValue(inbox([{ ...INVITE, is_read: true }, DISPUTED_WITH_MAP], 1));
    await click(buttonNamed(en.notifications.retryMarkRead));
    await flush();
    expect(markRead).toHaveBeenLastCalledWith([INVITE.id]);
    expect(document.body.textContent).not.toContain(en.notifications.markReadError);
    expect(document.body.textContent).toContain(en.notifications.markedRead);
  });

  it("does not announce mark success if the following inbox refresh fails", async () => {
    await mount();
    await openPanel();
    list.mockRejectedValue(new Error("offline"));
    await click(buttonNamed(en.notifications.markAllRead));
    await flush();
    expect(document.body.textContent).toContain(en.notifications.markReadError);
    expect(document.body.textContent).not.toContain(en.notifications.markedAllRead);
    expect(document.body.textContent).toContain("Alpha");
  });

  it("reaches the page behind the cursor instead of stopping at the newest 20", async () => {
    list.mockReset();
    list.mockResolvedValueOnce({ items: [INVITE], unread_count: 21, next_cursor: "cursor-1" });
    list.mockResolvedValueOnce({ items: [DISPUTED_NO_MAP], unread_count: 21, next_cursor: null });

    await mount();
    await openPanel();
    await flush();

    const older = [...document.body.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === en.notifications.loadMore
    );
    expect(older, "no control for the page the cursor points at").not.toBeUndefined();

    await click(older!);
    await flush();

    expect(list).toHaveBeenLastCalledWith({ cursor: "cursor-1" });
    // Both pages are on screen, newest first, and neither replaced the other.
    const panel = document.body.textContent ?? "";
    expect(panel).toContain("Alpha");
    expect(panel).toContain("A report in your match is disputed");
    // Last page: nothing left to ask the server for.
    expect(
      [...document.body.querySelectorAll("button")].some(
        (button) => button.textContent?.trim() === en.notifications.loadMore
      )
    ).toBe(false);
  });

  it("retries a failed older page at the same cursor and blocks duplicate in-flight loads", async () => {
    list.mockResolvedValueOnce({ items: [INVITE], unread_count: 21, next_cursor: "cursor-1" });
    list.mockRejectedValueOnce(new Error("offline"));
    await mount();
    await openPanel();
    await click(buttonNamed(en.notifications.loadMore));
    await flush();
    expect(document.body.textContent).toContain(en.notifications.loadMoreError);
    expect(document.body.textContent).not.toContain(en.notifications.refreshError);
    expect(document.body.textContent).toContain("Alpha");

    const nextPage = Promise.withResolvers<NotificationInbox>();
    list.mockReturnValueOnce(nextPage.promise);
    const retry = buttonNamed(en.notifications.retryLoadMore);
    await click(retry);
    await flush();
    await click(retry);
    expect(list).toHaveBeenCalledTimes(3);
    expect(list).toHaveBeenLastCalledWith({ cursor: "cursor-1" });
    expect(retry.disabled).toBe(true);
    await act(async () => nextPage.resolve(inbox([DISPUTED_NO_MAP], 21)));
    await flush();
    expect(document.body.querySelectorAll("li")).toHaveLength(2);
    expect(document.body.textContent).not.toContain(en.notifications.loadMoreError);
    expect(document.body.textContent).not.toContain(en.notifications.loadMore);
  });

  it("navigates without implicitly marking an announcement read", async () => {
    list.mockResolvedValue(inbox([ANNOUNCEMENT]));
    await mount();
    await openPanel();
    const link = document.body.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("/changelog");
    await click(link);
    await flush();
    expect(markRead).not.toHaveBeenCalled();
  });

  it("uses localized friendly text rather than an unknown wire kind", async () => {
    list.mockResolvedValue(inbox([item({ id: 91, kind: "future.private_event" })]));
    await mount("ru");
    await openPanel();
    expect(document.body.textContent).toContain(ru.notifications.unknownKind);
    expect(document.body.textContent).not.toContain("future.private_event");
    expect(document.body.textContent).not.toContain("notifications.kinds");
  });

  it("links an announcement row to its href", async () => {
    list.mockResolvedValue(inbox([ANNOUNCEMENT]));
    await mount();
    await openPanel();
    await flush();

    const link = document.body.querySelector("a");
    expect(link?.getAttribute("href")).toBe("/changelog");
    expect(link?.textContent).toContain("Maintenance window");
  });

  it("drops the anchor of an announcement whose href is not a safe target", async () => {
    // A `javascript:` payload on a row every recipient opens is stored XSS —
    // the row keeps its text and loses the anchor.
    list.mockResolvedValue(
      inbox([
        item({ ...ANNOUNCEMENT, payload: { ...ANNOUNCEMENT.payload, href: "javascript:alert(1)" } })
      ])
    );
    await mount();
    await openPanel();
    await flush();

    expect(document.body.querySelector("a")).toBeNull();
    expect(document.body.textContent).toContain("Maintenance window");
  });

  it("deletes the chosen row and shows the inbox without it", async () => {
    await mount();
    await openPanel();
    const deleteOne = [...document.body.querySelectorAll("button")].find(
      (button) =>
        button.getAttribute("aria-label")?.includes("Delete notification") &&
        button.getAttribute("aria-label")?.includes("Alpha")
    )!;
    expect(deleteOne, "no per-row delete control").not.toBeUndefined();

    list.mockResolvedValue(inbox([DISPUTED_WITH_MAP], 1));
    await click(deleteOne);
    await flush();

    expect(remove).toHaveBeenCalledWith({ ids: [INVITE.id] });
    // The list is refetched, not patched: what the panel shows is what the
    // server says is left.
    expect(document.body.textContent).not.toContain("Alpha");
    expect(document.body.textContent).toContain(en.notifications.deleted);
  });

  it("offers 'clear read' only while a read row is on screen, and never sends the unread ones", async () => {
    await mount();
    await openPanel();
    // Everything unread: the button would delete nothing, so it is unavailable
    // rather than a request that reports "deleted: 0".
    expect(buttonNamed(en.notifications.clearRead).getAttribute("aria-disabled")).toBe("true");

    list.mockResolvedValue(inbox([{ ...INVITE, is_read: true }, DISPUTED_WITH_MAP], 1));
    await act(async () => fireInvalidation());
    await flush();

    const clear = buttonNamed(en.notifications.clearRead);
    expect(clear.getAttribute("aria-disabled")).toBe("false");
    list.mockResolvedValue(inbox([DISPUTED_WITH_MAP], 1));
    await click(clear);
    await flush();

    // `only_read`, never an id list assembled on the client: the server decides
    // which rows are read, and the page on screen is not the whole inbox.
    expect(remove).toHaveBeenCalledWith({ onlyRead: true });
    expect(document.body.textContent).toContain(en.notifications.clearedRead);
    expect(document.body.textContent).not.toContain("Alpha");
  });

  it("keeps a failed delete visible and retries the same target", async () => {
    await mount();
    await openPanel();
    remove.mockRejectedValueOnce(new Error("offline"));
    const deleteOne = [...document.body.querySelectorAll("button")].find(
      (button) =>
        button.getAttribute("aria-label")?.includes("Delete notification") &&
        button.getAttribute("aria-label")?.includes("Alpha")
    )!;

    await click(deleteOne);
    await flush();
    expect(document.body.textContent).toContain(en.notifications.deleteError);
    expect(document.body.textContent).toContain("Alpha");

    list.mockResolvedValue(inbox([DISPUTED_WITH_MAP], 1));
    await click(buttonNamed(en.notifications.retryDelete));
    await flush();
    expect(remove).toHaveBeenLastCalledWith({ ids: [INVITE.id] });
    expect(document.body.textContent).not.toContain(en.notifications.deleteError);
    expect(document.body.textContent).toContain(en.notifications.deleted);
  });

  it("renders nothing for an anonymous visitor", async () => {
    authUser = undefined;

    const container = await mount();

    expect(container.textContent).toBe("");
    expect(list).not.toHaveBeenCalled();
    // No identity, no topic: `user:undefined:notifications` would be a
    // subscription the gateway ACL rejects on every reconnect.
    expect([...realtimeHandlers.keys()]).toEqual([]);
  });
});
