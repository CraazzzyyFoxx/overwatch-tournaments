import type { Window as HappyWindow } from "happy-dom";
import { act, createElement, type ComponentProps } from "react";
import type { Root } from "react-dom/client";
import { afterEach, vi } from "vitest";

import { en as kitEn } from "@craazzzyyfoxx/admin-kit/messages";

import appEn from "@/i18n/messages/en.json";

// `i18n/request.ts` serves the kit's `adminKit` namespace next to the app's tree.
const en = { ...appEn, ...kitEn };

// In the app every zone layout mounts `ZoneIntlProvider`, so a component never
// renders without messages. Tests render components bare, and the shared kit
// and data-table pieces are rendered by suites all over the tree. Outside a
// provider, `useTranslations` falls back to the English messages instead of
// throwing; inside one (or under a file's own `vi.mock("next-intl")`) nothing
// changes. The app's request config always supplies a zone; a test provider
// without one gets the runtime's — the zone next-intl would fall back to — so
// formatting stays the same minus an ENVIRONMENT_FALLBACK error per call.
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  // One translator per namespace: a fresh function every render would change
  // the identity of `t` and re-fire every effect and memo that depends on it.
  const fallbacks = new Map<string, ReturnType<typeof actual.createTranslator>>();
  const fallback = (namespace?: string) => {
    const key = namespace ?? "";
    let translator = fallbacks.get(key);
    if (!translator) {
      translator = actual.createTranslator({ locale: "en", messages: en, namespace: namespace as never, timeZone });
      fallbacks.set(key, translator);
    }
    return translator;
  };
  return {
    ...actual,
    NextIntlClientProvider: (props: ComponentProps<typeof actual.NextIntlClientProvider>) =>
      createElement(actual.NextIntlClientProvider, {
        timeZone,
        ...props,
        // A test's own `messages={en}` carries no `adminKit`; the app's zone bundles always do.
        ...(props.messages && { messages: { ...kitEn, ...props.messages } })
      }),
    useTranslations: ((namespace?: string) => {
      try {
        return actual.useTranslations(namespace as never);
      } catch {
        return fallback(namespace);
      }
    }) as typeof actual.useTranslations
  };
});

// The admin kit's `useIsMobile` asks `matchMedia`, which happy-dom answers from its own viewport —
// not from the `window.innerWidth` a test sets. Answer width queries from `innerWidth`, evaluated on
// every read; a test that stubs `matchMedia` itself overrides this.
if (typeof window !== "undefined") {
  window.matchMedia = ((query: string) => {
    const width = (kind: string) => Number(new RegExp(`\\(${kind}-width:\\s*(\\d+)px\\)`).exec(query)?.[1]);
    return {
      get matches() {
        const max = width("max");
        const min = width("min");
        return (Number.isNaN(max) || window.innerWidth <= max) && (Number.isNaN(min) || window.innerWidth >= min) && !(Number.isNaN(max) && Number.isNaN(min));
      },
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false
    };
  }) as unknown as typeof window.matchMedia;
}

// Radix (Select, Slider) calls these on pointerdown; happy-dom has neither.
if (typeof Element !== "undefined") {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
}

// No test reaches the network. The API base resolves to the page origin
// (localhost:3000), so an unmocked query hit whatever dev server happened to
// run — 401s and socket resets locally, refused connections in CI — and a
// Twitch embed fetched the real player. Unmocked requests now fail at once,
// quietly, with a 503; an iframe navigating gets an empty page.
if (typeof window !== "undefined" && "happyDOM" in window) {
  // happy-dom's own window; the DOM lib only knows it as a plain `Window`.
  const page = window as unknown as HappyWindow;
  page.happyDOM.settings.fetch.interceptor = {
    beforeAsyncRequest: async ({ window: from }) =>
      from === page
        ? new from.Response(null, { status: 503, statusText: "Network disabled in tests" })
        : new from.Response("<!doctype html>", { headers: { "Content-Type": "text/html" } })
  };
}

// Every test unmounts what it mounted, as Testing Library's auto-cleanup does.
// Dozens of suites never did: a leftover root kept its queries subscribed, and
// an answer landing after its test re-rendered it outside act — a warning that
// only surfaced under full-suite load. Unmounting twice is a no-op, so suites
// with their own cleanup are unaffected.
const mountedRoots = vi.hoisted(() => new Set<Root>());
vi.mock("react-dom/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-dom/client")>();
  const track = <R extends Root>(root: R): R => {
    mountedRoots.add(root);
    return root;
  };
  return {
    ...actual,
    createRoot: ((...args) => track(actual.createRoot(...args))) as typeof actual.createRoot,
    hydrateRoot: ((...args) => track(actual.hydrateRoot(...args))) as typeof actual.hydrateRoot
  };
});

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

afterEach(() => {
  if (mountedRoots.size === 0) return;
  const actEnvironment = globalThis.IS_REACT_ACT_ENVIRONMENT;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  try {
    act(() => {
      for (const root of mountedRoots) root.unmount();
    });
  } finally {
    mountedRoots.clear();
    globalThis.IS_REACT_ACT_ENVIRONMENT = actEnvironment;
  }
});
