/* OWT redesign mock kit — runtime shared by the three page mockups.
 *
 * Not production code. It exists so the mockups behave like the product:
 * real data (owt-data.js), real chrome behaviour (popovers close on Esc and
 * outside click, focus returns to the trigger, the mobile sheet traps focus),
 * and every page state reachable from the dev panel and deep-linkable via the
 * URL hash. Each render function here maps to one React component.
 */
(() => {
  const D = window.OWT_DATA;
  /** Mock "now" = snapshot day, so relative dates in the mock do not drift. */
  const NOW = new Date("2026-10-08T12:00:00Z");

  // ── templating ─────────────────────────────────────────────────────────
  class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
  const raw = (s) => new Raw(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const out = (v) => (v == null || v === false ? "" : v instanceof Raw ? v.s : Array.isArray(v) ? v.map(out).join("") : esc(v));
  function html(strings, ...vals) {
    let s = strings[0];
    vals.forEach((v, i) => { s += out(v) + strings[i + 1]; });
    return raw(s);
  }
  const icon = (n, cls = "") => raw(`<svg class="icon ${cls}" aria-hidden="true" focusable="false"><use href="#i-${n}"/></svg>`);

  // ── formatting (next-intl in the app; ru-RU here) ──────────────────────
  const nf = new Intl.NumberFormat("ru-RU");
  const pf = new Intl.NumberFormat("ru-RU", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const df = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", timeZone: "Europe/Moscow" });
  const dfy = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Moscow" });
  const dfm = new Intl.DateTimeFormat("ru-RU", { month: "short", year: "numeric", timeZone: "Europe/Moscow" });
  const dtf = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" });
  const rtf = new Intl.RelativeTimeFormat("ru", { numeric: "auto" });
  const plural = (n, [one, few, many]) => {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  };
  const fmt = {
    num: (n) => nf.format(n),
    pct: (v) => pf.format(v),
    date: (iso) => df.format(new Date(iso)),
    dateLong: (iso) => dfy.format(new Date(iso)),
    month: (iso) => { const d = new Date(iso); return `${dfm.format(d).replace(/\.|\s*г\.?$/g, "").split(" ")[0]} ${d.getUTCFullYear()}`; },
    dateTime: (iso) => dtf.format(new Date(iso)),
    range(a, b) {
      if (!b || a.slice(0, 10) === b.slice(0, 10)) return df.format(new Date(a));
      const A = new Date(a), B = new Date(b);
      if (A.getUTCMonth() === B.getUTCMonth()) return `${A.getUTCDate()}–${df.format(B)}`;
      return `${df.format(A)} – ${df.format(B)}`;
    },
    /** design-book §6: relative date + absolute in `title`. Past 30 days it is just the date. */
    rel(iso) {
      const ms = new Date(iso) - NOW, abs = Math.abs(ms);
      if (abs < 36e5) return rtf.format(Math.round(ms / 6e4), "minute");
      if (abs < 864e5) return rtf.format(Math.round(ms / 36e5), "hour");
      if (abs < 30 * 864e5) return rtf.format(Math.round(ms / 864e5), "day");
      return df.format(new Date(iso));
    },
    plural,
    count: (n, forms) => `${nf.format(n)} ${plural(n, forms)}`,
  };

  // ── domain helpers ─────────────────────────────────────────────────────
  const FALLBACK_ACCENTS = ["var(--aqt-teal)", "var(--aqt-blue)", "var(--aqt-amber)", "var(--aqt-violet)", "var(--aqt-emerald)", "var(--aqt-rose)"];
  const community = (slug) => D.communities.find((c) => c.slug === slug);
  const initials = (name) => name.replace(/[^\p{L}\p{N} ]/gu, "").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  /** The address shown to people: a verified custom domain only. Platform subdomains
   *  (<sub>.owt.craazzzyyfoxx.me) are plumbing and never displayed. */
  const host = (c) => (c.customDomain && c.customDomainVerified ? c.customDomain : null);

  /** WorkspaceAvatar: uploaded icon, initials on a deterministic accent otherwise. */
  function wsAvatar(c, size = 32, cls = "") {
    const a = FALLBACK_ACCENTS[c.id % FALLBACK_ACCENTS.length];
    const ini = initials(c.name);
    return html`<span class="ws-avatar ${cls}" style="--s:${size}px;--a:${a}" aria-hidden="true">${c.icon
      ? raw(`<img src="${esc(c.icon)}" alt="" width="${size}" height="${size}" loading="lazy" decoding="async" onerror="this.parentNode.textContent='${esc(ini)}'">`)
      : ini}</span>`;
  }
  const trustedBadge = (c) => (c.verification === "trusted"
    ? html`<span title="Доверенное сообщество — проверено командой платформы" style="display:inline-flex"><svg class="icon trusted" role="img" aria-label="Доверенное сообщество"><use href="#i-badge-check"/></svg></span>`
    : "");

  /** TOURNAMENT_STATUS_META (lib/tournament/status.ts) → pill variant + RU label. */
  const STATUS = {
    announcement: ["upcoming", "Анонс"], registration: ["upcoming", "Регистрация"], check_in: ["upcoming", "Чек-ин"],
    draft: ["draft", "Драфт"], live: ["live", "Идёт"], playoffs: ["live", "Плей-офф"],
    completed: ["finished", "Завершён"], archived: ["finished", "Архив"],
  };
  const statusPill = (status, label) => {
    const [v, l] = STATUS[status];
    return html`<span class="pill pill--${v}">${v === "live" ? raw('<span class="live-dot" aria-hidden="true"></span>') : ""}${label ?? l}</span>`;
  };
  const roleIcon = (role, size = 18) => html`<img src="frontend/public/roles/${role}.png" alt="" width="${size}" height="${size}" style="width:${size}px;height:${size}px;object-fit:contain" aria-hidden="true">`;

  // ── workspace palette (port of lib/workspace/theme.ts deriveWorkspacePalette) ─
  // ONE deliberate divergence, flagged in the report: the app derives the text
  // ramp as 96/62/42/32 % L, which drops --aqt-fg-dim/-faint under WCAG AA on a
  // branded tenant — the exact regression globals.css lifted to 58/52 for.
  // The mock uses the design-book ramp (96/65/58/52).
  const clamp = (n, a, b) => Math.min(b, Math.max(a, n));
  function hexToHsl(hex) {
    if (!hex) return null;
    const v = hex.replace("#", "");
    const r = parseInt(v.slice(0, 2), 16) / 255, g = parseInt(v.slice(2, 4), 16) / 255, b = parseInt(v.slice(4, 6), 16) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min, l = (max + min) / 2;
    let h = 0, s = 0;
    if (d) {
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      h = (max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4) * 60;
    }
    return { h, s: s * 100, l: l * 100 };
  }
  function hslToRgb({ h, s, l }) {
    s /= 100; l /= 100;
    const k = (n) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
    const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return [f(0), f(8), f(4)];
  }
  const lum = (rgb) => { const [r, g, b] = rgb.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const onColor = (hsl) => { const L = lum(hslToRgb(hsl)); return (L + 0.05) / 0.05 > 1.05 / (L + 0.05) ? "hsl(0 0% 9%)" : "hsl(0 0% 98%)"; };
  const H = ({ h, s, l }) => `hsl(${Math.round(h)} ${Math.round(clamp(s, 0, 100))}% ${Math.round(clamp(l, 0, 100))}%)`;
  function derivePalette(b) {
    const p = hexToHsl(b?.brand_primary), bg0 = hexToHsl(b?.brand_background);
    if (!p || !bg0) return null;
    const bg = { h: bg0.h, s: clamp(bg0.s, 0, 45), l: clamp(bg0.l, 4, 14) };
    const sf0 = hexToHsl(b.brand_surface);
    const surface = sf0 ? { h: sf0.h, s: clamp(sf0.s, 0, 45), l: clamp(sf0.l, 6, 16) } : { ...bg, l: clamp(bg.l + 2, 6, 16) };
    const accent = { h: p.h, s: clamp(p.s, 30, 95), l: clamp(p.l, 40, 70) };
    const sec0 = hexToHsl(b.brand_secondary);
    const secondary = sec0 ? { h: sec0.h, s: clamp(sec0.s, 30, 95), l: clamp(sec0.l, 40, 70) } : accent;
    const bd0 = hexToHsl(b.brand_border);
    const fg0 = hexToHsl(b.brand_foreground);
    return {
      "--aqt-bg": H(bg), "--aqt-bg-2": H({ ...bg, l: clamp(bg.l + 1, 4, 16) }),
      "--aqt-card": H(surface), "--aqt-card-2": H({ ...surface, l: clamp(surface.l + 1, 6, 18) }),
      "--aqt-border": H(bd0 ? { h: bd0.h, s: clamp(bd0.s, 0, 45), l: clamp(bd0.l, 6, 34) } : { ...surface, l: clamp(surface.l + 6, 8, 24) }),
      "--aqt-border-2": H({ ...surface, l: clamp(surface.l + 10, 10, 28) }), "--aqt-border-3": H({ ...surface, l: clamp(surface.l + 14, 12, 32) }),
      "--aqt-fg": H(fg0 ?? { h: bg.h, s: 16, l: 96 }),
      "--aqt-fg-muted": H({ h: bg.h, s: 12, l: 65 }), "--aqt-fg-dim": H({ h: bg.h, s: 10, l: 58 }), "--aqt-fg-faint": H({ h: bg.h, s: 10, l: 52 }),
      "--aqt-teal": H(accent), "--aqt-violet": H(secondary), "--aqt-on-teal": onColor(accent),
    };
  }
  let appliedVars = [];
  function applyPalette(branding) {
    const el = document.documentElement;
    appliedVars.forEach((n) => el.style.removeProperty(n));
    appliedVars = [];
    const map = branding ? derivePalette(branding) : null;
    if (!map) return;
    for (const [k, v] of Object.entries(map)) { el.style.setProperty(k, v); appliedVars.push(k); }
  }

  // ── chrome: navigation tree (components/site/site-nav-groups.ts) ───────
  // Groups open a menu; the two non-tournament destinations are plain links —
  // a two-item menu under a vague verb ("Играть") cost a click and a guess.
  const NAV = [
    { key: "tournaments", label: "Турниры", items: [["Турниры", "Расписание и архив", "trophy"], ["Встречи", "Все серии матчей", "swords"], ["Аналитика", "Турниры в сравнении", "chart-column"]] },
    { key: "users", label: "Игроки", items: [["Игроки", "Поиск и профили", "users"], ["Сравнение", "Два игрока рядом", "layers"], ["Рейтинг героев", "Лучшие на каждом герое", "list-ordered"], ["Достижения", "Редкие и общие", "crown"]] },
    { key: "mixes", label: "Миксы", href: "#", icon: "shuffle" },
    { key: "scrims", label: "Скримы", href: "#", icon: "monitor-play" },
  ];
  const NAV_LINKS = NAV.filter((n) => n.href);
  const LINK_META = {
    discord: { label: "Discord", img: "frontend/public/discord-white.svg", tint: "var(--aqt-brand-discord)" },
    twitch: { label: "Twitch", img: "frontend/public/twitch.png", tint: "var(--aqt-brand-twitch)" },
    boosty: { label: "Boosty", img: "frontend/public/boosty.svg", tint: "var(--aqt-brand-boosty)" },
  };

  function searchNames() {
    const set = new Set();
    for (const l of [D.platform.champions, D.platform.winrate, ...Object.values(D.workspaces).flatMap((w) => [w.champions, w.winrate])]) l.forEach((p) => set.add(p.name));
    for (const w of Object.values(D.workspaces)) w.chronicle.forEach((t) => t.winner?.players.forEach((n) => set.add(n)));
    return [...set];
  }
  const RECENT = ["Zuuuuuuuuuuz#2690", "Tref#2420"];

  function activeEventsPop(active) {
    const groups = {};
    for (const t of active) (groups[t.workspace] ??= []).push(t);
    const nWs = Object.keys(groups).length;
    return html`
      <div class="pop pop--end pop--wide" id="pop-active" role="dialog" aria-label="Активные события" hidden>
        <div style="padding:8px 10px 10px;border-bottom:1px solid var(--aqt-border);margin:-6px -6px 6px">
          <div style="font-weight:600">Активные события</div>
          <div class="dim" style="font-size:var(--text-caption)">${fmt.count(active.length, ["активное событие", "активных события", "активных событий"])} в ${fmt.count(nWs, ["сообществе", "сообществах", "сообществах"])}</div>
        </div>
        ${Object.entries(groups).map(([slug, list]) => {
          const c = community(slug);
          return html`
            <div class="pop__label" style="display:flex;align-items:center;gap:8px">${wsAvatar(c, 20)}<span style="flex:1;font-size:var(--text-caption);font-weight:600;color:var(--aqt-fg-muted)">${c.name}</span></div>
            ${list.map((t) => html`
              <a class="menu-item" href="#">
                <span class="grow"><span style="font-weight:600">${t.name}</span><small>${STATUS[t.status][1]} · ${t.status === "registration" || t.status === "check_in" ? fmt.count(t.registrations, ["заявка", "заявки", "заявок"]) : fmt.count(t.participants, ["участник", "участника", "участников"])}</small></span>
                <span class="dim tnum" style="font-size:var(--text-caption)" title="${fmt.dateLong(t.start)}">${fmt.date(t.start)}</span>
              </a>`)}`;
        })}
      </div>`;
  }

  function switcherPop(current) {
    return html`
      <div class="pop" id="pop-switcher" role="menu" aria-label="Сообщества" hidden>
        <div class="pop__label eyebrow">Сообщества</div>
        <a class="menu-item" role="menuitem" href="OWT Platform Landing.html" ${current ? "" : raw('aria-current="page"')}>
          <span class="ws-avatar" style="--s:24px;--a:var(--aqt-teal)" aria-hidden="true">${icon("globe", "icon--sm")}</span>
          <span class="grow"><span>Все сообщества</span></span>${current ? "" : icon("check")}
        </a>
        ${D.communities.map((c) => html`
          <a class="menu-item" role="menuitem" href="OWT Workspace Final.html#ws=${c.slug}" ${current?.slug === c.slug ? raw('aria-current="page"') : ""}>
            ${wsAvatar(c, 24)}
            <span class="grow"><span>${c.name}</span>${host(c) ? html`<small>${host(c)}</small>` : ""}</span>
            ${current?.slug === c.slug ? icon("check") : ""}
          </a>`)}
        <div class="pop__sep"></div>
        <a class="menu-item menu-item--muted" role="menuitem" href="OWT Get Workspace.html">${icon("plus")}<span class="grow"><span>Создать сообщество</span></span></a>
      </div>`;
  }

  /** Account menu only: the inbox moved to its own bell (decision Q1 of the notifications round). */
  function userPop() {
    return html`
      <div class="pop pop--end pop--wide" id="pop-user" role="dialog" aria-label="Аккаунт" hidden>
        <div style="display:flex;align-items:center;gap:12px;padding:8px 10px 12px">
          <span class="user-btn" style="cursor:default" aria-hidden="true">CF</span>
          <span style="min-width:0"><span style="display:block;font-weight:600">CraazzzyyFoxx</span><small class="dim">Игрок: <a href="#" style="color:var(--aqt-teal)">[ваш BattleTag]</a></small></span>
        </div>
        <div class="pop__sep"></div>
        <a class="menu-item" href="#">${icon("user")}<span class="grow"><span>Мой профиль</span></span></a>
        <a class="menu-item" href="#">${icon("layout-dashboard")}<span class="grow"><span>Панель управления</span></span></a>
        <button class="menu-item" type="button">${icon("settings")}<span class="grow"><span>Настройки аккаунта</span></span></button>
        <div class="pop__sep"></div>
        <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 10px"><span class="dim">Язык</span>${langSwitch()}</div>
        <div class="pop__sep"></div>
        <button class="menu-item menu-item--muted" type="button">${icon("log-out")}<span class="grow"><span>Выйти</span></span></button>
      </div>`;
  }

  // ── notifications (components/notifications/*, hooks/useNotifications.ts) ──
  // EXAMPLE inbox: real tournaments, teams and communities; the events themselves
  // are simulated. Kinds, wording and actions follow the 13 kinds the backend
  // emits (shared/services/notifications.py) and ru.json `notifications.kinds`.
  const NOTIF_KIND = {
    "team_invite.received": ["user-plus", "var(--aqt-blue)"],
    "team_invite.answered": ["user-plus", "var(--aqt-blue)"],
    "registration.approved": ["circle-check", "var(--aqt-emerald)"],
    "registration.rejected": ["circle-x", "var(--aqt-rose)"],
    "team.kicked": ["circle-x", "var(--aqt-rose)"],
    "team.rejected": ["circle-x", "var(--aqt-rose)"],
    "team.disbanded": ["circle-x", "var(--aqt-rose)"],
    "encounter.report_disputed": ["triangle-alert", "var(--aqt-amber)"],
    "encounter.dispute_review": ["gavel", "var(--aqt-rose)"],
    "registration.opened": ["calendar-plus", "var(--aqt-teal)"],
    "check_in.opened": ["clipboard-check", "var(--aqt-amber)"],
    "encounter.scheduled": ["calendar-clock", "var(--aqt-blue)"],
    "announcement.published": ["megaphone", "var(--aqt-teal)"],
  };
  /** Kinds a single click resolves — the same rule the Discord bot buttons follow. Value = urgency rank. */
  const ACTIONABLE = { "check_in.opened": 1, "team_invite.received": 2 };
  const ago = (h) => new Date(NOW.getTime() - h * 36e5).toISOString();
  const ANNOUNCEMENT = { title: "Смотреть миксы теперь можно без входа", href: "#" };
  const exampleInbox = () => [
    { id: 1, kind: "check_in.opened", ws: "moonrise", at: ago(0.3), read: false, p: { tournament_name: "SEITA: Last Duel", closes_at: "2026-10-10T13:30:00Z" } },
    { id: 2, kind: "team_invite.received", ws: "jaristo-squad", at: ago(3), read: false, p: { team_name: "Press W.", tournament_name: "OWT #2", slot: "Поддержка" } },
    { id: 3, kind: "announcement.published", ws: null, at: ago(20), read: false, p: ANNOUNCEMENT },
    { id: 4, kind: "registration.approved", ws: "moonrise", at: ago(44), read: true, p: { tournament_name: "SEITA: Last Duel" } },
    { id: 5, kind: "registration.opened", ws: "moonrise", at: "2026-10-05T15:45:00Z", read: true, p: { tournament_name: "SEITA: Last Duel", closes_at: "2026-10-10T09:00:00Z" } },
    { id: 6, kind: "encounter.scheduled", ws: "anak", at: "2026-06-12T10:00:00Z", read: true, p: { home: "Tref", away: "Lynxx", tournament_name: "Турнир Сабов Anakq #42", scheduled_at: "2026-06-13T15:00:00Z" } },
  ];
  const OLDER = [
    { id: 7, kind: "encounter.report_disputed", ws: "anak", at: "2026-03-14T19:10:00Z", read: true, p: { map_index: 2 } },
    { id: 8, kind: "registration.approved", ws: "anak", at: "2026-03-10T12:00:00Z", read: true, p: { tournament_name: "Турнир Сабов Anakq #41" } },
  ];
  const DONE = { "check_in.opened": "Чек-ин пройден", "team_invite.received": "Вы приняли приглашение" };

  let inbox = { mode: null, items: [], more: true, tenant: null, lastDone: null };
  function useInbox(mode, tenant) {
    if (inbox.mode !== mode) {
      const items = mode === "empty" || mode === "error" ? [] : exampleInbox();
      if (mode === "read") items.forEach((n) => { n.read = true; if (DONE[n.kind]) n.done = DONE[n.kind]; });
      inbox = { mode, items, more: mode === "new" || mode === "read", tenant: null, lastDone: null };
    }
    inbox.tenant = tenant ?? null;
  }
  const unread = () => inbox.items.filter((n) => !n.read).length;
  const pending = (scope) => inbox.items.filter((n) => ACTIONABLE[n.kind] && !n.done && (!scope || n.ws === scope)).sort((a, b) => ACTIONABLE[a.kind] - ACTIONABLE[b.kind]);

  function nfText(n) {
    const p = n.p;
    switch (n.kind) {
      case "check_in.opened": return html`Чек-ин на <b>${p.tournament_name}</b> открыт до ${fmt.dateTime(p.closes_at)} — подтвердите участие`;
      case "team_invite.received": return html`<b>${p.team_name}</b> приглашает вас в состав на <b>${p.tournament_name}</b>`;
      case "announcement.published": return html`<b>Объявление.</b> ${p.title}`;
      case "registration.approved": return html`Ваша заявка на <b>${p.tournament_name}</b> одобрена`;
      case "registration.opened": return html`Регистрация на <b>${p.tournament_name}</b> открыта до ${fmt.dateTime(p.closes_at)}`;
      case "encounter.scheduled": return html`Матч <b>${p.home} — ${p.away}</b> на ${p.tournament_name} назначен на ${fmt.dateTime(p.scheduled_at)}`;
      case "encounter.report_disputed": return html`Отчёт по карте ${p.map_index} вашего матча оспорен`;
      default: return "Новое уведомление о событии";
    }
  }
  const nfActions = (n) => (n.done
    ? html`<p class="nf__done">${icon("check", "icon--sm")}${n.done}</p>`
    : n.kind === "check_in.opened"
      ? html`<div class="nf__actions"><button class="btn btn--primary btn--sm" type="button" data-nf="checkin" data-id="${n.id}">Пройти чек-ин</button></div>`
      : n.kind === "team_invite.received"
        ? html`<div class="nf__actions"><button class="btn btn--primary btn--sm" type="button" data-nf="accept" data-id="${n.id}">Принять</button><button class="btn btn--outline btn--sm" type="button" data-nf="decline" data-id="${n.id}">Отклонить</button></div>`
        : "");
  /** Source line. On a community's own host its own rows drop the name (Q4); everything else says where it came from. */
  function nfSource(n) {
    if (n.ws && n.ws === inbox.tenant) return "";
    const c = n.ws ? community(n.ws) : null;
    return c ? html`${wsAvatar(c, 16)}<span>${c.name}</span><span aria-hidden="true">·</span>`
      : html`<img src="frontend/public/brand-mark.svg" alt="" width="16" height="16"><span>OWT</span><span aria-hidden="true">·</span>`;
  }
  function nfRow(n) {
    const [ic, tone] = NOTIF_KIND[n.kind] ?? ["bell", "var(--aqt-fg-dim)"];
    return html`<li class="nf ${n.read ? "" : "nf--unread"}">
      <span class="nf__icon" style="--c:${tone}" aria-hidden="true">${icon(ic)}</span>
      <div class="nf__body">
        <a class="nf__text" href="#" data-nf="open" data-id="${n.id}">${n.read ? "" : html`<span class="sr-only">Новое: </span>`}${nfText(n)}</a>
        <div class="nf__meta">${nfSource(n)}<time datetime="${n.at}" title="${fmt.dateTime(n.at)}">${fmt.rel(n.at)}</time></div>
        ${nfActions(n)}
      </div>
      <div class="nf__tools">
        ${n.read ? "" : html`<button class="btn btn--ghost btn--icon" type="button" data-nf="read" data-id="${n.id}" aria-label="Отметить прочитанным" title="Отметить прочитанным">${icon("check", "icon--sm")}</button>`}
        <button class="btn btn--ghost btn--icon" type="button" data-nf="delete" data-id="${n.id}" aria-label="Удалить" title="Удалить">${icon("trash-2", "icon--sm")}</button>
      </div>
    </li>`;
  }
  function bellPanel() {
    const n = unread();
    const body = inbox.mode === "error"
      ? html`<div class="state state--error">${icon("circle-alert")}<div><b>Не удалось загрузить уведомления</b>Это ошибка загрузки, а не пустой список.<br><button class="btn btn--outline btn--sm" type="button" data-nf="retry">Попробовать ещё раз</button></div></div>`
      : !inbox.items.length
        ? html`<div class="nf-empty">${icon("bell")}<b>Уведомлений пока нет</b><p>Здесь появятся приглашения в команду, решения по заявкам и назначенные матчи.</p></div>`
        : html`<ol class="nf-list">${inbox.items.map(nfRow)}</ol>`;
    return html`
      <div class="nf-head">
        <h2 id="nf-title" tabindex="-1">Уведомления</h2>${n ? html`<span class="nf-count">${fmt.count(n, ["новое", "новых", "новых"])}</span>` : ""}
        <span class="nf-head__tools">
          ${n ? html`<button class="btn btn--ghost btn--icon" type="button" data-nf="read-all" aria-label="Отметить все прочитанными" title="Отметить все прочитанными">${icon("check-check")}</button>` : ""}
          <a class="btn btn--ghost btn--icon" href="#" aria-label="Настроить уведомления" title="Настроить уведомления">${icon("settings-2")}</a>
          <button class="btn btn--ghost btn--icon below-sm" type="button" data-nf="close" aria-label="Закрыть уведомления">${icon("x")}</button>
        </span>
      </div>
      ${body}
      ${inbox.items.length ? html`<div class="nf-foot">${inbox.items.some((x) => x.read) ? html`<button class="nf-link" type="button" data-nf="clear-read">Очистить прочитанные</button>` : html`<span></span>`}${inbox.more ? html`<button class="nf-link" type="button" data-nf="more">Показать старые</button>` : ""}</div>` : ""}`;
  }
  const bellLabel = () => { const n = unread(); return n ? `Уведомления: ${fmt.count(n, ["новое", "новых", "новых"])}` : "Уведомления"; };
  const badgeText = (n) => (n > 99 ? "99+" : String(n));
  const bellButton = () => html`<button class="btn btn--outline btn--icon bell-btn" type="button" data-pop aria-expanded="false" aria-controls="pop-bell" aria-label="${bellLabel()}">${icon("bell")}<span class="badge" aria-hidden="true" ${unread() ? "" : raw("hidden")}>${badgeText(unread())}</span></button>`;

  /**
   * Decision Q3, revised: the one thing that needs this person now (an open
   * check-in, then a pending invite) as a compact card in the floating stack;
   * it stays while the page scrolls. `scope` limits it to one community's page.
   * After an action the card shows the confirmation for a few seconds, then the
   * next pending thing (or nothing). "Скрыть" hides it for this visit; the item
   * stays in the bell.
   */
  function stripInner(scope) {
    const inScope = (x) => !scope || x.ws === scope;
    const flash = inbox.items.find((x) => x.id === inbox.flash && inScope(x));
    if (flash) return html`<div class="fcard urgent urgent--done" role="status" tabindex="-1">${icon("circle-check")}<p>${flash.done}: <b>${flash.p.tournament_name}</b></p></div>`;
    const list = pending(scope);
    const n = list[0];
    if (!n || inbox.stripHidden) return "";
    const c = community(n.ws);
    const [ic, tone] = NOTIF_KIND[n.kind];
    const text = n.kind === "check_in.opened"
      ? html`<b>Чек-ин на ${n.p.tournament_name} открыт</b><span class="urgent__meta">${c.name} · до <time datetime="${n.p.closes_at}">${fmt.dateTime(n.p.closes_at)}</time> · ${fmt.rel(n.p.closes_at)}</span>`
      : html`<b>${n.p.team_name} приглашает вас в состав на ${n.p.tournament_name}</b><span class="urgent__meta">${c.name} · слот: ${n.p.slot}</span>`;
    return html`<section class="fcard urgent" style="--c:${tone}" aria-label="Требует действия">
      <span class="urgent__icon" aria-hidden="true">${icon(ic)}</span>
      <p class="urgent__text">${text}</p>
      <button class="btn btn--ghost btn--icon fcard__close" type="button" data-nf="hide-strip" aria-label="Скрыть до следующего захода" title="Скрыть — останется в уведомлениях">${icon("x", "icon--sm")}</button>
      <div class="urgent__actions">${nfActions(n)}${list.length > 1 ? html`<button class="nf-link" type="button" data-nf="open-bell">Ещё ${list.length - 1}</button>` : ""}</div>
    </section>`;
  }

  /** Decision Q5, revised: the announcement is a card in the same floating stack; dismissing it also reads it. */
  let annShown = null;
  function announcementCard(on) {
    if (on !== annShown) { annShown = on; inbox.annDismissed = false; }
    if (!on || inbox.annDismissed) return "";
    return html`<div class="fcard ann" id="ann" role="region" aria-label="Объявление">
      <span class="ann__tag">${icon("megaphone", "icon--sm")}<span class="ann__tag-text">Объявление</span></span>
      <button class="btn btn--ghost btn--icon fcard__close" type="button" data-nf="ann-dismiss" aria-label="Закрыть объявление" title="Закрыть объявление">${icon("x", "icon--sm")}</button>
      <a class="ann__title" href="${ANNOUNCEMENT.href}">${ANNOUNCEMENT.title}</a>
      <a class="more" href="${ANNOUNCEMENT.href}" aria-hidden="true" tabindex="-1">Подробнее${icon("arrow-right", "icon--sm")}</a>
    </div>`;
  }

  /**
   * The floating stack (hybrid, see owt-mock.css): slim bars sticky under the
   * header from 640 px, fixed cards at the bottom on phones. In the DOM right
   * after the header, so keyboard users reach an urgent action before the page
   * body, not after the footer.
   */
  const floatStack = ({ auth, scope = null, ann }) => html`
    <div class="float-stack" aria-label="Важное">
      ${announcementCard(ann)}
      ${auth === "in" ? html`<div id="action-strip" data-scope="${scope ?? ""}">${stripInner(scope)}</div>` : ""}
    </div>`;

  const langSwitch = (cls = "") => html`<span class="lang ${cls}" role="group" aria-label="Язык интерфейса"><button type="button" aria-pressed="true" title="Русский">RU</button><button type="button" aria-pressed="false" title="English">EN</button></span>`;

  function navGroups(currentKey) {
    return NAV.map((g) => (g.href
      ? html`<a class="nav__btn" href="${g.href}" ${g.key === currentKey ? raw('data-current aria-current="page"') : ""}>${g.label}</a>`
      : html`
      <div class="pop-anchor">
        <button class="nav__btn" type="button" data-pop aria-expanded="false" aria-controls="pop-nav-${g.key}" ${g.key === currentKey ? raw("data-current") : ""}>${g.label}${icon("chevron-down")}</button>
        <div class="pop" id="pop-nav-${g.key}" role="menu" aria-label="${g.label}" hidden>
          ${g.items.map(([t, d, ic]) => html`<a class="menu-item" role="menuitem" href="#">${icon(ic)}<span class="grow"><span>${t}</span><small>${d}</small></span></a>`)}
        </div>
      </div>`));
  }

  /**
   * Header. ctx: { tenant: community|null (white-label host), current: community|null
   * (apex switcher selection), auth: "in"|"out", active: tournament[], navCurrent }.
   */
  function header(ctx) {
    const t = ctx.tenant;
    useInbox(ctx.inbox ?? "new", t?.slug);
    return html`
      <a class="skip-link" href="#main">Перейти к содержимому</a>
      <header class="site-header"><div class="shell"><div class="site-header__plate">
        <button class="btn btn--outline btn--icon below-lg" type="button" data-sheet-open aria-label="Открыть меню навигации">${icon("menu")}</button>
        ${t
          ? html`<a class="brand" href="#" aria-label="${t.name} — на главную">${wsAvatar(t, 30)}<span class="brand__name only-sm" style="font-size:16px;max-width:12rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${t.name}</span></a>`
          : html`<a class="brand brand--apex only-sm" href="OWT Platform Landing.html" aria-label="OWT — на главную"><img src="frontend/public/brand-mark.svg" alt=""><span class="brand__name">OWT</span></a>
                 <span class="vsep only-sm"></span>
                 <div class="pop-anchor" style="min-width:0">
                   <button class="switcher-btn" type="button" data-pop aria-expanded="false" aria-controls="pop-switcher" aria-label="Сменить сообщество">
                     ${ctx.current ? wsAvatar(ctx.current, 24) : html`<span class="ws-avatar" style="--s:24px;--a:var(--aqt-teal)" aria-hidden="true">${icon("globe", "icon--sm")}</span>`}
                     <span>${ctx.current ? ctx.current.name : "Все сообщества"}</span>${icon("chevrons-up-down", "icon--sm")}
                   </button>
                   ${switcherPop(ctx.current)}
                 </div>`}
        <nav class="nav only-lg" aria-label="Навигация по сайту">${navGroups(ctx.navCurrent)}</nav>
        <div class="hdr-right">
          ${ctx.active.length ? html`
            <div class="pop-anchor">
              <button class="active-btn" type="button" data-pop aria-expanded="false" aria-controls="pop-active" aria-label="Активные события: ${ctx.active.length}">
                <span class="live-dot" style="color:var(--aqt-emerald)" aria-hidden="true"></span>
                <span class="tnum" aria-hidden="true">${ctx.active.length}<span class="active-word">&nbsp;${plural(ctx.active.length, ["активное", "активных", "активных"])}</span></span>
              </button>
              ${activeEventsPop(ctx.active)}
            </div>` : ""}
          <div class="hdr-search pop-anchor only-md" data-search>
            <label class="input"><span class="sr-only">Поиск игроков</span>${icon("search")}
              <input type="search" role="combobox" aria-expanded="false" aria-controls="search-list" aria-autocomplete="list" placeholder="Поиск игроков…" autocomplete="off">
            </label>
            <div class="pop pop--end pop--wide" id="search-list" hidden></div>
          </div>
          <button class="btn btn--outline btn--icon below-md" type="button" data-search-mobile aria-label="Поиск игроков">${icon("search")}</button>
          ${ctx.auth === "in"
            ? html`${bellButton()}<div class="pop-anchor"><button class="user-btn" type="button" data-pop aria-expanded="false" aria-controls="pop-user" aria-label="Аккаунт">CF</button>${userPop()}</div>`
            : html`${langSwitch("only-lg")}<button class="signin" type="button" aria-label="Войти">${icon("log-in", "below-sm")}<span class="only-sm">Войти</span></button>`}
        </div>
      </div>
      ${ctx.auth === "in" ? html`<div class="pop pop--end nf-pop" id="pop-bell" role="dialog" aria-labelledby="nf-title" hidden>${bellPanel()}</div>` : ""}
      <p class="sr-only" id="nf-live" aria-live="polite"></p>
      </div></header>
      ${mobileSheet(ctx)}`;
  }

  function mobileSheet(ctx) {
    const t = ctx.tenant;
    return html`
      <div class="sheet-backdrop" data-sheet-close hidden></div>
      <div class="sheet" id="sheet" role="dialog" aria-modal="true" aria-label="Навигация по сайту" hidden>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
          ${t ? html`<a class="brand" href="#">${wsAvatar(t, 32)}<span class="brand__name" style="font-size:16px">${t.name}</span></a>`
              : html`<a class="brand" href="OWT Platform Landing.html"><img src="frontend/public/brand-mark.svg" alt=""><span class="brand__name">OWT</span></a>`}
          <button class="btn btn--ghost btn--icon" type="button" data-sheet-close aria-label="Закрыть меню">${icon("x")}</button>
        </div>
        ${NAV.filter((g) => g.items).map((g) => html`<div class="sheet__group"><div class="eyebrow">${g.label}</div>${g.items.map(([n, , ic]) => html`<a class="menu-item" href="#">${icon(ic)}<span class="grow"><span>${n}</span></span></a>`)}</div>`)}
        <div class="sheet__group"><div class="eyebrow">Вне турниров</div>${NAV_LINKS.map((l) => html`<a class="menu-item" href="${l.href}">${icon(l.icon)}<span class="grow"><span>${l.label}</span></span></a>`)}</div>
        ${!t ? html`<div class="sheet__group"><div class="eyebrow">Организаторам</div><a class="menu-item" href="OWT Get Workspace.html">${icon("plus")}<span class="grow"><span>Создать сообщество</span></span></a></div>` : ""}
        ${ctx.auth === "out" ? html`<div class="sheet__group" style="padding:0 10px">${langSwitch()}</div>` : ""}
      </div>`;
  }

  function footer(ctx) {
    const t = ctx.tenant;
    const year = NOW.getUTCFullYear();
    const legal = html`<nav aria-label="Правовая информация"><a href="#">Условия использования</a><a href="#">Политика конфиденциальности</a><button type="button" style="all:unset;cursor:pointer" class="cookie-btn">Настройки cookie</button></nav>`;
    if (t) {
      return html`
        <footer class="site-footer"><div class="shell">
          <div class="site-footer__cols">
            <div>
              <a class="brand" href="#" style="display:inline-flex">${wsAvatar(t, 28)}<span class="brand__name" style="font-size:16px">${t.name}</span></a>
              <p class="dim" style="margin-top:12px;max-width:26rem;font-size:var(--text-caption)">${t.name} — сообщество на платформе OWT. Не связано с Blizzard Entertainment, Inc. и не одобрено ею.</p>
            </div>
            <div><h3 class="eyebrow">Сообщество</h3><ul><li><a href="#">Турниры</a></li><li><a href="#">Игроки</a></li><li><a href="#">Статистика</a></li>${(ctx.links ?? []).map((l) => html`<li><a href="#">${LINK_META[l.kind].label}${icon("arrow-up-right", "icon--sm")}</a></li>`)}</ul></div>
            <div><h3 class="eyebrow">Платформа OWT</h3><ul><li><a href="OWT Platform Landing.html">Все сообщества${icon("arrow-up-right", "icon--sm")}</a></li><li><a href="#">Мой профиль игрока</a></li><li><a href="#">Документация</a></li></ul></div>
          </div>
          <div class="site-footer__meta">
            <span class="powered">Работает на <a href="OWT Platform Landing.html"><img src="frontend/public/brand-mark.svg" alt="">OWT</a><span class="version">${D.version}</span></span>
            ${legal}
          </div>
        </div></footer>`;
    }
    return html`
      <footer class="site-footer"><div class="shell">
        <div class="site-footer__cols">
          <div>
            <a class="brand" href="OWT Platform Landing.html" style="display:inline-flex"><img src="frontend/public/brand-mark.svg" alt=""><span class="brand__name">OWT</span></a>
            <p class="dim" style="margin-top:12px;max-width:26rem;font-size:var(--text-caption)">OWT — независимая платформа турниров сообществ Overwatch. Не связана с Blizzard Entertainment, Inc. и не одобрена ею.</p>
          </div>
          <div><h3 class="eyebrow">Разделы</h3><ul><li><a href="#">Турниры</a></li><li><a href="#">Игроки</a></li><li><a href="#">Достижения</a></li><li><a href="OWT Platform Landing.html#directory">Сообщества</a></li></ul></div>
          <div><h3 class="eyebrow">Ресурсы</h3><ul><li><a href="#">Документация</a></li><li><a href="#">Документация API</a></li><li><a href="OWT Get Workspace.html">Создать сообщество</a></li><li><a href="#">Исходный код на GitHub${icon("arrow-up-right", "icon--sm")}</a></li></ul></div>
        </div>
        <div class="site-footer__meta">
          <span style="display:inline-flex;align-items:center;gap:10px">© ${year} OWT <span class="version">${D.version}</span></span>
          ${legal}
        </div>
      </div></footer>`;
  }

  // ── behaviour: popovers, sheet, search combobox ───────────────────────
  let openPop = null; // { btn, panel }
  function closePop(returnFocus) {
    if (!openPop) return;
    openPop.panel.hidden = true;
    openPop.btn.setAttribute("aria-expanded", "false");
    if (returnFocus) openPop.btn.focus();
    openPop = null;
  }
  function openPopFor(btn) {
    const panel = document.getElementById(btn.getAttribute("aria-controls"));
    if (!panel) return;
    closePop(false);
    panel.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    openPop = { btn, panel };
    if (panel.getAttribute("role") === "menu") panel.querySelector(".menu-item")?.focus();
    else panel.querySelector('[tabindex="-1"]')?.focus();
  }
  let sheetReturn = null;
  function setSheet(open) {
    const sheet = document.getElementById("sheet");
    const back = document.querySelector(".sheet-backdrop");
    if (!sheet) return;
    sheet.hidden = !open; back.hidden = !open;
    document.body.style.overflow = open ? "hidden" : "";
    if (open) { sheetReturn = document.activeElement; sheet.querySelector("a,button")?.focus(); }
    else sheetReturn?.focus();
  }

  document.addEventListener("click", (e) => {
    const trg = e.target.closest("[data-pop]");
    if (trg) { e.preventDefault(); trg.getAttribute("aria-expanded") === "true" ? closePop(false) : openPopFor(trg); return; }
    if (e.target.closest("[data-sheet-open]")) { setSheet(true); return; }
    if (e.target.closest("[data-sheet-close]")) { setSheet(false); return; }
    if (e.target.closest("[data-search-mobile]")) { openMobileSearch(); return; }
    if (openPop && !openPop.panel.contains(e.target)) closePop(false);
    if (!e.target.closest("[data-search]")) closeSearch();
    const a = e.target.closest('a[href="#"]');
    if (a) e.preventDefault(); // dead links in a mock must not jump to top
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!document.getElementById("sheet")?.hidden) { setSheet(false); return; }
      if (openPop) { closePop(true); return; }
      closeSearch();
    }
    if (openPop && openPop.panel.getAttribute("role") === "menu" && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      const items = [...openPop.panel.querySelectorAll(".menu-item")];
      const i = items.indexOf(document.activeElement);
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
    }
    const sheet = document.getElementById("sheet");
    if (e.key === "Tab" && sheet && !sheet.hidden) { // focus trap
      const f = [...sheet.querySelectorAll("a,button")];
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
    }
  });

  // Player search: usePlayerSearch semantics — debounced, ≥2 chars, recent history.
  function renderSearch(list, q) {
    const names = searchNames();
    let body;
    if (!q) body = html`<div class="pop__label eyebrow">Недавние</div>${RECENT.map((n) => html`<a class="menu-item" role="option" href="#">${icon("history")}<span class="grow"><span>${n}</span></span></a>`)}`;
    else if (q.length < 2) body = html`<div class="state" style="padding:12px 10px">Введите минимум 2 символа.</div>`;
    else {
      const hits = names.filter((n) => n.toLowerCase().includes(q.toLowerCase())).slice(0, 6);
      body = hits.length
        ? hits.map((n) => html`<a class="menu-item" role="option" href="#">${icon("user")}<span class="grow"><span>${n}</span></span></a>`)
        : html`<div class="state" style="padding:12px 10px">Игроки не найдены.</div>`;
    }
    list.innerHTML = html`<div role="listbox" aria-label="Результаты поиска игроков">${body}</div>`.s;
  }
  function closeSearch() {
    document.querySelectorAll("[data-search]").forEach((w) => { w.querySelector(".pop").hidden = true; w.querySelector("input")?.setAttribute("aria-expanded", "false"); });
  }
  document.addEventListener("focusin", (e) => {
    const w = e.target.closest?.("[data-search]");
    if (w && e.target.tagName === "INPUT") { const l = w.querySelector(".pop"); renderSearch(l, e.target.value.trim()); l.hidden = false; e.target.setAttribute("aria-expanded", "true"); }
  });
  let tmr;
  document.addEventListener("input", (e) => {
    const w = e.target.closest?.("[data-search]");
    if (!w) return;
    clearTimeout(tmr);
    tmr = setTimeout(() => renderSearch(w.querySelector(".pop"), e.target.value.trim()), 300);
  });
  function openMobileSearch() {
    const plate = document.querySelector(".site-header__plate");
    if (document.getElementById("m-search")) { document.getElementById("m-search").remove(); return; }
    plate.parentElement.insertAdjacentHTML("beforeend", html`<div id="m-search" data-search class="pop-anchor" style="margin-top:8px"><label class="input" style="background:var(--aqt-card-2)"><span class="sr-only">Поиск игроков</span>${icon("search")}<input type="search" placeholder="Поиск игроков…" autocomplete="off" role="combobox" aria-expanded="false" aria-controls="m-search-list"></label><div class="pop" id="m-search-list" style="right:0" hidden></div></div>`.s);
    document.querySelector("#m-search input").focus();
  }

  // ── state, dev panel, mount ────────────────────────────────────────────
  function readHash() {
    return Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
  }
  function mount({ defaults, schema, note, render, after }) {
    const app = document.getElementById("app");
    let state = { ...defaults, ...readHash() };
    const rerender = () => {
      document.body.dataset.loading = state.loading === "1" ? "1" : "0";
      app.innerHTML = out(render(state));
      after?.(state, app);
    };
    const panel = document.createElement("details");
    panel.className = "devpanel";
    panel.open = matchMedia("(min-width: 768px)").matches;
    panel.innerHTML = html`<summary>Состояния макета <span aria-hidden="true">⚙</span></summary><div class="devpanel__body">
      ${schema.map((f) => html`<fieldset><legend>${f.label}</legend><div class="opts">${f.options.map(([v, l]) => html`<label><input type="radio" name="${f.key}" value="${v}">${l}</label>`)}</div></fieldset>`)}
      <p>${note} Состояние в URL — ссылку можно отправить.</p></div>`.s;
    document.body.append(panel);
    const sync = () => schema.forEach((f) => { const el = panel.querySelector(`input[name="${f.key}"][value="${CSS.escape(String(state[f.key]))}"]`); if (el) el.checked = true; });
    panel.addEventListener("change", (e) => {
      state = { ...state, [e.target.name]: e.target.value };
      history.replaceState(null, "", "#" + new URLSearchParams(state));
      rerender();
    });
    window.addEventListener("hashchange", () => { state = { ...defaults, ...readHash() }; sync(); rerender(); });
    sync();
    rerender();
  }

  // Inbox actions. Registered after the popover handler, so that handler still
  // sees the clicked node inside the open panel before this one re-renders it.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-nf]");
    if (!b) return;
    const n = inbox.items.find((x) => x.id === Number(b.dataset.id));
    const say = (text) => { document.getElementById("nf-live").textContent = text; };
    const resolve = (text) => {
      n.done = text; n.read = true; say(text);
      inbox.flash = n.id;
      setTimeout(() => { if (inbox.flash === n.id) { inbox.flash = null; refreshInbox(); } }, 3500);
    };
    switch (b.dataset.nf) {
      case "open": case "read": n.read = true; break;
      case "delete": inbox.items = inbox.items.filter((x) => x !== n); say("Уведомление удалено."); break;
      case "read-all": inbox.items.forEach((x) => { x.read = true; }); say("Все уведомления отмечены прочитанными."); break;
      case "clear-read": inbox.items = inbox.items.filter((x) => !x.read); say("Прочитанные уведомления удалены."); break;
      case "more": inbox.items.push(...OLDER.map((x) => ({ ...x }))); inbox.more = false; break;
      case "retry": inbox.items = exampleInbox(); inbox.mode = "new"; inbox.more = true; break;
      case "checkin": resolve("Чек-ин пройден"); break;
      case "accept": resolve("Вы приняли приглашение"); break;
      case "decline": resolve("Вы отклонили приглашение"); break;
      case "ann-dismiss":
        inbox.annDismissed = true;
        document.getElementById("ann")?.remove();
        inbox.items.forEach((x) => { if (x.kind === "announcement.published") x.read = true; });
        break;
      case "hide-strip": inbox.stripHidden = true; say("Скрыто до следующего захода. Дело осталось в уведомлениях."); break;
      case "open-bell": document.querySelector('[aria-controls="pop-bell"]')?.click(); return;
      case "close": closePop(true); return;
    }
    refreshInbox(true);
  });
  function refreshInbox(focus = false) {
    const pop = document.getElementById("pop-bell");
    if (pop && focus) pop.innerHTML = bellPanel().s; // the timer only touches the floating card
    const btn = document.querySelector('[aria-controls="pop-bell"]');
    if (btn) {
      btn.setAttribute("aria-label", bellLabel());
      const badge = btn.querySelector(".badge");
      badge.hidden = !unread();
      badge.textContent = badgeText(unread());
    }
    const strip = document.getElementById("action-strip");
    const focusWasInStrip = focus && strip?.contains(document.activeElement);
    if (strip) strip.innerHTML = String(stripInner(strip.dataset.scope || null)); // "" when nothing is due
    if (!focus) return; // timer-driven refreshes never move focus
    // the clicked control is gone: keep focus where the person was working
    if (pop && !pop.hidden && !pop.contains(document.activeElement)) document.getElementById("nf-title")?.focus();
    else if (focusWasInStrip) strip.querySelector('[tabindex="-1"], button')?.focus();
  }

  // ── open-layout blocks (owt-mock.css "open layout"), shared by pages ──────
  const colHead = (title, sub) => html`<div class="col__head"><h3 class="col__title">${title}</h3>${sub ? html`<span class="col__sub">${sub}</span>` : ""}</div>`;
  const blockError = () => html`<div class="state state--error">${icon("circle-alert")}<div><b>Не удалось загрузить</b><button class="btn btn--outline btn--sm" type="button">Повторить</button></div></div>`;
  const fact = (value, label) => html`<span class="metric"><b class="sk">${value}</b><span>${label}</span></span>`;

  /* Totals list. A field missing from the API renders as a dash tagged with
     the field it needs (`path.key`), so the mock doubles as the backend requirement. */
  const KPI = {
    communities: ["Сообщества", "globe", "--aqt-rose"],
    tournaments: ["Турниры", "trophy", "--aqt-violet"],
    teams: ["Команды", "scale", "--aqt-blue"],
    players: ["Игроки", "users", "--aqt-emerald"],
    encounters: ["Встречи", "swords", "--aqt-amber"],
    maps: ["Карты", "layers", "--aqt-silver"],
    days: ["Дни", "calendar", "--aqt-bronze"],
    hours: ["Часы", "clock", "--aqt-teal"],
    champions: ["Чемпионы", "crown", "--aqt-gold"],
  };
  const kpiList = ({ title, totals, keys, path, err }) => html`
    <div class="col">
      ${colHead(title)}
      ${err ? blockError() : html`<dl class="kpi">${keys.map((key) => {
        const [label, ic, color] = KPI[key];
        return html`<div>
          <dt><span class="kpi__icon" style="--c:var(${color})">${icon(ic, "icon--sm")}</span>${label}</dt>
          ${totals[key] == null
            ? html`<dd class="kpi__na" title="Нужно поле ${path}.${key} в API"><span class="kpi__tag">нужно в API</span>—</dd>`
            : html`<dd class="sk">${fmt.num(totals[key])}</dd>`}
        </div>`;
      })}</dl>`}
    </div>`;

  /** LeaderboardCard as an open column. rows: null = load error, [] = empty (`empty` explains why). */
  const leaderboard = (title, rows, format, accent, sub, empty) => html`
    <div class="col">
      ${colHead(title, sub)}
      ${rows === null ? blockError()
        : rows.length === 0 ? html`<div class="state">${icon("info")}<div><b>Пока пусто</b>${empty}</div></div>`
        : html`<ol class="lb">${rows.map((p, i) => html`<li>${i < 3 ? html`<span class="place place--${i + 1}">${i + 1}</span>` : html`<span class="place">#${i + 1}</span>`}<a href="#" class="sk" title="${p.name}">${p.name}</a><span class="val sk" style="color:${accent}">${format(p.value)}</span></li>`)}</ol>`}
    </div>`;

  /** Product showcase row (owt-mock.css "product showcase"). `img` is a real
      production screenshot in design/shots: an 1800×1250 CSS-px viewport captured
      at DPR 1.6, so the app UI shows at ~¾ of its real size (admin-*.webp are
      ~1270 px wide, DPR 1, supplied by hand, window edges cropped). `ratio`
      overrides the 2:1 window when the interesting part sits lower in the shot. */
  const show = ({ title, text, more, img, alt, ratio }) => html`
    <div class="show">
      <div class="show__head"><h3 class="show__title">${title}</h3>
        <div class="show__text"><p>${text}</p>${more ? html`<a class="more" href="${more[1]}">${more[0]}${icon("arrow-right", "icon--sm")}</a>` : ""}</div></div>
      <div class="shot"${ratio ? raw(` style="aspect-ratio:${ratio}"`) : ""}><img src="design/shots/${img}" width="1800" height="1250" alt="${alt}" loading="lazy" decoding="async"></div>
    </div>`;

  window.OWT = { D, NOW, html, raw, esc, icon, fmt, community, host, wsAvatar, trustedBadge, statusPill, STATUS, roleIcon, LINK_META, derivePalette, applyPalette, header, footer, mount, floatStack, colHead, blockError, fact, kpiList, leaderboard, show };
})();
