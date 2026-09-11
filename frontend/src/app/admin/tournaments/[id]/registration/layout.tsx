"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";

import { AdminTabs, type AdminTabItem } from "@/components/admin/kit/AdminTabs";
import { usePermissions } from "@/hooks/usePermissions";
import { useHubTournamentQuery } from "../hubQueries";
import { REGISTRATION_SUB_TABS, type RegistrationSubTab } from "../tab-guards";

const SUB_TAB_LABELS: Record<RegistrationSubTab, string> = {
  entries: "Entries",
  teams: "Teams",
  form: "Form",
  feed: "Sheets feed",
  "rank-autofill": "Rank autofill"
};

const DEFAULT_SUB_TAB: RegistrationSubTab = "entries";

function isRegistrationSubTab(value: string): value is RegistrationSubTab {
  return (REGISTRATION_SUB_TABS as readonly string[]).includes(value);
}

/**
 * Sub-tab bar for the Registration hub tab.
 *
 * The three sibling routes (form, feed, rank-autofill) used to be reachable
 * only from a dropdown inside the entries table — an orphan cluster with no
 * visible switcher. They are the same kind of destination as the Matches
 * sub-tabs, so they get the same bar, from the same component.
 *
 * Navigation only: no queries beyond the tournament the guard needs (already
 * in cache from the shell), and no realtime — the hub shell owns that.
 */
export default function RegistrationLayout({ children }: Readonly<{ children: ReactNode }>) {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const pathname = usePathname();
  const router = useRouter();
  const { canAccessPermission, isLoaded: permissionsLoaded } = usePermissions();

  const basePath = `/admin/tournaments/${params.id}/registration`;
  const segment = pathname.startsWith(basePath)
    ? (pathname.slice(basePath.length).split("/").find(Boolean) ?? DEFAULT_SUB_TAB)
    : DEFAULT_SUB_TAB;

  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const workspaceId = tournamentQuery.data?.workspace_id ?? null;
  /**
   * Registered teams exist only where captains form them: on balancer or draft
   * formation the section is structurally empty, so it is not offered at all.
   * `null` while the tournament is still loading — a `false` there would bounce
   * a legitimate deep link to `teams` before the answer arrived.
   */
  const teamsOffered = tournamentQuery.data
    ? tournamentQuery.data.team_formation === "registration"
    : null;
  const isKnownSegment = isRegistrationSubTab(segment);
  const known = isKnownSegment && (segment !== "teams" || teamsOffered !== false);
  const active: RegistrationSubTab = known && isKnownSegment ? segment : DEFAULT_SUB_TAB;

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

  const items: AdminTabItem[] = REGISTRATION_SUB_TABS.map((key) => ({
    key,
    label: SUB_TAB_LABELS[key],
    href: `${basePath}/${key}`,
    hidden: key === "teams" && teamsOffered !== true
  }));

  // Held back until permissions resolve, so a legitimate visitor never sees the
  // tab bar blink out on first paint.
  const allowed = permissionsLoaded && canTeamRead;

  return (
    <div className="space-y-4">
      <AdminTabs items={items} activeKey={active} level={2} ariaLabel="Registration sections" />
      {allowed && known ? children : null}
    </div>
  );
}
