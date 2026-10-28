"use client";

import { useTranslations } from "next-intl";

import PlayerName from "@/components/PlayerName";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { ProfileStat } from "@/components/profile/atoms";
import { Separator } from "@/components/ui/separator";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { useFormatter } from "@/lib/datetime/client";
import { roleColor, type RoleOntology } from "@/lib/roster/ontology";
import type { Registration, RegistrationListResponse } from "@/types/registration.types";
import type { Tournament } from "@/types/tournament.types";

import { POOL_TEAM_FORMATIONS } from "../participants.model";
import { baseRole, isTournamentRole, ROLE_ORDER } from "../tournamentInsights.model";
import { AboutTournamentCard, CardColumns, OverviewSection, SectionLink } from "./OverviewCards";

const OUT = new Set(["withdrawn", "rejected", "declined", "cancelled"]);
const primaryRole = (registration: Registration) =>
  baseRole(
    registration.roles.find((role) => role.is_primary)?.role.role ??
      registration.roles[0]?.role.role
  );

/**
 * Before the first match: announcement, registration and check-in. How the field is filling — by role, against the
 * roster shape the draft will cut it into. The viewer's own application lives on the participants tab.
 */
export function OverviewPreStartView({
  tournament,
  slug,
  registrationList,
  aboutCard,
  formatCard,
  linksCard,
  phasesCard
}: Readonly<{
  tournament: Tournament;
  slug: string;
  registrationList: RegistrationListResponse | null;
  aboutCard: React.ReactNode;
  formatCard: React.ReactNode;
  linksCard: React.ReactNode;
  phasesCard: React.ReactNode;
}>) {
  const overviewHref = `/tournaments/${slug}`;
  const phase =
    tournament.status === "check_in"
      ? "check_in"
      : tournament.status === "announcement"
        ? "announcement"
        : "registration";
  const ontology =
    useDisciplineMetadata(tournament.workspace_id, tournament.discipline).data ?? null;

  // The field: submitted applications; `active` leaves out the withdrawn and the rejected.
  const field = (registrationList?.registrations ?? []).filter(
    (registration) => registration.submitted_at !== null
  );
  const active = field.filter((registration) => !OUT.has(registration.status));
  return (
    <div className="grid min-w-0 gap-4">
      {phase === "announcement" ? (
        // Nothing is filling yet: when registration opens beside the schedule, then the reference, full width.
        <>
          <CardColumns main={<AnnouncementCard tournament={tournament} />} side={phasesCard} />
          <AboutTournamentCard
            aboutCard={aboutCard}
            formatCard={formatCard}
            linksCard={linksCard}
          />
        </>
      ) : (
        <CardColumns
          main={
            <>
              {/* Only a pool is cut into rosters by role: solo and team-registration fields have no shape to fill. */}
              {POOL_TEAM_FORMATIONS[tournament.team_formation] ? (
                <FieldCard
                  tournament={tournament}
                  registrations={phase === "check_in" ? active.filter((r) => r.checked_in) : active}
                  phase={phase}
                  ontology={ontology}
                  overviewHref={overviewHref}
                />
              ) : null}
              {/* The schedule joins the reference here: beside the field and its lists it would leave this column
                  a card short. */}
              <AboutTournamentCard
                aboutCard={aboutCard}
                formatCard={formatCard}
                linksCard={linksCard}
                phasesCard={phasesCard}
              />
            </>
          }
          side={
            <>
              <RegistrationNumbersCard
                field={field}
                active={active}
                phase={phase}
                capacity={registrationList?.max_participants ?? null}
                teamRegistration={tournament.team_formation === "registration"}
              />
              {phase === "registration" ? (
                <LatestCard active={active} ontology={ontology} />
              ) : (
                <NotCheckedInCard active={active} ontology={ontology} />
              )}
            </>
          }
        />
      )}
    </div>
  );
}

/**
 * How the field fills against the roster shape: how many complete rosters the primary roles make, each role's share
 * of that in teams (so the bottleneck is the shortest bar), and how many of it the next team still needs.
 */
function FieldCard({
  tournament,
  registrations,
  phase,
  ontology,
  overviewHref
}: Readonly<{
  tournament: Tournament;
  registrations: readonly Registration[];
  phase: "registration" | "check_in";
  ontology: RoleOntology | null;
  overviewHref: string;
}>) {
  const t = useTranslations("tournamentDetail");
  const slots = (tournament.roster_shape?.slots ?? {}) as Record<string, number>;
  const counts = ROLE_ORDER.map((role) => ({
    role,
    count: registrations.filter((registration) => primaryRole(registration) === role).length,
    slot: slots[role] ?? 0
  })).filter((row) => row.slot > 0);
  const teams = counts.length
    ? Math.min(...counts.map((row) => Math.floor(row.count / row.slot)))
    : 0;
  const next = teams + 1;
  const short = counts
    .map((row) => ({ ...row, need: row.slot * next - row.count }))
    .filter((row) => row.need > 0);
  // Bars in teams, not heads: 26 tanks fill 26 teams, 41 damage only 20.
  const widest = Math.max(1, ...counts.map((row) => row.count / row.slot));

  return (
    <OverviewSection
      title={t(phase === "check_in" ? "overview.field.titleCheckIn" : "overview.field.title")}
      action={
        <SectionLink href={`${overviewHref}/participants`}>{t("overview.field.all")}</SectionLink>
      }
    >
      <div className="grid gap-5">
        <ProfileStat
          label={t("overview.field.teams")}
          value={teams}
          sub={t("overview.field.teamsSub", {
            roster: counts
              .map((row) => t(`overview.field.slot.${row.role}`, { count: row.slot }))
              .join(", ")
          })}
        />
        <ul className="grid gap-3">
          {counts.map((row) => (
            <li
              key={row.role}
              className="grid grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-x-3"
            >
              <PlayerRoleIcon role={row.role} ontology={ontology} size={18} decorative />
              <span className="flex min-w-0 flex-col gap-1">
                <span className="flex items-baseline justify-between gap-2 text-caption">
                  <span className="font-semibold">{t(`roles.${row.role}`)}</span>
                  <span className="text-label text-[color:var(--aqt-fg-dim)]">
                    {t("overview.field.enoughFor", { count: Math.floor(row.count / row.slot) })}
                  </span>
                </span>
                <span
                  aria-hidden
                  className="block h-1.5 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]"
                >
                  <span
                    className="block h-full rounded-full"
                    style={{
                      width: `${(row.count / row.slot / widest) * 100}%`,
                      backgroundColor: roleColor(ontology, row.role) ?? "var(--aqt-fg-muted)"
                    }}
                  />
                </span>
              </span>
              <span className="aqt-tnum w-10 text-right text-caption font-semibold">
                {row.count}
              </span>
            </li>
          ))}
        </ul>
        {short.length > 0 ? (
          <>
            <Separator />
            <p className="text-caption text-[color:var(--aqt-fg-muted)]">
              {t("overview.field.short", {
                team: next,
                list: short
                  .map((row) =>
                    t("overview.field.shortRole", { count: row.need, role: t(`roles.${row.role}`) })
                  )
                  .join(", ")
              })}
            </p>
          </>
        ) : null}
      </div>
    </OverviewSection>
  );
}

function RegistrationNumbersCard({
  field,
  active,
  phase,
  capacity,
  teamRegistration
}: Readonly<{
  field: readonly Registration[];
  active: readonly Registration[];
  phase: "registration" | "check_in";
  capacity: number | null;
  teamRegistration: boolean;
}>) {
  const t = useTranslations("tournamentDetail");
  const approved = active.filter((registration) => registration.status === "approved").length;
  // Team registration counts the teams the applications came in with; a pool counts its first-timers.
  const lastStat = teamRegistration
    ? {
        label: "overview.regNumbers.teams" as const,
        value: new Set(active.flatMap((registration) => registration.team?.id ?? [])).size
      }
    : {
        label: "overview.regNumbers.newcomers" as const,
        value: active.filter((registration) => (registration.tournament_history_count ?? 0) === 0)
          .length
      };
  const checkedIn = active.filter((registration) => registration.checked_in).length;
  return (
    <OverviewSection title={t("overview.regNumbers.title")}>
      <div className="grid grid-cols-2 gap-x-6 gap-y-5">
        <ProfileStat
          label={t("overview.regNumbers.applications")}
          value={active.length}
          sub={capacity ? t("common.ofTotal", { total: capacity }) : undefined}
          size="md"
        />
        <ProfileStat label={t("overview.regNumbers.approved")} value={approved} size="md" />
        {phase === "check_in" ? (
          <ProfileStat
            label={t("overview.regNumbers.checkedIn")}
            value={checkedIn}
            sub={t("common.ofTotal", { total: approved })}
            size="md"
          />
        ) : (
          <ProfileStat
            label={t("overview.regNumbers.onReview")}
            value={active.length - approved}
            size="md"
          />
        )}
        <ProfileStat
          label={t(lastStat.label)}
          value={lastStat.value}
          sub={
            field.length - active.length > 0
              ? t("overview.regNumbers.withdrawn", { count: field.length - active.length })
              : undefined
          }
          size="md"
        />
      </div>
    </OverviewSection>
  );
}

/** Rows in the side column's list: sized so that column ends level with the field and the reference beside it. */
const LIST_ROWS = 10;

/**
 * The pre-start lists' row, in the draft room's shape: role icon, handle over the role in words, and an optional
 * right-hand note.
 */
function RegistrationRows({
  registrations,
  ontology,
  trailing
}: Readonly<{
  registrations: readonly Registration[];
  ontology: RoleOntology | null;
  trailing?: (registration: Registration) => React.ReactNode;
}>) {
  const tCommon = useTranslations("common");
  return (
    <ol className="-my-2 divide-y divide-[color:var(--aqt-border)]">
      {registrations.map((registration) => {
        const role =
          registration.roles.find((item) => item.is_primary)?.role ??
          registration.roles[0]?.role ??
          null;
        const base = primaryRole(registration);
        return (
          <li
            key={registration.id}
            className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-x-2.5 py-2"
          >
            <PlayerRoleIcon role={role} ontology={ontology} size={16} decorative />
            <span className="min-w-0">
              <PlayerName
                player={{ name: registration.primary_handle ?? "—" }}
                className="text-caption"
              />
              {isTournamentRole(base) ? (
                <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
                  {tCommon(`roles.${base}`)}
                </span>
              ) : null}
            </span>
            <span className="aqt-tnum text-label text-[color:var(--aqt-fg-muted)]">
              {trailing?.(registration)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function LatestCard({
  active,
  ontology
}: Readonly<{ active: readonly Registration[]; ontology: RoleOntology | null }>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  // Null until hydration: the recency waits rather than disagree with the server render.
  const now = useMinuteClock();
  const latest = [...active]
    .sort((a, b) => String(b.submitted_at).localeCompare(String(a.submitted_at)))
    .slice(0, LIST_ROWS);
  return (
    <OverviewSection title={t("overview.latest.title")}>
      <RegistrationRows
        registrations={latest}
        ontology={ontology}
        trailing={(registration) =>
          registration.submitted_at && now !== null
            ? format.relativeTime(new Date(registration.submitted_at), { now, style: "short" })
            : null
        }
      />
    </OverviewSection>
  );
}

/** Approved players still to check in: the list a player scans for their own name before the deadline. */
function NotCheckedInCard({
  active,
  ontology
}: Readonly<{ active: readonly Registration[]; ontology: RoleOntology | null }>) {
  const t = useTranslations("tournamentDetail");
  const waiting = active.filter(
    (registration) => registration.status === "approved" && !registration.checked_in
  );
  const shown = waiting.slice(0, LIST_ROWS);
  return (
    <OverviewSection title={t("overview.notCheckedIn.title")}>
      {waiting.length === 0 ? (
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">
          {t("overview.notCheckedIn.none")}
        </p>
      ) : (
        <>
          <RegistrationRows registrations={shown} ontology={ontology} />
          {waiting.length > shown.length ? (
            <p className="mt-4 text-label text-[color:var(--aqt-fg-dim)]">
              {t("overview.notCheckedIn.more", { count: waiting.length - shown.length })}
            </p>
          ) : null}
        </>
      )}
    </OverviewSection>
  );
}

/** Before registration opens: when it does, and what a team here is made of. */
function AnnouncementCard({ tournament }: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("tournamentDetail");
  const format = useFormatter();
  const window = tournament.phase_schedule?.find((entry) => entry.status === "registration");
  return (
    <OverviewSection title={t("overview.announcement.title")}>
      <div className="grid gap-5 sm:grid-cols-2">
        <ProfileStat
          label={t("overview.announcement.opens")}
          value={
            window
              ? format.dateTime(new Date(window.starts_at), { day: "numeric", month: "long" })
              : t("overview.announcement.tba")
          }
          sub={
            window
              ? format.dateTime(new Date(window.starts_at), { hour: "2-digit", minute: "2-digit" })
              : undefined
          }
        />
        <ProfileStat
          label={t("overview.announcement.starts")}
          value={format.dateTime(new Date(tournament.start_date), {
            day: "numeric",
            month: "long"
          })}
          sub={t(`overview.formation.${tournament.team_formation === "draft" ? "draft" : "other"}`)}
        />
      </div>
      <p className="mt-5 max-w-[62ch] text-caption text-[color:var(--aqt-fg-muted)]">
        {t(
          tournament.team_formation === "draft"
            ? "overview.announcement.howDraft"
            : "overview.announcement.howOther"
        )}
      </p>
    </OverviewSection>
  );
}
