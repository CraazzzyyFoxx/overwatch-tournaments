"use client";

import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { cn } from "@/lib/utils";
import { BuildPath } from "./Build";
import { lobbyFirsts, rivals, shopPurchases, sourceKey, type DlPlayer, type MatchFeed, type Rival } from "./model";
import { DIM, FAINT, MUTED, SEAT, SEAT_TEXT, SourceIcon, useItems, useStatFormat } from "./parts";

/** Damage sources listed before the rest fold into "Other". */
const MAX_SOURCES = 7;

function Bar({ value, max, color }: Readonly<{ value: number; max: number; color: string }>) {
  return (
    <span aria-hidden className="block h-1.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]">
      <span className="block h-full rounded-full" style={{ width: `${max > 0 ? (value / max) * 100 : 0}%`, background: color }} />
    </span>
  );
}

function Block({ title, children, className }: Readonly<{ title: string; children: React.ReactNode; className?: string }>) {
  return (
    <div className={cn("min-w-0", className)}>
      <Eyebrow as="h4" className="mb-2.5 block">
        {title}
      </Eyebrow>
      {children}
    </div>
  );
}

interface PlayerPanelProps {
  player: DlPlayer;
  everyone: readonly DlPlayer[];
  feed: MatchFeed | null;
  durationS: number;
  /** The moment on screen: the build path draws its cursor there. */
  t: number;
}

/** One player's match beyond the row: his build on the match clock, whom and with what he hurt, rivals and firsts. */
export default function PlayerPanel({ player, everyone, feed, durationS, t: moment }: Readonly<PlayerPanelProps>) {
  const t = useTranslations();
  const text = useStatFormat();
  const items = useItems();
  const byMember = new Map(everyone.map((other) => [other.memberId, other]));
  const enemyColor = SEAT[player.side === "home" ? "away" : "home"];

  if (!feed || !items) {
    return (
      <div className="grid gap-4 p-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  const purchases = shopPurchases(feed, player.memberId, (id) => items.byId.get(id)?.type === "upgrade");
  const damageTo = [...(feed.damageTo.get(player.memberId) ?? [])].sort((a, b) => b.amount - a.amount);
  const damageMax = Math.max(0, ...damageTo.map((row) => row.amount));

  const sources = new Map<string, number>();
  for (const { source, amount } of feed.damageBySource.get(player.memberId) ?? []) {
    sources.set(sourceKey(source), (sources.get(sourceKey(source)) ?? 0) + amount);
  }
  const ranked = [...sources.entries()].sort((a, b) => b[1] - a[1]);
  const sourceTotal = ranked.reduce((total, [, amount]) => total + amount, 0);
  const shown = ranked.slice(0, MAX_SOURCES);
  const rest = ranked.slice(MAX_SOURCES).reduce((total, [, amount]) => total + amount, 0);
  const sourceMax = Math.max(0, ...shown.map(([, amount]) => amount), rest);

  const { nemesis, victim } = rivals(feed, player.memberId);
  const firsts = lobbyFirsts(player, everyone);
  const nameOf = (memberId: number) => byMember.get(memberId)?.display.name ?? "—";

  const rival = (label: string, entry: Rival | null) => {
    const other = entry ? byMember.get(entry.memberId) : undefined;
    return (
      <div className="grid gap-1">
        <Eyebrow as="dt">{label}</Eyebrow>
        <dd className="m-0 flex min-w-0 items-center gap-2 text-caption">
          {entry && other ? (
            <>
              {other.hero ? <CatalogEntityImage entity={other.hero} size={22} decorative /> : null}
              <span className={cn("truncate font-semibold", SEAT_TEXT[other.side])}>{nameOf(entry.memberId)}</span>
              <span className={cn("aqt-tnum shrink-0", DIM)}>
                {t("matches.deadlock.panel.times", { count: entry.count })}
              </span>
            </>
          ) : (
            <span className={FAINT}>—</span>
          )}
        </dd>
      </div>
    );
  };

  return (
    // Pinned to the scroller's left edge, so a wide table never carries the panel out of view; laid out by its own
    // width, since it opens both under a full-width table row and inside a half-width roster card.
    <div className="@container sticky left-0 w-full max-w-[min(100%,calc(100vw-2rem))]">
    <div className="grid gap-x-8 gap-y-6 p-4 @xl:grid-cols-2 @4xl:grid-cols-3">
      <Block title={t("matches.deadlock.panel.buildPath")} className="@xl:col-span-2 @4xl:col-span-3">
        {purchases.length === 0 ? (
          <p className={cn("text-caption", DIM)}>{t("matches.deadlock.noPurchases")}</p>
        ) : (
          <BuildPath purchases={purchases} durationS={durationS} t={moment} atEnd={moment >= durationS} />
        )}
      </Block>

      <Block title={t("matches.deadlock.panel.damageTo")}>
        {damageTo.length === 0 ? (
          <p className={cn("text-caption", DIM)}>—</p>
        ) : (
          <ul className="grid gap-2">
            {damageTo.map(({ target, amount }) => {
              const other = byMember.get(target);
              return (
                <li key={target} className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1">
                  {other?.hero ? <CatalogEntityImage entity={other.hero} size={22} decorative /> : <span />}
                  <span className={cn("truncate text-caption", MUTED)}>{nameOf(target)}</span>
                  <span className="aqt-tnum text-caption text-[color:var(--aqt-fg)]">{text(amount, "int")}</span>
                  <span className="col-span-2 col-start-2">
                    <Bar value={amount} max={damageMax} color={enemyColor} />
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Block>

      <Block title={t("matches.deadlock.panel.damageBySource")}>
        {shown.length === 0 ? (
          <p className={cn("text-caption", DIM)}>—</p>
        ) : (
          <ul className="grid gap-2">
            {[...shown, ...(rest > 0 ? ([["", rest]] as const) : [])].map(([source, amount]) => {
              const item = source ? items.byClass.get(source) : undefined;
              const label = source ? (item?.name ?? t("matches.deadlock.panel.otherSource")) : t("matches.deadlock.panel.rest");
              return (
                <li key={source || "rest"} className="grid grid-cols-[20px_minmax(0,1fr)_auto_auto] items-center gap-x-2 gap-y-1">
                  <SourceIcon item={item} />
                  <span className={cn("truncate text-caption", MUTED)} title={source || undefined}>
                    {label}
                  </span>
                  <span className="aqt-tnum text-caption text-[color:var(--aqt-fg)]">{text(amount, "int")}</span>
                  <span className={cn("aqt-tnum w-9 text-end text-label", FAINT)}>
                    {text(sourceTotal > 0 ? amount / sourceTotal : 0, "pct")}
                  </span>
                  <span className="col-span-3 col-start-2">
                    <Bar value={amount} max={sourceMax} color="var(--aqt-fg-muted)" />
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Block>

      <Block title={t("matches.deadlock.panel.rivals")}>
        <dl className="m-0 grid gap-3.5">
          {rival(t("matches.deadlock.panel.nemesis"), nemesis)}
          {rival(t("matches.deadlock.panel.victim"), victim)}
          <div className="grid gap-1">
            <Eyebrow as="dt">{t("matches.deadlock.panel.firsts")}</Eyebrow>
            <dd className="m-0 text-caption text-[color:var(--aqt-fg)]">
              {firsts.length ? (
                firsts.map((code) => t(`matches.deadlock.colTitle.${code}` as never)).join(", ")
              ) : (
                <span className={FAINT}>—</span>
              )}
            </dd>
          </div>
        </dl>
      </Block>
    </div>
    </div>
  );
}
