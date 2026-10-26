import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { PlayerBoard, PlayerBoardSkeleton } from "@/components/site/leaders";
import { MoreLink, OpenEmptyRow, OpenLoadError, Section, SectionHead } from "@/components/site/open-layout";
import { ServerGameScopeNotice } from "@/components/workspace/ServerGameScopeNotice";
import type { Formatter } from "@/lib/datetime";
import { getFormatter } from "@/lib/datetime/server";
import { resolveServerPageGame } from "@/lib/site/discipline-server";
import { cn } from "@/lib/utils";
import statisticsService from "@/services/statistics.service";
import type { CharacterPlaytime } from "@/types/user.types";

const TITLE_ID = "home-leaders-title";
const TOP = 5;
const BOARDS_CLASS = "mt-8 grid grid-cols-1 gap-x-10 gap-y-8 md:grid-cols-2";

/** A character row, on the player board's geometry: the leader on a card of its own, the rest as rows. */
const ROW_CLASS = "grid min-h-11 grid-cols-[2rem_auto_minmax(0,1fr)_auto] items-center gap-x-3 px-4 text-body";
const LEADER_CLASS =
  "mb-2 min-h-24 rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] py-4 sm:px-5";

const SHARE = { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 } as const;

/**
 * A slice of the almanac for the landing: the players with the most titles
 * and the characters played most, each a top five. Titles span every game
 * under "all games" and the game's own under one (spec §6.5); characters
 * always belong to one game — the page's, or under all games the first one
 * installed, named in the board's line. An invalid or empty game reads no
 * board and shows its notice, never another game's.
 */
export async function PlatformLeaders({ discipline }: Readonly<{ discipline: string | string[] | undefined }>) {
  const { init, resolution } = await resolveServerPageGame("multi", discipline);
  const page = resolution?.game ?? null;
  const boards = page?.kind === "all" || page?.kind === "game";
  const game = page?.kind === "game" ? page.code : null;
  const installed = init.disciplines ?? [];
  const characterGame = !boards
    ? null
    : (installed.find((entry) => (game === null ? entry.enabled : entry.code === game)) ?? null);

  const [t, format, champions, characters] = await Promise.all([
    getTranslations("home.leaders"),
    getFormatter(),
    boards ? statisticsService.getChampions(game, { skipWorkspace: true }).catch(() => null) : null,
    characterGame
      ? statisticsService
          .getCharacterPlaytime(characterGame.code, { axis: "all", perPage: TOP })
          .catch(() => null)
      : null
  ]);

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        title={t("title")}
        titleId={TITLE_ID}
        sub={t("sub")}
        aside={
          <MoreLink href="/statistics" className="min-h-11 whitespace-nowrap">
            {t("more")}
          </MoreLink>
        }
      />
      <ServerGameScopeNotice initial={init} />
      {boards ? (
        <div className={BOARDS_CLASS}>
          <PlayerBoard
            format={format}
            board={{
              title: t("mostWins"),
              sub: t("winsSub"),
              rows: champions === null ? null : champions.results.slice(0, TOP),
              value: "wins"
            }}
          />
          {characterGame ? (
            <CharacterBoard
              title={t("mostPlayed")}
              sub={t("mostPlayedSub", { game: characterGame.name })}
              empty={t("mostPlayedEmpty")}
              rows={characters === null ? null : characters.results.slice(0, TOP)}
              format={format}
            />
          ) : null}
        </div>
      ) : null}
    </Section>
  );
}

/**
 * The characters played most, by their share of the playtime the parsed logs
 * observed. The bar is scaled to the leader, so the five read against each
 * other; the figure beside it is the share itself.
 */
function CharacterBoard({
  title,
  sub,
  empty,
  rows,
  format
}: Readonly<{
  title: string;
  sub: string;
  empty: string;
  rows: CharacterPlaytime[] | null;
  format: Formatter;
}>) {
  const leader = rows?.[0]?.playtime ?? 0;

  return (
    <div className="min-w-0">
      <div className="mb-4">
        <h3 className="font-display text-heading font-semibold text-[color:var(--aqt-fg)]">{title}</h3>
        <p className="mt-1 text-caption text-[color:var(--aqt-fg-muted)]">{sub}</p>
      </div>
      {rows === null ? (
        <OpenLoadError />
      ) : rows.length === 0 ? (
        <OpenEmptyRow>{empty}</OpenEmptyRow>
      ) : (
        <ol>
          {rows.map((row, index) => (
            <li key={row.entity.id} className={cn(ROW_CLASS, index === 0 && LEADER_CLASS)}>
              <span className="text-center text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">
                {index + 1}
              </span>
              <CatalogEntityImage entity={row.entity} size={index === 0 ? 48 : 32} decorative />
              <span className="min-w-0">
                <span
                  className={cn(
                    "block truncate font-semibold text-[color:var(--aqt-fg)]",
                    index === 0 && "font-display text-heading"
                  )}
                >
                  {row.entity.name}
                </span>
                <span aria-hidden className="mt-1.5 block h-1.5 rounded-full bg-[color:var(--aqt-overlay-2)]">
                  <span
                    className="block h-full rounded-full bg-[color:var(--aqt-teal)]"
                    style={{ width: `${leader > 0 ? Math.round((row.playtime / leader) * 100) : 0}%` }}
                  />
                </span>
              </span>
              <span
                className={cn(
                  "whitespace-nowrap text-right font-semibold tabular-nums text-[color:var(--aqt-teal)]",
                  index === 0 && "font-display text-headline"
                )}
              >
                {format.number(row.playtime, SHARE)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function PlatformLeadersSkeleton() {
  const t = useTranslations("home.leaders");

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        title={t("title")}
        titleId={TITLE_ID}
        sub={t("sub")}
        aside={
          <MoreLink href="/statistics" className="min-h-11 whitespace-nowrap">
            {t("more")}
          </MoreLink>
        }
      />
      <div aria-hidden className={BOARDS_CLASS}>
        <PlayerBoardSkeleton />
        <PlayerBoardSkeleton />
      </div>
    </Section>
  );
}
