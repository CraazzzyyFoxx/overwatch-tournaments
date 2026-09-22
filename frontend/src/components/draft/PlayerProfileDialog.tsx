"use client";

import { useQuery } from "@tanstack/react-query";
import { Crown } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { AnswerValue } from "@/components/forms/AnswerValue";
import { Avatar, AvatarImage, AvatarStack } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/division-grid";
import { playerRoles, roleTopHeroes, rosterRoleForPlayer } from "@/lib/draft-workspace-model";
import { normalizePlayerRole } from "@/lib/player-role";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import userService from "@/services/user.service";
import type { DraftBoard, DraftPlayer } from "@/types/draft.types";
import type { UserProfile } from "@/types/user.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getHeroIconUrl, getPlayerSlug } from "@/utils/player";

const BADGE_CLASS =
  "rounded border border-[color:var(--aqt-border-2)] px-1 text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]";

const SECTION_TITLE = "text-xs uppercase tracking-wide text-[color:var(--aqt-fg-muted)]";

type ProfileTab = "registration" | "stats";

interface PlayerProfileDialogProps {
  player: DraftPlayer | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  board: DraftBoard;
  divisionGrid: DivisionGrid;
}

export function PlayerProfileDialog({
  player,
  open,
  onOpenChange,
  board,
  divisionGrid
}: Readonly<PlayerProfileDialogProps>) {
  const t = useTranslations("draftRedesign");
  const [tab, setTab] = useState<ProfileTab>("registration");
  // A different player behind the same open dialog is a different subject: the
  // stats tab must not stay open over someone else's numbers.
  const [shownPlayerId, setShownPlayerId] = useState<number | null>(null);
  if (player != null && player.id !== shownPlayerId) {
    setShownPlayerId(player.id);
    setTab("registration");
  }

  const userId = player?.user_id ?? null;
  const statsQuery = useQuery({
    queryKey: ["draft", "profile", userId],
    queryFn: () => userService.getUserProfile(userId as number),
    enabled: open && tab === "stats" && userId != null
  });

  if (!player) return null;

  const roles = playerRoles(player);
  const profileSlug = player.battle_tag ? getPlayerSlug(player.battle_tag) : null;
  const headerDivision = resolveDivisionFromRank(divisionGrid, player.effective_rank);
  const notes = player.notes?.trim() ? player.notes : null;
  // Every public registration answer the player gave, with the field's CURRENT
  // label and schema kind — the draft client needs no form schema of its own.
  const customFields = player.custom_fields ?? [];
  const displayName = player.battle_tag ?? `#${player.id}`;

  const draftedTeam =
    player.status === "picked"
      ? (board.teams.find((team) => team.id === player.drafted_by_team_id) ?? null)
      : null;
  const draftedRole = draftedTeam ? rosterRoleForPlayer(player, board.picks) : null;
  const statusText = draftedTeam
    ? t("profile.draftedBy", { team: draftedTeam.name })
    : player.status === "removed"
      ? t("profile.removed")
      : t("profile.available");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <div className="flex items-start gap-3 pr-8">
            {headerDivision != null && (
              <span
                className="shrink-0"
                title={getDivisionLabel(divisionGrid, headerDivision) ?? undefined}
              >
                <DivisionIcon
                  division={headerDivision}
                  tournamentGrid={divisionGrid}
                  width={40}
                  height={40}
                  className="h-10 w-10 object-contain"
                />
              </span>
            )}
            <div className="min-w-0 flex-1">
              <DialogTitle className="flex items-center gap-2 font-onest text-lg font-semibold">
                {profileSlug ? (
                  <Link
                    href={`/users/${profileSlug}`}
                    className="truncate hover:text-[color:var(--aqt-teal)] hover:underline"
                  >
                    {displayName}
                  </Link>
                ) : (
                  <span className="truncate">{displayName}</span>
                )}
                {player.is_captain && (
                  <Crown
                    className="h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]"
                    role="img"
                    aria-label={t("captain")}
                  />
                )}
              </DialogTitle>
              <DialogDescription className="text-xs text-[color:var(--aqt-fg-muted)]">
                {statusText}
                {draftedRole && <> · {t(`roles.${draftedRole}`)}</>}
              </DialogDescription>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 empty:hidden">
                {player.is_flex && <span className={BADGE_CLASS}>{t("flex")}</span>}
                {player.primary_role == null && <span className={BADGE_CLASS}>{t("noRole")}</span>}
              </div>
            </div>
          </div>
        </DialogHeader>

        <Tabs value={tab} onValueChange={(value) => setTab(value as ProfileTab)}>
          <TabsList>
            <TabsTrigger value="registration">{t("profile.tabRegistration")}</TabsTrigger>
            {userId != null && <TabsTrigger value="stats">{t("profile.tabStats")}</TabsTrigger>}
          </TabsList>

          <TabsContent value="registration" className="space-y-4">
            <section>
              <h3 className={SECTION_TITLE}>{t("profile.rolesHeading")}</h3>
              {roles.length === 0 ? (
                <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">{t("noRoleHint")}</p>
              ) : (
                <ul className="mt-2 flex flex-col gap-2">
                  {roles.map((entry) => {
                    // The role's OWN rank, with no fallback. Lending another
                    // role's number to a role the player was never ranked on
                    // invents a rating a captain then picks on; an unranked role
                    // renders the em-dash, and the player's overall strength
                    // stays in the header where `effective_rank` answers it once.
                    const roleRank = player.role_ranks[entry] ?? null;
                    const roleDivision = resolveDivisionFromRank(divisionGrid, roleRank);
                    // Provenance only when it is NOT the registration itself, so
                    // an inherited or Overwatch-derived rank is tellable apart
                    // from one the player declared.
                    const roleSource = player.role_sources[entry] ?? null;
                    const borrowedSource =
                      roleRank != null && roleSource != null && roleSource !== "registration"
                        ? roleSource
                        : null;
                    const heroes = roleTopHeroes(player, entry);
                    const isPrimary = player.primary_role != null && entry === player.primary_role;
                    return (
                      <li
                        key={entry}
                        title={[
                          t(`roles.${entry}`),
                          isPrimary ? t("primaryRole") : null,
                          roleRank != null ? `${roleRank} SR` : null,
                          borrowedSource ? t(`rankSource.${borrowedSource}`) : null
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                        className={`flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2 ${
                          isPrimary
                            ? "border-[color:var(--aqt-teal)]/60"
                            : "border-[color:var(--aqt-border-2)]"
                        }`}
                      >
                        <PlayerRoleIcon
                          role={getRoleIconName(entry)}
                          size={18}
                          color={ROLE_ACCENT[entry]}
                          decorative
                        />
                        <span className="text-sm text-[color:var(--aqt-fg)]">
                          {t(`roles.${entry}`)}
                        </span>
                        {isPrimary && player.sub_role && (
                          <span className="min-w-0 truncate text-label font-medium uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
                            {formatSubRoleLabel(player.sub_role)}
                          </span>
                        )}
                        <span className="ml-auto flex shrink-0 items-center gap-1.5">
                          {heroes.length > 0 && (
                            <AvatarStack size={24} max={3}>
                              {heroes.map((hero) => (
                                <Avatar key={hero.slug} className="h-6 w-6" title={hero.slug}>
                                  <AvatarImage
                                    src={getHeroIconUrl(hero.slug, hero.imagePath)}
                                    alt={hero.slug}
                                  />
                                </Avatar>
                              ))}
                            </AvatarStack>
                          )}
                          {borrowedSource && (
                            <span className="text-label uppercase tracking-wide text-[color:var(--aqt-fg-faint)]">
                              {t(`rankSourceShort.${borrowedSource}`)}
                            </span>
                          )}
                          {roleRank != null ? (
                            <span className="aqt-tnum text-sm text-[color:var(--aqt-fg)]">{`${roleRank} SR`}</span>
                          ) : (
                            <span className="text-sm text-[color:var(--aqt-fg-faint)]">—</span>
                          )}
                          {roleDivision != null && (
                            <span title={getDivisionLabel(divisionGrid, roleDivision) ?? undefined}>
                              <DivisionIcon
                                division={roleDivision}
                                tournamentGrid={divisionGrid}
                                width={24}
                                height={24}
                                className="h-6 w-6 object-contain"
                              />
                            </span>
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            {notes && (
              <section>
                <h3 className={SECTION_TITLE}>{t("note")}</h3>
                <p className="mt-1 whitespace-pre-line text-sm text-[color:var(--aqt-fg)]">
                  {notes}
                </p>
              </section>
            )}

            <section>
              <h3 className={SECTION_TITLE}>{t("profile.answersHeading")}</h3>
              {customFields.length === 0 ? (
                <p className="mt-1 text-sm text-[color:var(--aqt-fg-muted)]">
                  {t("profile.noAnswers")}
                </p>
              ) : (
                <dl className="mt-2 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
                  {customFields.map((entry) => (
                    <div key={entry.key} className="min-w-0">
                      <dt className="text-xs text-[color:var(--aqt-fg-muted)]">{entry.label}</dt>
                      <dd className="mt-0.5 break-words text-[color:var(--aqt-fg)]">
                        <AnswerValue
                          value={entry.value}
                          kind={entry.type}
                          labels={{ yes: t("customFieldYes"), no: t("customFieldNo") }}
                        />
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </section>
          </TabsContent>

          {userId != null && (
            <TabsContent value="stats">
              {statsQuery.isPending ? (
                <div className="space-y-2" aria-busy>
                  <span className="sr-only">{t("profile.stats.loading")}</span>
                  {[0, 1, 2].map((row) => (
                    <div
                      key={row}
                      className="h-10 animate-pulse rounded-lg bg-[color:var(--aqt-overlay-3)]"
                    />
                  ))}
                </div>
              ) : statsQuery.isError ? (
                <div className="space-y-2 text-sm text-[color:var(--aqt-fg-muted)]">
                  <p>{t("profile.stats.error")}</p>
                  <Button variant="outline" size="sm" onClick={() => statsQuery.refetch()}>
                    {t("profile.stats.retry")}
                  </Button>
                </div>
              ) : (
                <ProfileStats profile={statsQuery.data} />
              )}
            </TabsContent>
          )}
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function ProfileStats({ profile }: Readonly<{ profile: UserProfile }>) {
  const t = useTranslations("draftRedesign");
  // Guarded: a player with no map played has no winrate, not a 0%.
  const winrate = profile.maps_total > 0 ? profile.maps_won / profile.maps_total : null;
  const topHeroes = [...profile.hero_statistics]
    .sort((a, b) => b.playtime - a.playtime)
    .slice(0, 5);
  // Tournament ids grow over time, so the three highest are the three most
  // recent regardless of what order the API happened to return.
  const recent = [...profile.tournaments].sort((a, b) => b.id - a.id).slice(0, 3);
  const roles = [...profile.roles].sort((a, b) => b.tournaments - a.tournaments);

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label={t("profile.stats.tournaments")} value={String(profile.tournaments_count)} />
        <Metric label={t("profile.stats.won")} value={String(profile.tournaments_won)} />
        <Metric
          label={t("profile.stats.winrate")}
          value={winrate == null ? "—" : `${Math.round(winrate * 100)}%`}
        />
        <Metric
          label={t("profile.stats.avgPlacement")}
          value={profile.avg_placement == null ? "—" : profile.avg_placement.toFixed(1)}
        />
      </dl>

      {roles.length > 0 && (
        <section>
          <h3 className={SECTION_TITLE}>{t("profile.stats.roles")}</h3>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm">
            {roles.map((role) => (
              <li key={role.role} className="flex items-center gap-2">
                <PlayerRoleIcon role={normalizePlayerRole(role.role)} size={16} decorative />
                <span className="text-[color:var(--aqt-fg)]">{role.role}</span>
                <span className="ml-auto aqt-tnum text-[color:var(--aqt-fg-muted)]">
                  {t("profile.stats.maps", { won: role.maps_won, maps: role.maps })}
                </span>
                <DivisionIcon
                  division={role.division}
                  tournamentGrid={role.division_grid_version}
                  width={20}
                  height={20}
                  className="h-5 w-5 object-contain"
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      {topHeroes.length > 0 && (
        <section>
          <h3 className={SECTION_TITLE}>{t("profile.stats.topHeroes")}</h3>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm">
            {topHeroes.map((entry) => (
              <li key={entry.hero.id} className="flex items-center gap-2">
                <Avatar className="h-6 w-6" title={entry.hero.name}>
                  <AvatarImage
                    src={getHeroIconUrl(entry.hero.slug, entry.hero.image_path)}
                    alt={entry.hero.name}
                  />
                </Avatar>
                <span className="truncate text-[color:var(--aqt-fg)]">{entry.hero.name}</span>
                <span className="ml-auto aqt-tnum text-[color:var(--aqt-fg-muted)]">
                  {`${(entry.playtime * 100).toFixed(1)}%`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {recent.length > 0 && (
        <section>
          <h3 className={SECTION_TITLE}>{t("profile.stats.recentTournaments")}</h3>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm">
            {recent.map((tournament) => (
              <li key={tournament.id} className="flex items-center gap-2">
                <span className="truncate text-[color:var(--aqt-fg)]">{tournament.name}</span>
                {tournament.is_league && (
                  <span className={BADGE_CLASS}>{t("profile.stats.league")}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {roles.length === 0 && topHeroes.length === 0 && recent.length === 0 && (
        <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("profile.stats.empty")}</p>
      )}
    </div>
  );
}

function Metric({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-lg border border-[color:var(--aqt-border-2)] px-3 py-2">
      <dt className="text-label uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
        {label}
      </dt>
      <dd className="aqt-tnum mt-0.5 text-base font-semibold text-[color:var(--aqt-fg)]">{value}</dd>
    </div>
  );
}
