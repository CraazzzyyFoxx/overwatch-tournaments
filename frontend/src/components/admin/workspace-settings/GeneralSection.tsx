"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";

import { CommandGroup, CommandItem } from "@/components/ui/command";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownEditor } from "@/components/admin/MarkdownEditor";
import { AuditTrailButton } from "@/components/kit/AuditTrailSheet";
import { Combobox, ComboboxCheck, ComboboxMeta } from "@/components/ui/combobox";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, invalidProps } from "@/components/kit/SettingRow";
import {
  WorkspaceOwnerControl,
  WorkspaceOwnerTransferControl,
  WorkspaceOwnerValue
} from "@/components/admin/workspace-owner";
import {
  WorkspaceNotListedNotice,
  WorkspaceVerificationControl
} from "@/components/admin/workspace-verification";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { DEFAULT_WORKSPACE_TIMEZONE, getUtcOffsetLabel } from "@/lib/workspace/timezone";
import workspaceService from "@/services/workspace.service";
import { SettingsHeaderActions } from "./WorkspaceSettingsShell";
import { DisciplinesField } from "./DisciplinesField";
import { LINK_HOSTS } from "./fields";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

const ACCEPTED_IMAGE_TYPES = "image/webp,image/png,image/jpeg,image/gif";
const MAX_FILE_SIZE = 2 * 1024 * 1024; // 2 MB
/** `WorkspaceUpdate` limits in app-service `schemas/workspace.py`. */
const NAME_MAX = 255;
const TAGLINE_MAX = 120;
const ABOUT_MAX = 4000;

/** The three community links, rendered identically — label, type, example. */
const LINK_FIELDS = [
  { key: "discord_url", labelKey: "linkLabels.discord" },
  { key: "twitch_url", labelKey: "linkLabels.twitch" },
  { key: "boosty_url", labelKey: "linkLabels.boosty" }
] as const satisfies ReadonlyArray<{ key: keyof typeof LINK_HOSTS; labelKey: string }>;

/**
 * Every IANA zone the runtime knows, searchable by name or offset. The saved
 * zone stays selectable even when this runtime does not list it.
 */
function TimezoneField({
  id,
  value,
  onChange
}: Readonly<{ id: string; value: string; onChange: (zone: string) => void }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.general");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const zones = useMemo(() => {
    let names: string[];
    try {
      names = Intl.supportedValuesOf("timeZone");
    } catch {
      names = [DEFAULT_WORKSPACE_TIMEZONE, "UTC"];
    }
    if (!names.includes(value)) names = [value, ...names];
    return names.map((zone) => ({ zone, offset: getUtcOffsetLabel(zone) }));
  }, [value]);

  const label = `${value} (${getUtcOffsetLabel(value)})`;

  return (
    <Combobox
      id={id}
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch("");
      }}
      label={label}
      searchValue={search}
      onSearchValueChange={setSearch}
      searchPlaceholder={t("searchTimezone")}
      emptyMessage={t("noTimezone")}
    >
      <CommandGroup>
        {zones.map(({ zone, offset }) => (
          <CommandItem
            key={zone}
            // Offsets are searchable too: "+3" finds every zone at UTC+3.
            value={`${zone} ${offset}`}
            onSelect={() => {
              onChange(zone);
              setOpen(false);
              setSearch("");
            }}
          >
            <span className="min-w-0 flex-1 truncate">{zone}</span>
            <ComboboxMeta>{offset}</ComboboxMeta>
            <ComboboxCheck selected={zone === value} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}

/**
 * Name, icon, timezone, public page, links, games and ownership of a workspace.
 *
 * Grouped by what the reader is deciding, not by how a control saves. The
 * icon sits beside the name it stands for even though it uploads on its own:
 * it is a file, not a field, and goes through its own endpoint, so there is no
 * half-saved state where the avatar shown is a `blob:` URL the server never
 * received. Its hint says so, where the group cannot.
 *
 * The superuser-only controls are their own group, so an owner never reads a
 * page whose last rows are things they cannot touch, and the one owner fact
 * is said once, in Ownership.
 */
export function GeneralSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.general");
  const settings = useWorkspaceSettingsForm(workspaceId, "general");
  const { isSuperuser } = usePermissions();
  const { patch, invalidate, errors, reveal } = settings;

  const uploadIcon = useMutation({
    mutationFn: (file: File) => workspaceService.uploadIcon(workspaceId as number, file),
    onSuccess: () => {
      invalidate();
      notify.success(t("iconUpdated"));
    },
    onError: (error) => notify.apiError(error, { title: t("uploadIconError") })
  });

  const deleteIcon = useMutation({
    mutationFn: () => workspaceService.deleteIcon(workspaceId as number),
    onSuccess: () => {
      invalidate();
      notify.success(t("iconRemoved"));
    },
    onError: (error) => notify.apiError(error, { title: t("removeIconError") })
  });

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ workspace, form: values }) => (
        <>
          {/* The audit trail is a drawer the whole admin shares, not a section
              of its own: it answers "who changed this" about branding, the
              domain and the guild alike, and General is where the rail lands.
              It sits in the page header, beside the title it audits. */}
          <SettingsHeaderActions>
            <AuditTrailButton
              scope={{
                entityType: "workspace",
                entityId: workspace.id,
                workspaceId: workspace.id
              }}
              target={t("auditTarget", { name: workspace.name })}
              showCount
            />
          </SettingsHeaderActions>

          <WorkspaceNotListedNotice status={workspace.verification_status} />

          <SettingGroup
            id="identity"
            title={t("groups.identity.title")}
            description={t("groups.identity.description")}
          >
            <SettingRow htmlFor="workspace-name" label={t("name")} error={errors.name} stacked>
              <div className="flex w-full items-start gap-4">
                <EditableAvatar
                  src={workspace.icon_url}
                  name={values.name}
                  size={64}
                  shape="rounded"
                  busy={uploadIcon.isPending || deleteIcon.isPending}
                  onSelectFile={(file) => uploadIcon.mutate(file)}
                  onDelete={workspace.icon_url ? () => deleteIcon.mutate() : undefined}
                  accept={ACCEPTED_IMAGE_TYPES}
                  maxSizeBytes={MAX_FILE_SIZE}
                  onError={(message) => notify.error(message)}
                  labels={{ change: t("changeIcon"), remove: t("removeIcon") }}
                />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <Input
                    id="workspace-name"
                    maxLength={NAME_MAX}
                    value={values.name}
                    onChange={(event) => patch({ name: event.target.value })}
                    onBlur={() => reveal("name")}
                    {...invalidProps("workspace-name", errors.name)}
                  />
                  <p className="text-xs text-muted-foreground">{t("iconHelp")}</p>
                </div>
              </div>
            </SettingRow>
            <SettingRow htmlFor="workspace-timezone" label={t("timezone")} hint={t("timezoneHelp")}>
              <TimezoneField
                id="workspace-timezone"
                value={values.timezone}
                onChange={(zone) => patch({ timezone: zone })}
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup
            id="community"
            title={t("groups.publicPage.title")}
            description={
              // The way to check the result sits beside what it previews; in
              // the page header it crowded the title off narrow windows.
              <>
                {t("groups.publicPage.description")}{" "}
                <a
                  href={`/workspace/${workspace.slug}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 whitespace-nowrap font-medium text-foreground underline-offset-4 hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("openPage")}
                  <ArrowUpRight aria-hidden className="size-3.5" />
                  <span className="sr-only">{t("opensInNewTab")}</span>
                </a>
              </>
            }
          >
            <SettingRow
              htmlFor="workspace-tagline"
              label={t("tagline")}
              hint={t("taglineHelp")}
              error={errors.tagline}
              count={{ value: values.tagline.length, max: TAGLINE_MAX }}
              stacked
            >
              <Input
                id="workspace-tagline"
                maxLength={TAGLINE_MAX}
                value={values.tagline}
                onChange={(event) => patch({ tagline: event.target.value })}
                onBlur={() => reveal("tagline")}
                {...invalidProps("workspace-tagline", errors.tagline)}
              />
            </SettingRow>
            <SettingRow
              htmlFor="workspace-description"
              label={t("description")}
              hint={t("descriptionHelp")}
              stacked
            >
              <Textarea
                id="workspace-description"
                value={values.description}
                onChange={(event) => patch({ description: event.target.value })}
              />
            </SettingRow>
            {/* `MarkdownEditor` labels its own textarea; the row's label names
                the field for sighted readers and the counter. */}
            <SettingRow
              label={t("about")}
              hint={t("aboutHelp")}
              error={errors.about}
              count={{ value: values.about.length, max: ABOUT_MAX }}
              stacked
            >
              <MarkdownEditor
                label={t("about")}
                value={values.about}
                maxLength={ABOUT_MAX}
                onChange={(next) => patch({ about: next })}
                className="w-full"
              />
            </SettingRow>
          </SettingGroup>

          <SettingGroup
            id="links"
            title={t("groups.links.title")}
            description={t("groups.links.description")}
          >
            {LINK_FIELDS.map(({ key, labelKey }) => {
              const id = `workspace-${key}`;
              return (
                <SettingRow key={key} htmlFor={id} label={t(labelKey)} error={errors[key]} stacked>
                  <Input
                    id={id}
                    type="url"
                    inputMode="url"
                    autoComplete="url"
                    placeholder={`https://${LINK_HOSTS[key][0]}/…`}
                    value={values[key]}
                    onChange={(event) => patch({ [key]: event.target.value })}
                    onBlur={() => reveal(key)}
                    {...invalidProps(id, errors[key])}
                  />
                </SettingRow>
              );
            })}
          </SettingGroup>

          <SettingGroup
            id="games"
            title={t("groups.disciplines.title")}
            description={t("groups.disciplines.description")}
          >
            <div className="space-y-3">
              <DisciplinesField
                workspace={workspace}
                value={values.disciplines_enabled}
                onChange={(next) => patch({ disciplines_enabled: next })}
              />
              <p className="max-w-prose px-2 text-caption text-pretty text-muted-foreground">
                {t("disciplines.help")}
              </p>
            </div>
          </SettingGroup>

          {/* The transfer row renders nothing for a caller it is not offered
              to, so a co-administrator reads the owner and nothing to press. */}
          <SettingGroup
            id="ownership"
            title={t("groups.ownership.title")}
            description={t("groups.ownership.description")}
            immediate
          >
            <SettingRow label={t("owner")}>
              <div className="min-w-0 text-sm [overflow-wrap:anywhere]">
                <WorkspaceOwnerValue workspaceId={workspace.id} />
              </div>
            </SettingRow>
            <WorkspaceOwnerTransferControl
              workspaceId={workspace.id}
              workspaceName={workspace.name}
              isSuperuser={isSuperuser}
            />
          </SettingGroup>

          {isSuperuser ? (
            <SettingGroup
              id="platform"
              title={t("groups.platform.title")}
              description={t("groups.platform.description")}
              immediate
            >
              <WorkspaceOwnerControl workspaceId={workspace.id} isSuperuser={isSuperuser} />
              <WorkspaceVerificationControl
                workspace={workspace}
                isSuperuser={isSuperuser}
                onChanged={invalidate}
              />
            </SettingGroup>
          ) : null}

          <SaveBar
            dirty={settings.dirty}
            summary={settings.summary}
            error={settings.error}
            saving={settings.saving}
            onDiscard={settings.discard}
            onSave={settings.save}
          />
        </>
      )}
    </WorkspaceSettingsFrame>
  );
}
