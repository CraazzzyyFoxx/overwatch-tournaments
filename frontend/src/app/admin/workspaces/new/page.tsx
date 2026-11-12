"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { PermissionGate } from "@/components/admin/PermissionGate";
import { WizardShell } from "@/components/kit/WizardShell";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { SLUG_MAX_LENGTH } from "@/lib/workspace/slug";
import workspaceService from "@/services/workspace.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

import { BasicsStep, type BasicsValue } from "./steps/BasicsStep";
import { BrandingStep } from "./steps/BrandingStep";
import { DiscordStep } from "./steps/DiscordStep";
import { DoneStep } from "./steps/DoneStep";
import { ProfileStep } from "./steps/ProfileStep";
import {
  basicsPayload,
  brandingForm,
  brandingPayload,
  createRefusal,
  nextWizardStep,
  previousWizardStep,
  profileForm,
  profilePayload,
  railSteps,
  validateBasics,
  wizardLocation,
  WIZARD_STEPS,
  type BrandingForm,
  type ProfileForm,
  type ProfilePayload,
  type SkippedSteps,
  type WizardStep
} from "./wizard-model";

const EMPTY_BASICS: BasicsValue = {
  name: "",
  slug: "",
  slugTouched: false,
  description: "",
  icon: null
};

/**
 * The T6 wizard that creates a workspace and walks its first setup.
 *
 * Step 1 creates the workspace (the `/get-workspace` form is the same step and
 * lands here on step 2); every later step PATCHes it on Continue, so there is
 * no draft to lose and "Finish later" is always safe. The step and the id live
 * in the URL, so a reload keeps the place.
 */
export default function NewWorkspacePage() {
  const t = useTranslations("adminWorkspace.newWorkspace");
  const router = useRouter();
  const queryClient = useQueryClient();
  const { canUseCapability, isLoaded } = usePermissions();
  const fetchWorkspaces = useWorkspaceStore((s) => s.fetchWorkspaces);
  const setCurrentWorkspace = useWorkspaceStore((s) => s.setCurrentWorkspace);
  // `push`: the browser Back button should step back a step.
  const { searchParams, setParams } = useQueryParams({ mode: "push" });
  const { step: activeStep, id } = wizardLocation(
    searchParams?.get("step"),
    searchParams?.get("id")
  );

  const [skipped, setSkipped] = useState<SkippedSteps>({});
  // `null` = untouched: a step shows the saved workspace until it is edited.
  const [basicsDraft, setBasics] = useState<BasicsValue | null>(null);
  const [profileDraft, setProfile] = useState<ProfileForm | null>(null);
  const [brandingDraft, setBranding] = useState<BrandingForm | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  // What the server said about one slug; stale as soon as the slug changes.
  const [refusal, setRefusal] = useState<{ slug: string; code: "reserved" | "taken" } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const workspaceQuery = useQuery({
    queryKey: adminQueryKeys.workspace(id ?? 0),
    queryFn: () => workspaceService.getById(id as number),
    enabled: id !== null
  });
  const workspace = workspaceQuery.data;

  const basics =
    basicsDraft ??
    (workspace
      ? {
          ...EMPTY_BASICS,
          name: workspace.name,
          slug: workspace.slug,
          description: workspace.description ?? ""
        }
      : EMPTY_BASICS);
  const profile = profileDraft ?? (workspace ? profileForm(workspace) : null);
  const branding = brandingDraft ?? (workspace ? brandingForm(workspace) : null);

  const refresh = (workspaceId: number) => {
    void queryClient.invalidateQueries({ queryKey: adminQueryKeys.workspaces() });
    void queryClient.invalidateQueries({ queryKey: adminQueryKeys.workspace(workspaceId) });
    void fetchWorkspaces();
  };

  const advance = (from: WizardStep, skip: boolean) => {
    setSkipped((current) => ({ ...current, [from]: skip || undefined }));
    setParams({ step: nextWizardStep(from) });
  };

  const basicsMutation = useMutation({
    mutationFn: async (value: BasicsValue): Promise<number> => {
      let workspaceId: number;
      if (workspace) {
        const payload = basicsPayload(value, workspace);
        if (Object.keys(payload).length > 0) await workspaceService.update(workspace.id, payload);
        workspaceId = workspace.id;
      } else {
        const created = await workspaceService.create({
          slug: value.slug,
          name: value.name.trim(),
          description: value.description.trim() || undefined
        });
        workspaceId = created.id;
      }
      // The icon has its own endpoint, so it can only follow the workspace. A
      // failed upload must not fail the step: the workspace already exists,
      // and a retried Create would be refused or make a second one.
      if (value.icon) {
        await workspaceService
          .uploadIcon(workspaceId, value.icon.file)
          .catch((error) => notify.apiError(error, { title: t("basics.iconError") }));
      }
      return workspaceId;
    },
    onSuccess: (workspaceId) => {
      setBasics((current) => current && { ...current, icon: null });
      refresh(workspaceId);
      setParams({ id: workspaceId, step: nextWizardStep("basics") });
    },
    onError: (error, value) => {
      if (workspace) {
        notify.apiError(error, { title: t("saveError") });
        return;
      }
      const code = createRefusal(error);
      if (code === "limit") setFormError(t("validation.limit"));
      else if (code) setRefusal({ slug: value.slug, code });
      else setFormError(getApiErrorMessage(error, t("validation.createError")));
    }
  });

  const patchMutation = useMutation({
    mutationFn: async ({
      payload
    }: {
      step: WizardStep;
      payload: ProfilePayload | Partial<BrandingForm>;
    }) => {
      if (Object.keys(payload).length > 0) await workspaceService.update(id as number, payload);
    },
    onSuccess: (_, { step }) => {
      refresh(id as number);
      advance(step, false);
    },
    onError: (error) => notify.apiError(error, { title: t("saveError") })
  });

  const pending = basicsMutation.isPending || patchMutation.isPending;
  const locked = workspace !== undefined;

  const problems = validateBasics(basics);
  const slugRefusal = refusal?.slug === basics.slug ? refusal.code : undefined;
  // A slug error shows as it is typed; an empty field only after a Create.
  const slugCode = locked
    ? undefined
    : (slugRefusal ?? (showErrors || basics.slug ? problems.slug : undefined));
  const basicsErrors = {
    name: showErrors && problems.name ? t("validation.name.empty") : undefined,
    slug: slugCode ? t(`validation.slug.${slugCode}`, { max: SLUG_MAX_LENGTH }) : undefined,
    form: formError ?? undefined
  };

  const submitBasics = () => {
    setShowErrors(true);
    setFormError(null);
    if (problems.name || (!locked && (problems.slug || slugRefusal))) return;
    basicsMutation.mutate(basics);
  };

  const onNext: Record<WizardStep, () => void> = {
    basics: submitBasics,
    profile: () => {
      if (workspace && profile) {
        patchMutation.mutate({ step: "profile", payload: profilePayload(profile, workspace) });
      }
    },
    branding: () => {
      if (workspace && branding) {
        patchMutation.mutate({ step: "branding", payload: brandingPayload(branding, workspace) });
      }
    },
    // Continue without a server is a skip, and the rail says so.
    discord: () => advance("discord", !workspace?.discord_guild_id),
    done: () => router.push("/admin/settings")
  };

  const nextLabel =
    activeStep === "done"
      ? t("actions.finish")
      : activeStep === "basics" && !locked
        ? t(pending ? "actions.creating" : "actions.create")
        : t(pending ? "actions.saving" : "actions.continue");
  const skippable =
    activeStep === "profile" || activeStep === "branding" || activeStep === "discord";

  return (
    <PermissionGate
      loaded={isLoaded}
      allowed={canUseCapability("workspace.self_create")}
      description={t("unauthorizedDescription")}
    >
      <div className="space-y-5">
        <AdminPageHeader title={t("title")} description={t("description")} />

        <WizardShell
          steps={railSteps(activeStep, skipped).map(({ key, state }) => ({
            key,
            label: t(`steps.${key}.label`),
            state
          }))}
          aside={
            id !== null && activeStep !== "done" ? (
              <Link
                href="/admin/settings"
                onClick={() => setCurrentWorkspace(id)}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:text-primary"
              >
                {t("actions.finishLater")}
              </Link>
            ) : null
          }
          footer={{
            back:
              activeStep !== "basics" && activeStep !== "done"
                ? () => setParams({ step: previousWizardStep(activeStep) })
                : undefined,
            secondary: skippable ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={pending}
                onClick={() => advance(activeStep, true)}
              >
                {t("actions.skip")}
              </Button>
            ) : null,
            next: {
              label: nextLabel,
              onClick: onNext[activeStep],
              disabled: pending || (id !== null && !workspace)
            }
          }}
        >
          <div className="space-y-1">
            <p className={`${eyebrowClass("muted")} tabular-nums`}>
              {t("stepOf", {
                current: WIZARD_STEPS.indexOf(activeStep) + 1,
                total: WIZARD_STEPS.length
              })}
            </p>
            <h2 className="font-display text-xl font-semibold text-foreground">
              {t(`steps.${activeStep}.label`)}
            </h2>
            <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
              {t(`steps.${activeStep}.description`)}
            </p>
          </div>

          {id !== null && !workspace ? (
            workspaceQuery.isError ? (
              <div className="mt-5">
                <PageStateCard state="error" onAction={() => void workspaceQuery.refetch()} />
              </div>
            ) : (
              <Skeleton className="mt-5 h-64 w-full rounded-xl" />
            )
          ) : activeStep === "done" && workspace ? (
            <div className="mt-5">
              <DoneStep workspace={workspace} />
            </div>
          ) : (
            <Card className="mt-5 p-4 sm:p-6">
              {activeStep === "basics" ? (
                <BasicsStep
                  value={basics}
                  onChange={setBasics}
                  locked={locked}
                  iconSrc={workspace?.icon_url ?? null}
                  errors={basicsErrors}
                />
              ) : null}
              {activeStep === "profile" && profile ? (
                <ProfileStep value={profile} onChange={setProfile} />
              ) : null}
              {activeStep === "branding" && branding ? (
                <BrandingStep value={branding} onChange={setBranding} />
              ) : null}
              {activeStep === "discord" && workspace ? (
                <DiscordStep workspace={workspace} onLinked={() => refresh(workspace.id)} />
              ) : null}
            </Card>
          )}
        </WizardShell>
      </div>
    </PermissionGate>
  );
}
