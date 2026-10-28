"use client";

import { Fragment, useId, type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { lobbyLetter } from "@/app/balancer/mix/pickup-chrome";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { formatRelative } from "@/components/kit/format-time";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { SearchField } from "@/components/ui/search-field";
import { Skeleton } from "@/components/ui/skeleton";
import { GameLabel } from "@/components/workspace/GameLabel";
import { WorkspaceAvatar, type WorkspaceAvatarSource } from "@/components/workspace/WorkspaceAvatar";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { CustomGameListItem } from "@/services/custom-game.service";
import type { DisciplineDescriptor } from "@/types/discipline.types";

/** Passed only when the page spans several communities / games: then every row names its own (spec §6.1). */
type RowMarks = {
  communities?: Map<number, WorkspaceAvatarSource>;
  gameMarks?: Map<string, DisciplineDescriptor>;
};

/**
 * One `text-caption` meta line, facts joined by a dim middle dot (DESIGN §4). `narrowTail` is a fact the row shows in
 * its own column from `md` up, so below that it joins the line instead.
 */
function MetaLine({ parts, narrowTail }: Readonly<{ parts: ReactNode[]; narrowTail?: string }>) {
  const shown = parts.filter((part) => part != null && part !== false && part !== "");
  const dot = <span className="text-[color:var(--aqt-fg-dim)]"> · </span>;
  return (
    <span className="block min-w-0 truncate text-caption text-[color:var(--aqt-fg-muted)]">
      {shown.map((part, index) => (
        <Fragment key={index}>
          {index > 0 ? dot : null}
          {part}
        </Fragment>
      ))}
      {narrowTail ? (
        <span className="md:hidden">
          {shown.length > 0 ? dot : null}
          {narrowTail}
        </span>
      ) : null}
    </span>
  );
}

/* ─── Now: the mixes still running ─────────────────────────────────────── */

/**
 * The open mixes, each a whole-card link: where a lobby is, how many signed
 * up, and the one state worth a pill. Nothing open renders nothing -- an
 * empty "now" block would spend the top of the page saying so.
 */
export function ActiveMixes({
  games,
  loading,
  error,
  onRetry,
  communities,
  gameMarks
}: Readonly<{ games: CustomGameListItem[]; loading: boolean; error: boolean; onRetry: () => void } & RowMarks>) {
  const t = useTranslations("mixes.now");
  const common = useTranslations("common");
  const id = useId();

  if (error) {
    return (
      <PageStateCard
        state="error"
        title={t("errorTitle")}
        actionLabel={common("retry")}
        onAction={onRetry}
        className="w-full min-w-0 px-4 py-8"
      />
    );
  }
  if (loading) {
    return (
      <Card role="status" className="flex flex-col gap-3 p-5">
        <span className="sr-only">{t("loading")}</span>
        <Skeleton className="h-6 w-1/3 motion-reduce:animate-none" />
        <Skeleton className="h-4 w-1/2 motion-reduce:animate-none" />
      </Card>
    );
  }
  if (games.length === 0) return null;

  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col gap-3">
      <h2 id={id} className="text-ui font-semibold text-[color:var(--aqt-fg)]">
        {t("title")}
      </h2>
      <ul className={cn("grid min-w-0 gap-3", games.length > 1 && "2xl:grid-cols-2")}>
        {games.map((game) => (
          <ActiveMixCard
            key={game.id}
            game={game}
            community={communities?.get(game.workspace_id)}
            gameMarks={gameMarks}
          />
        ))}
      </ul>
    </section>
  );
}

function ActiveMixCard({
  game,
  community,
  gameMarks
}: Readonly<{ game: CustomGameListItem; community?: WorkspaceAvatarSource; gameMarks?: Map<string, DisciplineDescriptor> }>) {
  const t = useTranslations("mixes.now");
  const history = useTranslations("mixes.history");
  const lobbies = useTranslations("mixes.lobbies");
  const format = useFormatter();
  const now = useMinuteClock();
  const single = game.lobbies.length <= 1;
  const status =
    game.self_signup !== "closed"
      ? { variant: "open" as const, label: t("signupOpen") }
      : game.status === "balanced"
        ? { variant: "upcoming" as const, label: t("teamsReady") }
        : null;

  return (
    <li className="min-w-0">
      <Link
        href={`/balancer/mix/${game.id}`}
        className="flex min-w-0 flex-col gap-4 rounded-xl border border-[color:color-mix(in_srgb,var(--aqt-teal)_32%,var(--aqt-border))] bg-[color:var(--aqt-card)] p-4 transition-colors hover:border-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)] sm:p-5 lg:flex-row lg:items-center lg:gap-6"
      >
        <span className="flex min-w-0 flex-1 items-center gap-3">
          {community ? <WorkspaceAvatar workspace={community} size={40} /> : null}
          <span className="min-w-0">
            <span className="block truncate font-display text-heading font-semibold text-[color:var(--aqt-fg)]">
              {game.name}
            </span>
            <MetaLine
              parts={[
                community?.name,
                gameMarks ? <GameLabel key="game" code={game.discipline} games={gameMarks} /> : null,
                history("host", { name: game.host_display_name ?? `#${game.host_user_id}` }),
                game.created_at && now !== null
                  ? t("started", { time: formatRelative(format, game.created_at, now) })
                  : null
              ]}
            />
          </span>
        </span>

        <dl className="flex flex-wrap gap-x-6 gap-y-2">
          {game.lobbies.map((lobby) => (
            <div key={lobby.lobby_index} className="min-w-0">
              <Eyebrow as="dt">
                {single ? t("game") : lobbies("tab", { letter: lobbyLetter(lobby.lobby_index) })}
              </Eyebrow>
              <dd className="mt-0.5 text-ui font-semibold tabular-nums text-[color:var(--aqt-fg)]">
                {single
                  ? format.number((lobby.matches_count ?? 0) + 1)
                  : lobbies("game", { number: (lobby.matches_count ?? 0) + 1 })}
              </dd>
            </div>
          ))}
          <div className="min-w-0">
            <Eyebrow as="dt">{t("signedUp")}</Eyebrow>
            <dd className="mt-0.5 text-ui font-semibold tabular-nums text-[color:var(--aqt-fg)]">
              {format.number(game.roster_count)}
            </dd>
          </div>
        </dl>

        <span className="flex shrink-0 items-center justify-between gap-4 lg:justify-end">
          {status ? <TournamentStatusPill status={status.variant}>{status.label}</TournamentStatusPill> : <span />}
          <span className="inline-flex items-center gap-1.5 text-caption font-semibold text-[color:var(--aqt-teal)]">
            {t("open")}
            <ArrowRight aria-hidden className="size-4" />
          </span>
        </span>
      </Link>
    </li>
  );
}

/* ─── History: every finished mix, by month ────────────────────────────── */

type MixHistoryProps = {
  items: CustomGameListItem[];
  loading: boolean;
  /** The rows on screen still answer the previous search. */
  updating: boolean;
  error: boolean;
  onRetry: () => void;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  search: string;
  onSearchChange: (value: string) => void;
  /** The search the rows answer (debounced, trimmed). */
  query: string;
  /** Nothing open and nothing finished: the whole directory is empty. */
  nothingYet: boolean;
  canEdit: boolean;
  onCreateGame: () => void;
} & RowMarks;

export function MixHistory({
  items,
  loading,
  updating,
  error,
  onRetry,
  hasMore,
  loadingMore,
  onLoadMore,
  search,
  onSearchChange,
  query,
  nothingYet,
  canEdit,
  onCreateGame,
  communities,
  gameMarks
}: Readonly<MixHistoryProps>) {
  const t = useTranslations("mixes.history");
  const common = useTranslations("common");
  const mixes = useTranslations("mixes");
  const format = useFormatter();
  const id = useId();

  // Consecutive rows of one calendar month share a heading; the rows arrive newest first.
  const groups: { label: string; items: CustomGameListItem[] }[] = [];
  for (const item of items) {
    const month = item.created_at
      ? format.dateTime(new Date(item.created_at), { month: "long", year: "numeric" })
      : "";
    const label = month.charAt(0).toUpperCase() + month.slice(1);
    const last = groups.at(-1);
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }

  const searching = query !== "" || search !== "";
  let body: ReactNode;
  if (error && items.length === 0) {
    body = (
      <PageStateCard
        state="error"
        title={mixes("list.errorTitle")}
        description={mixes("list.errorDescription")}
        actionLabel={common("retry")}
        onAction={onRetry}
        className="w-full min-w-0 px-4"
      />
    );
  } else if (loading) {
    body = (
      <Card role="status" className="w-full min-w-0 divide-y divide-[color:var(--aqt-border)]">
        <span className="sr-only">{mixes("loading")}</span>
        {[0, 1, 2, 3].map((row) => (
          <div key={row} aria-hidden="true" className="flex items-center gap-4 px-4 py-3.5">
            <Skeleton className="h-9 w-9 shrink-0 motion-reduce:animate-none" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-1/2 motion-reduce:animate-none" />
              <Skeleton className="h-3 w-1/3 motion-reduce:animate-none" />
            </div>
            <Skeleton className="hidden h-7 w-28 shrink-0 md:block motion-reduce:animate-none" />
            <Skeleton className="h-7 w-10 shrink-0 motion-reduce:animate-none" />
          </div>
        ))}
      </Card>
    );
  } else if (items.length === 0) {
    body = searching ? (
      <PageStateCard
        state="filtered-empty"
        title={t("noResultsTitle")}
        description={t("noResultsDescription", { q: query || search.trim() })}
        actionLabel={t("clearSearch")}
        onAction={() => onSearchChange("")}
        className="w-full min-w-0 px-4"
      />
    ) : (
      <PageStateCard
        state="empty"
        title={t(nothingYet ? "emptyTitle" : "noneFinishedTitle")}
        description={t(nothingYet ? (canEdit ? "emptyHost" : "emptyViewer") : "noneFinishedDescription")}
        actionLabel={mixes("createAction")}
        onAction={nothingYet && canEdit ? onCreateGame : undefined}
        className="w-full min-w-0 px-4"
      />
    );
  } else {
    body = (
      <div
        aria-busy={updating || undefined}
        className={cn("flex min-w-0 flex-col gap-5 transition-opacity", updating && "opacity-60")}
      >
        {groups.map((group) => (
          <section key={`${group.label}-${group.items[0].id}`} aria-label={group.label || undefined} className="min-w-0">
            {group.label ? (
              <h3 className="mb-2 text-caption font-semibold text-[color:var(--aqt-fg-muted)]">{group.label}</h3>
            ) : null}
            <Card asChild>
              <ul className="flex min-w-0 flex-col divide-y divide-[color:var(--aqt-border)]">
                {group.items.map((game) => (
                  <HistoryRow
                    key={game.id}
                    game={game}
                    community={communities?.get(game.workspace_id)}
                    gameMarks={gameMarks}
                  />
                ))}
              </ul>
            </Card>
          </section>
        ))}
        {error ? (
          <p role="alert" className="flex flex-wrap items-center justify-center gap-3 text-caption text-[color:var(--aqt-fg-muted)]">
            {t("moreError")}
            <Button variant="outline" size="sm" onClick={onRetry}>
              {common("retry")}
            </Button>
          </p>
        ) : hasMore || loadingMore ? (
          <Button variant="outline" className="self-center" onClick={onLoadMore} disabled={loadingMore}>
            {t("showMore")}
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col gap-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <h2 id={id} className="text-ui font-semibold text-[color:var(--aqt-fg)]">
          {t("title")}
        </h2>
        {/* A search with nothing to search is not a choice. */}
        {items.length > 0 || searching ? (
          <SearchField
            label={t("search")}
            placeholder={t("searchPlaceholder")}
            value={search}
            onValueChange={onSearchChange}
            containerClassName="w-full sm:w-64"
          />
        ) : null}
      </div>
      {body}
    </section>
  );
}

function HistoryRow({
  game,
  community,
  gameMarks
}: Readonly<{ game: CustomGameListItem; community?: WorkspaceAvatarSource; gameMarks?: Map<string, DisciplineDescriptor> }>) {
  const t = useTranslations("mixes.history");
  const lobbies = useTranslations("mixes.lobbies");
  const format = useFormatter();
  const now = useMinuteClock();
  const created = game.created_at ? new Date(game.created_at) : null;
  const activity = game.last_match_at ?? game.created_at;
  const cancelled = game.status === "cancelled";
  const relative = activity && now !== null ? formatRelative(format, activity, now) : "";
  const activityTitle = game.last_match_at
    ? t("lastMatch", { date: format.dateTime(new Date(game.last_match_at), { dateStyle: "medium", timeStyle: "short" }) })
    : created
      ? t("created", { date: format.dateTime(created, { dateStyle: "medium" }) })
      : undefined;

  return (
    <li className="min-w-0 first:[&>a]:rounded-t-xl last:[&>a]:rounded-b-xl">
      <Link
        href={`/balancer/mix/${game.id}`}
        className="grid min-w-0 grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-x-3 px-3 py-3 transition-colors hover:bg-[color:var(--aqt-overlay-2)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)] sm:gap-x-4 sm:px-4 md:grid-cols-[2.75rem_minmax(0,1fr)_8.5rem_3.5rem_3.5rem_5.5rem]"
      >
        <span aria-hidden="true" className="flex flex-col items-center border-e border-[color:var(--aqt-border)] pe-3">
          {created ? (
            <>
              <span className="font-display text-heading font-bold leading-none tabular-nums text-[color:var(--aqt-fg)]">
                {format.dateTime(created, { day: "numeric" })}
              </span>
              <Eyebrow className="mt-1">
                {format.dateTime(created, { weekday: "short" })}
              </Eyebrow>
            </>
          ) : null}
        </span>

        <span className="flex min-w-0 items-center gap-3">
          {community ? <WorkspaceAvatar workspace={community} size={28} /> : null}
          <span className="min-w-0">
            <span
              className={cn(
                "block truncate text-ui font-semibold",
                cancelled ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg)]"
              )}
            >
              {game.name}
            </span>
            {created ? (
              <span className="sr-only">{format.dateTime(created, { dateStyle: "long" })}</span>
            ) : null}
            <MetaLine
              parts={[
                community?.name,
                gameMarks ? <GameLabel key="game" code={game.discipline} games={gameMarks} /> : null,
                t("host", { name: game.host_display_name ?? `#${game.host_user_id}` }),
                game.lobby_count > 1 ? lobbies("count", { count: game.lobby_count }) : null,
                cancelled ? t("cancelled") : null
              ]}
              narrowTail={relative}
            />
          </span>
        </span>

        <MapStack game={game} />

        <span className="text-end">
          <span className="block font-display text-ui font-semibold leading-tight tabular-nums text-[color:var(--aqt-fg)]">
            {format.number(game.matches_count)}
          </span>
          <span className="block text-label text-[color:var(--aqt-fg-faint)]">
            {t("matches", { count: game.matches_count })}
          </span>
        </span>

        <span className="hidden text-end md:block">
          <span className="block font-display text-ui font-semibold leading-tight tabular-nums text-[color:var(--aqt-fg)]">
            {format.number(game.players_count)}
          </span>
          <span className="block text-label text-[color:var(--aqt-fg-faint)]">
            {t("players", { count: game.players_count })}
          </span>
        </span>

        <span
          title={activityTitle}
          className="hidden text-end text-caption tabular-nums text-[color:var(--aqt-fg-dim)] md:block"
        >
          {relative}
        </span>
      </Link>
    </li>
  );
}

/** The maps a mix played as overlapping thumbnails: the one picture a finished mix has of itself. */
function MapStack({ game }: Readonly<{ game: CustomGameListItem }>) {
  const t = useTranslations("mixes.history");
  const format = useFormatter();
  if (game.maps.length === 0) return <span aria-hidden="true" className="hidden md:block" />;
  const names = game.maps.map((map) => map.name).join(", ");
  const extra = game.maps_count - game.maps.length;

  return (
    <span title={names} className="hidden min-w-0 items-center md:flex">
      <span className="sr-only">{t("maps", { names })}</span>
      {game.maps.map((map) => (
        <CatalogEntityImage
          key={map.name}
          entity={map}
          size={28}
          shape="wide"
          decorative
          className="-ms-3 border-2 border-[color:var(--aqt-card)] first:ms-0"
        />
      ))}
      {extra > 0 ? (
        <span aria-hidden="true" className="ms-1.5 text-caption tabular-nums text-[color:var(--aqt-fg-faint)]">
          +{format.number(extra)}
        </span>
      ) : null}
    </span>
  );
}
