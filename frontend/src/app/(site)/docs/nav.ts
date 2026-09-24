import type { Locale } from "@/i18n/resolve-locale";

type Localized = Record<Locale, string>;

export type DocLink = {
  href: string;
  title: string;
  keywords: string;
  /** Same-origin but not a Next route (gateway Scalar, static HTML). */
  bypassNext?: boolean;
};

export type DocGroup = {
  label: string;
  items: DocLink[];
};

export type GuideId = "players" | "organizers" | "dev";

export type DocSection = {
  id: GuideId;
  label: string;
  href: string;
  groups: DocGroup[];
};

type GuideArticle = { slug: string; title: Localized; keywords: Localized };
/** A sidebar entry that is not an MDX article: the schema page, the gateway's API reference. */
type GuideLink = { href: string; title: Localized; keywords: Localized; bypassNext?: boolean };
type GuideGroup = { label: Localized; articles: GuideArticle[]; links?: GuideLink[] };

export const GUIDE_IDS: GuideId[] = ["players", "organizers", "dev"];

/**
 * Every guide. Each article is one MDX file per locale at
 * `_content/<locale>/<guide>/<slug>.mdx`; `content.parity.test.ts` holds the
 * two in step. The title lives here, not in the file, because the sidebar
 * needs every title without loading every article.
 */
export const GUIDES: Record<GuideId, GuideGroup[]> = {
  players: [
    {
      label: { ru: "Начало", en: "Getting started" },
      articles: [
        {
          slug: "quickstart",
          title: { ru: "Быстрый старт", en: "Quick start" },
          keywords: {
            ru: "первый турнир вход регистрация чек-ин матч",
            en: "first tournament sign in register check-in match",
          },
        },
        {
          slug: "account",
          title: { ru: "Аккаунт и вход", en: "Account and sign-in" },
          keywords: {
            ru: "discord battle.net twitch battletag профиль привязка приватность удалить аккаунт",
            en: "discord battle.net twitch battletag profile link privacy delete account",
          },
        },
        {
          slug: "notifications",
          title: { ru: "Уведомления и Discord-бот", en: "Notifications and the Discord bot" },
          keywords: {
            ru: "колокольчик личные сообщения бот кнопки отключить",
            en: "bell direct messages bot buttons mute",
          },
        },
      ],
    },
    {
      label: { ru: "Турниры", en: "Tournaments" },
      articles: [
        {
          slug: "tournaments",
          title: { ru: "Как устроен турнир", en: "How a tournament works" },
          keywords: {
            ru: "фазы сетка таблица очки формат трансляция стрим",
            en: "phases bracket standings points format stream",
          },
        },
        {
          slug: "registration",
          title: { ru: "Регистрация", en: "Registration" },
          keywords: {
            ru: "заявка роли герои ранг статус очередь снять заявку",
            en: "application roles heroes rank status waitlist withdraw",
          },
        },
        {
          slug: "admission",
          title: { ru: "Требования допуска", en: "Entry requirements" },
          keywords: {
            ru: "допуск подписка открытый профиль overwatch discord twitch код",
            en: "admission subscription public overwatch profile discord twitch code",
          },
        },
        {
          slug: "captain-teams",
          title: { ru: "Команды капитанов и приглашения", en: "Captain teams and invites" },
          keywords: {
            ru: "капитан команда приглашение ссылка замена состав",
            en: "captain team invite link substitute roster",
          },
        },
        {
          slug: "check-in",
          title: { ru: "Чек-ин", en: "Check-in" },
          keywords: {
            ru: "чек-ин подтверждение участия окно",
            en: "check in confirm attendance window",
          },
        },
        {
          slug: "draft",
          title: { ru: "Драфт", en: "Draft" },
          keywords: {
            ru: "драфт капитаны пик очередь таймер автопик",
            en: "draft captains pick order timer autopick",
          },
        },
        {
          slug: "matches",
          title: { ru: "Матчи: пик-бан и результат", en: "Matches: pick-ban and results" },
          keywords: {
            ru: "встреча пик-бан карты герои отчёт результат спор чат",
            en: "encounter pick ban maps heroes report result dispute chat",
          },
        },
      ],
    },
    {
      label: { ru: "Скримы и миксы", en: "Scrims and mixes" },
      articles: [
        {
          slug: "scrims",
          title: { ru: "Скримы", en: "Scrims" },
          keywords: {
            ru: "скрим комната соперник ссылка тренировка",
            en: "scrim room opponent link practice",
          },
        },
        {
          slug: "mixes",
          title: { ru: "Миксы", en: "Mixes" },
          keywords: {
            ru: "микс кастомка состав ротация скамейка",
            en: "mix custom game lineup rotation bench",
          },
        },
      ],
    },
    {
      label: { ru: "Статистика", en: "Stats" },
      articles: [
        {
          slug: "stats",
          title: { ru: "Профиль, статистика и ранги", en: "Profile, stats and ranks" },
          keywords: {
            ru: "профиль статистика ранг дивизион сравнение mvp влияние аналитика",
            en: "profile statistics rank division compare mvp impact analytics",
          },
        },
        {
          slug: "achievements",
          title: { ru: "Достижения", en: "Achievements" },
          keywords: { ru: "достижения награды ачивки", en: "achievements awards badges" },
        },
      ],
    },
    {
      label: { ru: "Помощь", en: "Help" },
      articles: [
        {
          slug: "faq",
          title: { ru: "Вопросы и проблемы", en: "FAQ and troubleshooting" },
          keywords: {
            ru: "не могу ошибка проблема вопрос не вижу",
            en: "cannot error problem question missing",
          },
        },
        {
          slug: "glossary",
          title: { ru: "Словарь терминов", en: "Glossary" },
          keywords: { ru: "термины словарь значение", en: "terms glossary meaning" },
        },
      ],
    },
  ],
  organizers: [
    {
      label: { ru: "Начало", en: "Getting started" },
      articles: [
        {
          slug: "getting-started",
          title: { ru: "Начало работы", en: "Getting started" },
          keywords: {
            ru: "воркспейс админка обзор сообщество",
            en: "workspace admin panel overview community",
          },
        },
        {
          slug: "roles",
          title: { ru: "Роли и права", en: "Roles and permissions" },
          keywords: {
            ru: "владелец админ хост участник права запрет",
            en: "owner admin host member permissions deny",
          },
        },
        {
          slug: "workspace",
          title: { ru: "Настройки воркспейса", en: "Workspace settings" },
          keywords: {
            ru: "брендинг домен поддомен видимость discord квоты",
            en: "branding domain subdomain visibility discord quota",
          },
        },
      ],
    },
    {
      label: { ru: "Турнир", en: "Tournament setup" },
      articles: [
        {
          slug: "first-tournament",
          title: { ru: "Первый турнир по шагам", en: "Your first tournament" },
          keywords: {
            ru: "создать турнир мастер чек-лист настройки",
            en: "create tournament wizard checklist settings",
          },
        },
        {
          slug: "schedule",
          title: { ru: "Фазы и расписание", en: "Phases and schedule" },
          keywords: {
            ru: "фазы расписание автопереход архив предпросмотр скрытый",
            en: "phases schedule automatic transitions archive preview hidden",
          },
        },
        {
          slug: "registration",
          title: { ru: "Регистрация и заявки", en: "Registration and entries" },
          keywords: {
            ru: "форма регистрации заявки статусы google sheets автозаполнение рангов чек-ин",
            en: "registration form entries statuses google sheets rank autofill check-in",
          },
        },
        {
          slug: "subscriptions",
          title: { ru: "Подписки и допуск", en: "Subscriptions and admission" },
          keywords: {
            ru: "подписка допуск discord роль twitch код требование",
            en: "subscription admission discord role twitch code requirement",
          },
        },
        {
          slug: "divisions",
          title: { ru: "Ранги и дивизионы", en: "Ranks and divisions" },
          keywords: {
            ru: "ранг дивизион сетка дивизионов версия импорт",
            en: "rank division grid version import",
          },
        },
      ],
    },
    {
      label: { ru: "Команды", en: "Teams" },
      articles: [
        {
          slug: "team-formation",
          title: { ru: "Балансировщик и команды", en: "Balancer and teams" },
          keywords: {
            ru: "балансировщик команды ростер капитан замена экспорт",
            en: "balancer teams roster captain substitute export",
          },
        },
        {
          slug: "draft",
          title: { ru: "Драфт капитанов", en: "Captain draft" },
          keywords: {
            ru: "драфт капитаны формат таймер автопик пауза",
            en: "draft captains format timer autopick pause",
          },
        },
      ],
    },
    {
      label: { ru: "Игра", en: "Matches" },
      articles: [
        {
          slug: "brackets",
          title: { ru: "Стадии и сетка", en: "Stages and brackets" },
          keywords: {
            ru: "стадия группа сетка швейцарка плей-офф посев очки тай-брейки",
            en: "stage group bracket swiss playoffs seeding points tiebreakers",
          },
        },
        {
          slug: "matches",
          title: { ru: "Проведение матчей", en: "Running matches" },
          keywords: {
            ru: "встречи пик-бан форма отчёта спор исправить результат",
            en: "encounters pick ban report form dispute correct result",
          },
        },
        {
          slug: "logs",
          title: { ru: "Логи матчей", en: "Match logs" },
          keywords: {
            ru: "лог загрузка discord бот статистика нераспознанные",
            en: "log upload discord bot statistics unresolved",
          },
        },
      ],
    },
    {
      label: { ru: "Сообщество", en: "Community" },
      articles: [
        {
          slug: "mixes",
          title: { ru: "Миксы для хостов", en: "Mixes for hosts" },
          keywords: {
            ru: "микс хост кастомка ротация соведущий",
            en: "mix host custom game rotation co-host",
          },
        },
        {
          slug: "achievements",
          title: { ru: "Достижения", en: "Achievements" },
          keywords: {
            ru: "достижения правила условия выдать отозвать пересчёт",
            en: "achievements rules conditions grant revoke recompute",
          },
        },
        {
          slug: "analytics",
          title: { ru: "Аналитика", en: "Analytics" },
          keywords: {
            ru: "аналитика рейтинг прогноз сдвиг качество матча пересчёт",
            en: "analytics rating prediction shift match quality recompute",
          },
        },
        {
          slug: "announcements",
          title: { ru: "Объявления и уведомления", en: "Announcements and notifications" },
          keywords: {
            ru: "объявление баннер уведомления discord",
            en: "announcement banner notifications discord",
          },
        },
      ],
    },
    {
      label: { ru: "Управление", en: "Administration" },
      articles: [
        {
          slug: "people",
          title: { ru: "Люди и доступ", en: "People and access" },
          keywords: {
            ru: "игроки участники аккаунты сессии api ключи журнал аудита",
            en: "players members accounts sessions api keys audit log",
          },
        },
        {
          slug: "content",
          title: { ru: "Контент и сбор данных", en: "Content and data collection" },
          keywords: {
            ru: "карты герои режимы нераспознанные сборщики ранги стримы",
            en: "maps heroes modes unresolved collectors ranks streams",
          },
        },
      ],
    },
    {
      label: { ru: "Помощь", en: "Help" },
      articles: [
        {
          slug: "playbooks",
          title: { ru: "Готовые сценарии", en: "Playbooks" },
          keywords: {
            ru: "сценарий пример турнир 5v5 драфт швейцарка микс",
            en: "playbook example tournament 5v5 draft swiss mix",
          },
        },
        {
          slug: "faq",
          title: { ru: "Вопросы и проблемы", en: "FAQ and troubleshooting" },
          keywords: {
            ru: "не работает ошибка проблема вопрос",
            en: "not working error problem question",
          },
        },
      ],
    },
  ],
  dev: [
    {
      label: { ru: "Начало", en: "Getting started" },
      articles: [
        {
          slug: "overview",
          title: { ru: "Обзор для разработчиков", en: "Developer overview" },
          keywords: {
            ru: "архитектура шлюз gateway интеграция api",
            en: "architecture gateway integration api",
          },
        },
        {
          slug: "contributing",
          title: { ru: "Участие в разработке", en: "Contributing" },
          keywords: {
            ru: "репозиторий локальный запуск docker ci pull request",
            en: "repository local setup docker ci pull request",
          },
        },
      ],
    },
    {
      label: { ru: "API", en: "API" },
      articles: [
        {
          slug: "identity",
          title: { ru: "Аутентификация и ключи API", en: "Authentication and API keys" },
          keywords: {
            ru: "jwt api-ключ токен скоупы oauth сессия квоты",
            en: "jwt api key token scopes oauth session quota",
          },
        },
        {
          slug: "api",
          title: { ru: "HTTP API", en: "HTTP API" },
          keywords: {
            ru: "v1 v2 envelope ошибки коды версии пагинация кэш",
            en: "v1 v2 envelope errors codes versions pagination cache",
          },
        },
        {
          slug: "realtime",
          title: { ru: "Realtime (WebSocket)", en: "Realtime (WebSocket)" },
          keywords: {
            ru: "websocket топик подписка replay события",
            en: "websocket topic subscribe replay events",
          },
        },
      ],
      links: [
        {
          href: "/api/docs",
          title: { ru: "Справочник эндпоинтов", en: "Endpoint reference" },
          keywords: { ru: "scalar openapi swagger v1 v2", en: "scalar openapi swagger v1 v2" },
          bypassNext: true,
        },
      ],
    },
    {
      label: { ru: "Предметная область", en: "Domain model" },
      articles: [
        {
          slug: "workspaces",
          title: { ru: "Воркспейсы и права", en: "Workspaces and permissions" },
          keywords: {
            ru: "tenant домен поддомен rbac роли участники",
            en: "tenant domain subdomain rbac roles members",
          },
        },
        {
          slug: "tournaments",
          title: { ru: "Турниры, стадии и сетка", en: "Tournaments, stages and brackets" },
          keywords: {
            ru: "фазы стадии сетка встречи таблица",
            en: "phases stages bracket encounters standings",
          },
        },
        {
          slug: "registration",
          title: { ru: "Регистрация и составы", en: "Registration and rosters" },
          keywords: {
            ru: "заявка допуск чек-ин ростер форма ростера команды капитанов",
            en: "registration admission check-in roster shape captain teams",
          },
        },
        {
          slug: "matches",
          title: { ru: "Встречи, результаты и логи", en: "Encounters, results and logs" },
          keywords: {
            ru: "встреча игра отчёт пик-бан лог матч статистика",
            en: "encounter game report pick ban log match statistics",
          },
        },
        {
          slug: "balancer",
          title: { ru: "Балансировщик, драфт и миксы", en: "Balancer, draft and mixes" },
          keywords: {
            ru: "балансировщик драфт микс кастомка капитаны",
            en: "balancer draft mix custom game captains",
          },
        },
      ],
    },
    {
      label: { ru: "Данные", en: "Data" },
      articles: [
        {
          slug: "data-model",
          title: { ru: "Модель данных", en: "Data model" },
          keywords: {
            ru: "postgres схемы таблицы идентичность erd",
            en: "postgres schemas tables identity erd",
          },
        },
      ],
      links: [
        {
          href: "/docs/dev/schema",
          title: { ru: "Схема БД", en: "Database schema" },
          keywords: { ru: "erd таблицы диаграмма alembic", en: "erd tables diagram alembic" },
        },
      ],
    },
  ],
};

export function isGuideId(value: string): value is GuideId {
  return (GUIDE_IDS as string[]).includes(value);
}

export function toDocLocale(locale: string): Locale {
  return locale === "en" ? "en" : "ru";
}

export function findGuideArticle(guide: GuideId, slug: string): GuideArticle | undefined {
  return GUIDES[guide].flatMap((group) => group.articles).find((article) => article.slug === slug);
}

export function guideGroups(guide: GuideId, locale: Locale): DocGroup[] {
  return GUIDES[guide].map((group) => ({
    label: group.label[locale],
    items: [
      ...group.articles.map((article) => ({
        href: `/docs/${guide}/${article.slug}`,
        title: article.title[locale],
        keywords: article.keywords[locale],
      })),
      ...(group.links ?? []).map((link) => ({
        href: link.href,
        title: link.title[locale],
        keywords: link.keywords[locale],
        bypassNext: link.bypassNext,
      })),
    ],
  }));
}

export function docSections(locale: Locale, labels: Record<GuideId, string>): DocSection[] {
  return GUIDE_IDS.map((id) => ({
    id,
    label: labels[id],
    href: `/docs/${id}`,
    groups: guideGroups(id, locale),
  }));
}
