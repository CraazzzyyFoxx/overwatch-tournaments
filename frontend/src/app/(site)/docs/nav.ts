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

export type GuideId = "players" | "organizers";
export type SectionId = GuideId | "dev";

export type DocSection = {
  id: SectionId;
  label: string;
  href: string;
  groups: DocGroup[];
};

type GuideArticle = { slug: string; title: Localized; keywords: Localized };
type GuideGroup = { label: Localized; articles: GuideArticle[] };

/**
 * Player and organizer guides. Each article is one MDX file per locale at
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
            ru: "профиль статистика ранг дивизион сравнение mvp влияние аналитика owal",
            en: "profile statistics rank division compare mvp impact analytics owal",
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
};

/** Developer articles. Russian only, like their content in `articles.tsx`. */
const DEV_GROUPS: DocGroup[] = [
  {
    label: "Платформа",
    items: [
      { href: "/docs/dev", title: "Обзор", keywords: "owt платформа воркспейс tenant" },
      { href: "/docs/dev/workspaces", title: "Воркспейсы", keywords: "домен rbac members branding" },
      { href: "/docs/dev/identity", title: "Аккаунты и доступ", keywords: "oauth jwt api key player session" },
    ],
  },
  {
    label: "Турниры",
    items: [
      { href: "/docs/dev/tournaments", title: "Турниры и сетка", keywords: "stage bracket standings phase" },
      { href: "/docs/dev/registration", title: "Регистрация и ростер", keywords: "check-in roster shape sheets" },
      { href: "/docs/dev/matches", title: "Встречи и логи", keywords: "encounter match report veto log" },
      { href: "/docs/dev/balancer", title: "Балансировщик и драфт", keywords: "balancer draft captains" },
      { href: "/docs/dev/realtime", title: "Realtime", keywords: "websocket topic replay" },
    ],
  },
  {
    label: "API",
    items: [
      { href: "/docs/dev/api", title: "HTTP API", keywords: "v1 v2 envelope auth errors openapi" },
      {
        href: "/api/docs",
        title: "Справочник эндпоинтов",
        keywords: "scalar swagger openapi v1 v2",
        bypassNext: true,
      },
    ],
  },
  {
    label: "Данные",
    items: [
      { href: "/docs/dev/schema", title: "Схема БД", keywords: "erd postgres таблицы alembic" },
    ],
  },
];

export const ARTICLE_SLUGS = [
  "workspaces",
  "identity",
  "tournaments",
  "registration",
  "matches",
  "balancer",
  "realtime",
  "api",
] as const;

export type ArticleSlug = (typeof ARTICLE_SLUGS)[number] | "";

export function isArticleSlug(slug: string): slug is Exclude<ArticleSlug, ""> {
  return (ARTICLE_SLUGS as readonly string[]).includes(slug);
}

export function isGuideId(value: string): value is GuideId {
  return value === "players" || value === "organizers";
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
    items: group.articles.map((article) => ({
      href: `/docs/${guide}/${article.slug}`,
      title: article.title[locale],
      keywords: article.keywords[locale],
    })),
  }));
}

export function docSections(locale: Locale, labels: Record<SectionId, string>): DocSection[] {
  return [
    { id: "players", label: labels.players, href: "/docs/players", groups: guideGroups("players", locale) },
    {
      id: "organizers",
      label: labels.organizers,
      href: "/docs/organizers",
      groups: guideGroups("organizers", locale),
    },
    { id: "dev", label: labels.dev, href: "/docs/dev", groups: DEV_GROUPS },
  ];
}
