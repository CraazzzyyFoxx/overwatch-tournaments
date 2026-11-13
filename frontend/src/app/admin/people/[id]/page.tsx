"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { UserMergeDialog } from "@/components/admin/UserMergeDialog";
import { LinkTabs, type LinkTabItem } from "@/components/kit/LinkTabs";
import { PersonAccountTab } from "@/components/admin/people/PersonAccountTab";
import { PersonAchievementsTab } from "@/components/admin/people/PersonAchievementsTab";
import { PersonHubHeader } from "@/components/admin/people/PersonHubHeader";
import { PersonParticipationsTab } from "@/components/admin/people/PersonParticipationsTab";
import { PersonProfileTab } from "@/components/admin/people/PersonProfileTab";
import { PersonRanksTab } from "@/components/admin/people/PersonRanksTab";
import { SubscriptionPlayerPanel } from "@/components/admin/people/PersonSubscriptionPanel";
import { PermissionGate } from "@/components/admin/PermissionGate";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { User } from "@/types/user.types";
import { adminQueryKeys } from "@/lib/admin/query-keys";

const TABS = [
  "profile",
  "participations",
  "achievements",
  "ranks",
  "subscriptions",
  "account"
] as const;
type PersonTab = (typeof TABS)[number];

/**
 * One person: who they are, what they played, who signs in as them.
 *
 * The identity itself has no by-id read (`/api/v1/admin/users/{id}` is
 * PATCH/DELETE only), so the person is picked out of the same full list the
 * People browser loads — one shared cache entry, not a second fetch shape.
 * The key is exactly the one `breadcrumb-registry.ts` declares for the
 * `people` segment, which is how the crumb shows a name instead of "Details".
 */
export default function PersonHubPage() {
  const t = useTranslations("adminPeople.person");
  const params = useParams<{ id: string }>();
  const personId = Number(params.id);
  const searchParams = useSearchParams();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission, hasPermission, isSuperuser, isLoaded } = usePermissions();
  const [mergeOpen, setMergeOpen] = useState(false);

  const canRead = canAccessPermission("user.read", workspaceId);
  const canUpdate = hasPermission("user.update");
  const canReadAuth = hasPermission("auth_user.read");
  const canReadRanks = canAccessPermission("team.update", workspaceId);
  const canMerge = isSuperuser;
  const canManageIdentity = isSuperuser;

  const requested = searchParams.get("tab") ?? "";
  const tab: PersonTab = (TABS as readonly string[]).includes(requested)
    ? (requested as PersonTab)
    : "profile";

  const personQuery = useQuery({
    queryKey: adminQueryKeys.person(personId),
    queryFn: async () => {
      const page = await adminService.getUsers({ per_page: -1 });
      const found = page.results.find((candidate) => candidate.id === personId);
      if (!found) throw new Error(t("error", { id: personId }));
      return found;
    },
    enabled: canRead && Number.isFinite(personId)
  });

  // Only asked once the gate passes (`enabled: canRead`), so an error here is
  // always the person's, never the grant's.
  if (personQuery.isError) {
    return (
      <PageStateCard
        state="not-found"
        headingLevel={1}
        title={t("notFound")}
        description={t("notFoundDescription", { id: personId })}
      />
    );
  }

  const person: User | undefined = personQuery.data;
  const tabLabels: Record<PersonTab, string> = {
    profile: t("tabs.profile"), participations: t("tabs.participations"), achievements: t("tabs.achievements"),
    ranks: t("tabs.ranks"), subscriptions: t("tabs.subscriptions"), account: t("tabs.account")
  };
  const items: LinkTabItem[] = TABS.map((key) => ({
    key,
    label: tabLabels[key],
    href: `/admin/people/${personId}?tab=${key}`
  }));

  const name = person?.name ?? t("fallbackName", { id: personId });

  return (
    <PermissionGate loaded={isLoaded} allowed={canRead} description={t("noPermission")}>
      <div className="space-y-6">
        <PersonHubHeader
          person={person}
          personId={personId}
          canEdit={canUpdate}
          actions={
            canMerge && person ? (
              <Button variant="outline" size="sm" onClick={() => setMergeOpen(true)}>
                {t("merge")}
              </Button>
            ) : null
          }
        />

        <LinkTabs items={items} activeKey={tab} ariaLabel={t("sectionsLabel")} />

        {tab === "profile" ? (
          person ? (
            <PersonProfileTab
              key={person.id}
              person={person}
              workspaceId={workspaceId}
              canManageIdentity={canManageIdentity}
              canSetVisibility={canRead}
              canReadAuth={canReadAuth}
            />
          ) : (
            <Skeleton className="h-64 w-full rounded-xl" />
          )
        ) : null}

        {tab === "participations" ? (
          <PersonParticipationsTab
            personId={personId}
            personName={person?.name ?? ""}
            workspaceId={workspaceId}
          />
        ) : null}

        {tab === "achievements" ? <PersonAchievementsTab personId={personId} /> : null}

        {/* `team.update` is the roster owner's grant, the one the ranks endpoint
            checks; without it the tab keeps only collection and history. */}
        {tab === "ranks" ? <PersonRanksTab personId={personId} canReadRanks={canReadRanks} /> : null}

        {tab === "subscriptions" ? <SubscriptionPlayerPanel userId={personId} label={name} /> : null}

        {tab === "account" ? (
          <PersonAccountTab personId={personId} canReadAuth={canReadAuth} />
        ) : null}

        {mergeOpen && person ? (
          <UserMergeDialog
            key={person.id}
            sourceUser={person}
            open
            onOpenChange={setMergeOpen}
            onMerged={() => setMergeOpen(false)}
          />
        ) : null}
      </div>
    </PermissionGate>
  );
}
