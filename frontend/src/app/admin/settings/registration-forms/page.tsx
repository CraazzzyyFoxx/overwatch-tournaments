"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  SchemaEditor,
  useSubroleCatalog
} from "@/components/balancer/form/RegistrationFormBuilder";
import {
  blockedFieldKeys,
  sanitizeSchema
} from "@/components/balancer/form/_components/schemaEdits";
import { registrationFormTemplatesKey } from "@/components/balancer/form/_components/TemplateMenu";
import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { SaveBar } from "@/components/kit/SaveBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { defaultFormSchema } from "@/lib/forms/default-schema";
import { fieldErrorsFrom } from "@/lib/forms/form-errors";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import registrationFormTemplatesService from "@/services/registration-form-templates.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { FormSchema } from "@/types/forms.types";

/**
 * Saved questionnaires, shared by every tournament of the workspace.
 *
 * The same editor the tournament builder runs, without the tournament: there is
 * no form row to version, no stale-registration count and no policy toggles to
 * echo back — a template is a schema and a name, and applying one to a
 * tournament is the builder's "Load template".
 *
 * Copy here is plain English like its neighbours in this hub (`sub-roles`,
 * `statuses`, `divisions`); the editor inside carries its own i18n.
 */
export default function WorkspaceRegistrationFormsSettingsPage() {
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const tErrors = useTranslations("forms.errors");

  const [selectedId, setSelectedId] = useState<number | null>(null);
  /** `null` = the selected template's saved schema, untouched. */
  const [draft, setDraft] = useState<FormSchema | null>(null);
  const [newName, setNewName] = useState("");
  /**
   * The destructive action waiting on a confirmation: deleting a shared
   * template, or walking away from unsaved questions. Both are one dialog with
   * a swapped intent, the pattern every other section of this hub follows —
   * and neither is recoverable from the UI once done.
   */
  const [pending, setPending] = useState<
    { kind: "delete"; id: number; name: string } | { kind: "switch"; id: number } | null
  >(null);

  const canEdit = canAccessPermission("registration_form.update", workspaceId);
  const { catalog, loading: catalogLoading } = useSubroleCatalog(workspaceId);

  const listQuery = useQuery({
    queryKey: registrationFormTemplatesKey(workspaceId ?? 0),
    queryFn: () => registrationFormTemplatesService.list(workspaceId as number),
    enabled: workspaceId !== null
  });

  const templates = useMemo(() => listQuery.data ?? [], [listQuery.data]);
  const selected = templates.find((template) => template.id === selectedId) ?? null;
  const schema = draft ?? selected?.form_schema ?? null;
  const blocked = schema ? blockedFieldKeys(schema) : null;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: registrationFormTemplatesKey(workspaceId ?? 0) });

  const createMutation = useMutation({
    mutationFn: (name: string) =>
      // A new template starts from the same questionnaire the server would
      // build for a fresh tournament, so "new template" and "new tournament"
      // never disagree about what a form asks by default.
      registrationFormTemplatesService.create(workspaceId as number, name, defaultFormSchema()),
    onSuccess: async (created) => {
      setNewName("");
      await invalidate();
      // Opening the new template would discard whatever is unsaved in the pane
      // — the same loss the switch confirmation exists to prevent, so the
      // selection simply stays put and the row is waiting in the list.
      if (draft !== null) {
        notify.success(`Template “${created.name}” created — open it once you have saved this one`);
        return;
      }
      setSelectedId(created.id);
      notify.success("Template created");
    },
    onError: (error) => notify.error(fieldErrorsFrom(error, tErrors).form ?? "Could not create the template")
  });

  const saveMutation = useMutation({
    mutationFn: ({ id, name, form_schema }: { id: number; name: string; form_schema: FormSchema }) =>
      registrationFormTemplatesService.update(workspaceId as number, id, name, form_schema),
    onSuccess: async () => {
      setDraft(null);
      await invalidate();
      notify.success("Template saved");
    },
    onError: (error) => notify.error(fieldErrorsFrom(error, tErrors).form ?? "Could not save the template")
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => registrationFormTemplatesService.remove(workspaceId as number, id),
    onSuccess: async (_result, id) => {
      if (selectedId === id) {
        setSelectedId(null);
        setDraft(null);
      }
      await invalidate();
      notify.success("Template deleted");
    },
    onError: (error) => notify.apiError(error, { title: "Could not delete the template" })
  });

  /** Select a template, asking first when the one on screen has unsaved edits. */
  const openTemplate = (id: number) => {
    if (id === selectedId) return;
    if (draft !== null) {
      setPending({ kind: "switch", id });
      return;
    }
    setSelectedId(id);
  };

  const confirmIntent: ConfirmIntent =
    pending?.kind === "delete"
      ? {
          title: "Delete this template?",
          description: `“${pending.name}” is shared by every tournament in this workspace. Forms already built from it keep their questions; the template itself cannot be restored.`,
          confirmLabel: "Delete template",
          tone: "danger"
        }
      : {
          title: "Discard unsaved questions?",
          description:
            "The questions you edited here have not been saved. Opening another template drops them.",
          confirmLabel: "Discard and switch",
          tone: "warning"
        };

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title="No workspace selected"
        description="Pick a workspace in the sidebar to manage its registration form templates."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <div className="flex w-full shrink-0 flex-col gap-2 lg:w-72">
          {listQuery.isLoading ? (
            <Skeleton className="h-40 w-full rounded-md" />
          ) : (
            <ul className="flex flex-col gap-1.5">
              {templates.map((template) => (
                <li
                  key={template.id}
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-2.5 py-1.5",
                    template.id === selectedId
                      ? "border-primary/40 bg-primary/10"
                      : "border-border/60"
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <InlineEditText
                      value={template.name}
                      label="Template name"
                      canEdit={canEdit}
                      onSave={(name) =>
                        saveMutation.mutateAsync({
                          id: template.id,
                          name,
                          // Renaming must not publish the schema being edited in
                          // the pane next to it: a rename sends what is SAVED.
                          form_schema: template.form_schema
                        })
                      }
                    />
                    <button
                      type="button"
                      className="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
                      onClick={() => openTemplate(template.id)}
                    >
                      {template.id === selectedId ? "Editing" : "Edit questions"}
                    </button>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 shrink-0"
                    disabled={!canEdit || deleteMutation.isPending}
                    aria-label={`Delete ${template.name}`}
                    onClick={() =>
                      setPending({ kind: "delete", id: template.id, name: template.name })
                    }
                  >
                    <Trash2 className="size-3.5" aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
          )}

          {canEdit && (
            <div className="flex items-center gap-2">
              <Input
                value={newName}
                placeholder="New template name"
                className="h-8 text-xs"
                onChange={(event) => setNewName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && newName.trim()) {
                    event.preventDefault();
                    createMutation.mutate(newName.trim());
                  }
                }}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 shrink-0"
                disabled={!newName.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate(newName.trim())}
              >
                {createMutation.isPending ? (
                  <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden />
                ) : (
                  <Plus className="mr-1 size-3.5" aria-hidden />
                )}
                Add
              </Button>
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1">
          {selected && schema ? (
            <SchemaEditor
              key={selected.id}
              schema={schema}
              onChange={setDraft}
              subroleCatalog={catalog}
              catalogLoading={catalogLoading}
              fieldErrors={{}}
            />
          ) : (
            <PageStateCard
              state="empty"
              title={templates.length === 0 ? "No templates yet" : "Pick a template"}
              description={
                templates.length === 0
                  ? "Name one on the left and it starts from the default questionnaire."
                  : "Choose a template on the left to edit the questions it asks."
              }
            />
          )}
        </div>
      </div>

      {selected && schema && (
        <SaveBar
          dirty={draft !== null}
          summary={blocked && blocked.size > 0 ? "Fix the highlighted questions first" : "Unsaved changes"}
          saving={saveMutation.isPending}
          primaryLabel="Save template"
          onDiscard={() => setDraft(null)}
          onSave={() => {
            if (blocked && blocked.size > 0) {
              notify.error("Fix the highlighted questions first");
              return;
            }
            saveMutation.mutate({
              id: selected.id,
              name: selected.name,
              form_schema: sanitizeSchema(schema)
            });
          }}
        />
      )}

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        intent={confirmIntent}
        pending={deleteMutation.isPending}
        onConfirm={async () => {
          if (pending === null) return;
          if (pending.kind === "delete") {
            await deleteMutation.mutateAsync(pending.id);
          } else {
            setDraft(null);
            setSelectedId(pending.id);
          }
          setPending(null);
        }}
      />
    </div>
  );
}
