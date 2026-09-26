"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { cn, initials } from "@/lib/utils";
import { getPlayerSlug } from "@/lib/player";
import { formatOptional } from "@/app/(site)/users/components/shared/list-utils";
import type { UserCatalogEntry } from "@/types/user.types";

import { DivisionHex } from "./DivisionHex";
import { ALPHABET, primaryRoleLabel, splitTag } from "./users-index.model";
import type { UsersIndexData } from "./useUsersIndexData";
import type { UsersIndexParamControls } from "./useUsersIndexParams";
import styles from "./Users.module.css";

/** A-Z browse view: one card grid per initial, with an alphabet jump bar. */
export function UsersCatalogView({
  controls,
  data
}: Readonly<{
  controls: UsersIndexParamControls;
  data: UsersIndexData;
}>) {
  const t = useTranslations();
  const { letter } = controls.params;
  const { catalogQuery, availableLetters } = data;

  return (
    <section>
      <div className={styles.alphaBar}>
        <span className={styles.alphaLabel}>{t("users.list.catalog.jumpTo")}</span>
        <button
          type="button"
          className={cn(styles.alphaLink, !letter && styles.alphaLinkActive)}
          onClick={() => controls.setLetter(null)}
        >
          {t("common.all")}
        </button>
        {ALPHABET.map((alpha) => {
          const isAvailable = availableLetters.has(alpha);
          return (
            <button
              key={alpha}
              type="button"
              className={cn(
                styles.alphaLink,
                letter === alpha && styles.alphaLinkActive,
                !isAvailable && !catalogQuery.isLoading && styles.alphaLinkDisabled
              )}
              disabled={!isAvailable && !catalogQuery.isLoading}
              onClick={() => controls.setLetter(alpha)}
            >
              {alpha}
            </button>
          );
        })}
      </div>

      {catalogQuery.isError ? (
        <p className={styles.errorMsg}>
          {(catalogQuery.error as Error)?.message || t("users.list.errors.catalog")}
        </p>
      ) : catalogQuery.data && catalogQuery.data.letters.length > 0 ? (
        <>
          {catalogQuery.data.letters.map((bucket) => (
            <div key={bucket.letter} className={styles.catSection}>
              <h3 className={styles.catLetter}>{bucket.letter}</h3>
              <div className={styles.catGrid}>
                {bucket.users.map((cardUser) => (
                  <CatalogCard key={cardUser.id} user={cardUser} />
                ))}
              </div>
            </div>
          ))}
          <div
            className={styles.paginationBar}
            style={{
              marginTop: 18,
              border: "1px solid var(--u-border)",
              borderRadius: 12,
              borderTop: "1px solid var(--u-border)"
            }}
          >
            <span className={styles.pageInfo}>
              {t("users.list.catalog.showing", {
                count: catalogQuery.data.letters.reduce((acc, b) => acc + b.users.length, 0),
                total: catalogQuery.data.total
              })}
            </span>
            <span className={styles.pageInfo}>
              {catalogQuery.isFetching ? t("users.list.pagination.refreshing") : null}
            </span>
          </div>
        </>
      ) : catalogQuery.isPending ? (
        <div className={styles.catSection}>
          <div className={styles.catGrid}>
            {Array.from({ length: 8 }).map((_, idx) => (
              <div
                key={`cat-skel-${idx}`}
                className={cn(styles.catCard, styles.skelRow)}
                style={{ height: 160 }}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className={styles.empty}>{t("users.list.empty")}</div>
      )}
    </section>
  );
}

function CatalogCard({ user }: Readonly<{ user: UserCatalogEntry }>) {
  const t = useTranslations();
  const { handle, tag } = splitTag(user.name);
  const topHeroes = user.top_heroes.slice(0, 3);

  return (
    <HoverPrefetchLink href={`/users/${getPlayerSlug(user.name)}`} className={styles.catCard}>
      <div className={styles.catCardTop}>
        <div className={styles.catCardAvatar} aria-hidden>
          {initials(user.name)}
        </div>
        <div className={styles.catCardInfo}>
          <div className={styles.catCardName} title={user.name}>
            {handle}
            {tag ? <span className="tag">{tag}</span> : null}
          </div>
          <div className={styles.catCardMeta}>{primaryRoleLabel(user.roles, t)}</div>
        </div>
        <div className={styles.catCardRoles}>
          {user.roles.map((roleRow) => (
            <DivisionHex
              key={`${user.id}-cat-${roleRow.role}-${roleRow.division}`}
              role={roleRow.role}
              division={roleRow.division}
              size={28}
            />
          ))}
        </div>
      </div>

      <div className={styles.catCardHeroes}>
        <span>{t("users.list.table.topHeroes")}</span>
        <div className={styles.catCardHeroesStrip}>
          {topHeroes.length === 0 ? (
            <span className={styles.playerSub}>—</span>
          ) : (
            topHeroes.map((heroRow) => (
              <div
                key={`${user.id}-heroes-${heroRow.hero.id}`}
                className={styles.heroChip}
                title={heroRow.hero.name}
              >
                <Image
                  src={heroRow.hero.image_path}
                  alt={heroRow.hero.name}
                  width={28}
                  height={28}
                  className="object-contain select-none"
                />
              </div>
            ))
          )}
        </div>
      </div>

      <div className={styles.catStats}>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>{t("users.list.catalog.tournaments")}</span>
          <span className={styles.catStatValue}>{user.tournaments_count}</span>
        </div>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>{t("users.list.catalog.achievements")}</span>
          <span className={styles.catStatValue}>{user.achievements_count}</span>
        </div>
        <div className={styles.catStat}>
          <span className={styles.catStatLabel}>{t("users.list.catalog.avgPlacement")}</span>
          <span className={styles.catStatValue}>{formatOptional(user.avg_placement)}</span>
        </div>
      </div>
    </HoverPrefetchLink>
  );
}
