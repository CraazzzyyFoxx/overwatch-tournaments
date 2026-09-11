"use client";

import { startTransition, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { NumberInput } from "@/components/ui/number-input";
import { Switch } from "@/components/ui/switch";
import { SaveBar } from "@/components/admin/kit/SaveBar";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { EYEBROW_CLASS } from "@/components/admin/tone";
import { notify } from "@/lib/notify";
import { useRequirementDescription } from "@/components/admin/subscriptions/useRequirementDescription";
import { ROLES, canonicalToRegistrationRole } from "@/lib/roles";
import adminService from "@/services/admin.service";
import balancerAdminService from "@/services/balancer-admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  AdminCustomFieldDef,
  AdminRegistrationForm,
  AdminRegistrationFormUpsert,
  BuiltInFieldConfig
} from "@/types/balancer-admin.types";

import { BuiltInFieldsCard } from "./_components/BuiltInFieldsCard";
import { CustomFieldsCard } from "./_components/CustomFieldsCard";
import { type CatalogEntry, SubrolesTab } from "./_components/SubrolesTab";
import {
  ROLE_FIELD_KEYS,
  getBuiltInConfig,
  getCustomFieldDefaultValidation,
  hydrateCustomField,
  makeUniqueCustomFieldKey,
  normalizeValidation,
  supportsCustomFieldValidation
} from "./_components/formConfig";

/**
 * One setting: what it is and why on the left, the control on the right — the
 * row every T5 settings section is built from, so this page reads like the
 * tournament Settings tab beside it rather than a column of prose.
 */
function SettingRow({
  htmlFor,
  label,
  hint,
  children
}: Readonly<{ htmlFor?: string; label: string; hint?: ReactNode; children: ReactNode }>) {
  return (
    <div className="grid gap-3 py-4 first:pt-0 last:pb-0 md:grid-cols-2 md:items-center">
      <div className="min-w-0">
        <Label htmlFor={htmlFor} className="text-sm font-medium text-foreground">
          {label}
        </Label>
        {hint ? <p className="mt-0.5 max-w-prose text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      <div className="flex min-w-0 items-center md:justify-end">{children}</div>
    </div>
  );
}

/** A group of rows under an eyebrow; groups are separated by a hairline. */
function SettingGroup({
  title,
  description,
  children
}: Readonly<{ title: string; description?: ReactNode; children: ReactNode }>) {
  return (
    <section className="border-t border-border pt-5 first:border-t-0 first:pt-0">
      <h2 className={EYEBROW_CLASS}>{title}</h2>
      {description ? (
        <p className="mt-1 max-w-prose text-xs text-muted-foreground">{description}</p>
      ) : null}
      <div className="mt-3 divide-y divide-border/60">{children}</div>
    </section>
  );
}

export default function RegistrationFormBuilder({
  tournamentId
}: Readonly<{
  tournamentId: number | null;
}>) {
  const t = useTranslations("registrationFormAdmin.page");
  const tStatus = useTranslations("registrationFormAdmin.status");
  const ids = useId();

  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  const [isOpen, setIsOpen] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  const [requireOpenProfile, setRequireOpenProfile] = useState(false);
  const [openProfileScope, setOpenProfileScope] = useState<"main" | "all">("main");
  const [showRanks, setShowRanks] = useState(false);
  const [maxSubstitutes, setMaxSubstitutes] = useState(0);
  const [subscriptionScope, setSubscriptionScope] = useState<"player" | "team">("player");
  const [teamRankMin, setTeamRankMin] = useState<number | null>(null);
  const [teamRankMax, setTeamRankMax] = useState<number | null>(null);
  const [teamRankSpread, setTeamRankSpread] = useState<number | null>(null);
  const [teamUniqueIdentity, setTeamUniqueIdentity] = useState(false);
  const [teamRequireDiscordGuild, setTeamRequireDiscordGuild] = useState(false);
  const [requireSubscription, setRequireSubscription] = useState(false);
  const [subscriptionStage, setSubscriptionStage] = useState<"registration" | "check_in">(
    "check_in"
  );
  const [builtInFields, setBuiltInFields] = useState<Record<string, BuiltInFieldConfig>>(() =>
    getBuiltInConfig({})
  );
  const [customFields, setCustomFields] = useState<AdminCustomFieldDef[]>([]);
  const [hasChanges, setHasChanges] = useState(false);

  const formQuery = useQuery({
    queryKey: ["balancer-admin", "registration-form", tournamentId],
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId as number),
    enabled: tournamentId !== null,
    // This page is a long-lived editor; a background refetch must not clobber
    // the admin's unsaved edits.
    refetchOnWindowFocus: false
  });

  // Read-only: the rule lives on the workspace now, and the server resolves it
  // onto the read model so this page can show what the toggle above enforces
  // without offering to edit it here.
  const resolvedRequirement = useRequirementDescription(
    formQuery.data?.subscription_requirement_json
  );

  const loadedFormKeyRef = useRef<string | null>(null);

  /** Local state ← a saved form (or the defaults, for a tournament with none). */
  const applyForm = (data: AdminRegistrationForm | null) => {
    startTransition(() => {
      // Derived + read-only: "is registration open right now", computed by the
      // server from the REGISTRATION phase-schedule window.
      setIsOpen(data?.is_open ?? false);
      setAutoApprove(data?.auto_approve ?? false);
      setRequireOpenProfile(data?.require_open_profile ?? false);
      setRequireSubscription(data?.require_subscription ?? false);
      // Default to the looser stage on a form saved before the field existed, so
      // loading an old form never silently arms a sign-up wall.
      setSubscriptionStage(
        data?.subscription_stage === "registration" ? "registration" : "check_in"
      );
      setOpenProfileScope((data?.open_profile_scope as "main" | "all") ?? "main");
      setShowRanks(data?.show_ranks ?? false);
      setMaxSubstitutes(data?.max_substitutes ?? 0);
      setSubscriptionScope(data?.subscription_scope === "team" ? "team" : "player");
      setTeamRankMin(data?.team_rank_min ?? null);
      setTeamRankMax(data?.team_rank_max ?? null);
      setTeamRankSpread(data?.team_max_rank_spread ?? null);
      setTeamUniqueIdentity(data?.team_unique_identity ?? false);
      setTeamRequireDiscordGuild(data?.team_require_discord_guild ?? false);
      setBuiltInFields(getBuiltInConfig(data?.built_in_fields ?? {}));
      setCustomFields((data?.custom_fields ?? []).map(hydrateCustomField));
      setHasChanges(false);
    });
  };

  useEffect(() => {
    const data = formQuery.data;
    if (!data) {
      return;
    }
    const formKey = String(data.id);
    // Always hydrate on initial load / when switching to a different form.
    // For background refetches of the same form, never clobber unsaved edits.
    if (loadedFormKeyRef.current === formKey && hasChanges) {
      return;
    }
    loadedFormKeyRef.current = formKey;
    applyForm(data);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- applyForm only closes over setters
  }, [formQuery.data, hasChanges]);

  // The workspace `PlayerSubRole` catalog is fetched with row ids so the tab can
  // key its chips; managing it lives on `/admin/sub-roles`. The form's embedded
  // `subrole_catalog` only carries {slug,label} for the public wizard.
  const workspaceId = formQuery.data?.workspace_id ?? currentWorkspaceId ?? null;

  const catalogQuery = useQuery({
    queryKey: ["admin", "player-sub-roles", workspaceId],
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId as number }),
    enabled: workspaceId !== null
  });

  const subroleCatalog = useMemo<Record<string, CatalogEntry[]>>(() => {
    const grouped: Record<string, CatalogEntry[]> = Object.fromEntries(
      ROLES.map((role) => [role.code, [] as CatalogEntry[]])
    );
    for (const row of catalogQuery.data ?? []) {
      const code = canonicalToRegistrationRole(row.role);
      if (code && grouped[code]) {
        grouped[code].push({ id: row.id, slug: row.slug, label: row.label });
      }
    }
    return grouped;
  }, [catalogQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!tournamentId) throw new Error(t("noTournamentError"));
      const payload: AdminRegistrationFormUpsert = {
        // No `is_open`: openness is the tournament's REGISTRATION schedule
        // window now, and the server ignores the field.
        auto_approve: autoApprove,
        require_open_profile: requireOpenProfile,
        open_profile_scope: openProfileScope,
        show_ranks: showRanks,
        max_substitutes: maxSubstitutes,
        subscription_scope: subscriptionScope,
        team_rank_min: teamRankMin,
        team_rank_max: teamRankMax,
        team_max_rank_spread: teamRankSpread,
        team_unique_identity: teamUniqueIdentity,
        team_require_discord_guild: teamRequireDiscordGuild,
        require_subscription: requireSubscription,
        subscription_stage: subscriptionStage,
        built_in_fields: Object.fromEntries(
          Object.entries(builtInFields).map(([key, value]) => [
            key,
            { ...value, validation: normalizeValidation(value.validation) }
          ])
        ),
        custom_fields: customFields.map((field) => ({
          ...field,
          validation: normalizeValidation(field.validation)
        }))
      };
      return balancerAdminService.upsertRegistrationForm(tournamentId, payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "registration-form", tournamentId]
      });
      setHasChanges(false);
      notify.success(t("savedToast"));
    }
  });

  const updateBuiltIn = (key: string, updates: Partial<BuiltInFieldConfig>) => {
    setBuiltInFields((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        ...updates,
        ...(Object.prototype.hasOwnProperty.call(updates, "validation")
          ? { validation: normalizeValidation(updates.validation) }
          : {})
      }
    }));
    setHasChanges(true);
  };

  // A single sub-role selection drives both the primary and additional role pickers.
  const subroleSelection =
    builtInFields.primary_role?.subroles ?? builtInFields.additional_roles?.subroles ?? {};

  const handleToggleSubrole = (role: string, _slug: string, nextSlugs: string[]) => {
    setBuiltInFields((prev) => {
      const next = { ...prev };
      for (const fieldKey of ROLE_FIELD_KEYS) {
        const cfg = prev[fieldKey] ?? { enabled: true, required: false };
        next[fieldKey] = {
          ...cfg,
          subroles: { ...(cfg.subroles ?? {}), [role]: nextSlugs }
        };
      }
      return next;
    });
    setHasChanges(true);
  };

  const addCustomField = () => {
    setCustomFields((prev) => [
      ...prev,
      {
        key: "",
        label: "",
        type: "text",
        required: false,
        placeholder: null,
        options: null,
        validation: getCustomFieldDefaultValidation("text")
      }
    ]);
    setHasChanges(true);
  };

  const updateCustomField = (index: number, updates: Partial<AdminCustomFieldDef>) => {
    setCustomFields((prev) =>
      prev.map((field, i) => {
        if (i !== index) return field;
        const updated: AdminCustomFieldDef = { ...field, ...updates };

        if ("type" in updates && updates.type && !supportsCustomFieldValidation(updates.type)) {
          updated.validation = null;
        } else if ("type" in updates && updates.type) {
          updated.validation =
            normalizeValidation(updated.validation) ??
            getCustomFieldDefaultValidation(updates.type);
        }

        // Assign a stable, unique key once when the field is first named; never
        // regenerate it from the label afterwards (keeps custom_fields_json safe).
        if ("label" in updates && updates.label !== undefined && !field.key) {
          const otherKeys = prev.filter((_, j) => j !== index).map((other) => other.key);
          updated.key = makeUniqueCustomFieldKey(updates.label, otherKeys);
        }

        if ("validation" in updates) {
          updated.validation = normalizeValidation(updates.validation);
        }
        return updated;
      })
    );
    setHasChanges(true);
  };

  const removeCustomField = (index: number) => {
    setCustomFields((prev) => prev.filter((_, i) => i !== index));
    setHasChanges(true);
  };

  if (!tournamentId) {
    return (
      <Alert>
        <AlertTitle>{t("noTournament.title")}</AlertTitle>
        <AlertDescription>{t("noTournament.description")}</AlertDescription>
      </Alert>
    );
  }

  if (formQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{t("loadError.title")}</AlertTitle>
        <AlertDescription>
          {(formQuery.error as Error)?.message ?? t("loadError.fallback")}
        </AlertDescription>
      </Alert>
    );
  }

  // Avoid flashing default toggles while the saved form is still loading.
  if (formQuery.isLoading) {
    return (
      <output className="flex flex-1 items-center justify-center py-16 text-sm text-muted-foreground">
        <LoaderCircle className="mr-2 size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        {t("loading")}
      </output>
    );
  }

  const formExists = formQuery.data != null;
  const mark = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setHasChanges(true);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Rules first: everything that decides WHO gets in, as setting rows in
          the same register as the tournament Settings tab. The field builders
          below are lists and keep their own cards. */}
      <Card>
        <CardContent className="flex flex-col gap-5 pt-6">
          <SettingGroup title={tStatus("title")} description={tStatus("description")}>
            <SettingRow label={tStatus("acceptLabel")} hint={tStatus("scheduleHint")}>
              <StatusPill tone={isOpen ? "success" : "neutral"}>
                {isOpen ? tStatus("stateOpen") : tStatus("stateClosed")}
              </StatusPill>
            </SettingRow>
            <SettingRow
              htmlFor={`${ids}-auto-approve`}
              label={tStatus("autoApproveLabel")}
              hint={tStatus("autoApproveHint")}
            >
              <Switch
                id={`${ids}-auto-approve`}
                checked={autoApprove}
                onCheckedChange={mark(setAutoApprove)}
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("team.title")} description={t("team.description")}>
            <SettingRow
              htmlFor={`${ids}-max-substitutes`}
              label={t("team.maxSubstitutes")}
              hint={t("team.maxSubstitutesHint")}
            >
              <NumberInput
                id={`${ids}-max-substitutes`}
                integer
                min={0}
                value={maxSubstitutes}
                onValueChange={(next) => mark(setMaxSubstitutes)(next ?? 0)}
                aria-label={t("team.maxSubstitutesAria")}
                className="h-8 w-20 text-sm tabular-nums"
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("admission.title")}>
            <SettingRow
              htmlFor={`${ids}-open-profile`}
              label={t("admission.requireOpenProfile")}
              hint={t("admission.hint")}
            >
              <Switch
                id={`${ids}-open-profile`}
                checked={requireOpenProfile}
                onCheckedChange={mark(setRequireOpenProfile)}
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-scope`} label={t("admission.scope")}>
              <Select
                value={openProfileScope}
                disabled={!requireOpenProfile}
                onValueChange={mark((value: string) => setOpenProfileScope(value as "main" | "all"))}
              >
                <SelectTrigger
                  id={`${ids}-scope`}
                  // Sized from content, not a pixel width: the Russian option
                  // labels are longer and a fixed 230px clipped them.
                  className="h-8 w-fit min-w-[230px] max-w-full text-sm"
                  aria-label={t("admission.scopeAria")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="main">{t("admission.scopeMain")}</SelectItem>
                  <SelectItem value="all">{t("admission.scopeAll")}</SelectItem>
                </SelectContent>
              </Select>
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("subscription.title")} description={t("subscription.hint")}>
            <SettingRow
              htmlFor={`${ids}-subscription`}
              label={t("subscription.require")}
              hint={
                <>
                  {/* The workspace rule reaches this page as a projection ON the
                      form, so `resolvedRequirement === ""` means two different
                      things: the workspace has no rule, or there is no form to
                      read one from (`reg_form_get` returns null until the first
                      save — rows are created lazily). Only the first licenses the
                      "enforces nothing" claim; asserting it for a brand-new
                      tournament states a truth nobody has looked up. `!formExists`
                      also covers `formQuery.isPending`. */}
                  {!formExists
                    ? t("subscription.resolvedUnknown")
                    : resolvedRequirement
                      ? t("subscription.resolved", { rule: resolvedRequirement })
                      : t("subscription.resolvedEmpty")}{" "}
                  {/* The workspace rule is workspace *configuration*, so it lives
                      in settings; /admin/subscriptions is the collector dashboard. */}
                  <Link
                    href="/admin/settings/subscriptions"
                    className="font-medium text-foreground underline underline-offset-4"
                  >
                    {t("subscription.manage")}
                  </Link>
                </>
              }
            >
              <Switch
                id={`${ids}-subscription`}
                checked={requireSubscription}
                onCheckedChange={mark(setRequireSubscription)}
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-stage`} label={t("subscription.stage")}>
              <Select
                value={subscriptionStage}
                disabled={!requireSubscription}
                onValueChange={mark((value: string) =>
                  setSubscriptionStage(value as "registration" | "check_in")
                )}
              >
                <SelectTrigger
                  id={`${ids}-stage`}
                  className="h-8 w-fit min-w-[230px] max-w-full text-sm"
                  aria-label={t("subscription.stageAria")}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="check_in">{t("subscription.stageCheckIn")}</SelectItem>
                  <SelectItem value="registration">
                    {t("subscription.stageRegistration")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("team.title")} description={t("team.description")}>
            <SettingRow
              htmlFor={`${ids}-max-subs`}
              label={t("team.maxSubstitutes")}
              hint={t("team.maxSubstitutesHint")}
            >
              <NumberInput
                id={`${ids}-max-subs`}
                integer
                min={0}
                value={maxSubstitutes}
                onValueChange={mark((value: number | null) => setMaxSubstitutes(value ?? 0))}
                aria-label={t("team.maxSubstitutesAria")}
                className="h-8 w-24"
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-sub-scope`} label={t("team.scope")} hint={t("team.scopeHint")}>
              <Select
                value={subscriptionScope}
                onValueChange={mark((value: string) => setSubscriptionScope(value as "player" | "team"))}
              >
                <SelectTrigger id={`${ids}-sub-scope`} className="h-8 w-fit min-w-[230px] max-w-full text-sm" aria-label={t("team.scopeAria")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="player">{t("team.scopePlayer")}</SelectItem>
                  <SelectItem value="team">{t("team.scopeTeam")}</SelectItem>
                </SelectContent>
              </Select>
            </SettingRow>
            <SettingRow htmlFor={`${ids}-rank-min`} label={t("team.rankMin")} hint={t("team.rankHint")}>
              <NumberInput
                id={`${ids}-rank-min`}
                integer
                min={0}
                value={teamRankMin}
                onValueChange={mark(setTeamRankMin)}
                className="h-8 w-24"
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-rank-max`} label={t("team.rankMax")}>
              <NumberInput
                id={`${ids}-rank-max`}
                integer
                min={0}
                value={teamRankMax}
                onValueChange={mark(setTeamRankMax)}
                className="h-8 w-24"
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-rank-spread`} label={t("team.rankSpread")}>
              <NumberInput
                id={`${ids}-rank-spread`}
                integer
                min={0}
                value={teamRankSpread}
                onValueChange={mark(setTeamRankSpread)}
                className="h-8 w-24"
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-unique-id`} label={t("team.uniqueIdentity")} hint={t("team.uniqueIdentityHint")}>
              <Switch
                id={`${ids}-unique-id`}
                checked={teamUniqueIdentity}
                onCheckedChange={mark(setTeamUniqueIdentity)}
              />
            </SettingRow>
            <SettingRow htmlFor={`${ids}-discord-guild`} label={t("team.requireDiscordGuild")} hint={t("team.requireDiscordGuildHint")}>
              <Switch
                id={`${ids}-discord-guild`}
                checked={teamRequireDiscordGuild}
                onCheckedChange={mark(setTeamRequireDiscordGuild)}
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup title={t("display.title")}>
            <SettingRow
              htmlFor={`${ids}-show-ranks`}
              label={t("display.showRanks")}
              hint={t("display.hint")}
            >
              <Switch
                id={`${ids}-show-ranks`}
                checked={showRanks}
                onCheckedChange={mark(setShowRanks)}
              />
            </SettingRow>
          </SettingGroup>
        </CardContent>
      </Card>

      <BuiltInFieldsCard builtInFields={builtInFields} onUpdate={updateBuiltIn} />

      <SubrolesTab
        catalog={subroleCatalog}
        selection={subroleSelection}
        onToggleOffered={handleToggleSubrole}
        isLoading={catalogQuery.isLoading}
      />

      <CustomFieldsCard
        customFields={customFields}
        onAdd={addCustomField}
        onUpdate={updateCustomField}
        onRemove={removeCustomField}
      />

      {/* The shared bar. Shown while dirty like every settings section — and
          also for a tournament with no saved form, where "Create form" must be
          reachable before any edit; the navigation guard stays off in that
          untouched state so the page does not prompt on every tab switch. */}
      <SaveBar
        dirty={hasChanges || !formExists}
        guardNavigation={hasChanges}
        summary={hasChanges ? t("unsavedChanges") : ""}
        saving={saveMutation.isPending}
        primaryLabel={formExists ? t("saveChanges") : t("createForm")}
        onDiscard={() => applyForm(formQuery.data ?? null)}
        onSave={() => saveMutation.mutate()}
      />
    </div>
  );
}
