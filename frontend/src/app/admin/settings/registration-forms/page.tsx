"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { gameFilterDefs } from "@/components/admin/game-filter";
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
import { FilterBar } from "@/components/kit/FilterBar";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { MasterDetail, MasterList, MasterListSkeleton } from "@/components/kit/MasterDetail";
import { SaveBar } from "@/components/kit/SaveBar";
import { useFilters } from "@/components/kit/useFilters";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { GameField } from "@/components/workspace/GameField";
import { GameIcon } from "@/components/workspace/GameIcon";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useGameScope } from "@/hooks/useGameScope";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";
import { defaultFormSchema } from "@/lib/forms/default-schema";
import { fieldErrorsFrom } from "@/lib/forms/form-errors";
import { notify } from "@/lib/notify";
import { defaultCreationGame, showsGameMarks } from "@/lib/site/discipline-scope";
import registrationFormTemplatesService from "@/services/registration-form-templates.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { FormSchema } from "@/types/forms.types";

/**
 * Saved questionnaires of the workspace (T4), each owned by one game (spec §6.13, §8.4).
 *
 * The list is a multi surface: every game's templates (marked) unless the game filter names one. A selected template
 * is an owner: its game names the editor's roles and metadata, whatever the list's game. "New template" files under
 * the creation game (the filtered game, else the first enabled), asking that game's identity.
 *
 * The same editor the tournament builder runs, without the tournament: there is
 * no form row to version, no stale-registration count and no policy toggles to
 * echo back — a template is a schema and a name, and applying one to a
 * tournament is the builder's "Load template".
 *
 * `?template=` is the selection, written with `mode: "push"`: below `md`
 * `MasterDetail` shows the list or the editor, and its Back is `history.back()`.
 */
export default function WorkspaceRegistrationFormsSettingsPage() {
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const scope = useGameScope({ pageClass: "multi", axis: workspaceId ?? "all" });
  const kind = scope.resolution?.game.kind;
  const listGame = scope.game;
  const games = useMemo(() => scope.games ?? [], [scope.games]);
  const marks = scope.resolution !== null && showsGameMarks(scope.resolution, games);
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const tErrors = useTranslations("forms.errors");
  const t = useTranslations("adminSettings.registrationForms");
  const tTable = useTranslations("kitTable.dataTableExtra");
  const gameT = useTranslations("common.discipline");
  const { searchParams, setParams } = useQueryParams({ mode: "push" });
  // An open `?template=` owns its game, so a game pick keeps it.
  const gameDefs = gameFilterDefs(games, gameT("column"), undefined, gameT("all"));
  const filters = useFilters(gameDefs);

  const selectedId = Number(searchParams?.get("template")) || null;
  const setSelectedId = (id: number | null) => setParams({ template: id });
  const [edit, setEdit] = useState<{ templateId: number; schema: FormSchema } | null>(null);
  /**
   * The selected template's unsaved schema, `null` = its saved one. Edits
   * belong to the template they were made on, so a selection that changes
   * without `openTemplate` (browser Back, the narrow-viewport Back) leaves
   * them behind instead of pasting them onto another template.
   */
  const draft = edit !== null && edit.templateId === selectedId ? edit.schema : null;
  const setDraft = (schema: FormSchema | null) =>
    setEdit(schema !== null && selectedId !== null ? { templateId: selectedId, schema } : null);
  const [newName, setNewName] = useState("");
  const [newGame, setNewGame] = useState<string | null>(null);
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

  const listQuery = useQuery({
    queryKey: balancerQueryKeys.registrationFormTemplateList(workspaceId ?? 0, listGame),
    queryFn: () => registrationFormTemplatesService.list(workspaceId as number, listGame),
    enabled: workspaceId !== null && (kind === "game" || kind === "all")
  });

  const templates = useMemo(() => listQuery.data ?? [], [listQuery.data]);
  // The selection is resolved over every game's templates: one of another game than the list's (opened by link,
  // or just created under another game) still opens in the editor.
  const outsideList = selectedId !== null && listGame !== null && !templates.some((entry) => entry.id === selectedId);
  const allTemplatesQuery = useQuery({
    queryKey: balancerQueryKeys.registrationFormTemplateList(workspaceId ?? 0, null),
    queryFn: () => registrationFormTemplatesService.list(workspaceId as number, null),
    enabled: workspaceId !== null && outsideList && listQuery.isSuccess
  });
  const selected =
    templates.find((template) => template.id === selectedId) ??
    allTemplatesQuery.data?.find((template) => template.id === selectedId) ??
    null;
  const schema = draft ?? selected?.form_schema ?? null;
  const blocked = schema ? blockedFieldKeys(schema) : null;

  // The selected template is an owner (spec §5): its game drives the editor.
  const ownerGame = selected?.discipline ?? null;
  const { catalog, loading: catalogLoading } = useSubroleCatalog(workspaceId, ownerGame);
  const metadata = useDisciplineMetadata(workspaceId ?? "all", workspaceId !== null ? ownerGame : null);

  const enabledGames = games.filter((entry) => entry.enabled);
  // A pick counts only while it is an enabled game of the area; otherwise the default applies again.
  const pickedGame = newGame !== null && enabledGames.some((entry) => entry.code === newGame) ? newGame : null;
  const creationGame = pickedGame ?? defaultCreationGame(listGame, enabledGames);
  // A template starts from the questionnaire the server would build for a fresh tournament OF ITS GAME.
  const identityProvider = games.find((entry) => entry.code === creationGame)?.identity_provider ?? null;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: registrationFormTemplatesKey(workspaceId ?? 0) });

  const createMutation = useMutation({
    mutationFn: (name: string) => {
      if (creationGame === null || identityProvider === null) throw new Error("no creation game");
      // "New template" and "new tournament" never disagree about what a form asks by default.
      return registrationFormTemplatesService.create(
        workspaceId as number,
        name,
        creationGame,
        defaultFormSchema(identityProvider)
      );
    },
    onSuccess: async (created) => {
      setNewName("");
      await invalidate();
      // Opening the new template would discard whatever is unsaved in the pane
      // — the same loss the switch confirmation exists to prevent, so the
      // selection simply stays put and the row is waiting in the list.
      if (draft !== null) {
        notify.success(t("toast.createdOpenLater", { name: created.name }));
        return;
      }
      setSelectedId(created.id);
      notify.success(t("toast.created"));
    },
    onError: (error) => notify.error(fieldErrorsFrom(error, tErrors).form ?? t("errors.create"))
  });

  const saveMutation = useMutation({
    mutationFn: ({ id, name, form_schema }: { id: number; name: string; form_schema: FormSchema }) =>
      registrationFormTemplatesService.update(workspaceId as number, id, name, form_schema),
    onSuccess: async () => {
      setDraft(null);
      await invalidate();
      notify.success(t("toast.saved"));
    },
    onError: (error) => notify.error(fieldErrorsFrom(error, tErrors).form ?? t("errors.save"))
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => registrationFormTemplatesService.remove(workspaceId as number, id),
    onSuccess: async (_result, id) => {
      if (selectedId === id) {
        setSelectedId(null);
        setDraft(null);
      }
      await invalidate();
      notify.success(t("toast.deleted"));
    },
    onError: (error) => notify.apiError(error, { title: t("errors.delete") })
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
          title: t("confirm.deleteTitle"),
          description: t("confirm.deleteDescription", { name: pending.name }),
          confirmLabel: t("confirm.delete"),
          tone: "danger"
        }
      : {
          title: t("confirm.discardTitle"),
          description: t("confirm.discardDescription"),
          confirmLabel: t("confirm.discard"),
          tone: "warning"
        };

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title={t("noWorkspace.title")}
        description={t("noWorkspace.description")}
      />
    );
  }
  // The list reads nothing until the area's games resolve it.
  if (scope.resolution === null) {
    return scope.isError ? (
      <PageStateCard state="error" onAction={scope.refetch} />
    ) : (
      <Skeleton className="h-40 w-full rounded-md" />
    );
  }
  if (kind === "invalid" || kind === "empty") {
    // The way out lands on the list: a selection made under the unknown game does not follow.
    return <GameScopeControl scope={scope} variant="multi" dropParams={["template"]} />;
  }

  if (listQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("errors.load")}
        onAction={() => void listQuery.refetch()}
      />
    );
  }

  const canCreate = newName.trim().length > 0 && identityProvider !== null && !createMutation.isPending;

  return (
    <div className="flex flex-col gap-4">
      {gameDefs.length > 0 ? <FilterBar defs={gameDefs} filters={filters} /> : null}
      <MasterDetail
        list={
          <div className="flex flex-col gap-2">
            {listQuery.isLoading ? (
              <MasterListSkeleton />
            ) : templates.length > 0 ? (
              <MasterList
                label={t("listLabel")}
                items={templates.map((template) => ({
                  key: template.id,
                  label: template.name,
                  icon: marks ? <GameIcon slug={template.discipline} /> : undefined
                }))}
                selectedKey={selectedId}
                onSelect={openTemplate}
              />
            ) : null}

            {canEdit && (
              <div className="flex flex-col gap-2">
                {enabledGames.length > 1 ? (
                  <GameField
                    id="registration-template-game"
                    games={enabledGames}
                    value={creationGame}
                    onChange={setNewGame}
                  />
                ) : null}
                <div className="flex items-center gap-2">
                  <Input
                    value={newName}
                    aria-label={t("newTemplateName")}
                    placeholder={t("newTemplateName")}
                    onChange={(event) => setNewName(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && canCreate) {
                        event.preventDefault();
                        createMutation.mutate(newName.trim());
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className="shrink-0"
                    disabled={!canCreate}
                    onClick={() => createMutation.mutate(newName.trim())}
                  >
                    {createMutation.isPending ? (
                      <Spinner className="mr-1 size-3.5" />
                    ) : (
                      <Plus className="mr-1 size-3.5" aria-hidden />
                    )}
                    {t("add")}
                  </Button>
                </div>
              </div>
            )}
          </div>
        }
        detail={
          selected && schema ? (
            <section aria-labelledby="registration-template-title" className="space-y-4">
              <div className="flex items-center gap-2">
                {/* The heading names the template; the editable text beside it
                    is the control, so the heading's name stays the bare name
                    rather than "name, Edit template name". */}
                <h2 id="registration-template-title" className="sr-only">
                  {selected.name}
                </h2>
                <InlineEditText
                  className="flex-1"
                  textClassName="text-ui font-semibold text-foreground"
                  value={selected.name}
                  label={t("templateName")}
                  canEdit={canEdit}
                  onSave={(name) =>
                    saveMutation.mutateAsync({
                      id: selected.id,
                      name,
                      // Renaming must not publish the schema being edited
                      // below it: a rename sends what is SAVED.
                      form_schema: selected.form_schema
                    })
                  }
                />
                {canEdit && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={tTable("actionsFor", { label: selected.name })}
                        title={tTable("actionsFor", { label: selected.name })}
                      >
                        <MoreHorizontal aria-hidden className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() =>
                          setPending({ kind: "delete", id: selected.id, name: selected.name })
                        }
                      >
                        {t("delete")}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
              <SchemaEditor
                key={selected.id}
                schema={schema}
                onChange={setDraft}
                subroleCatalog={catalog}
                catalogLoading={catalogLoading}
                metadata={metadata.data ?? null}
                fieldErrors={{}}
              />
            </section>
          ) : outsideList && allTemplatesQuery.isError ? (
            // The selection is still in the URL: its failed lookup is an error with a retry, not "nothing selected".
            <PageStateCard
              state="error"
              title={t("errors.load")}
              onAction={() => void allTemplatesQuery.refetch()}
            />
          ) : null
        }
        emptyDetail={
          listQuery.isLoading || allTemplatesQuery.isLoading ? (
            <div aria-hidden className="space-y-4">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-64 w-full rounded-xl" />
            </div>
          ) : (
            <PageStateCard
              state="empty"
              title={templates.length === 0 ? t("emptyTitle") : t("pickTitle")}
              description={
                templates.length === 0
                  ? t("emptyDescription")
                  : t("pickDescription")
              }
            />
          )
        }
      />

      {selected && schema && (
        <SaveBar
          dirty={draft !== null}
          summary={blocked && blocked.size > 0 ? t("fixQuestions") : t("unsavedChanges")}
          saving={saveMutation.isPending}
          primaryLabel={t("save")}
          onDiscard={() => setDraft(null)}
          onSave={() => {
            if (blocked && blocked.size > 0) {
              notify.error(t("fixQuestions"));
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
