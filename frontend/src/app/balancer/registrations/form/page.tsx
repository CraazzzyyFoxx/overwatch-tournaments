"use client";

import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Save } from "lucide-react";

import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { ROLES, canonicalToRegistrationRole } from "@/lib/roles";
import adminService from "@/services/admin.service";
import balancerAdminService from "@/services/balancer-admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  AdminCustomFieldDef,
  AdminRegistrationFormUpsert,
  BuiltInFieldConfig,
} from "@/types/balancer-admin.types";

import { BuiltInFieldsCard } from "./_components/BuiltInFieldsCard";
import { CustomFieldsCard } from "./_components/CustomFieldsCard";
import { RegistrationStatusCard } from "./_components/RegistrationStatusCard";
import { type CatalogEntry, SubrolesTab } from "./_components/SubrolesTab";
import {
  ROLE_FIELD_KEYS,
  getBuiltInConfig,
  getCustomFieldDefaultValidation,
  hydrateCustomField,
  makeUniqueCustomFieldKey,
  normalizeValidation,
  supportsCustomFieldValidation,
} from "./_components/formConfig";

export default function RegistrationFormConfigPage() {
  const tournamentId = useBalancerTournamentId();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  const [isOpen, setIsOpen] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  const [requireOpenProfile, setRequireOpenProfile] = useState(false);
  const [openProfileScope, setOpenProfileScope] = useState<"main" | "all">("main");
  const [builtInFields, setBuiltInFields] = useState<Record<string, BuiltInFieldConfig>>(() =>
    getBuiltInConfig({}),
  );
  const [customFields, setCustomFields] = useState<AdminCustomFieldDef[]>([]);
  const [hasChanges, setHasChanges] = useState(false);

  const formQuery = useQuery({
    queryKey: ["balancer-admin", "registration-form", tournamentId],
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId as number),
    enabled: tournamentId !== null,
    // This page is a long-lived editor; a background refetch must not clobber
    // the admin's unsaved edits.
    refetchOnWindowFocus: false,
  });

  const loadedFormKeyRef = useRef<string | null>(null);

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
    startTransition(() => {
      setIsOpen(data.is_open);
      setAutoApprove(data.auto_approve ?? false);
      setRequireOpenProfile(data.require_open_profile ?? false);
      setOpenProfileScope((data.open_profile_scope as "main" | "all") ?? "main");
      setBuiltInFields(getBuiltInConfig(data.built_in_fields ?? {}));
      setCustomFields((data.custom_fields ?? []).map(hydrateCustomField));
      setHasChanges(false);
    });
  }, [formQuery.data, hasChanges]);

  // The PlayerSubRole catalog (with row ids) is fetched directly so it can be
  // managed (create/remove) here; the form's embedded subrole_catalog only
  // carries {slug,label} for the public wizard.
  const workspaceId = formQuery.data?.workspace_id ?? currentWorkspaceId ?? null;

  const catalogQuery = useQuery({
    queryKey: ["admin", "player-sub-roles", workspaceId],
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId as number }),
    enabled: workspaceId !== null,
  });

  const subroleCatalog = useMemo<Record<string, CatalogEntry[]>>(() => {
    const grouped: Record<string, CatalogEntry[]> = Object.fromEntries(
      ROLES.map((role) => [role.code, [] as CatalogEntry[]]),
    );
    for (const row of catalogQuery.data ?? []) {
      const code = canonicalToRegistrationRole(row.role);
      if (code && grouped[code]) {
        grouped[code].push({ id: row.id, slug: row.slug, label: row.label });
      }
    }
    return grouped;
  }, [catalogQuery.data]);

  const invalidateCatalog = async () => {
    // Only refetch the catalog (fast, drives this tab). Do NOT await/refetch the
    // form query here: returning a slow promise from onSuccess keeps the mutation
    // stuck in `isPending` (and re-hydrating the form is unnecessary — the tab
    // reads the live catalog, and the public wizard fetches the form on its own).
    await queryClient.invalidateQueries({ queryKey: ["admin", "player-sub-roles", workspaceId] });
  };

  const createSubroleMutation = useMutation({
    mutationFn: ({ role, label }: { role: string; label: string }) => {
      if (workspaceId === null) throw new Error("No workspace selected");
      return adminService.createPlayerSubRole({ workspace_id: workspaceId, role, label });
    },
    onSuccess: async () => {
      await invalidateCatalog();
      toast({ title: "Sub-role added" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to add sub-role", description: error.message, variant: "destructive" });
    },
  });

  const deleteSubroleMutation = useMutation({
    mutationFn: (id: number) => adminService.deletePlayerSubRole(id),
    onSuccess: async () => {
      await invalidateCatalog();
      toast({ title: "Sub-role removed" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to remove sub-role", description: error.message, variant: "destructive" });
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!tournamentId) throw new Error("No tournament selected");
      const payload: AdminRegistrationFormUpsert = {
        is_open: isOpen,
        auto_approve: autoApprove,
        require_open_profile: requireOpenProfile,
        open_profile_scope: openProfileScope,
        built_in_fields: Object.fromEntries(
          Object.entries(builtInFields).map(([key, value]) => [
            key,
            { ...value, validation: normalizeValidation(value.validation) },
          ]),
        ),
        custom_fields: customFields.map((field) => ({
          ...field,
          validation: normalizeValidation(field.validation),
        })),
      };
      return balancerAdminService.upsertRegistrationForm(tournamentId, payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "registration-form", tournamentId],
      });
      setHasChanges(false);
      toast({ title: "Registration form saved" });
    },
    onError: (error: Error) => {
      toast({ title: "Failed to save", description: error.message, variant: "destructive" });
    },
  });

  const updateBuiltIn = (key: string, updates: Partial<BuiltInFieldConfig>) => {
    setBuiltInFields((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        ...updates,
        ...(Object.prototype.hasOwnProperty.call(updates, "validation")
          ? { validation: normalizeValidation(updates.validation) }
          : {}),
      },
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
          subroles: { ...(cfg.subroles ?? {}), [role]: nextSlugs },
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
        validation: getCustomFieldDefaultValidation("text"),
      },
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
          updated.validation = normalizeValidation(updated.validation) ?? getCustomFieldDefaultValidation(updates.type);
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
      }),
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
        <AlertTitle>Select a tournament</AlertTitle>
        <AlertDescription>
          Choose a tournament in the sidebar before configuring the registration form.
        </AlertDescription>
      </Alert>
    );
  }

  if (formQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Failed to load the registration form</AlertTitle>
        <AlertDescription>
          {(formQuery.error as Error)?.message ?? "Reload the page and try again."}
        </AlertDescription>
      </Alert>
    );
  }

  // Avoid flashing default toggles while the saved form is still loading.
  if (formQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center py-16 text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        Loading registration form…
      </div>
    );
  }

  const formExists = formQuery.data != null;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto">
      <Tabs defaultValue="status" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="self-start">
          <TabsTrigger value="status">Status</TabsTrigger>
          <TabsTrigger value="fields">Fields</TabsTrigger>
          <TabsTrigger value="subroles">Subroles</TabsTrigger>
          <TabsTrigger value="custom">Custom Fields</TabsTrigger>
        </TabsList>

        <TabsContent value="status">
          <div className="space-y-4">
            <RegistrationStatusCard
              isOpen={isOpen}
              autoApprove={autoApprove}
              onChangeOpen={(value) => {
                setIsOpen(value);
                setHasChanges(true);
              }}
              onChangeAutoApprove={(value) => {
                setAutoApprove(value);
                setHasChanges(true);
              }}
            />

            <div className="space-y-3 rounded-lg border p-4">
              <div className="font-medium">Admission</div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={requireOpenProfile}
                  onChange={(event) => {
                    setRequireOpenProfile(event.target.checked);
                    setHasChanges(true);
                  }}
                />
                Require open Overwatch profile
              </label>
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Scope</span>
                <select
                  className="rounded-md border border-border bg-background px-2 py-1 text-sm disabled:opacity-50"
                  value={openProfileScope}
                  disabled={!requireOpenProfile}
                  onChange={(event) => {
                    setOpenProfileScope(event.target.value as "main" | "all");
                    setHasChanges(true);
                  }}
                >
                  <option value="main">Main account only</option>
                  <option value="all">All accounts (incl. smurfs)</option>
                </select>
              </div>
              <p className="text-xs text-muted-foreground">
                When enabled, players whose Overwatch profile is private are not admitted (blocked at
                check-in). Unranked players are already excluded separately.
              </p>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="fields">
          <BuiltInFieldsCard builtInFields={builtInFields} onUpdate={updateBuiltIn} />
        </TabsContent>

        <TabsContent value="subroles">
          <SubrolesTab
            catalog={subroleCatalog}
            selection={subroleSelection}
            onToggleOffered={handleToggleSubrole}
            onCreate={(role, label) => createSubroleMutation.mutate({ role, label })}
            onDelete={(entry) => deleteSubroleMutation.mutate(entry.id)}
            isLoading={catalogQuery.isLoading}
            isMutating={createSubroleMutation.isPending || deleteSubroleMutation.isPending}
          />
        </TabsContent>

        <TabsContent value="custom">
          <CustomFieldsCard
            customFields={customFields}
            onAdd={addCustomField}
            onUpdate={updateCustomField}
            onRemove={removeCustomField}
          />
        </TabsContent>
      </Tabs>

      <div className="flex justify-end pb-4">
        <Button
          size="lg"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || (!hasChanges && formExists)}
        >
          {saveMutation.isPending ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <Save className="mr-2 size-4" />
          )}
          {formExists ? "Save changes" : "Create form"}
        </Button>
      </div>
    </div>
  );
}
