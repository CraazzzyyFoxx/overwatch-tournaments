# Миграция i18n на next-intl + покрытие переводами `(site)`

**Дата:** 2026-07-08
**Статус:** Design (одобрен пользователем, вариант A)
**Область:** `frontend/` (Next.js 16 App Router, React 19)

## Проблема

Мультиязычность реализована самописным клиентским провайдером
(`src/i18n/LanguageContext.tsx`): контекст с `t(key, vars)`, локаль в cookie
`NEXT_LOCALE`, два TS-словаря (`locales/en.ts` ~883 стр., `locales/ru.ts`
~885 стр.). Проблемы:

1. **Клиентский-только рендеринг** — `<html lang>` захардкожен `en`, есть
   мигание языка (FOUC), локаль не участвует в SSR/метаданных.
2. **Кривые переводы** — оба словаря выглядят машинными, без учёта контекста
   UI; русская плюрализация неверна (`{count} команд` при любом числе).
3. **Неполное покрытие** — многие `(site)`-страницы содержат хардкод-строки;
   есть антипаттерн inline-условных строк (`locale.startsWith("ru") ? ... : ...`).

## Цель

- Перевести инфраструктуру на **next-intl** (App Router, **без** i18n-routing —
  локаль остаётся в cookie, URL не меняется).
- Включить **SSR-рендеринг** переводов (корректный `<html lang>`, без FOUC).
- **Вычитать оба словаря** (ru + en) с учётом контекста, единый глоссарий,
  ICU-плюрализация.
- **Покрыть переводом все страницы `(site)`** (публичная часть). `admin/*` и
  `balancer/*` новыми переводами НЕ расширяем, но их существующие вызовы
  переводов мигрируем на новый API (иначе билд сломается).

### Не-цели (Non-goals)

- i18n-routing с сегментом `/[locale]/` (конфликт с workspace-middleware по
  хосту / white-label доменами).
- Новые переводы для `admin/*` и `balancer/*` (кроме миграции существующих
  вызовов).
- Добавление новых языков помимо `en`/`ru`.

## Решения (из брейншторминга)

| Вопрос | Решение |
|---|---|
| Роутинг | Cookie `NEXT_LOCALE`, **без** сегмента в URL. `middleware.ts` (workspace-по-хосту) не трогаем. |
| Объём новых переводов | Только `(site)`. |
| Язык-источник | Вычитать **оба** словаря. |
| Рендеринг | **SSR + клиент**. |
| Чистка shim'а (Фаза 4) | **Включена** в объём. |
| Формат сообщений | **JSON** (`messages/{en,ru}.json`) + типизация через `AppConfig`. |

## Ключевой факт совместимости

Текущая интерполяция `{var}` совпадает с ICU-синтаксисом next-intl, а сигнатура
`t("ns.key", { var })` идентична `useTranslations()(...)`. → миграция
call-site'ов почти механическая, ключи в вызовах не меняются.

## Архитектура

### 1. Зависимости и конфиг

- Добавить `next-intl` (последняя мажорная; совместимость с Next 16.2
  подтверждена — официальный пример `example-app-router-without-i18n-routing`
  работает без middleware).
- `next.config.*`: обернуть экспорт `createNextIntlPlugin("./src/i18n/request.ts")`.

### 2. Резолв локали — `src/i18n/request.ts`

```ts
import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

const LOCALES = ["en", "ru"] as const;
type Locale = (typeof LOCALES)[number];

export default getRequestConfig(async () => {
  const store = await cookies();
  const cookieLocale = store.get("NEXT_LOCALE")?.value;
  const locale: Locale = LOCALES.includes(cookieLocale as Locale)
    ? (cookieLocale as Locale)
    : await detectFromAcceptLanguage(); // ru->ru, иначе en; дефолт ru
  const messages = (await import(`./messages/${locale}.json`)).default;
  return {
    locale,
    messages,
    onError(error) { /* MISSING_MESSAGE: log-only; иначе report */ },
    getMessageFallback({ namespace, key }) {
      return [namespace, key].filter(Boolean).join("."); // как сейчас — ключ
    },
  };
});
```

- Порядок: cookie `NEXT_LOCALE` → `Accept-Language` (первый визит) → дефолт `ru`.
- Имя cookie `NEXT_LOCALE` сохраняем — выбор существующих пользователей не теряется.

### 3. Структура сообщений

- `src/i18n/messages/en.json`, `src/i18n/messages/ru.json` (из текущих `.ts`).
- Типизация — `src/global.d.ts`:

```ts
import messages from "./i18n/messages/en.json";
declare module "next-intl" {
  interface AppConfig {
    Locale: "en" | "ru";
    Messages: typeof messages;
  }
}
```

- Существующие namespace'ы сохраняем: `common`, `registration`, `draft`,
  `matchEdit`, `matchReport`, `rankAutofill`, `analytics`.
- Новые namespace'ы под домены `(site)` (по мере извлечения хардкода):
  `home`, `nav`, `tournamentsList`, `users`, `teams`, `statistics`, `matches`,
  `encounters`, `achievements`, `owal`, `workspace`, `errors`.
- **ICU-плюрализация** для счётных строк, напр.:
  `"teamsCount": "{count, plural, one {# команда} few {# команды} many {# команд} other {# команды}}"`.
- Экранировать апострофы в EN там, где `'` соседствует с `{`/`}` (`''`).

### 4. Провайдер и SSR — `app/layout.tsx`

```tsx
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";

export default async function RootLayout({ children }) {
  const locale = await getLocale();
  return (
    <html lang={locale}>
      <body className={...}>
        <NextIntlClientProvider>
          <Providers>{...children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
```

- `providers.tsx`: убрать `LanguageProvider`, оставить QueryClient + bootstrap.
- `generateMetadata`: `openGraph.locale` = реальная (`ru_RU`/`en_US`).

### 5. Переключение языка

- Server action `src/i18n/locale-actions.ts`:

```ts
"use server";
import { cookies } from "next/headers";
export async function setUserLocale(locale: "en" | "ru") {
  (await cookies()).set("NEXT_LOCALE", locale, { maxAge: 60*60*24*365, path: "/" });
}
```

- `LanguageSwitcher` и `UserMenu`: `const locale = useLocale();` +
  `onClick`: `await setUserLocale(next); router.refresh();`.

### 6. Транзитный shim (де-риск миграции call-site'ов)

`src/i18n/LanguageContext.tsx` временно переписываем как тонкий совместимый слой,
чтобы **все 55 файлов работали без правок**, билд оставался зелёным:

```tsx
"use client";
import { useTranslations, useLocale } from "next-intl";
import { setUserLocale } from "./locale-actions";
import { useRouter } from "next/navigation";

export function useTranslation() {
  const t = useTranslations();
  const locale = useLocale();
  const router = useRouter();
  const setLocale = (l: "en" | "ru") => { void setUserLocale(l).then(() => router.refresh()); };
  return { t, locale, setLocale };
}
```

Удаляется в Фазе 4 после перевода всех call-site'ов на идиоматичный API.

### 7. Обработка ошибок и форматирование

- `getMessageFallback` → возвращает ключ (как текущее поведение).
- `onError` → `MISSING_MESSAGE` только логируем; прочее — репорт.
- Даты/числа: унификация через `useFormatter`/`getFormatter` (locale-aware),
  замена ручных `locale.startsWith("ru")` в `participantsColumns.tsx`,
  `TournamentClientLayout.tsx`; inline-условные строки `UserRankHistory.tsx` →
  ключи словаря.

## Глоссарий терминов (черновик, поправить при ревью)

Единая терминология для консистентности (EN → RU):

| EN | RU |
|---|---|
| Standings | Турнирная таблица |
| Bracket | Сетка |
| Playoff | Плей-офф |
| Group stage | Групповой этап |
| Round-robin | Круговой |
| Swiss | Швейцарка |
| Check-in | Чек-ин |
| Withdraw | Снять заявку |
| Roster / Rostered | Состав / В составе |
| Participants | Участники |
| Heroes | Герои |
| Roles (Tank/Damage/Support) | Роли (Танк/Дамаг/Саппорт) |
| Rank / SR | Ранг / SR |
| Draft | Драфт |
| Encounter | Встреча |
| Match | Матч |
| Tiebreakers | Тай-брейки |
| Balancer | Балансировщик |
| Registration | Регистрация |

## План (фазы; каждая оставляет билд зелёным)

### Фаза 1 — Инфраструктура
- Установить `next-intl`, настроить `next.config`.
- `request.ts`, `global.d.ts`, конверт словарей `.ts` → `.json` (без изменения
  содержимого — только формат).
- `layout.tsx` (SSR-локаль, `NextIntlClientProvider`), `providers.tsx`.
- `locale-actions.ts`, обновить `LanguageSwitcher`/`UserMenu`.
- Shim `useTranslation()`.
- **Критерий:** всё работает как раньше, `bun run build` зелёный, ручная
  проверка переключения RU/EN.

### Фаза 2 — Вычитка словарей
- Согласовать глоссарий.
- Пройти namespace-за-namespace: переписать ru + en с учётом контекста UI,
  консистентная терминология, ICU-плюрали.
- Parity-тест: ключи `en.json` ≡ `ru.json`.

### Фаза 3 — Покрытие `(site)`
- Инвентаризация хардкод-строк по всем `(site)`-страницам/компонентам
  (JSX-текст, `title`/`placeholder`/`aria-label`, тосты).
- Добавить ключи, заменить литералы; server-компоненты — `getTranslations`.

### Фаза 4 — Чистка
- Механически перевести 55 call-site'ов на `useTranslations`/`useLocale`.
- Удалить shim и старые `locales/{en,ru}.ts`, `LanguageContext` контекст.
- Унифицировать форматирование дат/чисел.

## Тестирование

- Юнит: резолв локали (`request.ts`) — cookie/Accept-Language/дефолт;
  `setUserLocale` пишет cookie.
- Компонентные: репрезентативные компоненты рендерят корректные строки per-locale
  (`NextIntlClientProvider` + messages).
- Parity-тест словарей (идентичность ключей).
- Раннер: `bun test <path>`.
- Финал: зелёные `eslint` + `next build`.

## Риски

- **Совместимость next-intl ↔ Next 16.2** — подтверждена по докам; при проблеме
  фиксируем версию через build-error-resolver.
- **ICU-экранирование апострофов** в EN — аудит на этапе конверта в JSON.
- **`t()` для не-строковых ключей** — текущие call-site'ы обращаются к листовым
  строкам; `getMessageFallback` страхует.
- Объём Фаз 2–3 большой — выполняется намспейсами/страницами, билд зелёный на
  каждом шаге.
