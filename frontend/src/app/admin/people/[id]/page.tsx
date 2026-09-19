"use client";

import { useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowRightLeft } from "lucide-react";

import { PlayerProfileBody } from "@/components/admin/PlayerProfileDialog";
import { UserMergeDialog } from "@/components/admin/UserMergeDialog";
import { AdminTabs, type AdminTabItem } from "@/components/kit/AdminTabs";
import { EntityHubHeader } from "@/components/kit/EntityHubHeader";
import { PersonAccountTab } from "@/components/admin/people/PersonAccountTab";
import { PersonAchievementsTab } from "@/components/admin/people/PersonAchievementsTab";
import { PersonParticipationsTab } from "@/components/admin/people/PersonParticipationsTab";
import { RankPlayerPanel } from "@/components/admin/people/PersonRankPanel";
import { SubscriptionPlayerPanel } from "@/components/admin/people/PersonSubscriptionPanel";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { User } from "@/types/user.types";

const TABS = ["identity", "participations", "account", "achievements"] as const;
type PersonTab = (typeof TABS)[number];

const TAB_LABELS: Record<PersonTab, string> = {
  identity: "Identity",
  participations: "Participations",
  account: "Account",
  achievements: "Achievements"
};

function Section({
  title,
  children
}: Readonly<{ title: string; children: React.ReactNode }>) {
  return (
    <section className="rounded-xl border border-border/60 p-4">
      <h2 className={EYEBROW_CLASS}>{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

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
  const params = useParams<{ id: string }>();
  const personId = Number(params.id);
  const searchParams = useSearchParams();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission, hasPermission, isSuperuser, isLoaded } = usePermissions();
  const [mergeOpen, setMergeOpen] = useState(false);

  const canRead = canAccessPermission("user.read", workspaceId);
  const canUpdate = hasPermission("user.update");
  const canReadAuth = hasPermission("auth_user.read");
  const canMerge = isSuperuser;
  const canManageIdentity = isSuperuser;

  const requested = searchParams.get("tab") ?? "";
  const tab: PersonTab = (TABS as readonly string[]).includes(requested)
    ? (requested as PersonTab)
    : "identity";

  const personQuery = useQuery({
    queryKey: ["admin", "person", personId],
    queryFn: async () => {
      const page = await adminService.getUsers({ per_page: -1 });
      const found = page.results.find((candidate) => candidate.id === personId);
      if (!found) throw new Error(`Player identity #${personId} does not exist.`);
      return found;
    },
    enabled: canRead && Number.isFinite(personId)
  });

  if (!isLoaded) {
    return <div className="h-40 animate-pulse rounded-lg bg-muted/40 motion-reduce:animate-none" />;
  }

  if (!canRead) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Unauthorized</CardTitle>
          <CardDescription>
            You do not have permission to read player identities in this workspace.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (personQuery.isError) {
    return (
      <PageStateCard
        state="not-found"
        title="No such player identity"
        description={`Nothing in this workspace is player #${personId}.`}
      />
    );
  }

  const person: User | undefined = personQuery.data;
  const items: AdminTabItem[] = TABS.map((key) => ({
    key,
    label: TAB_LABELS[key],
    href: `/admin/people/${personId}?tab=${key}`
  }));

  return (
    <div className="space-y-4">
      <EntityHubHeader
        title={person?.name ?? `Player #${personId}`}
        backHref="/admin/people"
        meta={[
          <span key="id" className="font-mono tabular-nums">
            #{personId}
          </span>,
          `${person?.social_accounts?.length ?? 0} identities`
        ]}
        actions={
          canMerge && person ? (
            <Button variant="outline" size="sm" onClick={() => setMergeOpen(true)}>
              <ArrowRightLeft aria-hidden className="size-3.5" />
              Merge
            </Button>
          ) : null
        }
      />

      <AdminTabs items={items} activeKey={tab} ariaLabel="Person sections" />

      {tab === "identity" ? (
        person ? (
          // The profile body was built for a max-w-md dialog — a centred avatar
          // and a stacked identity list. Stretched across the page it read as
          // empty, so it keeps dialog width as the left rail and the rank and
          // subscription panels (tables, a chart) take the rest.
          <div className="grid items-start gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <Section title="Profile">
              <PlayerProfileBody
                key={person.id}
                user={person}
                canEdit={canUpdate}
                canManageIdentity={canManageIdentity}
                canSetVisibility={canRead}
                workspaceId={workspaceId}
                // The header already carries Merge; a second button under the
                // avatar said the same thing twice.
                canMerge={false}
              />
            </Section>

            <div className="flex min-w-0 flex-col gap-4">
              <Section title="Rank collection">
                <RankPlayerPanel userId={person.id} />
              </Section>

              <Section title="Subscription">
                <SubscriptionPlayerPanel userId={person.id} label={person.name} />
              </Section>
            </div>
          </div>
        ) : (
          <div className="h-64 animate-pulse rounded-lg bg-muted/40 motion-reduce:animate-none" />
        )
      ) : null}

      {tab === "participations" ? (
        <PersonParticipationsTab
          personId={personId}
          personName={person?.name ?? ""}
          workspaceId={workspaceId}
        />
      ) : null}

      {tab === "account" ? (
        <PersonAccountTab
          personId={personId}
          personName={person?.name ?? ""}
          canReadAuth={canReadAuth}
        />
      ) : null}

      {tab === "achievements" ? <PersonAchievementsTab personId={personId} /> : null}

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
  );
}
