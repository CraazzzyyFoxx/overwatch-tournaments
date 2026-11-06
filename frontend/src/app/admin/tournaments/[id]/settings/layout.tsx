"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import type messages from "@/i18n/messages/en.json";
import type { ComponentType, ReactNode } from "react";

import { SectionNav, useSectionNavEntrance, type SectionNavGroup } from "@/components/kit/SectionNav";
import { SettingsContinuation } from "@/components/kit/SettingsContinuation";
import { SettingsOutlineProvider } from "@/components/kit/SettingsOutline";
import { useHubTournamentQuery } from "../hubQueries";
import { useSubTabSegment, useTabAccess } from "../sub-tabs";
import { allowedSettingsSection, SETTINGS_SECTIONS, type SettingsSection } from "../tab-guards";
import { SETTINGS_SECTION_GROUPS, SETTINGS_SECTION_LABEL_KEYS } from "./settings-sections";

/**
 * The sections a reader can scroll through, in rail order, each with its page
 * for the ghost under the one before it. Pre-game, the report form and links
 * are editors and tables with scroll areas of their own, and a strip of one
 * says nothing about it; Danger zone is never a page a scroll should land on.
 * They keep their rail items and are skipped by the chain.
 */
const CONTINUED_SECTIONS: Partial<Record<SettingsSection, ComponentType>> = {
  general: dynamic(() => import("./general/page")),
  rules: dynamic(() => import("./rules/page")),
  scoring: dynamic(() => import("./scoring/page")),
  schedule: dynamic(() => import("./schedule/page")),
  roster: dynamic(() => import("./roster/page")),
  registration: dynamic(() => import("./registration/page")),
  admission: dynamic(() => import("./admission/page")),
  challonge: dynamic(() => import("./challonge/page")),
  discord: dynamic(() => import("./discord/page")),
  preview: dynamic(() => import("./preview/page"))
};

/**
 * Navigation of the settings hub (T5), and the scroll chain between its form
 * sections: a ghost of the next one under each, a pull past the top back to
 * the previous one (`SettingsContinuation`, keyed per section so each page
 * lands at the edge it was entered from).
 *
 * No queries and no subscriptions live here: the hub shell is the single
 * realtime mount, and the tournament read below is the same cached key the
 * shell already resolved (TanStack dedupes the observer), needed only to
 * decide which sections this caller may open.
 */
export default function TournamentSettingsLayout({
  children
}: Readonly<{ children: ReactNode }>) {
  const params = useParams<{ id: string }>();
  const t = useTranslations("adminTournament.settings");
  const tournamentId = Number(params.id);
  // `/admin/tournaments/14/settings/pre-game` → section `pre-game`; the bare
  // `/settings` renders General in place (`page.tsx`), so it is General too.
  const { active: activeKey } = useSubTabSegment(
    `/admin/tournaments/${tournamentId}/settings`,
    SETTINGS_SECTIONS,
    "general"
  );

  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const access = useTabAccess(tournamentQuery.data);
  const columnRef = useSectionNavEntrance<HTMLDivElement>();

  type SectionKey = keyof typeof messages.adminTournament.settings.sections;
  type GroupKey = keyof typeof messages.adminTournament.settings.groups;
  const sectionLabel = (key: SectionKey) =>
    t(`sections.${key}` as `sections.${SectionKey}`);
  const groupLabel = (key: GroupKey) => t(`groups.${key}` as `groups.${GroupKey}`);
  const href = (section: SettingsSection) =>
    `/admin/tournaments/${tournamentId}/settings/${section}`;

  const groups: SectionNavGroup[] = SETTINGS_SECTION_GROUPS.map((group) => ({
    label: group.labelKey ? groupLabel(group.labelKey) : group.label,
    items: group.sections.map((section) => ({
      key: section,
      label: sectionLabel(SETTINGS_SECTION_LABEL_KEYS[section]),
      href: href(section),
      tone: section === "danger" ? ("danger" as const) : undefined,
      hidden: !allowedSettingsSection(section, access)
    }))
  }));

  // Only sections this caller may open: a ghost of a refused page would show
  // its "not permitted" card, and a pull would land on it.
  const chain = SETTINGS_SECTIONS.filter(
    (section) => CONTINUED_SECTIONS[section] && allowedSettingsSection(section, access)
  );
  const index = chain.indexOf(activeKey);
  const previousKey = index > 0 ? chain[index - 1] : undefined;
  const nextKey = index >= 0 ? chain[index + 1] : undefined;
  const NextPage = nextKey ? CONTINUED_SECTIONS[nextKey] : undefined;

  return (
    <SettingsOutlineProvider>
      <div className="flex flex-col gap-4 lg:flex-row lg:gap-6">
        <SectionNav groups={groups} activeKey={activeKey} />
        <div ref={columnRef} className="flex min-w-0 flex-1 flex-col gap-4">
          <SettingsContinuation
            key={activeKey}
            previous={
              previousKey
                ? {
                    href: href(previousKey),
                    title: sectionLabel(SETTINGS_SECTION_LABEL_KEYS[previousKey])
                  }
                : null
            }
            next={
              nextKey && NextPage
                ? {
                    href: href(nextKey),
                    title: sectionLabel(SETTINGS_SECTION_LABEL_KEYS[nextKey]),
                    preview: <NextPage />
                  }
                : null
            }
          >
            {children}
          </SettingsContinuation>
        </div>
      </div>
    </SettingsOutlineProvider>
  );
}
