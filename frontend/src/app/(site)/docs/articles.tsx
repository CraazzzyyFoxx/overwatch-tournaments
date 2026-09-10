import Link from "next/link";
import type { JSX, ReactNode } from "react";

import type { ArticleSlug } from "./nav";
import styles from "./docs.module.css";

function Api({ children }: Readonly<{ children: ReactNode }>) {
  return <code className={styles.code}>{children}</code>;
}

const ARTICLES: Record<ArticleSlug, () => JSX.Element> = {
  "": Overview,
  workspaces: Workspaces,
  identity: Identity,
  tournaments: Tournaments,
  registration: Registration,
  matches: Matches,
  balancer: Balancer,
  realtime: Realtime,
  api: ApiGuide,
};

export function Article({ slug }: Readonly<{ slug: ArticleSlug }>) {
  const Page = ARTICLES[slug];
  return (
    <article className={styles.prose}>
      <Page />
    </article>
  );
}

function Overview() {
  return (
    <>
      <h1>OWT — платформа турниров Overwatch</h1>
      <p className={styles.lead}>
        OWT проводит турнир от заявки до статистики: воркспейс организатора, сетка, драфт или
        балансировщик, разбор логов и публичная история игроков.
      </p>

      <h2>Кому это</h2>
      <ul>
        <li>
          <strong>Игрокам и зрителям</strong> — турниры, таблица, сетка, профили, стримы, регистрация
          команды.
        </li>
        <li>
          <strong>Организаторам</strong> — свой воркспейс: брендинг, домен, роли, сетка, чек-ин,
          veto, логи, достижения.
        </li>
        <li>
          <strong>Интеграциям</strong> — HTTP API с ключом воркспейса. Справочник:{" "}
          <a href="/api/docs">/api/docs</a>.
        </li>
      </ul>

      <h2>Как устроен продукт</h2>
      <p>
        Корень аренды — <strong>воркспейс</strong>. В нём живут турниры, участники, ранги и
        достижения. Запрос попадает в воркспейс по хосту (поддомен или свой домен) или явно через{" "}
        <Api>workspace_id</Api>.
      </p>
      <p>
        Турнир идёт фазами: регистрация → чек-ин → драфт или балансировка → live → финиш. Фаза —
        жизненный цикл, не путать со <strong>стейджем</strong> (группа, плей-офф).
      </p>

      <div className={styles.callout}>
        Живой сайт —{" "}
        <a href="https://owt.craazzzyyfoxx.me" rel="noreferrer">
          owt.craazzzyyfoxx.me
        </a>
        . Схема таблиц — <Link href="/docs/schema">/docs/schema</Link>. Эндпоинты —{" "}
        <a href="/api/docs">/api/docs</a>, переключатель v1/v2 в шапке справочника.
      </div>
    </>
  );
}

function Workspaces() {
  return (
    <>
      <h1>Воркспейсы</h1>
      <p className={styles.lead}>
        Воркспейс — изолированный мир организатора: участники, турниры, брендинг, домен и права.
      </p>

      <h2>Что в нём лежит</h2>
      <p>
        Почти каждая бизнес-строка несёт <Api>workspace_id</Api>, напрямую или через турнир /
        участника. Чужой воркспейс снаружи не читается: неизвестный id и «не ваш» отвечают одинаково
        404.
      </p>
      <ul>
        <li>Брендинг и тема, логотип, публичные страницы.</li>
        <li>Поддомен или подтверждённый свой домен.</li>
        <li>Участники (<Api>workspace_member</Api>) — якорь ростера, заявок, драфта, рангов.</li>
        <li>Роли и права (RBAC) плюс точечные запреты.</li>
        <li>API-ключи, привязанные к этому воркспейсу.</li>
      </ul>

      <h2>Доступ</h2>
      <p>
        Суперпользователь платформы видит всё. Остальные — только то, что дают роли воркспейса.
        Владелец воркспейса не обходит чужой tenant.
      </p>
      <p>
        Подробнее про логин, игрока и ключи — в{" "}
        <Link href="/docs/identity">аккаунтах и доступе</Link>.
      </p>
    </>
  );
}

function Identity() {
  return (
    <>
      <h1>Аккаунты и доступ</h1>
      <p className={styles.lead}>
        Логин и игрок — разные сущности. Ключ API никогда не шире прав владельца и не выходит за
        один воркспейс.
      </p>

      <h2>Логин и игрок</h2>
      <table>
        <thead>
          <tr>
            <th>Сущность</th>
            <th>Что это</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Логин</td>
            <td>
              <Api>auth.user</Api> — пароль, сессии, OAuth, ключи.
            </td>
          </tr>
          <tr>
            <td>Игрок</td>
            <td>
              <Api>players.user</Api> — BattleTag, статистика, история. Связь с логином не больше
              1:1.
            </td>
          </tr>
          <tr>
            <td>Виртуальный игрок</td>
            <td>Есть в логах или импорте, в систему не входил. <Api>auth_user_id</Api> пуст.</td>
          </tr>
        </tbody>
      </table>

      <h2>Чем входите</h2>
      <ul>
        <li>
          <strong>Сессия JWT</strong> — браузер. <Api>POST /api/auth/login</Api>, обновление через{" "}
          <Api>/api/auth/refresh</Api>. Несёт все роли и воркспейсы.
        </li>
        <li>
          <strong>API-ключ</strong> — <Api>aqt_sk_…</Api>, один воркспейс. Создаётся в{" "}
          <Api>POST /api/auth/api-keys</Api>, секрет показывается один раз. В заголовке{" "}
          <Api>Authorization: Bearer</Api>, как JWT.
        </li>
      </ul>
      <p>
        Операции «про меня» (выход, <Api>/api/auth/me</Api>, управление ключами) принимают только
        JWT. <Api>GET /api/auth/api-keys/self</Api> — наоборот, только ключ.
      </p>
    </>
  );
}

function Tournaments() {
  return (
    <>
      <h1>Турниры и сетка</h1>
      <p className={styles.lead}>
        Турнир живёт фазами. Сетка — это стейджи и рёбра между встречами, а не подразумеваемое
        дерево.
      </p>

      <h2>Фаза ≠ стейдж</h2>
      <ul>
        <li>
          <strong>Фаза</strong> — где турнир в жизни: регистрация, чек-ин, драфт, live, финиш. От
          неё зависят публичная страница и админка.
        </li>
        <li>
          <strong>Стейдж</strong> — соревновательный кусок: группа, швейцарка, плей-офф.
        </li>
      </ul>

      <h2>Сетка</h2>
      <p>
        Стейдж состоит из <em>stage item</em> (группа или ветка) и их входов. Встреча — серия между
        двумя командами. Кто куда проходит, задаёт <em>encounter link</em>: победитель или проигравший
        одной встречи занимает слот другой.
      </p>
      <p>
        Таблица стейджа считается на сервере: очки, тай-брейки (Бухгольц, личные встречи), места.
      </p>
    </>
  );
}

function Registration() {
  return (
    <>
      <h1>Регистрация и ростер</h1>
      <p className={styles.lead}>
        Заявка, чек-ин и состав команды. Форма ростера приходит с сервера уже посчитанной — клиент её
        не выводит заново.
      </p>

      <h2>Заявка</h2>
      <p>
        Игрок или команда подаёт заявку: роли, топ героев, статус. Можно подтянуть состав из Google
        Sheets. Допуск на регистрацию или чек-ин может требовать роль Discord или подписку Twitch.
      </p>
      <p>
        Чек-ин — подтверждение в окне времени, что заявка реально играет. Снять заявку — отдельное
        действие, не путать с чек-ином.
      </p>

      <h2>Ростер</h2>
      <p>
        Слот ростера указывает на <Api>workspace_member</Api>, не на голого игрока. Форма ростера —
        сколько слотов и каких ролей, например <Api>{"{tank: 1, dps: 2, support: 2}"}</Api> или шесть
        флексов. <Api>team_size</Api> и <Api>draft_rounds</Api> считаются из неё на сервере.
      </p>
    </>
  );
}

function Matches() {
  return (
    <>
      <h1>Встречи и логи</h1>
      <p className={styles.lead}>
        Встреча — серия. Матч — одна сыгранная карта. Лог парсится в статистику, киллфид и ассисты.
      </p>

      <h2>Встреча и матч</h2>
      <p>
        Best-of-3 — одна встреча, до трёх матчей. Капитаны сдают отчёт по серии; при расхождении
        организатор подтверждает счёт. Форма отчёта настраивается на турнир.
      </p>

      <h2>Veto</h2>
      <p>
        Пул карт стейджа сужается пиками и банами. Резервная карта — на тай. Кто банит первым,
        задаётся правилом сида, не «ротацией».
      </p>

      <h2>Логи</h2>
      <p>
        Файл лога Overwatch грузится организатором или Discord-ботом. Парсер пишет матчи, покруговую
        статистику, киллфид. С лога считаются достижения и MVP impact.
      </p>
    </>
  );
}

function Balancer() {
  return (
    <>
      <h1>Балансировщик и драфт</h1>
      <p className={styles.lead}>
        Два способа собрать команды: солвер или живой драфт капитанов. Турнир выбирает один.
      </p>

      <h2>Балансировщик</h2>
      <p>
        Многокритериальный генетический поиск (Rust <Api>tournament_balancer</Api>). Учитывает ранг, роли,
        комфорт, тильт. Результат — набор составов, который организатор принимает.
      </p>

      <h2>Драфт</h2>
      <p>
        Капитаны пикают змейкой. Часы и состояние — на сервере, оптимистичная конкуренция по{" "}
        <Api>version</Api>. Публичная страница и админка смотрят один realtime-топик.
      </p>
    </>
  );
}

function Realtime() {
  return (
    <>
      <h1>Realtime</h1>
      <p className={styles.lead}>
        Сетка, драфт, veto и стримы идут по WebSocket. После обрыва соединение добирает пропущенные
        события.
      </p>

      <h2>Куда подключаться</h2>
      <p>
        <Api>/ws</Api> и <Api>/api/realtime/ws</Api>. Сессия JWT или API-ключ. Ключ без грантов в
        воркспейсе коннектится как аноним и не подписаться на закрытые топики.
      </p>

      <h2>Топики</h2>
      <table>
        <thead>
          <tr>
            <th>Топик</th>
            <th>Кто видит</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <Api>tournament:{"{id}"}:bracket</Api>, <Api>:draft</Api>, <Api>:streams</Api>
            </td>
            <td>Публично, пока турнир не скрыт</td>
          </tr>
          <tr>
            <td>
              <Api>encounter:{"{id}"}:map-veto</Api>
            </td>
            <td>То же правило скрытости, через турнир встречи</td>
          </tr>
          <tr>
            <td>
              <Api>tournament:{"{id}"}:balancer</Api>
            </td>
            <td>Участник воркспейса</td>
          </tr>
        </tbody>
      </table>
      <p>
        Replay читается из <Api>realtime.workspace_event</Api>. У недолговечных топиков строки нет —
        после реконнекта догонять нечего.
      </p>
    </>
  );
}

function ApiGuide() {
  return (
    <>
      <h1>HTTP API</h1>
      <p className={styles.lead}>
        Один шлюз на весь HTTP. v1 — развёрнутый JSON, v2 — тот же путь и статус, тело — RPC
        envelope. Справочник методов: <a href="/api/docs">/api/docs</a>.
      </p>

      <h2>Версии</h2>
      <table>
        <thead>
          <tr>
            <th></th>
            <th>v1</th>
            <th>v2</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Префикс</td>
            <td>
              <Api>/api/v1</Api>, плюс <Api>/api/auth</Api>
            </td>
            <td>
              <Api>/api/v2</Api>. Auth остаётся на v1
            </td>
          </tr>
          <tr>
            <td>Успех</td>
            <td>Голый ресурс</td>
            <td>
              <Api>{"{ok: true, data, warnings?}"}</Api>
            </td>
          </tr>
          <tr>
            <td>Ошибка</td>
            <td>
              <Api>{"{detail, code?, fields?, retry_after?}"}</Api>
            </td>
            <td>
              <Api>{"{ok: false, error: {code, message, details?}}"}</Api>
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        Ветвитесь по <Api>code</Api> / <Api>error.code</Api>. Человеческое сообщение показывайте,
        не парсите.
      </p>

      <h2>Коды</h2>
      <table>
        <thead>
          <tr>
            <th>code</th>
            <th>HTTP</th>
            <th>Когда</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <Api>unauthorized</Api>
            </td>
            <td>401</td>
            <td>Нет или протух bearer. На session-only маршрутах — и ключ.</td>
          </tr>
          <tr>
            <td>
              <Api>forbidden</Api>
            </td>
            <td>403</td>
            <td>Аутентифицирован, но нет права, воркспейса или скоупа.</td>
          </tr>
          <tr>
            <td>
              <Api>not_found</Api>
            </td>
            <td>404</td>
            <td>Нет id или id чужого воркспейса.</td>
          </tr>
          <tr>
            <td>
              <Api>unprocessable</Api>
            </td>
            <td>422</td>
            <td>JSON прошёл, схема или правило — нет. Смотрите <Api>fields</Api>.</td>
          </tr>
          <tr>
            <td>
              <Api>rate_limited</Api>
            </td>
            <td>429</td>
            <td>
              Ждите <Api>retry_after</Api> секунд и заголовок <Api>Retry-After</Api>.
            </td>
          </tr>
        </tbody>
      </table>

      <h2>Воркспейс в запросе</h2>
      <p>
        Чтения с арендой принимают <Api>workspace_id</Api>. У ключа он один — параметр можно не
        слать, шлюз подставит. Явное значение всегда побеждает. Сессия с несколькими воркспейсами
        должна указать один, иначе отказ, без угадывания.
      </p>
    </>
  );
}
