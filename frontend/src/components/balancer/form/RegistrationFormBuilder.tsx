"use client";

import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SaveBar } from "@/components/kit/SaveBar";
import { notify } from "@/lib/notify";
import { makeUniqueFieldKey } from "@/lib/forms/keys";
import { toRegistrationFormUpsert } from "@/lib/registration-form-upsert";
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
  normalizeValidation,
  supportsCustomFieldValidation
} from "./_components/formConfig";

/**
 * The questionnaire: what a registrant is asked, and what they may answer.
 *
 * Nothing that decides who gets in lives here any more. Admission rules, the
 * public-page display and the bench size moved to the Settings rail
 * (`settings/admission`, `settings/registration`, `settings/roster`) — they are
 * tournament policy, and holding them inside a field builder is what made this
 * one screen answer four unrelated questions under headings joined by "and".
 *
 * The save still sends the WHOLE form: the upsert is a full replace, so the
 * policy fields are echoed back from `toRegistrationFormUpsert`.
 */
export default function RegistrationFormBuilder({
  tournamentId
}: Readonly<{
  tournamentId: number | null;
}>) {
  const t = useTranslations("registrationFormAdmin.page");

  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

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

  const loadedFormKeyRef = useRef<string | null>(null);

  /** Local state ← a saved form (or the defaults, for a tournament with none). */
  const applyForm = (data: AdminRegistrationForm | null) => {
    startTransition(() => {
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
        // The upsert is a full replace, so the policy fields this page no
        // longer shows travel back untouched from the saved form. Editing a
        // custom field must not reset the admission rules.
        ...toRegistrationFormUpsert(formQuery.data),
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
          updated.key = makeUniqueFieldKey(updates.label, otherKeys);
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
  return (
    <div className="flex flex-col gap-4">
      {/* The policy that used to sit above these cards — who is admitted, what
          the public sees, how deep the bench goes — moved to the Settings rail
          (`settings/registration`, `settings/admission`, `settings/roster`).
          This page is the questionnaire and nothing else: what a registrant is
          asked, and what they may answer. */}

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
