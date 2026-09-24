// @vitest-environment happy-dom
//
// The operator screen for announcements. What is pinned here is the half the
// server cannot teach the operator in time:
//
//  1. the audience selector offers `global` only to a superuser — the RPC gates
//     a platform-wide announcement on the platform principal, so offering the
//     option to a workspace owner would be a button that guarantees a 403;
//  2. a platform-wide announcement with an empty English title never leaves the
//     browser. The server rejects it too (422), but a 422 toast is a worse way
//     to learn "this one needs both languages" than the form saying so;
//  3. a workspace announcement in one language does submit, and the body it
//     sends is the flat shape the RPC schema accepts (`extra="forbid"`);
//  4. the fallback-locale choice offers exactly the locales that have a title,
//     which is what makes rule (2)'s sibling rule — "default_locale must be
//     among the filled ones" — unreachable rather than merely validated.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import en from "@/i18n/messages/en.json";
import type { NotificationItem } from "@/types/notification.types";

import AdminAnnouncementsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listAnnouncements = vi.fn();
const createAnnouncement = vi.fn();
const retireAnnouncement = vi.fn();

let superuser = false;
let permitted = true;
let workspaceId: number | null = 7;

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: () => permitted,
    isLoaded: true,
    isSuperuser: superuser
  })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number | null }) => unknown) =>
    selector({ currentWorkspaceId: workspaceId })
}));
vi.mock("@/services/notification.service", () => ({
  default: {
    listAnnouncements: (...args: unknown[]) => listAnnouncements(...args),
    createAnnouncement: (...args: unknown[]) => createAnnouncement(...args),
    retireAnnouncement: (...args: unknown[]) => retireAnnouncement(...args)
  }
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/announcements",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

function row(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 91,
    audience: "workspace",
    kind: "announcement.published",
    payload: {
      locales: { ru: { title: "Ремонт" }, en: { title: "Maintenance" } },
      default_locale: "en"
    },
    workspace_id: 7,
    published_at: "2026-09-01T10:00:00Z",
    expires_at: null,
    is_read: false,
    ...overrides
  };
}

const mounted: Root[] = [];

async function settle(turns = 6) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(search = ""): Promise<HTMLElement> {
  window.history.replaceState(null, "", `/admin/announcements${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push(root);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          {/* `AdminLayoutClient` mounts one around every admin screen; the
              table's `StatusIcon` renders a Radix tooltip and throws without it. */}
          <TooltipProvider>
            <AdminAnnouncementsPage />
          </TooltipProvider>
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
  return container;
}

function field(scope: HTMLElement, name: string): HTMLElement {
  const element = scope.querySelector<HTMLElement>(`[data-field="${name}"]`);
  if (!element) throw new Error(`no [data-field="${name}"] on screen`);
  return element;
}

// The segments are read by their label rather than by a value attribute (the
// house `ToggleGroupItem` renders none), and the expectations name the same
// dictionary entry the UI does — the claim is which options exist and in what
// order, not how they are worded this week.
const LABEL = en.notifications.admin;

function options(scope: HTMLElement, name: string): string[] {
  return [...field(scope, name).querySelectorAll("[role='radio']")].map(
    (item) => (item.textContent ?? "").trim()
  );
}

/** The scope tabs are `LinkTabs` links, not segments — read as rendered. */
function scopeTabs(scope: HTMLElement): string[] {
  return [...field(scope, "audience").querySelectorAll("a[data-link-tab]")].map(
    (item) => (item.textContent ?? "").trim()
  );
}

/** Types into a controlled input the way React hears it. */
async function type(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto =
    input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    // Radix picks a segment up on mousedown; a plain click alone never selects.
    element?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle(2);
}

/**
 * The composer is an `EntityFormDialog`, so its fields live in a portal on
 * `document.body` rather than inside the page's container — every helper below
 * takes the scope it works in rather than assuming the page's own subtree.
 */
async function openComposer(container: HTMLElement): Promise<HTMLElement> {
  await click(field(container, "compose"));
  const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
  if (!dialog) throw new Error("the composer did not open");
  return dialog;
}

async function fillTitle(scope: HTMLElement, locale: "ru" | "en", title: string) {
  const tab = field(scope, `locale-tab-${locale}`);
  await click(tab);
  const input = scope.querySelector<HTMLInputElement>(`[data-field="title-${locale}"]`);
  if (!input) throw new Error(`no title input for ${locale}`);
  await type(input, title);
}

// `await act(...)`, never `act(...).then(...)`: React's act thenable has to be
// awaited to close its scope, and a chained `.then` leaves it open — after
// which every later render in the FILE is queued and never flushed, so the next
// test's screen comes up blank with no error anywhere.
async function submit(scope: HTMLElement): Promise<void> {
  const button = [...scope.querySelectorAll<HTMLButtonElement>('button[type="submit"]')].at(0);
  if (!button) throw new Error("no publish button on screen");
  await act(async () => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle(3);
}

beforeEach(() => {
  superuser = false;
  permitted = true;
  workspaceId = 7;
  listAnnouncements.mockReset().mockResolvedValue([row()]);
  createAnnouncement.mockReset().mockResolvedValue(row({ id: 92 }));
  retireAnnouncement.mockReset().mockResolvedValue(undefined);
});

// Unmount, awaited, and nothing else: emptying `document.body` by hand while a
// root still owns a node in it leaves React reconciling against a tree that is
// no longer there, and the NEXT test's mount comes up blank. `unmount` already
// empties the container it owns.
afterEach(async () => {
  for (const root of mounted.splice(0)) {
    await act(async () => root.unmount());
  }
});

describe("/admin/announcements", () => {
  it("offers the platform-wide audience only to a superuser", async () => {
    const workspaceOwner = await mount();
    expect(scopeTabs(workspaceOwner)).toEqual([LABEL.audience.workspace]);

    superuser = true;
    const platformAdmin = await mount();
    expect(scopeTabs(platformAdmin)).toEqual([LABEL.audience.workspace, LABEL.audience.global]);
  });

  it("keeps the scope in the URL, so a platform-wide feed is linkable", async () => {
    superuser = true;
    const container = await mount("?scope=global");

    const active = field(container, "audience").querySelector('a[aria-current="page"]');
    expect((active?.textContent ?? "").trim()).toBe(LABEL.audience.global);
    // The platform feed is not a workspace's: the list must be asked for the
    // global scope, not for workspace 7's rows.
    expect(listAnnouncements).toHaveBeenLastCalledWith({ workspaceId: null });
  });

  it("blocks a platform-wide announcement whose English title is empty", async () => {
    superuser = true;
    const container = await mount("?scope=global");

    const dialog = await openComposer(container);
    await fillTitle(dialog, "ru", "Технические работы");
    await submit(dialog);

    expect(createAnnouncement).not.toHaveBeenCalled();
    expect(dialog.querySelector('[role="alert"]')?.textContent ?? "").toContain("English");
  });

  it("publishes a workspace announcement written in one language", async () => {
    const container = await mount();
    const dialog = await openComposer(container);
    await fillTitle(dialog, "ru", "Турнир перенесён");
    await submit(dialog);

    expect(createAnnouncement).toHaveBeenCalledTimes(1);
    expect(createAnnouncement.mock.calls[0][0]).toMatchObject({
      audience: "workspace",
      workspace_id: 7,
      locales: { ru: { title: "Турнир перенесён" } },
      default_locale: "ru"
    });
    // `en` was never typed into, so it must not ride along as an empty title —
    // the payload schema rejects one, and an empty locale is not a translation.
    expect(createAnnouncement.mock.calls[0][0].locales.en).toBeUndefined();
    // A published announcement closes its composer: the next one starts blank
    // rather than in the last one's leftovers.
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("offers a fallback locale only among the ones that have a title", async () => {
    const container = await mount();
    const dialog = await openComposer(container);
    expect(options(dialog, "default-locale")).toEqual([]);

    await fillTitle(dialog, "ru", "Только по-русски");
    expect(options(dialog, "default-locale")).toEqual([LABEL.locales.ru]);

    await fillTitle(dialog, "en", "In English too");
    expect(options(dialog, "default-locale")).toEqual([LABEL.locales.ru, LABEL.locales.en]);
  });

  it("dates the state and falls back to the locale it was written in", async () => {
    listAnnouncements.mockResolvedValue([
      // Retired: an expiry in the past, which is what "unpublish" writes.
      row({ id: 93, expires_at: "2026-09-02T10:00:00Z" }),
      // Written in Russian only, and this viewer reads English — a workspace
      // announcement is allowed exactly one locale, so the fallback is the row's
      // own `default_locale` rather than an empty cell.
      row({
        id: 94,
        published_at: "2099-01-01T10:00:00Z",
        payload: { locales: { ru: { title: "Только по-русски" } }, default_locale: "ru" }
      })
    ]);
    const container = await mount();
    const text = container.textContent ?? "";
    // The state cell is a compact glyph, so its name lives in `aria-label` —
    // `StatusIcon` carries `role="img"` precisely so that name survives whether
    // or not the pointer-only tooltip is reachable. Reading `textContent` for it
    // would only ever pin a text cell this column deliberately is not.
    const stateNames = [...container.querySelectorAll('[role="img"]')].map((element) =>
      element.getAttribute("aria-label")
    );

    expect(text).toContain("Maintenance");
    expect(text).toContain("Только по-русски");
    expect(stateNames).toContain(LABEL.state.retired);
    expect(stateNames).toContain(LABEL.state.scheduled);
  });

  it("refuses the screen when the workspace grants nothing and the account is not a superuser", async () => {
    permitted = false;
    const container = await mount();

    expect(container.querySelector('[data-field="audience"]')).toBeNull();
    expect(container.textContent ?? "").toContain(LABEL.unauthorized.title);
    expect(listAnnouncements).not.toHaveBeenCalled();
  });
});
