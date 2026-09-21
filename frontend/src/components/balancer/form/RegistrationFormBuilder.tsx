"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy
} from "@dnd-kit/sortable";
import { LoaderCircle, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import SchemaForm from "@/components/forms/SchemaForm";
import type { FieldRendererContext } from "@/components/forms/types";
import { SaveBar } from "@/components/kit/SaveBar";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { SortableGrip, useSortableRow } from "@/components/kit/SortableRows";
import { registrationRenderers } from "@/components/registration/registrationRenderers";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { defaultFormSchema } from "@/lib/forms/default-schema";
import { fieldErrorsFrom } from "@/lib/forms/form-errors";
import { makeUniqueFieldKey } from "@/lib/forms/keys";
import { notify } from "@/lib/notify";
import { toRegistrationFormUpsert } from "@/lib/registration-form-upsert";
import { ROLES, canonicalToRegistrationRole } from "@/lib/roles";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import balancerAdminService from "@/services/balancer-admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { AdminRegistrationForm } from "@/types/balancer-admin.types";
import type { FieldKind, FormField, FormSchema } from "@/types/forms.types";

import { AddFieldMenu, newBuiltinField, newCustomField } from "./_components/AddFieldMenu";
import { FieldEditor } from "./_components/FieldEditor";
import type { CatalogEntry, SubroleCatalogByRole } from "./_components/RolesParamsEditor";
import { FIELD_DRAG_PREFIX, SECTION_DRAG_PREFIX, SectionList } from "./_components/SectionList";
import { TemplateMenu } from "./_components/TemplateMenu";
import {
  appendField,
  blockedFieldKeys,
  earlierFields,
  fieldDisplayLabel,
  fieldKeyAtSchemaPath,
  flatFields,
  moveFieldOnto,
  moveFieldToSection,
  pruneStrandedConditions,
  removeField,
  renameField,
  replaceField,
  sanitizeSchema
} from "./_components/schemaEdits";

// ---------------------------------------------------------------------------
// The editor
// ---------------------------------------------------------------------------

function FieldRow({
  field,
  label,
  selected,
  invalid,
  onSelect,
  onDelete
}: Readonly<{
  field: FormField;
  label: string;
  selected: boolean;
  invalid: boolean;
  onSelect: () => void;
  onDelete: () => void;
}>) {
  const t = useTranslations("registrationFormAdmin.builder");
  const tKinds = useTranslations("registrationFormAdmin.kinds");
  const { ref, style, handleProps, isDragging } = useSortableRow(`${FIELD_DRAG_PREFIX}${field.key}`);

  return (
    <div
      ref={ref}
      style={style}
      className={cn(
        "flex items-center gap-2 rounded-lg border px-2 py-1.5",
        selected ? "border-primary/40 bg-primary/5" : "border-border/60",
        invalid && "border-destructive/50",
        isDragging && "opacity-90"
      )}
    >
      <SortableGrip handleProps={handleProps} label={t("reorderField", { field: label })} />
      <button type="button" onClick={onSelect} className="min-w-0 flex-1 text-left">
        <span className="block truncate text-sm font-medium">{label}</span>
        <span className="flex flex-wrap items-center gap-1.5 pt-0.5">
          <span className="font-mono text-xs text-muted-foreground">{field.key}</span>
          {field.kind === "builtin" ? null : (
            <Badge variant="outline" className="text-[10px]">
              {tKinds(field.kind)}
            </Badge>
          )}
          {field.required && (
            <Badge variant="outline" className="text-[10px]">
              {t("requiredBadge")}
            </Badge>
          )}
          {field.visibility === "organizers" && (
            <Badge variant="outline" className="text-[10px]">
              {t("organizersBadge")}
            </Badge>
          )}
          {field.visible_when && (
            <Badge variant="outline" className="text-[10px]">
              {t("conditionalBadge")}
            </Badge>
          )}
        </span>
      </button>
      <Button
        variant="ghost"
        size="icon"
        className="size-7 shrink-0"
        aria-label={t("deleteField", { field: label })}
        onClick={onDelete}
      >
        <Trash2 className="size-3.5" aria-hidden />
      </Button>
    </div>
  );
}

export interface SchemaEditorProps {
  schema: FormSchema;
  onChange: (next: FormSchema) => void;
  /** Workspace `PlayerSubRole` rows, grouped by role — the `roles` params
   *  editor keys its chips by row id, the preview only needs slug/label. */
  subroleCatalog: SubroleCatalogByRole;
  catalogLoading?: boolean;
  /** `schema_invalid` rejections, already resolved from path to field key. */
  fieldErrors: Record<string, string>;
  /** Template menu, save-as, anything the owning screen puts above the tabs. */
  toolbar?: ReactNode;
}

/**
 * The questionnaire itself: sections on the rail, that section's questions in
 * the pane, one question's settings under them, and a read-only preview.
 *
 * Owns no persistence — a tournament's form and a workspace template are the
 * same document written to different endpoints, and the difference is the save
 * button, not the editor.
 *
 * The server's schema invariants are made UNREACHABLE here rather than reported
 * after the fact: a builtin whose visibility the catalog fixes gets a disabled
 * selector, a `visible_when` only ever lists earlier fields, a reorder that
 * would strand a condition clears it and says so, and a custom key is derived
 * from the label once and then locked.
 */
export function SchemaEditor({
  schema,
  onChange,
  subroleCatalog,
  catalogLoading = false,
  fieldErrors,
  toolbar
}: Readonly<SchemaEditorProps>) {
  const t = useTranslations("registrationFormAdmin.builder");
  const tBuiltins = useTranslations("registrationFormAdmin.builtins");
  const tFormErrors = useTranslations("forms.errors");

  const [sectionKey, setSectionKey] = useState<string | null>(null);
  const [fieldKey, setFieldKey] = useState<string | null>(null);
  /** Custom fields whose key is still derived from the label. Emptied one field
   *  at a time, the first time the label leaves the box with text in it. */
  const [unlockedKeys, setUnlockedKeys] = useState<ReadonlySet<string>>(() => new Set());
  const [previewStep, setPreviewStep] = useState(0);

  const sensors = useSensors(
    // 5px before a drag starts, so a click on a row's button stays a click.
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const section = schema.sections.find((entry) => entry.key === sectionKey) ?? schema.sections[0];
  const field = section?.fields.find((entry) => entry.key === fieldKey) ?? null;
  const usedKeys = useMemo(() => new Set(flatFields(schema).map((entry) => entry.key)), [schema]);
  const invalidKeys = useMemo(() => blockedFieldKeys(schema), [schema]);


  /** Apply an edit; `prune` for the structural ones, which can strand a condition. */
  const commit = (next: FormSchema, prune = false) => {
    if (!prune) {
      onChange(next);
      return;
    }
    const { schema: pruned, cleared } = pruneStrandedConditions(next);
    if (cleared.length > 0) {
      const names = cleared
        .map((key) => flatFields(pruned).find((entry) => entry.key === key))
        .filter((entry): entry is FormField => entry !== undefined)
        .map((entry) => `\u201c${fieldDisplayLabel(entry, tBuiltins)}\u201d`);
      notify.warning(t("strandedCleared", { fields: names.join(", ") }));
    }
    onChange(pruned);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const activeId = String(event.active.id);
    const overId = event.over ? String(event.over.id) : null;
    if (!overId || activeId === overId) return;

    if (activeId.startsWith(SECTION_DRAG_PREFIX)) {
      if (!overId.startsWith(SECTION_DRAG_PREFIX)) return;
      const keys = schema.sections.map((entry) => entry.key);
      const from = keys.indexOf(activeId.slice(SECTION_DRAG_PREFIX.length));
      const to = keys.indexOf(overId.slice(SECTION_DRAG_PREFIX.length));
      if (from === -1 || to === -1) return;
      commit({ ...schema, sections: arrayMove(schema.sections, from, to) }, true);
      return;
    }

    const moved = activeId.slice(FIELD_DRAG_PREFIX.length);
    if (overId.startsWith(SECTION_DRAG_PREFIX)) {
      commit(moveFieldToSection(schema, moved, overId.slice(SECTION_DRAG_PREFIX.length)), true);
      return;
    }
    commit(moveFieldOnto(schema, moved, overId.slice(FIELD_DRAG_PREFIX.length)), true);
  };

  const addSection = () => {
    // Section keys answer to the same `KEY_PATTERN` and are never typed by
    // hand, so the field-key factory generates them too. Its reserved-namespace
    // guard is a harmless superset here — "section" is not a builtin key.
    const key = makeUniqueFieldKey(
      "section",
      schema.sections.map((entry) => entry.key)
    );
    commit({
      ...schema,
      sections: [...schema.sections, { key, title: null, description: null, fields: [] }]
    });
    setSectionKey(key);
    setFieldKey(null);
  };

  const deleteSection = (key: string) => {
    commit({ ...schema, sections: schema.sections.filter((entry) => entry.key !== key) }, true);
    if (sectionKey === key) setSectionKey(null);
  };

  const patchSection = (key: string, updates: { title?: string | null; description?: string | null }) =>
    commit({
      ...schema,
      sections: schema.sections.map((entry) => (entry.key === key ? { ...entry, ...updates } : entry))
    });

  const addBuiltin = (key: string) => {
    if (!section) return;
    commit(appendField(schema, section.key, newBuiltinField(key)));
    setFieldKey(key);
  };

  const addCustom = (kind: FieldKind) => {
    if (!section) return;
    const created = newCustomField(kind, usedKeys);
    commit(appendField(schema, section.key, created));
    setFieldKey(created.key);
    setUnlockedKeys((previous) => new Set(previous).add(created.key));
  };

  const deleteField = (key: string) => {
    commit(removeField(schema, key), true);
    if (fieldKey === key) setFieldKey(null);
    setUnlockedKeys((previous) => {
      if (!previous.has(key)) return previous;
      const next = new Set(previous);
      next.delete(key);
      return next;
    });
  };

  /**
   * Derive the answer key from the label, once.
   *
   * Runs when the label box is left. A still-empty label leaves the key
   * provisional rather than freezing the placeholder one: the organizer has not
   * named the question yet, and the key is what every stored answer is filed
   * under.
   */
  const commitKey = () => {
    if (!field || !unlockedKeys.has(field.key)) return;
    const label = (field.label ?? "").trim();
    if (!label) return;
    setUnlockedKeys((previous) => {
      const next = new Set(previous);
      next.delete(field.key);
      return next;
    });
    const derived = makeUniqueFieldKey(
      label,
      flatFields(schema)
        .filter((entry) => entry.key !== field.key)
        .map((entry) => entry.key)
    );
    if (derived === field.key) return;
    commit(renameField(schema, field.key, derived));
    setFieldKey(derived);
  };

  const previewContext = useMemo<FieldRendererContext>(
    () => ({
      mode: "public",
      accounts: [],
      subroleCatalog,
      heroes: [],
      lockedRole: null,
      subscription: null,
      t: tFormErrors
    }),
    [subroleCatalog, tFormErrors]
  );

  return (
    <Tabs defaultValue="edit" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TabsList>
          <TabsTrigger value="edit">{t("editTab")}</TabsTrigger>
          <TabsTrigger value="preview">{t("previewTab")}</TabsTrigger>
        </TabsList>
        {toolbar}
      </div>

      <TabsContent value="edit" className="m-0">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <div className="flex flex-col gap-4 md:flex-row md:items-start">
            <SectionList
              sections={schema.sections}
              selectedKey={section?.key ?? ""}
              onSelect={(key) => {
                setSectionKey(key);
                setFieldKey(null);
              }}
              onAdd={addSection}
              onDelete={deleteSection}
            />

            <div className="min-w-0 flex-1 rounded-xl border p-4">
              {section ? (
                <div className="grid gap-4">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="grid gap-1.5">
                      <Label htmlFor="registration-section-title" className="text-xs">
                        {t("sectionTitle")}
                      </Label>
                      <Input
                        id="registration-section-title"
                        value={section.title ?? ""}
                        placeholder={t("sectionTitlePlaceholder")}
                        onChange={(event) =>
                          patchSection(section.key, { title: event.target.value || null })
                        }
                      />
                    </div>
                    <div className="grid gap-1.5">
                      <Label htmlFor="registration-section-description" className="text-xs">
                        {t("sectionDescription")}
                      </Label>
                      <Input
                        id="registration-section-description"
                        value={section.description ?? ""}
                        placeholder={t("sectionDescriptionPlaceholder")}
                        onChange={(event) =>
                          patchSection(section.key, { description: event.target.value || null })
                        }
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {t("fieldCount", { count: section.fields.length })}
                    </p>
                    <AddFieldMenu
                      usedKeys={usedKeys}
                      onAddBuiltin={addBuiltin}
                      onAddCustom={addCustom}
                    />
                  </div>

                  <SortableContext
                    items={section.fields.map((entry) => `${FIELD_DRAG_PREFIX}${entry.key}`)}
                    strategy={verticalListSortingStrategy}
                  >
                    <div className="flex flex-col gap-1.5">
                      {section.fields.map((entry) => (
                        <FieldRow
                          key={entry.key}
                          field={entry}
                          label={fieldDisplayLabel(entry, tBuiltins)}
                          selected={entry.key === field?.key}
                          invalid={invalidKeys.has(entry.key) || fieldErrors[entry.key] !== undefined}
                          onSelect={() => setFieldKey(entry.key)}
                          onDelete={() => deleteField(entry.key)}
                        />
                      ))}
                    </div>
                  </SortableContext>

                  {section.fields.length === 0 && (
                    <EmptyNote title={t("emptySection")}>{t("emptySectionHint")}</EmptyNote>
                  )}

                  {field && (
                    <FieldEditor
                      key={field.key}
                      field={field}
                      earlierFields={earlierFields(schema, field.key)}
                      keyLocked={!unlockedKeys.has(field.key)}
                      serverError={fieldErrors[field.key] ?? null}
                      catalog={subroleCatalog}
                      catalogLoading={catalogLoading}
                      onChange={(next) => commit(replaceField(schema, field.key, next))}
                      onCommitKey={commitKey}
                    />
                  )}
                </div>
              ) : null}
            </div>
          </div>
        </DndContext>
      </TabsContent>

      <TabsContent value="preview" className="m-0">
        <div className="grid gap-3 rounded-xl border p-4">
          <p className="text-xs text-muted-foreground">{t("previewNote")}</p>
          <SchemaForm
            readOnly
            schema={schema}
            answers={{}}
            onChange={() => undefined}
            renderers={registrationRenderers}
            context={previewContext}
            serverErrors={{}}
            step={previewStep}
            onStepChange={setPreviewStep}
            showErrors={false}
            footer={({ canGoBack, isLast }) => (
              <div className="flex items-center justify-between gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!canGoBack}
                  onClick={() => setPreviewStep((current) => Math.max(0, current - 1))}
                >
                  {t("previewBack")}
                </Button>
                <Button
                  size="sm"
                  disabled={isLast}
                  onClick={() => setPreviewStep((current) => current + 1)}
                >
                  {isLast ? t("previewDone") : t("previewNext")}
                </Button>
              </div>
            )}
          />
        </div>
      </TabsContent>
    </Tabs>
  );
}

// ---------------------------------------------------------------------------
// The tournament's own questionnaire
// ---------------------------------------------------------------------------

/** The workspace sub-role catalog, grouped the way both the params editor and
 *  the preview renderers want it. */
export function useSubroleCatalog(workspaceId: number | null) {
  const catalogQuery = useQuery({
    queryKey: ["admin", "player-sub-roles", workspaceId],
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId as number }),
    enabled: workspaceId !== null
  });

  const catalog = useMemo<SubroleCatalogByRole>(() => {
    const grouped: SubroleCatalogByRole = Object.fromEntries(
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

  return { catalog, loading: catalogQuery.isLoading };
}

/**
 * The questionnaire: what a registrant is asked, and what they may answer.
 *
 * Nothing that decides who gets in lives here. Admission rules, the public-page
 * display and the bench size are the Settings rail's (`settings/admission`,
 * `settings/registration`, `settings/roster`) — they are tournament policy, and
 * holding them inside a field builder is what made this one screen answer four
 * unrelated questions under headings joined by "and".
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
  const tBuilder = useTranslations("registrationFormAdmin.builder");
  const tErrors = useTranslations("forms.errors");

  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  /** `null` means untouched: the editor renders the server's schema until the
   *  organizer changes something, so a background refetch cannot clobber edits
   *  and no effect copies query data into state. */
  const [draft, setDraft] = useState<FormSchema | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const formQuery = useQuery({
    queryKey: ["balancer-admin", "registration-form", tournamentId],
    queryFn: () => balancerAdminService.getRegistrationForm(tournamentId as number),
    enabled: tournamentId !== null,
    // This page is a long-lived editor; a background refetch must not clobber
    // the admin's unsaved edits.
    refetchOnWindowFocus: false
  });

  // The form's own workspace wins: a superuser may be looking at a tournament
  // that is not in the workspace their sidebar has selected.
  const workspaceId = formQuery.data?.workspace_id ?? currentWorkspaceId ?? null;
  const { catalog, loading: catalogLoading } = useSubroleCatalog(workspaceId);

  // A tournament with no form row yet has no schema to render, and the upsert
  // that creates it needs one; the server would have built exactly this.
  const serverSchema = useMemo<FormSchema>(
    () => formQuery.data?.form_schema ?? defaultFormSchema(),
    [formQuery.data]
  );
  const schema = draft ?? serverSchema;
  const blocked = useMemo(() => blockedFieldKeys(schema), [schema]);

  const saveMutation = useMutation({
    mutationFn: (payload: FormSchema) => {
      if (!tournamentId) throw new Error(t("noTournamentError"));
      return balancerAdminService.upsertRegistrationForm(tournamentId, {
        // The upsert is a full replace, so the policy fields this page no
        // longer shows travel back untouched from the saved form. Editing a
        // question must not reset the admission rules.
        ...toRegistrationFormUpsert(formQuery.data),
        form_schema: payload
      });
    },
    onSuccess: async (updated: AdminRegistrationForm) => {
      queryClient.setQueryData(["balancer-admin", "registration-form", tournamentId], updated);
      await queryClient.invalidateQueries({
        queryKey: ["balancer-admin", "registration-form", tournamentId]
      });
      setDraft(null);
      setFieldErrors({});
      notify.success(t("savedToast"));
    },
    onError: (error, payload) => {
      const { fields, form } = fieldErrorsFrom(error, tErrors);
      const byKey: Record<string, string> = {};
      let unplaced: string | null = null;
      for (const [path, message] of Object.entries(fields)) {
        // `schema_invalid` files its rejection under a schema PATH. Resolved to
        // the field it names, it lands under the control that caused it; the
        // path travels with it because it is the server's own vocabulary.
        const key = fieldKeyAtSchemaPath(payload, path);
        if (key) byKey[key] = `${message} (${path})`;
        else unplaced ??= message;
      }
      setFieldErrors(byKey);
      const toast = unplaced ?? form;
      if (toast && Object.keys(byKey).length === 0) notify.error(toast);
    }
  });

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

  // Avoid flashing the default questionnaire while the saved one is loading.
  if (formQuery.isLoading) {
    return (
      <output className="flex flex-1 items-center justify-center py-16 text-sm text-muted-foreground">
        <LoaderCircle className="mr-2 size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        {t("loading")}
      </output>
    );
  }

  const saved = formQuery.data ?? null;
  const stale = saved?.stale_registrations ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <SchemaEditor
        schema={schema}
        onChange={setDraft}
        subroleCatalog={catalog}
        catalogLoading={catalogLoading}
        fieldErrors={fieldErrors}
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            {saved && <Badge variant="outline">{tBuilder("version", { number: saved.version_number })}</Badge>}
            {stale > 0 && (
              <Badge tone="warning" title={tBuilder("staleHint")}>
                {tBuilder("stale", { count: stale })}
              </Badge>
            )}
            <TemplateMenu
              workspaceId={workspaceId}
              tournamentId={tournamentId}
              dirty={draft !== null}
              onLoad={setDraft}
            />
          </div>
        }
      />

      {/* The shared bar. Shown while dirty like every settings section — and
          also for a tournament with no saved form, where "Create form" must be
          reachable before any edit; the navigation guard stays off in that
          untouched state so the page does not prompt on every tab switch. */}
      <SaveBar
        dirty={draft !== null || saved === null}
        guardNavigation={draft !== null}
        summary={
          blocked.size > 0 ? tBuilder("blocked") : draft !== null ? t("unsavedChanges") : ""
        }
        saving={saveMutation.isPending}
        primaryLabel={saved ? t("saveChanges") : t("createForm")}
        onDiscard={() => {
          setDraft(null);
          setFieldErrors({});
        }}
        onSave={() => {
          if (blocked.size > 0) {
            notify.error(tBuilder("blocked"));
            return;
          }
          saveMutation.mutate(sanitizeSchema(schema));
        }}
      />
    </div>
  );
}
