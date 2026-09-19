"use client";

import { useMemo } from "react";
import { useMutation } from "@tanstack/react-query";

import { Card, CardContent } from "@/components/ui/card";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AuditTrailButton } from "@/components/kit/AuditTrailSheet";
import { SaveBar } from "@/components/kit/SaveBar";
import {
  WorkspaceOwnerControl,
  WorkspaceOwnerTransferControl,
  WorkspaceOwnerValue
} from "@/components/admin/workspace-owner";
import {
  WorkspaceNotListedNotice,
  WorkspaceVerificationIcon,
  WorkspaceVerificationControl
} from "@/components/admin/workspace-verification";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { DEFAULT_WORKSPACE_TIMEZONE, getUtcOffsetLabel } from "@/lib/timezone";
import workspaceService from "@/services/workspace.service";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

const ACCEPTED_IMAGE_TYPES = "image/webp,image/png,image/jpeg,image/gif";
const MAX_FILE_SIZE = 2 * 1024 * 1024; // 2 MB

/**
 * Name, description, timezone and icon of a workspace.
 *
 * The icon is not part of the `SaveBar` diff: it is a file, not a field, and
 * it travels through its own endpoint — so picking one uploads it and there is
 * no half-saved state where the avatar shown is a `blob:` URL the server never
 * received.
 */
export function GeneralSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const settings = useWorkspaceSettingsForm(workspaceId, "general");
  const { isSuperuser } = usePermissions();
  const { form, patch, invalidate } = settings;

  // Every IANA zone the runtime knows, with the saved value kept selectable
  // even when this runtime does not list it.
  const timezoneOptions = useMemo(() => {
    let zones: string[];
    try {
      zones = Intl.supportedValuesOf("timeZone");
    } catch {
      zones = [DEFAULT_WORKSPACE_TIMEZONE, "UTC"];
    }
    const current = form?.timezone;
    return current && !zones.includes(current) ? [current, ...zones] : zones;
  }, [form?.timezone]);

  const uploadIcon = useMutation({
    mutationFn: (file: File) => workspaceService.uploadIcon(workspaceId as number, file),
    onSuccess: () => {
      invalidate();
      notify.success("Icon updated");
    },
    onError: (error) => notify.apiError(error, { title: "Could not upload the icon" })
  });

  const deleteIcon = useMutation({
    mutationFn: () => workspaceService.deleteIcon(workspaceId as number),
    onSuccess: () => {
      invalidate();
      notify.success("Icon removed");
    },
    onError: (error) => notify.apiError(error, { title: "Could not remove the icon" })
  });

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ workspace, form: values }) => (
        <>
          {/* The audit trail is a drawer the whole admin shares, not a section
              of its own: it answers "who changed this" about branding, the
              domain and the guild alike, and General is where the rail lands. */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{workspace.name}</span>
              <WorkspaceVerificationIcon status={workspace.verification_status} />
            </div>
            <AuditTrailButton
              scope={{
                entityType: "workspace",
                entityId: workspace.id,
                workspaceId: workspace.id
              }}
              target={`workspace “${workspace.name}”`}
              showCount
            />
          </div>

          <WorkspaceNotListedNotice status={workspace.verification_status} />

          <Card>
            <CardContent className="flex flex-col gap-4 pt-6">
              <div>
                <Label htmlFor="workspace-name">Name</Label>
                <Input
                  id="workspace-name"
                  className="mt-1.5"
                  value={values.name}
                  onChange={(event) => patch({ name: event.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="workspace-description">Description</Label>
                <Textarea
                  id="workspace-description"
                  className="mt-1.5"
                  value={values.description}
                  onChange={(event) => patch({ description: event.target.value })}
                />
              </div>

              <div>
                <Label htmlFor="workspace-timezone">Timezone</Label>
                <Select
                  value={values.timezone}
                  onValueChange={(value) => patch({ timezone: value })}
                >
                  <SelectTrigger id="workspace-timezone" className="mt-1.5 w-full">
                    <SelectValue placeholder="Select timezone" />
                  </SelectTrigger>
                  <SelectContent>
                    {timezoneOptions.map((zone) => (
                      <SelectItem key={zone} value={zone}>
                        {zone} ({getUtcOffsetLabel(zone)})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="mt-1 text-xs text-muted-foreground">
                  Tournament schedule times are entered and shown in this zone.
                </p>
              </div>

              <div>
                <p className="text-sm font-medium leading-none">Icon</p>
                <div className="mt-1.5">
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
                  />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  PNG, JPEG, WebP or GIF, max 2 MB. Saved as soon as you pick it.
                </p>
              </div>

              <div>
                <p className="text-sm font-medium leading-none">Owner</p>
                <p className="mt-1.5 text-sm">
                  <WorkspaceOwnerValue workspaceId={workspace.id} />
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  The account accountable for this workspace, counted against that account&apos;s
                  workspace limit.
                </p>
                <WorkspaceOwnerControl workspaceId={workspace.id} isSuperuser={isSuperuser} />
                <WorkspaceOwnerTransferControl
                  workspaceId={workspace.id}
                  workspaceName={workspace.name}
                  isSuperuser={isSuperuser}
                />
              </div>

              <WorkspaceVerificationControl
                workspace={workspace}
                isSuperuser={isSuperuser}
                onChanged={invalidate}
              />
            </CardContent>
          </Card>

          <SaveBar
            dirty={settings.dirty}
            summary={settings.summary}
            saving={settings.saving}
            onDiscard={settings.discard}
            onSave={settings.save}
          />
        </>
      )}
    </WorkspaceSettingsFrame>
  );
}
