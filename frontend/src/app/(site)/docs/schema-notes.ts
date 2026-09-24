import type { Locale } from "@/i18n/resolve-locale";

type Note = { title: Record<Locale, string>; description: Record<Locale, string> };

/**
 * Human titles for the model packages in `schema.generated.json`. The tables and
 * diagrams are generated; only this prose is written by hand, and it changes when
 * a package's purpose does, not when a column does. A package missing here still
 * renders, under its key and without a description.
 */
export const PACKAGE_NOTES: Record<string, Note> = {
  identity: {
    title: { ru: "Идентичность", en: "Identity" },
    description: {
      ru: "Учётные записи, refresh-токены, OAuth-подключения, API-ключи, каталог прав RBAC с оверлеем запретов, доменный игрок и журнал слияний игроков.",
      en: "Login accounts, refresh tokens, OAuth connections, API keys, the grant-only RBAC catalog with its deny overlay, the domain player and the audit trail of player merges.",
    },
  },
  tenancy: {
    title: { ru: "Воркспейсы", en: "Tenancy" },
    description: {
      ru: "Корень арендатора и якорь членства, а также настройки воркспейса: брендинг, поддомен и свой домен, сервер Discord, форма ростера и сетка дивизионов по умолчанию.",
      en: "The tenant root and its membership anchor, plus workspace settings: branding, subdomain and custom domain, Discord guild binding, default roster shape and division grid.",
    },
  },
  member_rank: {
    title: { ru: "Ранги участников", en: "Member ranks" },
    description: {
      ru: "Ранг игрока внутри воркспейса в двух слоях, которые никогда не сливаются: общий канон воркспейса и личная книга каждого автора рангов.",
      en: "A player's rank inside one workspace, in two layers that are never merged: the workspace canon and each ranking author's own book.",
    },
  },
  catalog: {
    title: { ru: "Справочник игры", en: "Game catalog" },
    description: {
      ru: "Герои, карты и режимы, а также журнал названий из логов, которые не распознал ни один алиас.",
      en: "Heroes, maps and game modes, plus the log of names from match logs that no alias resolves.",
    },
  },
  division_grid: {
    title: { ru: "Сетки дивизионов", en: "Division grids" },
    description: {
      ru: "Версионируемые сетки рангов: тиры с диапазонами SR и маппинги между версиями, чтобы ранги оставались сопоставимыми между сезонами.",
      en: "Versioned rank grids: tiers with SR ranges and mappings between versions, so ranks stay comparable across seasons.",
    },
  },
  ranks: {
    title: { ru: "Телеметрия рангов", en: "Rank telemetry" },
    description: {
      ru: "Ранги Overwatch, собираемые по привязанным BattleTag: ряд снимков, состояние опроса по каждому BattleTag и журнал запросов.",
      en: "Overwatch ranks polled for linked BattleTags: the snapshot series, the per-BattleTag fetch state and the fetch log.",
    },
  },
  tournament: {
    title: { ru: "Турниры", en: "Tournaments" },
    description: {
      ru: "Турнир и его жизненный цикл, стадии и их элементы, команды и ростеры, встречи, игры серии и рёбра продвижения, из которых состоит сетка, пик-бан, отчёты, таблицы, скрим-комнаты и синхронизация с Challonge.",
      en: "The tournament and its lifecycle, stages and stage items, teams and rosters, encounters, encounter games and the advancement edges that form the bracket, pick-ban, reports, standings, scrim rooms and the Challonge sync.",
    },
  },
  registration: {
    title: { ru: "Регистрация", en: "Registration" },
    description: {
      ru: "Формы регистрации и их поля, заявки игроков и команд, роли и топ-герои, приглашения в команды и привязка импорта из Google Sheets.",
      en: "Registration forms and their fields, player and team applications, roles and top-hero preferences, team invites and the Google Sheets import binding.",
    },
  },
  balancer: {
    title: { ru: "Балансировщик и драфт", en: "Balancer and draft" },
    description: {
      ru: "Запуски балансировщика и получившиеся команды, а также живой драфт: сессии, капитаны, пул игроков, последовательность пиков и журнал.",
      en: "Balancing runs and their resulting teams, and the live draft: sessions, captains, the player pool, the pick sequence and its audit trail.",
    },
  },
  custom_game: {
    title: { ru: "Миксы", en: "Mixes" },
    description: {
      ru: "Кастомные игры воркспейса: игра, хост и соведущие, состав, ограничения по ролям и «обязательно играет», слоты ролей команды.",
      en: "Workspace custom games: the game, its host and co-hosts, the lineup, per-player role and must-play constraints, and the role slots of a team.",
    },
  },
  casual: {
    title: { ru: "Неформальные матчи", en: "Casual matches" },
    description: {
      ru: "Матчи, записанные вне турнирной сетки.",
      en: "Matches recorded outside a tournament bracket.",
    },
  },
  matches: {
    title: { ru: "Матчи из логов", en: "Match logs" },
    description: {
      ru: "Разобранные логи: строка на сыгранную карту, статистика по раундам, киллфид, ассисты и статистические базовые линии.",
      en: "Parsed match logs: one row per played map, per-round statistics, the kill feed, assists and the statistical baselines derived from them.",
    },
  },
  ingestion: {
    title: { ru: "Загрузка логов", en: "Log ingestion" },
    description: {
      ru: "Конвейер загрузки и разбора: запись на каждый обработанный файл и каналы Discord, из которых приходят логи.",
      en: "The upload and parse pipeline: a record per processed log file, and the Discord channels logs arrive from.",
    },
  },
  achievements: {
    title: { ru: "Достижения", en: "Achievements" },
    description: {
      ru: "Декларативный движок достижений: правила как JSON-деревья условий, результаты их вычисления, ручные выдачи и отзывы, журнал запусков.",
      en: "The declarative achievement engine: rules as JSON condition trees, their evaluation results, the manual grant/revoke overlay and evaluation runs.",
    },
  },
  analytics: {
    title: { ru: "Аналитика", en: "Analytics" },
    description: {
      ru: "Сигналы поверх результатов турниров и логов: сдвиги рейтинга, результативность игроков, распределения мест, качество встреч и аномалии.",
      en: "Signals computed from tournament results and match logs: rating shifts, player performance, placement distributions, encounter quality and anomalies.",
    },
  },
  subscriptions: {
    title: { ru: "Подписки", en: "Subscriptions" },
    description: {
      ru: "Проверка подписок как условие допуска: как воркспейс проверяет подписку у провайдера, что требует, последние вердикты и журнал проверок.",
      en: "Subscription checks as an admission condition: how a workspace verifies subscriptions with a provider, what it requires, the latest verdicts and the check log.",
    },
  },
  preferences: {
    title: { ru: "Предпочтения", en: "Preferences" },
    description: {
      ru: "Настройки аккаунта: избранные игроки и сохранённые виды встреч.",
      en: "Per-account preferences: favourite players and saved encounter views.",
    },
  },
  platform: {
    title: { ru: "Платформа", en: "Platform" },
    description: {
      ru: "Междоменная инфраструктура: transactional outbox, журнал realtime-событий для replay, журнал аудита, уведомления и чат комнат.",
      en: "Cross-domain infrastructure: the transactional outbox, the realtime event journal replays come from, the audit log, notifications and room chat.",
    },
  },
  quota: {
    title: { ru: "Квоты", en: "Quotas" },
    description: {
      ru: "Квоты на принципала: планы с лимитом на каждую область (воркспейс, ключ, сессия), переопределения для воркспейса и ключа, каталог операций.",
      en: "Per-principal quotas: plans with a limit per scope (workspace, key, session), workspace and key overrides, and the operation catalog.",
    },
  },
};
