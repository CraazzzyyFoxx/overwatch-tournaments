"use client";

import { useId, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { gameFilterDefs } from "@/components/admin/game-filter";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { FilterBar } from "@/components/kit/FilterBar";
import { invalidProps, settingErrorId } from "@/components/kit/SettingRow";
import { useFilters } from "@/components/kit/useFilters";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { triggerChevronClass } from "@/components/ui/chevron";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ColorSwatch } from "@/components/ui/color-swatch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { RowButton } from "@/components/ui/row-button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { GameMark } from "@/components/workspace/GameMark";
import { GameScopeGate } from "@/components/workspace/GameScopeGate";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useGameScope } from "@/hooks/useGameScope";
import { usePermissions } from "@/hooks/usePermissions";
import { useRoleName } from "@/hooks/useRoleName";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { getApiErrorMessage } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { ratedDimension, rolePresentation, selectableRoles, type RoleOntology } from "@/lib/roster/ontology";
import { disciplineQueryKeys } from "@/lib/site/discipline-query-keys";
import { ALL_DISCIPLINES } from "@/lib/site/discipline-scope";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { PlayerSubRole, PlayerSubRoleUpdateInput } from "@/types/admin.types";
import type { DisciplineDescriptor } from "@/types/discipline.types";

/** A rated, top-level role of one game: the parent every sub-role hangs under. */
interface ParentRole {
  id: number;
  code: string;
  name: string;
  /** Its own resolved icon and colour: what a sub-role without its own wears. */
  icon: string | null;
  color: string | null;
}

interface SubRolePermissions {
  create: boolean;
  edit: boolean;
  deactivate: boolean;
}

const PRESENTATION_KEYS = ["icon", "color"] as const;
type PresentationKey = (typeof PRESENTATION_KEYS)[number];
/** `undefined` inherits from the parent role, `null` is explicitly none, a string is its own. */
type Presentation = Record<PresentationKey, string | null | undefined>;

function presentationOf(entry: PlayerSubRole): Presentation {
  const read = (key: PresentationKey) => {
    if (!Object.hasOwn(entry.attrs, key)) return undefined;
    const value = entry.attrs[key];
    return typeof value === "string" ? value : null;
  };
  return { icon: read("icon"), color: read("color") };
}

/** What a sub-role actually shows: its own value, none, or its parent's. */
function effective(own: string | null | undefined, inherited: string | null): string | null {
  return own === undefined ? inherited : own;
}

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/** `validate_presentation` in `shared/domain/roles.py`. */
function iconAccepted(icon: string, discipline: string): boolean {
  if (icon.length > 512 || /[\s'"<>\\]/.test(icon) || icon.includes("..")) return false;
  const game = discipline.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return (
    /^https:\/\/\S+$/.test(icon) ||
    new RegExp(`^assets/${game}/[a-z0-9_/-]+\\.(svg|png|webp)$`).test(icon) ||
    new RegExp(`^/disciplines/${game}/[a-z0-9_/-]+\\.(svg|png|webp)$`).test(icon)
  );
}

/**
 * The workspace's sub-role catalog: under each game, one card per rated role
 * holding that role's sub-roles. The game filter only narrows which games are
 * shown; there is no second layout for one game, and nothing opens into a
 * mode of its own.
 *
 * Each card is the whole workflow for its role: add a sub-role at its foot
 * (game and parent are where it is typed, so nothing asks for them), switch
 * one off or back on in its row, open a row to edit its name, description,
 * colour and icon. Switched-off sub-roles fold away under a count, since a
 * catalog that keeps its retired entries would otherwise read half retired.
 */
export default function WorkspaceSubRolesSettingsPage() {
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const t = useTranslations("adminSettings.subRoles");
  const gameT = useTranslations("common.discipline");
  const scope = useGameScope({ axis: workspaceId ?? "all" });
  const gameDefs = gameFilterDefs(scope.games, gameT("column"), undefined, gameT("all"));
  const filters = useFilters(gameDefs);

  if (workspaceId === null) {
    return (
      <PageStateCard
        state="empty"
        title={t("noWorkspace.title")}
        description={t("noWorkspace.description")}
      />
    );
  }
  const games = (scope.games ?? []).filter((entry) => entry.enabled);
  return (
    <GameScopeGate scope={scope}>
      {(game) => (
        <div className="space-y-6">
          {gameDefs.length > 0 ? <FilterBar defs={gameDefs} filters={filters} /> : null}
          <SubRoleCatalog
            workspaceId={workspaceId}
            games={game === null ? games : games.filter((entry) => entry.code === game)}
            namedGames={game === null && games.length > 1}
          />
          <p className="max-w-prose text-caption text-pretty text-muted-foreground">{t("deactivationNote")}</p>
        </div>
      )}
    </GameScopeGate>
  );
}

/** Role cards in DESIGN §7's three-column role grid; the skeleton draws the same grid. */
const ROLE_GRID_CLASS = "grid gap-3 lg:grid-cols-2 xl:grid-cols-3 lg:items-start";

function RoleGridSkeleton() {
  return (
    <div aria-hidden className={ROLE_GRID_CLASS}>
      {[0, 1, 2].map((card) => (
        <Card key={card} className="space-y-3 p-4">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </Card>
      ))}
    </div>
  );
}

function SubRoleCatalog({
  workspaceId,
  games,
  namedGames
}: Readonly<{ workspaceId: number; games: DisciplineDescriptor[]; namedGames: boolean }>) {
  const t = useTranslations("adminSettings.subRoles");
  const { canAccessPermission } = usePermissions();
  // One read for every game: switching the filter then costs nothing.
  const catalog = useQuery({
    queryKey: adminQueryKeys.playerSubRolesAll(workspaceId, ALL_DISCIPLINES),
    queryFn: ({ signal }) =>
      adminService.getPlayerSubRoles({ workspace_id: workspaceId, include_inactive: true }, signal)
  });
  const permissions: SubRolePermissions = {
    create: canAccessPermission("player.create", workspaceId),
    edit: canAccessPermission("player.update", workspaceId),
    deactivate: canAccessPermission("player.delete", workspaceId)
  };

  if (catalog.isError) {
    return <PageStateCard state="error" title={t("errors.load")} onAction={() => void catalog.refetch()} />;
  }
  if (!catalog.data) {
    return (
      <div aria-busy="true">
        <span className="sr-only">{t("loading")}</span>
        <RoleGridSkeleton />
      </div>
    );
  }
  return (
    <div className="space-y-8">
      {games.map((game) => (
        <GameSection
          key={game.code}
          workspaceId={workspaceId}
          game={game}
          named={namedGames}
          entries={catalog.data.filter((row) => row.discipline === game.code)}
          permissions={permissions}
        />
      ))}
    </div>
  );
}

/** One game: its heading (when several are listed), then a card per rated role. */
function GameSection({
  workspaceId,
  game,
  named,
  entries,
  permissions
}: Readonly<{
  workspaceId: number;
  game: DisciplineDescriptor;
  named: boolean;
  entries: PlayerSubRole[];
  permissions: SubRolePermissions;
}>) {
  const t = useTranslations("adminSettings.subRoles");
  const roleT = useTranslations("common.roleOntology");
  const nameOf = useRoleName();
  const headingId = useId();
  const metadata = useDisciplineMetadata(workspaceId, game.code);
  const ontology = metadata.data;
  const rated = ontology ? ratedDimension(ontology) : null;

  let body;
  if (metadata.isError) {
    body = <PageStateCard state="error" title={t("errors.load")} onAction={() => void metadata.refetch()} />;
  } else if (!ontology) {
    body = <RoleGridSkeleton />;
  } else if (!rated) {
    body = <PageStateCard state="error" title={roleT("metadataError")} />;
  } else {
    const parents: ParentRole[] = selectableRoles(ontology, rated.code)
      .filter((role) => role.parent_id === null)
      .map((role) => ({ id: role.id, code: role.code, name: nameOf(role), ...rolePresentation(ontology.roles, role.id) }));
    body = (
      <div className={ROLE_GRID_CLASS}>
        {parents.map((parent) => (
          <RoleCard
            key={parent.code}
            workspaceId={workspaceId}
            discipline={game.code}
            dimension={rated.code}
            ontology={ontology}
            parent={parent}
            entries={entries.filter((row) => row.dimension === rated.code && row.role === parent.code)}
            permissions={permissions}
          />
        ))}
      </div>
    );
  }

  return named ? (
    <section aria-labelledby={headingId} className="space-y-3">
      <h2 id={headingId} className="flex items-center gap-2 text-heading font-semibold text-foreground">
        <GameMark discipline={game} size={22} decorative />
        {game.name}
      </h2>
      {body}
    </section>
  ) : (
    body
  );
}

function useInvalidateSubRoles(workspaceId: number, discipline: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      // Every game's list shows this game's rows too: drop the workspace's sub-role lists, not one game's.
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.playerSubRoles(workspaceId) }),
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.playerSubRolesPublic(workspaceId, discipline) }),
      queryClient.invalidateQueries({ queryKey: disciplineQueryKeys.metadata(workspaceId, discipline) })
    ]);
}

/** One parent role: its active sub-roles, the switched-off ones folded, and the field that adds one. */
function RoleCard({
  workspaceId,
  discipline,
  dimension,
  ontology,
  parent,
  entries,
  permissions
}: Readonly<{
  workspaceId: number;
  discipline: string;
  dimension: string;
  ontology: RoleOntology;
  parent: ParentRole;
  entries: PlayerSubRole[];
  permissions: SubRolePermissions;
}>) {
  const t = useTranslations("adminSettings.subRoles");
  const headingId = useId();
  const invalidate = useInvalidateSubRoles(workspaceId, discipline);
  const [editing, setEditing] = useState<PlayerSubRole | null>(null);
  const active = entries.filter((entry) => entry.is_active);
  const inactive = entries.filter((entry) => !entry.is_active);

  // Switching off lives in the editor; a folded row only comes back.
  const restore = useMutation({
    mutationFn: (entry: PlayerSubRole) => adminService.updatePlayerSubRole(entry.id, { is_active: true }),
    onSuccess: async (_result, entry) => {
      await invalidate();
      notify.success(t("toast.restored", { name: entry.label }));
    },
    onError: (error) => notify.apiError(error, { title: t("errors.update") })
  });
  const restoringId = restore.isPending ? restore.variables?.id : undefined;

  const row = (entry: PlayerSubRole) => (
    <SubRoleRow
      key={entry.id}
      entry={entry}
      parent={parent}
      canEdit={permissions.edit}
      restoring={restoringId === entry.id}
      onOpen={() => setEditing(entry)}
      onRestore={() => restore.mutate(entry)}
    />
  );

  return (
    <Card asChild>
      <section aria-labelledby={headingId}>
        <header className="flex items-center gap-2.5 border-b border-border px-4 py-3">
          <PlayerRoleIcon role={{ dimension, role: parent.code }} ontology={ontology} size={20} decorative />
          <h3 id={headingId} className="min-w-0 flex-1 truncate text-ui font-semibold text-foreground">
            {parent.name}
          </h3>
          {/* Zero is said by the empty line below; a "0" here would say it twice. */}
          {active.length > 0 ? (
            <span className="aqt-tnum text-caption text-muted-foreground">
              <span aria-hidden>{active.length}</span>
              <span className="sr-only">{t("activeCount", { count: active.length })}</span>
            </span>
          ) : null}
        </header>

        {active.length > 0 ? (
          <ul className="divide-y divide-border/60">{active.map(row)}</ul>
        ) : (
          <p className="px-4 py-3 text-caption text-muted-foreground">{t("empty")}</p>
        )}

        {inactive.length > 0 ? (
          <Collapsible className="border-t border-border/60">
            <CollapsibleTrigger className="group/trigger flex w-full items-center gap-1.5 px-4 py-2 text-caption text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
              <ChevronDown aria-hidden className={cn(triggerChevronClass, "size-3.5")} />
              {t("inactiveToggle", { count: inactive.length })}
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul className="divide-y divide-border/60 border-t border-border/60">{inactive.map(row)}</ul>
            </CollapsibleContent>
          </Collapsible>
        ) : null}

        {permissions.create ? (
          <AddSubRole
            workspaceId={workspaceId}
            discipline={discipline}
            parent={parent}
            onAdded={invalidate}
          />
        ) : null}

        {editing ? (
          <EditSubRoleDialog
            entry={editing}
            discipline={discipline}
            parent={parent}
            canSwitchOff={permissions.deactivate}
            onClose={() => setEditing(null)}
            onSaved={invalidate}
          />
        ) : null}
      </section>
    </Card>
  );
}

/** An inline error: icon and words, never colour alone (DESIGN §12). */
function FieldError({ id, message, className }: Readonly<{ id: string; message: string; className?: string }>) {
  return (
    <p id={id} role="alert" className={cn("flex items-start gap-1.5 text-caption text-danger", className)}>
      <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
      {message}
    </p>
  );
}

/** The sub-role's own icon in its colour, its parent's when it has none of its own, a dot without an icon. */
function SubRoleMark({ icon, color, size = 18 }: Readonly<{ icon: string | null; color: string | null; size?: number }>) {
  const tint = color ?? "var(--aqt-fg-muted)";
  if (!icon) {
    return (
      <span aria-hidden className="flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
        <span className="size-2.5 rounded-full" style={{ background: tint }} />
      </span>
    );
  }
  const mask = `url("${icon}")`;
  return (
    <span
      aria-hidden
      className="shrink-0"
      style={{
        width: size,
        height: size,
        backgroundColor: tint,
        maskImage: mask,
        WebkitMaskImage: mask,
        maskSize: "contain",
        WebkitMaskSize: "contain",
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
        maskPosition: "center",
        WebkitMaskPosition: "center"
      }}
    />
  );
}

/**
 * A sub-role. Its state is where it sits (the list or the fold), so an active
 * row carries no control; a folded one offers "Restore" to whoever may edit.
 */
function SubRoleRow({
  entry,
  parent,
  canEdit,
  restoring,
  onOpen,
  onRestore
}: Readonly<{
  entry: PlayerSubRole;
  parent: ParentRole;
  canEdit: boolean;
  restoring: boolean;
  onOpen: () => void;
  onRestore: () => void;
}>) {
  const t = useTranslations("adminSettings.subRoles");
  const own = presentationOf(entry);

  return (
    <li className="relative flex items-center gap-3 px-4 py-2.5">
      <SubRoleMark icon={effective(own.icon, parent.icon)} color={effective(own.color, parent.color)} />
      <div className="min-w-0 flex-1">
        <p className={cn("truncate text-sm font-medium", entry.is_active ? "text-foreground" : "text-muted-foreground")}>
          {entry.label}
        </p>
        {entry.description ? (
          <p className="truncate text-caption text-muted-foreground">{entry.description}</p>
        ) : null}
      </div>
      {canEdit ? (
        // The whole row opens the editor; "Restore" comes after it and sits above its box.
        <RowButton onClick={onOpen} aria-label={t("edit", { name: entry.label })} className="absolute inset-0" />
      ) : null}
      {canEdit && !entry.is_active ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="relative -my-1"
          disabled={restoring}
          aria-label={t("restore", { name: entry.label })}
          onClick={onRestore}
        >
          {t("restoreAction")}
        </Button>
      ) : null}
    </li>
  );
}

/** Adds a sub-role under this card's role: type a name, Enter. Stays focused for the next one. */
function AddSubRole({
  workspaceId,
  discipline,
  parent,
  onAdded
}: Readonly<{ workspaceId: number; discipline: string; parent: ParentRole; onAdded: () => Promise<unknown> }>) {
  const t = useTranslations("adminSettings.subRoles");
  const inputId = useId();
  const [label, setLabel] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (value: string) =>
      adminService.createPlayerSubRole({ workspace_id: workspaceId, discipline, role: parent.code, label: value }),
    onSuccess: async () => {
      setLabel("");
      await onAdded();
    },
    onError: (error) => setRefusal(getApiErrorMessage(error, t("errors.add")))
  });
  const value = label.trim();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (value && !create.isPending) create.mutate(value);
  };

  return (
    <form onSubmit={submit} className="border-t border-border/60 px-4 py-2.5">
      <div className="flex items-center gap-2">
        <Plus aria-hidden className="size-4 shrink-0 text-muted-foreground" />
        <Input
          id={inputId}
          size="sm"
          value={label}
          placeholder={t("addPlaceholder")}
          aria-label={t("addLabel", { role: parent.name })}
          // Read-only, not disabled: a disabled field drops focus, and the next sub-role is typed right after.
          readOnly={create.isPending}
          onChange={(event) => {
            setLabel(event.target.value);
            setRefusal(null);
          }}
          {...invalidProps(inputId, refusal ?? undefined)}
        />
        <Button type="submit" size="sm" variant="outline" disabled={!value || create.isPending}>
          {t("add")}
        </Button>
      </div>
      {refusal ? (
        <FieldError id={settingErrorId(inputId)} message={refusal} className="mt-1.5" />
      ) : null}
    </form>
  );
}

/** One presentation key in the editor: its own value, none, or its parent's, shown before it is typed. */
function PresentationField({
  kind,
  entry,
  parent,
  value,
  error,
  onChange
}: Readonly<{
  kind: PresentationKey;
  entry: PlayerSubRole;
  parent: ParentRole;
  value: string | null | undefined;
  error?: string;
  onChange: (next: string | null) => void;
}>) {
  const t = useTranslations("adminSettings.subRoles");
  const id = `sub-role-${entry.id}-${kind}`;
  const label = t(kind === "color" ? "colorField" : "iconField");
  const inherited = kind === "color" ? parent.color : parent.icon;
  const placeholder =
    value === undefined ? t("presentationInherits", { role: parent.name }) : t("presentationNone");

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        {kind === "color" ? (
          <ColorSwatch
            value={value ?? ""}
            fallback={value === undefined ? (inherited ?? undefined) : undefined}
            label={label}
            onValueChange={onChange}
          />
        ) : (
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-dashed border-[color:var(--aqt-border-2)]">
            <SubRoleMark
              icon={value && iconAccepted(value, entry.discipline) ? value : value === undefined ? inherited : null}
              color={parent.color}
              size={20}
            />
          </span>
        )}
        <Input
          id={id}
          value={value ?? ""}
          placeholder={placeholder}
          spellCheck={false}
          className={cn(kind === "color" && "font-mono placeholder:font-sans")}
          onChange={(event) => onChange(event.target.value)}
          {...invalidProps(id, error)}
        />
        {value === null ? null : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={t("removePresentation", { field: label, name: entry.label })}
            onClick={() => onChange(null)}
          >
            {t("remove")}
          </Button>
        )}
      </div>
      {error ? (
        <FieldError id={settingErrorId(id)} message={error} />
      ) : kind === "icon" ? (
        <p className="text-caption text-muted-foreground">{t("iconHint", { game: entry.discipline })}</p>
      ) : null}
    </div>
  );
}

/**
 * A sub-role's name, description, colour and icon. Colour and icon each
 * inherit from the parent role until set; "Remove" sets them to none (the API
 * keeps an explicit none apart from inheriting, and cannot go back to it).
 * "Switch off" at the footer's start saves what was edited first, so nothing
 * typed is lost to it.
 */
function EditSubRoleDialog({
  entry,
  discipline,
  parent,
  canSwitchOff,
  onClose,
  onSaved
}: Readonly<{
  entry: PlayerSubRole;
  discipline: string;
  parent: ParentRole;
  canSwitchOff: boolean;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}>) {
  const t = useTranslations("adminSettings.subRoles");
  const [initial] = useState(() => ({
    label: entry.label,
    description: entry.description ?? "",
    ...presentationOf(entry)
  }));
  const [form, setForm] = useState(initial);
  const [attempted, setAttempted] = useState(false);

  // An emptied field that was inheriting still inherits; one that had a value is now none.
  const presentationValue = (key: PresentationKey) => {
    const value = form[key];
    if (value === null || value === undefined) return value;
    return value.trim() || (initial[key] === undefined ? undefined : null);
  };

  const patch: PlayerSubRoleUpdateInput = {};
  if (form.label.trim() !== initial.label) patch.label = form.label.trim();
  if (form.description.trim() !== initial.description.trim()) patch.description = form.description.trim() || null;
  for (const key of PRESENTATION_KEYS) {
    const value = presentationValue(key);
    if (value !== initial[key] && value !== undefined) patch[key] = value;
  }
  const dirty = Object.keys(patch).length > 0;

  const errors: Record<string, string> = {};
  if (!form.label.trim()) errors.label = t("errors.labelRequired");
  const color = presentationValue("color");
  if (typeof color === "string" && !HEX_RE.test(color)) errors.color = t("errors.color");
  const icon = presentationValue("icon");
  if (typeof icon === "string" && !iconAccepted(icon, discipline)) errors.icon = t("errors.icon", { game: discipline });
  const shown = attempted ? errors : {};

  const save = useMutation({
    mutationFn: async ({ off }: { off: boolean }) => {
      if (dirty) await adminService.updatePlayerSubRole(entry.id, patch);
      if (off) await adminService.deletePlayerSubRole(entry.id);
    },
    onSuccess: async (_result, { off }) => {
      await onSaved();
      const name = patch.label ?? entry.label;
      notify.success(off ? t("toast.deactivated", { name }) : t("toast.saved", { name }));
      onClose();
    }
  });

  const submit = (off: boolean) => {
    setAttempted(true);
    if (Object.keys(errors).length > 0) return;
    if (dirty || off) save.mutate({ off });
    else onClose();
  };

  return (
    <EntityFormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("editTitle", { name: entry.label })}
      description={t("editDescription", { role: parent.name })}
      isDirty={dirty}
      isSubmitting={save.isPending}
      fieldErrors={shown}
      errorMessage={save.isError ? getApiErrorMessage(save.error, t("errors.update")) : undefined}
      onSubmit={() => submit(false)}
      footerStart={
        entry.is_active && canSwitchOff ? (
          <Button type="button" variant="ghost" disabled={save.isPending} onClick={() => submit(true)}>
            {t("switchOff")}
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-1.5">
        <Label htmlFor="sub-role-label">{t("labelField")}</Label>
        <Input
          id="sub-role-label"
          value={form.label}
          onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))}
          {...invalidProps("sub-role-label", shown.label)}
        />
        {shown.label ? <FieldError id={settingErrorId("sub-role-label")} message={shown.label} /> : null}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="sub-role-description">{t("descriptionField")}</Label>
        <Textarea
          id="sub-role-description"
          rows={2}
          value={form.description}
          onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
        />
      </div>
      {PRESENTATION_KEYS.map((key) => (
        <PresentationField
          key={key}
          kind={key}
          entry={entry}
          parent={parent}
          value={form[key]}
          error={shown[key]}
          onChange={(next) => setForm((current) => ({ ...current, [key]: next }))}
        />
      ))}
    </EntityFormDialog>
  );
}
