import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Crown, Scale, ShieldCheck, type LucideIcon } from "lucide-react";

import { Markdown } from "@/components/Markdown";
import {
  Column,
  ColumnHead,
  EYEBROW_CLASS,
  Section,
  SectionHead
} from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatLocale } from "@/lib/datetime/server";
import { getPlayerSlug } from "@/lib/player";
import { tournamentHref } from "@/lib/tournament/url";
import { getUtcOffsetLabel } from "@/lib/workspace/timezone";
import workspaceService from "@/services/workspace.service";
import type { WorkspaceStaffMember, WorkspaceStaffRole, Workspace } from "@/types/workspace.types";

import { getCommunityTournament } from "./community.data";

const TITLE_ID = "about-title";

const ROLE_ICON: Record<WorkspaceStaffRole, LucideIcon> = {
  owner: Crown,
  admin: ShieldCheck,
  referee: Scale
};

export async function AboutStaffSkeleton({ workspace }: Readonly<{ workspace: Workspace }>) {
  const t = await getTranslations("workspace");
  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        rubric={workspace.about ? t("about.rubric") : undefined}
        title={workspace.about ? t("about.title") : t("about.staffTitle")}
        titleId={TITLE_ID}
      />
      <div className="grid gap-y-3">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-14 w-full" />
        ))}
      </div>
    </Section>
  );
}

/**
 * Who the community is and who runs it. Both halves are organizer-supplied, so
 * the section only exists once at least one of them does.
 */
export async function AboutStaff({ workspace }: Readonly<{ workspace: Workspace }>) {
  const t = await getTranslations("workspace");

  let staff: WorkspaceStaffMember[] = [];
  try {
    staff = await workspaceService.getStaff(workspace.id);
  } catch {
    // The staff list is optional data, not a failure worth a page state.
  }

  if (!workspace.about && staff.length === 0) return null;

  if (!workspace.about) {
    return (
      <Section labelledBy={TITLE_ID}>
        <SectionHead
          rubric={t("about.rubric")}
          title={t("about.staffTitle")}
          titleId={TITLE_ID}
        />
        <StaffList staff={staff} />
      </Section>
    );
  }

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead rubric={t("about.rubric")} title={t("about.title")} titleId={TITLE_ID} />
      <div className="grid items-start gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div>
          <Markdown
            source={workspace.about}
            className="max-w-[46rem] space-y-3 text-ui leading-[1.6] text-[color:var(--aqt-fg-muted)]"
          />
          <AboutFacts workspace={workspace} />
        </div>
        {staff.length > 0 ? (
          <Column>
            <ColumnHead title={t("about.staffTitle")} />
            <StaffList staff={staff} />
          </Column>
        ) : null}
      </div>
    </Section>
  );
}

/** When matches are played, and where to read the rules of the next one. */
async function AboutFacts({ workspace }: Readonly<{ workspace: Workspace }>) {
  const [t, locale] = await Promise.all([getTranslations("workspace"), getFormatLocale()]);

  let tournament = null;
  try {
    tournament = await getCommunityTournament(workspace.id);
  } catch {
    // Only the second row depends on it.
  }

  const zone =
    new Intl.DateTimeFormat(locale, {
      timeZone: workspace.timezone,
      timeZoneName: "shortGeneric"
    })
      .formatToParts(new Date())
      .find((part) => part.type === "timeZoneName")?.value ?? workspace.timezone;

  return (
    <dl className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(min(100%,180px),1fr))] gap-x-6 gap-y-3 border-y border-[color:var(--aqt-border)] py-3.5">
      <div>
        <dt className={EYEBROW_CLASS}>{t("about.matchTime")}</dt>
        <dd className="mt-1 text-ui text-[color:var(--aqt-fg)]">
          {t("about.matchTimeValue", {
            zone,
            offset: getUtcOffsetLabel(workspace.timezone)
          })}
        </dd>
      </div>
      {tournament ? (
        <div>
          <dt className={EYEBROW_CLASS}>{t("about.nextTournament")}</dt>
          <dd className="mt-1 text-ui">
            <Link
              href={tournamentHref(tournament, "/rules")}
              prefetch={false}
              className="text-[color:var(--aqt-teal)] hover:text-[color:color-mix(in_srgb,var(--aqt-teal)_78%,white)]"
            >
              {t("about.rulesOf", { name: tournament.name })}
            </Link>
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

async function StaffList({ staff }: Readonly<{ staff: WorkspaceStaffMember[] }>) {
  const t = await getTranslations("workspace");
  return (
    <ul>
      {staff.map((member) => {
        const Icon = ROLE_ICON[member.role];
        return (
          <li key={`${member.role}-${member.name}`}>
            <Link
              href={`/users/${getPlayerSlug(member.name)}`}
              prefetch={false}
              className="flex min-h-14 items-center gap-3 border-b border-[color:var(--aqt-border)]"
            >
              <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-dim)]">
                <Icon className="size-3.5" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block truncate font-semibold text-[color:var(--aqt-fg)]">
                  {member.name}
                </span>
                <small className="text-caption text-[color:var(--aqt-fg-dim)]">
                  {t(`about.role.${member.role}`)}
                </small>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
