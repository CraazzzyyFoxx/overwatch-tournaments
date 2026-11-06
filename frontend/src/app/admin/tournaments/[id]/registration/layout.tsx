"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import type { LinkTabItem } from "@/components/kit/LinkTabs";
import { usePermissions } from "@/hooks/usePermissions";
import { hasTeamIntake } from "@/lib/tournament/flow-nodes";
import { useHubTournamentQuery } from "../hubQueries";
import { SubTabShell, useSubTabSegment } from "../sub-tabs";
import { REGISTRATION_SUB_TABS, type RegistrationSubTab } from "../tab-guards";

const DEFAULT_SUB_TAB: RegistrationSubTab = "entries";

/**
 * Sub-tab bar of the Registration hub tab: the two views of who entered
 * (entries, teams) and the tools that act on entries (Sheets feed, rank
 * autofill), each a routed tab. The questionnaire builder is configuration
 * and lives in Settings › Registration (`form` redirects there), so it has no
 * tab here.
 *
 * Navigation only: no queries beyond the tournament the guard needs (already
 * in cache from the shell), and no realtime — the hub shell owns that.
 */
export default function RegistrationLayout({ children }: Readonly<{ children: ReactNode }>) {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const router = useRouter();
  const { canAccessPermission, isLoaded: permissionsLoaded } = usePermissions();
  const t = useTranslations("adminTournament.registration");

  const basePath = `/admin/tournaments/${params.id}/registration`;
  const { active: requested, isKnown } = useSubTabSegment(basePath, REGISTRATION_SUB_TABS, DEFAULT_SUB_TAB);

  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const workspaceId = tournamentQuery.data?.workspace_id ?? null;
  /**
   * Registered teams exist only where captains form them: on balancer or draft
   * formation the section is structurally empty, so it is not offered at all.
   * `null` while the tournament is still loading — a `false` there would bounce
   * a legitimate deep link to `teams` before the answer arrived.
   */
  const teamsOffered = tournamentQuery.data ? hasTeamIntake(tournamentQuery.data) : null;
  const known = isKnown && (requested !== "teams" || teamsOffered !== false);
  const active: RegistrationSubTab = known ? requested : DEFAULT_SUB_TAB;

  // Every section of Registration reads teams and registrations, so they share
  // the tab's own grant rather than each carrying a different one.
  const canTeamRead = canAccessPermission("team.read", workspaceId);

  // A URL naming a section that does not exist lands on the landing segment.
  // A caller without the grant is NOT bounced here: the hub shell already
  // replaces the whole tab with `overview`, and bouncing to a sibling section
  // that is gated on the same permission would only loop.
  useEffect(() => {
    if (known) return;
    router.replace(`${basePath}/${DEFAULT_SUB_TAB}`);
  }, [known, basePath, router]);

  const items: LinkTabItem[] = [
    { key: "entries", label: t("tabs.entries"), href: `${basePath}/entries` },
    {
      key: "teams",
      label: t("tabs.teams"),
      href: `${basePath}/teams`,
      hidden: teamsOffered !== true
    },
    { key: "feed", label: t("tabs.feed"), href: `${basePath}/feed` },
    { key: "rank-autofill", label: t("tabs.rankAutofill"), href: `${basePath}/rank-autofill` }
  ];

  // Held back until permissions resolve, so a legitimate visitor never sees the
  // tab bar blink out on first paint.
  const allowed = permissionsLoaded && canTeamRead;

  return (
    <SubTabShell items={items} activeKey={active} ariaLabel={t("ariaLabel")} allowed={allowed && known}>
      {children}
    </SubTabShell>
  );
}
