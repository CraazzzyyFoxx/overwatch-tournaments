"use client";

import { useCallback, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import SubscriptionProvidersCard, {
  type ProviderDraft
} from "@/components/admin/subscriptions/SubscriptionProviderCard";
import { SaveBar } from "@craazzzyyfoxx/admin-kit/kit/SaveBar";
import { SettingsGrid } from "@/components/kit/SettingRow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";
import balancerAdminService from "@/services/balancer-admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { SubscriptionRequirement } from "@/types/registration.types";

import { WorkspaceRequirementCard } from "./_components/workspace-requirement";
import { useUnsavedReporter } from "@/components/kit/SettingsContinuation";

/**
 * Subscription entitlements: which providers this workspace checks against, and
 * the single admission rule every one of its tournaments enforces.
 *
 * This is workspace configuration, which is why it sits in settings rather than
 * on the collector dashboard it used to share a tab strip with — the dashboard
 * answers "are the checks running", this answers "what are they checking".
 */
export default function WorkspaceSubscriptionsSettingsPage() {
  const t = useTranslations("adminSettings.subscriptions");
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission } = usePermissions();
  // The provider-config RPCs behind this section are gated on team.read/team.update
  // (`sub_config_list` / `sub_config_upsert`), so reuse that permission rather than
  // invent a role check: whoever can open this can also save what is on it.
  const canConfigureWorkspace = canAccessPermission("team.update", workspaceId);

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title={t("noWorkspace.title")}
        description={t("noWorkspace.description")}
      />
    );
  }

  if (!canConfigureWorkspace) {
    return (
      <PageStateCard
        state="error"
        title={t("notAvailable.title")}
        description={t("notAvailable.description")}
      />
    );
  }

  return <SubscriptionsSettings workspaceId={workspaceId} />;
}

/**
 * One save for the whole section: every provider draft and the workspace rule
 * go out together behind one `SaveBar`, so there is no per-card Save button to
 * miss and leaving with unsaved edits goes through one guard.
 */
function SubscriptionsSettings({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const reportUnsaved = useUnsavedReporter();
  const tBar = useTranslations("admin.saveBar");
  const tProviders = useTranslations("subscriptionProviders");
  const tRequirement = useTranslations("subscriptionWorkspace");
  const queryClient = useQueryClient();

  const [resetKey, setResetKey] = useState(0);
  const [providerDrafts, setProviderDrafts] = useState<Record<string, ProviderDraft>>({});
  const [requirementDraft, setRequirementDraft] = useState<SubscriptionRequirement | null>(null);

  const onProviderDraft = useCallback((provider: string, draft: ProviderDraft | null) => {
    setProviderDrafts((current) => {
      if (draft) return { ...current, [provider]: draft };
      if (!(provider in current)) return current;
      const rest = { ...current };
      delete rest[provider];
      return rest;
    });
  }, []);

  const drafts = Object.values(providerDrafts);
  const dirty = drafts.length > 0 || requirementDraft !== null;
  const blocked = drafts.some((draft) => draft.blocked);
  const summary = [
    ...drafts.map((draft) => draft.label),
    ...(requirementDraft ? [tRequirement("title")] : [])
  ].join(" · ");

  const discard = () => {
    setRequirementDraft(null);
    setResetKey((key) => key + 1);
  };

  const refetch = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: workspaceQueryKeys.subscriptionProviders(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: workspaceQueryKeys.subscriptionRequirement(workspaceId) })
    ]);

  const save = useMutation({
    // Providers first: the rule may name a provider this save is enabling.
    mutationFn: async () => {
      for (const draft of drafts) {
        await balancerAdminService.upsertSubscriptionProvider(workspaceId, draft.payload);
      }
      if (requirementDraft) {
        await balancerAdminService.upsertSubscriptionRequirement(workspaceId, {
          requirement: requirementDraft
        });
      }
    },
    onSuccess: async () => {
      await refetch();
      discard();
      notify.success(tBar("saved"));
    },
    // What did save re-keys from the refetched config; what did not stays a draft.
    onError: async (error: unknown) => {
      await refetch();
      notify.error(error instanceof Error ? error.message : tBar("saveFailed"));
    }
  });

  return (
    <div className="flex flex-col gap-4">
      <SettingsGrid>
        <SubscriptionProvidersCard
          workspaceId={workspaceId}
          resetKey={resetKey}
          onDraftChange={onProviderDraft}
        />
        <WorkspaceRequirementCard
          workspaceId={workspaceId}
          draft={requirementDraft}
          onDraftChange={setRequirementDraft}
        />
      </SettingsGrid>
      <SaveBar
        onDirtyChange={reportUnsaved}
        dirty={dirty}
        summary={summary}
        saving={save.isPending}
        onDiscard={discard}
        onSave={() => {
          if (blocked) {
            notify.error(tProviders("warnings.duplicateRole"));
            return;
          }
          save.mutate();
        }}
      />
    </div>
  );
}
