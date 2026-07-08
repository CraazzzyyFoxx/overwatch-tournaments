# i18n → next-intl Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom client-only `LanguageProvider` with next-intl (App Router, cookie-based locale, no i18n routing), enable SSR of translations, proofread both ru/en dictionaries, and cover all `(site)` pages with translations.

**Architecture:** next-intl **without i18n routing** — locale lives in the `NEXT_LOCALE` cookie (resolved server-side in `getRequestConfig`), so `src/middleware.ts` (workspace-by-host / white-label) is untouched. Messages move from `.ts` modules to JSON. A transitional compat shim (`useTranslation()`) keeps the existing 55 call-sites working during infra migration; it is removed in Phase 4 after call-sites move to the idiomatic `useTranslations`/`useLocale` API.

**Tech Stack:** Next.js 16.2, React 19, next-intl v4, TypeScript (strict), bun (package manager + test runner), Tailwind v4.

## Global Constraints

- Locale cookie name: `NEXT_LOCALE` (keep — do not rename; existing users' choice must survive).
- Locales: `"en" | "ru"`; default `"ru"`.
- **No i18n routing** — no `/[locale]/` segment; **do not modify `src/middleware.ts`**.
- Message files: `frontend/src/i18n/messages/en.json`, `frontend/src/i18n/messages/ru.json`.
- Translation **keys stay identical** to the current dictionaries through Phase 1 (call-sites unchanged).
- New translations **only for `(site)`**; do not add admin/balancer translations (only migrate their existing calls).
- Commands run from `frontend/`: build `bun run build`, lint `bun run lint`, tests `bun test <path>`.
- ICU: `{var}` interpolation is compatible; escape a literal `'` as `''` when adjacent to `{`/`}`.
- Commit after every green step.

---

## Phase 1 — Infrastructure (build stays green; behavior unchanged)

### Task 1: Convert dictionaries `.ts` → JSON + parity test

**Files:**
- Create: `frontend/src/i18n/messages/en.json`
- Create: `frontend/src/i18n/messages/ru.json`
- Create: `frontend/src/i18n/messages.parity.test.ts`
- Keep (for now): `frontend/src/i18n/locales/en.ts`, `ru.ts` (removed in Phase 4)

**Interfaces:**
- Produces: JSON message bundles importable as `import en from "@/i18n/messages/en.json"`.

- [ ] **Step 1: Generate JSON from the existing TS modules**

bun can import `.ts` directly. Run from `frontend/`:

```bash
bun -e 'import {en} from "./src/i18n/locales/en.ts"; await Bun.write("src/i18n/messages/en.json", JSON.stringify(en, null, 2) + "\n")'
bun -e 'import {ru} from "./src/i18n/locales/ru.ts"; await Bun.write("src/i18n/messages/ru.json", JSON.stringify(ru, null, 2) + "\n")'
```

- [ ] **Step 2: Write the parity test**

```ts
// frontend/src/i18n/messages.parity.test.ts
import { describe, it, expect } from "bun:test";
import en from "./messages/en.json";
import ru from "./messages/ru.json";

function keyPaths(obj: unknown, prefix = ""): string[] {
  if (obj === null || typeof obj !== "object") return [prefix];
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) =>
    keyPaths(v, prefix ? `${prefix}.${k}` : k),
  );
}

describe("message dictionaries", () => {
  it("en and ru have identical key sets", () => {
    const enKeys = new Set(keyPaths(en));
    const ruKeys = new Set(keyPaths(ru));
    const missingInRu = [...enKeys].filter((k) => !ruKeys.has(k));
    const missingInEn = [...ruKeys].filter((k) => !enKeys.has(k));
    expect({ missingInRu, missingInEn }).toEqual({ missingInRu: [], missingInEn: [] });
  });
});
```

- [ ] **Step 3: Run the test**

Run: `bun test src/i18n/messages.parity.test.ts`
Expected: PASS (current dictionaries already mirror each other; if it fails it surfaces a pre-existing drift — reconcile by adding the missing key to the deficient file, matching the other's text as a placeholder to be fixed in Phase 2).

- [ ] **Step 4: Audit ICU apostrophes in en.json**

Run: `grep -nE "'\\s*[{}]|[{}]\\s*'" src/i18n/messages/en.json` (expect no matches). If any `'` sits next to `{`/`}`, double it (`''`). Standalone apostrophes in words (`don't`) are safe.

- [ ] **Step 5: Commit**

```bash
git add src/i18n/messages/ src/i18n/messages.parity.test.ts
git commit -m "feat(i18n): add JSON message bundles + dictionary parity test"
```

---

### Task 2: Locale-resolution helper (pure, TDD) + `request.ts` + type augmentation

**Files:**
- Create: `frontend/src/i18n/resolve-locale.ts`
- Create: `frontend/src/i18n/resolve-locale.test.ts`
- Create: `frontend/src/i18n/request.ts`
- Create: `frontend/src/global.d.ts`

**Interfaces:**
- Produces: `resolveLocale(cookieValue: string | undefined, acceptLanguage: string | null): "en" | "ru"`
- Produces: default export `getRequestConfig(...)` at `@/i18n/request`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/i18n/resolve-locale.test.ts
import { describe, it, expect } from "bun:test";
import { resolveLocale } from "./resolve-locale";

describe("resolveLocale", () => {
  it("prefers a valid cookie value", () => {
    expect(resolveLocale("en", "ru,en;q=0.9")).toBe("en");
    expect(resolveLocale("ru", null)).toBe("ru");
  });
  it("ignores an invalid cookie and falls back to Accept-Language", () => {
    expect(resolveLocale("de", "ru-RU,ru;q=0.9")).toBe("ru");
    expect(resolveLocale("", "en-US,en;q=0.9")).toBe("en");
  });
  it("uses Accept-Language when no cookie: ru wins only if ru is present", () => {
    expect(resolveLocale(undefined, "ru-RU,ru;q=0.9,en;q=0.8")).toBe("ru");
    expect(resolveLocale(undefined, "fr-FR,fr;q=0.9")).toBe("en");
  });
  it("defaults to ru when nothing is available", () => {
    expect(resolveLocale(undefined, null)).toBe("ru");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bun test src/i18n/resolve-locale.test.ts`
Expected: FAIL (`resolveLocale` not defined).

- [ ] **Step 3: Implement the helper**

```ts
// frontend/src/i18n/resolve-locale.ts
export const LOCALES = ["en", "ru"] as const;
export type Locale = (typeof LOCALES)[number];

function isLocale(v: string | undefined): v is Locale {
  return v === "en" || v === "ru";
}

/**
 * Resolve the active locale. Order: valid cookie → Accept-Language
 * (ru only if explicitly requested) → default "ru". Mirrors the previous
 * client behavior (ru-first audience) but computed on the server.
 */
export function resolveLocale(
  cookieValue: string | undefined,
  acceptLanguage: string | null,
): Locale {
  if (isLocale(cookieValue)) return cookieValue;
  const primary = acceptLanguage?.split(",")[0]?.trim().split("-")[0]?.toLowerCase();
  if (primary === "ru") return "ru";
  if (primary === "en") return "en";
  return "ru";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bun test src/i18n/resolve-locale.test.ts`
Expected: PASS.

- [ ] **Step 5: Write `request.ts`**

```ts
// frontend/src/i18n/request.ts
import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import { IntlErrorCode } from "next-intl";
import { resolveLocale } from "./resolve-locale";

export default getRequestConfig(async () => {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const locale = resolveLocale(
    cookieStore.get("NEXT_LOCALE")?.value,
    headerStore.get("accept-language"),
  );
  const messages = (await import(`./messages/${locale}.json`)).default;

  return {
    locale,
    messages,
    onError(error) {
      if (error.code !== IntlErrorCode.MISSING_MESSAGE) {
        // Real bug — surface it. MISSING_MESSAGE is expected during rollout.
        console.error(error);
      }
    },
    getMessageFallback({ namespace, key }) {
      return [namespace, key].filter(Boolean).join(".");
    },
  };
});
```

- [ ] **Step 6: Write the type augmentation**

```ts
// frontend/src/global.d.ts
import type messages from "./i18n/messages/en.json";

declare module "next-intl" {
  interface AppConfig {
    Locale: "en" | "ru";
    Messages: typeof messages;
  }
}
```

- [ ] **Step 7: Commit**

```bash
git add src/i18n/resolve-locale.ts src/i18n/resolve-locale.test.ts src/i18n/request.ts src/global.d.ts
git commit -m "feat(i18n): server-side locale resolution + next-intl request config"
```

---

### Task 3: Wire the plugin, SSR locale in root layout, provider cleanup

**Files:**
- Modify: `frontend/next.config.mjs`
- Modify: `frontend/src/app/layout.tsx`
- Modify: `frontend/src/app/providers.tsx`

**Interfaces:**
- Consumes: `@/i18n/request` (via plugin), `getLocale` from `next-intl/server`.

- [ ] **Step 1: Wrap the config with the next-intl plugin**

In `next.config.mjs`, add at top:

```js
import createNextIntlPlugin from 'next-intl/plugin';
const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');
```

Change the final export:

```js
export default withNextIntl(nextConfig);
```

- [ ] **Step 2: SSR locale + provider in root layout**

In `frontend/src/app/layout.tsx`:
- Add imports: `import { NextIntlClientProvider } from "next-intl";` and `import { getLocale } from "next-intl/server";`
- Make `RootLayout` async and read the locale:

```tsx
export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const locale = await getLocale();
  return (
    <html lang={locale}>
      <body className={cn(inter.className, inter.variable, jetbrainsMono.variable, onest.variable, "dark")}>
        <GoogleAnalytics gaId="G-6TYE0K6SQM" />
        <NextIntlClientProvider>
          <Providers>
            <Suspense fallback={null}><LoginModalTrigger /></Suspense>
            <AuthModal />
            <Suspense fallback={null}><AccountSettingsModal /></Suspense>
            <Toaster />
            {children}
          </Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
```

- In `generateMetadata`, set `openGraph.locale` from the active locale: add `const locale = await getLocale();` and use `` locale === "ru" ? "ru_RU" : "en_US" `` instead of the hardcoded `"en_US"`.

- [ ] **Step 3: Remove `LanguageProvider` from `providers.tsx`**

Delete the `import { LanguageProvider }` line and unwrap it:

```tsx
export function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrap />
      <WorkspaceBootstrap />
      {children}
    </QueryClientProvider>
  );
}
```

- [ ] **Step 4: Verify the build compiles**

Run: `bun run build`
Expected: build succeeds. (Call-sites still import `useTranslation` from `@/i18n/LanguageContext` — fixed in Task 4/5; if build runs before Task 4, it fails on the now-removed provider export. Sequence Task 4 immediately; do not commit a broken build. If executing tasks individually, fold Task 4 into this commit.)

- [ ] **Step 5: Commit (jointly with Task 4 — see note)**

---

### Task 4: Locale-switch server action + compat shim (keeps 55 call-sites working)

**Files:**
- Create: `frontend/src/i18n/locale-actions.ts`
- Rewrite: `frontend/src/i18n/LanguageContext.tsx` (now a thin shim)
- Modify: `frontend/src/components/LanguageSwitcher.tsx`
- Modify: `frontend/src/components/UserMenu.tsx`

**Interfaces:**
- Produces: `setUserLocale(locale: "en" | "ru"): Promise<void>` (server action).
- Produces: `useTranslation(): { t; locale: "en" | "ru"; setLocale: (l) => void }` (shim, unchanged signature) and `useLocale`/`Locale` re-exports.

- [ ] **Step 1: Server action**

```ts
// frontend/src/i18n/locale-actions.ts
"use server";
import { cookies } from "next/headers";

export async function setUserLocale(locale: "en" | "ru"): Promise<void> {
  (await cookies()).set("NEXT_LOCALE", locale, {
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
    sameSite: "lax",
  });
}
```

- [ ] **Step 2: Rewrite `LanguageContext.tsx` as a shim**

```tsx
// frontend/src/i18n/LanguageContext.tsx
"use client";
import { useTranslations, useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import { setUserLocale } from "./locale-actions";

export type Locale = "en" | "ru";

/**
 * Backwards-compatible shim over next-intl so existing call-sites keep working
 * during migration. Removed in Phase 4 once call-sites use next-intl directly.
 */
export function useTranslation() {
  const t = useTranslations();
  const locale = useLocale() as Locale;
  const router = useRouter();
  const setLocale = (next: Locale) => {
    void setUserLocale(next).then(() => router.refresh());
  };
  return { t, locale, setLocale };
}
```

Note: `LanguageProvider` export is deleted. Confirm nothing except `providers.tsx` (already fixed) imported it:
Run: `grep -rn "LanguageProvider" src` → expect no results.

- [ ] **Step 3: Update `LanguageSwitcher.tsx` and `UserMenu.tsx`**

Both already destructure `{ locale, setLocale }` from `useTranslation()` — the shim preserves this exact shape, so **no change is required** for them to work. Leave as-is in Phase 1 (they migrate to the idiomatic API in Phase 4).

- [ ] **Step 4: Build + run all tests**

Run: `bun run build && bun test`
Expected: build succeeds; existing tests pass.

- [ ] **Step 5: Commit (Tasks 3+4 together)**

```bash
git add next.config.mjs src/app/layout.tsx src/app/providers.tsx src/i18n/locale-actions.ts src/i18n/LanguageContext.tsx
git commit -m "feat(i18n): wire next-intl plugin, SSR locale, locale-switch action + compat shim"
```

---

### Task 5: Manual + automated smoke of locale switching

**Files:**
- Create: `frontend/src/i18n/i18n-smoke.test.tsx`

- [ ] **Step 1: Render smoke test per locale**

```tsx
// frontend/src/i18n/i18n-smoke.test.tsx
import { describe, it, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import ru from "./messages/ru.json";
import en from "./messages/en.json";
import { useTranslations } from "next-intl";

function Probe() {
  const t = useTranslations("common");
  return <span>{t("back")}</span>;
}

describe("i18n smoke", () => {
  it("renders ru message", () => {
    const html = renderToStaticMarkup(
      <NextIntlClientProvider locale="ru" messages={ru}><Probe /></NextIntlClientProvider>,
    );
    expect(html).toContain(ru.common.back);
  });
  it("renders en message", () => {
    const html = renderToStaticMarkup(
      <NextIntlClientProvider locale="en" messages={en}><Probe /></NextIntlClientProvider>,
    );
    expect(html).toContain(en.common.back);
  });
});
```

- [ ] **Step 2: Run**

Run: `bun test src/i18n/i18n-smoke.test.tsx`
Expected: PASS. (If bun cannot resolve JSX in `.tsx` tests, mirror the existing test setup used by other `*.test.tsx` in the repo; check one before writing.)

- [ ] **Step 3: Manual dev check**

Run `bun run dev`, load `/`, toggle the language switcher, confirm text switches and a full-page refresh shows the new language with correct `<html lang>` (no flash). Reload to confirm the cookie persists.

- [ ] **Step 4: Commit**

```bash
git add src/i18n/i18n-smoke.test.tsx
git commit -m "test(i18n): locale render smoke tests"
```

**Phase 1 exit criteria:** `bun run build`, `bun run lint`, `bun test` all green; UI behaves exactly as before but locale is now server-rendered.

---

## Phase 2 — Proofread both dictionaries (ru + en)

> The deliverable here is corrected translation *content*. Keys never change in this phase. Work one namespace at a time; after each, run the parity test and build. Commit per namespace.

### Task 6: Establish the glossary

**Files:**
- Create: `frontend/src/i18n/GLOSSARY.md`

- [ ] **Step 1** — Write the EN↔RU glossary (seed from the spec's table: Standings→Турнирная таблица, Bracket→Сетка, Playoff→Плей-офф, Group stage→Групповой этап, Round-robin→Круговой, Swiss→Швейцарка, Check-in→Чек-ин, Withdraw→Снять заявку, Roster→Состав, Participants→Участники, Heroes→Герои, Tank/Damage/Support→Танк/Дамаг/Саппорт, Rank/SR→Ранг/SR, Draft→Драфт, Encounter→Встреча, Match→Матч, Tiebreakers→Тай-брейки, Balancer→Балансировщик, Registration→Регистрация). This is the authority for terminology consistency across all namespaces.
- [ ] **Step 2** — Commit: `docs(i18n): terminology glossary`.

### Tasks 7–13: Proofread each namespace

One task per namespace: `common`, `registration`, `draft`, `matchEdit`, `matchReport`, `rankAutofill`, `analytics`.

For each namespace, per task:
- [ ] **Step 1: Map usage context.** `grep -rn '"<namespace>\.' src` (and shim call-sites) to see where each key renders, so wording fits the UI (button vs heading vs tooltip vs toast).
- [ ] **Step 2: Rewrite `ru.json` and `en.json`** for that namespace: natural, context-aware phrasing; apply the glossary; fix ICU apostrophe escaping in en.
- [ ] **Step 3: Convert count strings to ICU plurals** where the key interpolates a count (e.g. `teamsCount`, `topAdvance`, `noMatches` if count-bearing). Russian form:
  `"{count, plural, one {# команда} few {# команды} many {# команд} other {# команды}}"`; English: `"{count, plural, one {# team} other {# teams}}"`.
- [ ] **Step 4: Run** `bun test src/i18n/messages.parity.test.ts` (keys unchanged → still PASS) and `bun run build`.
- [ ] **Step 5: Commit** `fix(i18n): proofread <namespace> translations (ru+en)`.

**Phase 2 exit criteria:** both dictionaries read as native, glossary-consistent copy; parity test green; RU plurals grammatically correct.

---

## Phase 3 — Cover all `(site)` pages with translations

### Task 14: Inventory hardcoded strings in `(site)`

**Files:**
- Create: `docs/superpowers/plans/2026-07-08-i18n-site-inventory.md`

- [ ] **Step 1: Enumerate `(site)` surfaces.** Route groups/areas: `(home)`, `tournaments` (list, `[id]/*`, `analytics`, `draft`, `bracket`, `standings`, `matches`, `teams`, `participants`, `heroes`), `users` (list, `[slug]`, `compare`, `heroes-compare`), `teams`, `statistics`, `matches`, `encounters`, `achievements`, `owal`, `workspace/[slug]`, `not-configured`, plus shared components rendered on `(site)` (`src/components/**` used by these pages).
- [ ] **Step 2: Find candidate literals.** For each area, scan for untranslated user-facing text: JSX text nodes, and `title=`, `placeholder=`, `aria-label=`, `alt=`, toast/`notify` messages, `label`/empty-state strings not already wrapped in `t(...)`. Record file → string → proposed `namespace.key`.
- [ ] **Step 3: Commit the inventory doc.**

### Tasks 15+: Extract per area

One task per `(site)` area from the inventory. Worked example (pattern to repeat):

**Example — Task: translate `(site)/statistics`**
- [ ] **Step 1:** Add keys under a `statistics` namespace to **both** `en.json` and `ru.json` (context-correct copy, glossary-consistent).
- [ ] **Step 2:** In the page/components, replace literals. Client components: `const t = useTranslations("statistics");` then `{t("title")}`. Server components: `const t = await getTranslations("statistics");`.
- [ ] **Step 3:** For any `title`/`placeholder`/`aria-label`, replace with `t(...)`.
- [ ] **Step 4:** Run `bun test src/i18n/messages.parity.test.ts` + `bun run build` + `bun run lint`.
- [ ] **Step 5:** Commit `feat(i18n): translate <area>`.

Repeat until the inventory checklist is empty. **Do not** add keys consumed only by admin/balancer.

**Phase 3 exit criteria:** no user-facing hardcoded strings remain on any `(site)` page; parity test green; build/lint green.

---

## Phase 4 — Cleanup (idiomatic API, remove shim)

### Task N: Migrate call-sites off the shim

**Files:** all files importing `useTranslation` from `@/i18n/LanguageContext` (list via `grep -rln "@/i18n/LanguageContext" src`).

Per file (mechanical):
- [ ] **Step 1:** Replace `import { useTranslation } from "@/i18n/LanguageContext";` → `import { useTranslations, useLocale } from "next-intl";`.
- [ ] **Step 2:** Replace `const { t } = useTranslation();` → `const t = useTranslations();`. For files using locale: `const { t, locale } = useTranslation();` → `const t = useTranslations(); const locale = useLocale();`.
- [ ] **Step 3:** For `setLocale` consumers (`LanguageSwitcher`, `UserMenu`): import `setUserLocale` from `@/i18n/locale-actions` and `useRouter`; call `await setUserLocale(next); router.refresh();` on click. Remove `setLocale` usage.
- [ ] **Step 4:** `bun run build` after each batch; commit per logical batch (e.g. per top-level area): `refactor(i18n): use next-intl directly in <area>`.

### Task N+1: Delete the shim and legacy dictionaries

- [ ] **Step 1:** Confirm zero importers remain: `grep -rn "@/i18n/LanguageContext" src` → empty.
- [ ] **Step 2:** Delete `src/i18n/LanguageContext.tsx`, `src/i18n/locales/en.ts`, `src/i18n/locales/ru.ts`.
- [ ] **Step 3:** `bun run build && bun test && bun run lint` → all green.
- [ ] **Step 4:** Commit `refactor(i18n): remove compat shim and legacy TS dictionaries`.

### Task N+2: Unify date/number formatting

**Files:** `src/app/(site)/tournaments/[id]/_components/TournamentClientLayout.tsx`, `src/app/(site)/tournaments/[id]/pages/_components/participantsColumns.tsx`, `src/components/UserRankHistory.tsx`, and any other `locale.startsWith("ru")` sites in `(site)`.

- [ ] **Step 1:** Replace manual `locale.startsWith("ru") ? "ru-RU" : "en-GB"` date logic with next-intl `useFormatter()`/`getFormatter()` (`format.dateTime(...)`), or keep `Intl.DateTimeFormat` seeded from `useLocale()`.
- [ ] **Step 2:** Replace `UserRankHistory` inline `locale.startsWith("ru") ? "Ошибка загрузки" : "Failed to load"` with `t(...)` keys (add to `errors`/`users` namespace, both dictionaries).
- [ ] **Step 3:** `bun run build && bun run lint`; commit `refactor(i18n): locale-aware date/number formatting via next-intl`.

**Phase 4 exit criteria:** no `@/i18n/LanguageContext` imports; no legacy `.ts` dictionaries; no `locale.startsWith` string branching; all green.

---

## Self-Review coverage map

| Spec section | Covered by |
|---|---|
| Deps + plugin | Task 1, 3 |
| `request.ts` locale resolution | Task 2 |
| JSON messages + typing | Task 1, 2 |
| SSR provider + `<html lang>` | Task 3 |
| Locale switch action | Task 4 |
| Compat shim | Task 4 |
| onError/getMessageFallback | Task 2 |
| Proofread both dicts + glossary + ICU plurals | Tasks 6–13 |
| `(site)` coverage | Tasks 14–15+ |
| Call-site migration + shim removal | Phase 4 |
| Date/number unification | Task N+2 |
| Tests (parity, smoke, unit) | Tasks 1, 2, 5 |
