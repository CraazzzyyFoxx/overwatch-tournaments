"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { SaveBar } from "@/components/kit/SaveBar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { ApiError, getApiErrorMessage } from "@/lib/api/error";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import { notify } from "@/lib/notify";
import notificationService from "@/services/notification.service";
import type { NotificationWorkspaceConfigUpdate } from "@/types/notification.types";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

/**
 * Human names for the kinds the server offers. The list itself comes from the
 * server (`broadcastable_kinds`), so a kind added there appears here without a
 * release — unnamed, but never missing.
 */
const KIND_LABELS: Record<string, string> = {
  "registration.opened": "Registration opened",
  "check_in.opened": "Check-in opened",
  "encounter.scheduled": "Match scheduled"
};

/**
 * The three ways a save can fail, in the organiser's words: a channel that is
 * not this guild's, a guild that was unlinked since the page loaded, and
 * Discord being unreachable are three different fixes.
 */
function saveFailure(error: unknown): string {
  const status = error instanceof ApiError ? error.status : 0;
  if (status === 409) {
    return "This workspace has no linked Discord server, so there is no channel to post in. Link one in the Discord section first.";
  }
  if (status === 503) {
    return "Discord could not be reached, so the channel could not be checked. Nothing was saved — try again in a moment.";
  }
  return getApiErrorMessage(error, "Could not save the notification settings.");
}

const LOCALES = [
  { value: "ru", label: "Russian" },
  { value: "en", label: "English" }
] as const;

/** What the form holds; the wire body is this exact shape. */
type Draft = NotificationWorkspaceConfigUpdate;

function sameDraft(left: Draft, right: Draft): boolean {
  return (
    left.discord_channel_id === right.discord_channel_id &&
    left.locale === right.locale &&
    left.broadcast_kinds.length === right.broadcast_kinds.length &&
    left.broadcast_kinds.every((kind) => right.broadcast_kinds.includes(kind))
  );
}

/**
 * Where this workspace's tournament events are announced, and which of them.
 *
 * One channel, not one per tournament: the bot posts as the workspace, and a
 * per-tournament override would be a second place for the same decision to
 * disagree with itself. Personal notifications are not configured here at all —
 * they follow each recipient's own opt-outs.
 */
function ChannelCard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const configQuery = useQuery({
    queryKey: notificationQueryKeys.workspaceConfig(workspaceId),
    queryFn: () => notificationService.workspaceConfig(workspaceId)
  });
  const config = configQuery.data;
  // The wire body is a subset of the read: the server's catalogue and the
  // guild id ride along on the response but are not editable here.
  const baseline: Draft | null = config
    ? {
        discord_channel_id: config.discord_channel_id,
        locale: config.locale,
        broadcast_kinds: config.broadcast_kinds
      }
    : null;
  const values = draft ?? baseline;

  const save = useMutation({
    mutationFn: (body: Draft) => notificationService.updateWorkspaceConfig(workspaceId, body),
    onSuccess: (saved) => {
      setError(null);
      setDraft(null);
      queryClient.setQueryData(notificationQueryKeys.workspaceConfig(workspaceId), saved);
      notify.success("Notification settings saved");
    },
    onError: (cause) => {
      setError(saveFailure(cause));
      notify.apiError(cause, { title: "Could not save the notification settings" });
    }
  });

  if (!config || !values || !baseline) {
    return (
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">
            {configQuery.isError
              ? "The notification settings failed to load. Reload the page."
              : "Loading notification settings…"}
          </p>
        </CardContent>
      </Card>
    );
  }

  const patch = (partial: Partial<Draft>) => setDraft({ ...values, ...partial });
  const dirty = !sameDraft(values, baseline);

  return (
    <>
      <Card>
        <CardContent className="flex flex-col gap-4 pt-6">
          <h2 className={EYEBROW_CLASS}>Announcement channel</h2>

          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <DiscordChannelSelect
                workspaceId={workspaceId}
                // The picker has no null: "" is its no-channel value.
                value={values.discord_channel_id ?? ""}
                onChange={(next) => patch({ discord_channel_id: next === "" ? null : next })}
                disabled={save.isPending}
                ariaLabel="Notification Discord channel"
                placeholder="No channel"
              />
            </div>
            {values.discord_channel_id ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={save.isPending}
                onClick={() => patch({ discord_channel_id: null })}
              >
                Clear
              </Button>
            ) : null}
          </div>

          <p className="max-w-prose text-xs text-muted-foreground text-pretty">
            With no channel the bot posts nothing — personal notifications and the in-app inbox are
            unaffected. Hidden tournaments never reach the channel, whatever is ticked below.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-6">
          <h2 className={EYEBROW_CLASS}>What gets posted</h2>

          <div className="flex flex-col gap-2">
            {config.broadcastable_kinds.map((kind) => {
              const id = `broadcast-${kind}`;
              const checked = values.broadcast_kinds.includes(kind);
              return (
                <div key={kind} className="flex items-center gap-2">
                  <Checkbox
                    id={id}
                    checked={checked}
                    disabled={save.isPending}
                    onCheckedChange={(next) =>
                      patch({
                        broadcast_kinds:
                          next === true
                            ? [...values.broadcast_kinds, kind]
                            : values.broadcast_kinds.filter((entry) => entry !== kind)
                      })
                    }
                  />
                  <Label htmlFor={id} className="text-sm font-normal">
                    {KIND_LABELS[kind] ?? kind}
                  </Label>
                </div>
              );
            })}
          </div>

          <p className="max-w-prose text-xs text-muted-foreground text-pretty">
            A scheduled match is one post per match, so a whole round scheduled at once is a whole
            round of posts. It is off by default for that reason.
          </p>

          <div>
            <Label htmlFor="notification-locale">Language</Label>
            <Select
              value={values.locale}
              onValueChange={(next) => patch({ locale: next as "ru" | "en" })}
            >
              <SelectTrigger id="notification-locale" className="mt-1.5 w-full max-w-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LOCALES.map((locale) => (
                  <SelectItem key={locale.value} value={locale.value}>
                    {locale.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="mt-1 max-w-prose text-xs text-muted-foreground">
              The language of the channel posts. Times render in each reader&apos;s own timezone,
              whichever language is chosen.
            </p>
          </div>

          {error ? (
            <p role="alert" className="max-w-prose text-sm font-medium text-danger">
              {error}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <SaveBar
        dirty={dirty}
        summary="Notification settings"
        saving={save.isPending}
        onDiscard={() => {
          setDraft(null);
          setError(null);
        }}
        onSave={() => save.mutate(values)}
      />
    </>
  );
}

/**
 * The workspace half of event notifications: the channel the bot posts in.
 *
 * Gated on a linked Discord guild rather than merely disabled without one: the
 * channel picker reads that guild's channels, so with none bound there is
 * nothing to pick and the only useful control is a link to the section that
 * binds it.
 */
export function NotificationsSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const settings = useWorkspaceSettingsForm(workspaceId, "notifications");
  // Same shell, two routes (`/admin/settings/*` and `/admin/workspaces/[id]/*`):
  // the sibling section sits next to this one under either.
  const pathname = usePathname();
  const discordHref = pathname.replace(/\/notifications$/, "/discord");

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ workspace }) =>
        workspace.discord_guild_id ? (
          <ChannelCard workspaceId={workspace.id} />
        ) : (
          <Card>
            <CardContent className="flex flex-col items-start gap-3 pt-6">
              <h2 className={EYEBROW_CLASS}>No Discord server linked</h2>
              <p className="max-w-prose text-sm text-muted-foreground">
                Tournament events are announced by the bot in a channel of this workspace&apos;s
                Discord server. Link one first — until then the in-app inbox is the only place they
                appear.
              </p>
              <Button asChild variant="outline" size="sm">
                <Link href={discordHref}>Open Discord settings</Link>
              </Button>
            </CardContent>
          </Card>
        )
      }
    </WorkspaceSettingsFrame>
  );
}
