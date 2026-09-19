"use client";

import { useMutation } from "@tanstack/react-query";
import { BadgeCheck, ShieldAlert, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { TONE_CLASS, type Tone } from "@/components/kit/tone";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import type { Workspace, WorkspaceVerificationStatus } from "@/types/workspace.types";

// `tone` is narrowed to the three that are also `StatusIcon` variants, so the
// glyph and the notice's tinted surface stay driven by one field.
const TIERS: Record<
  WorkspaceVerificationStatus,
  { label: string; tone: Extract<Tone, "warning" | "info" | "success">; icon: LucideIcon }
> = {
  unverified: { label: "Unverified", tone: "warning", icon: ShieldAlert },
  verified: { label: "Verified", tone: "info", icon: ShieldCheck },
  trusted: { label: "Trusted", tone: "success", icon: BadgeCheck }
};

const ORDER: WorkspaceVerificationStatus[] = ["unverified", "verified", "trusted"];

/**
 * The trust tier of a workspace, next to its name.
 *
 * A glyph, not a text pill: these sit in a table cell and beside a heading
 * where a filled `Trusted`/`Verified` badge on every row was louder than the
 * workspace name it annotates. Same `StatusIcon` treatment (tooltip +
 * `role="img"` label) as the `is_active` column right next to it.
 */
export function WorkspaceVerificationIcon({
  status
}: Readonly<{ status: WorkspaceVerificationStatus }>) {
  const tier = TIERS[status] ?? TIERS.unverified;
  return <StatusIcon icon={tier.icon} label={tier.label} variant={tier.tone} />;
}

/**
 * Why a brand-new workspace is invisible, said on the screen its owner
 * already opened.
 *
 * The public directory lists `verified` and `trusted`, so only an
 * `unverified` organiser finds their workspace nowhere on the home page and
 * has no other way to learn that this is by design rather than a bug.
 */
export function WorkspaceNotListedNotice({
  status
}: Readonly<{ status: WorkspaceVerificationStatus }>) {
  if (status !== "unverified") return null;

  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-3 text-sm",
        TONE_CLASS[TIERS.unverified.tone]
      )}
    >
      <p className="font-medium">Not listed on the home page yet</p>
      <p className="mt-1 max-w-prose opacity-90">
        Your workspace is live — you can run tournaments, invite members and share its link right
        now. It stays off the public workspace directory until the platform team reviews it.
        Linking the Discord server you run helps that review along.
      </p>
    </div>
  );
}

/** Superuser-only trust tier control. Renders nothing for anyone else. */
export function WorkspaceVerificationControl({
  workspace,
  isSuperuser,
  onChanged
}: Readonly<{ workspace: Workspace; isSuperuser: boolean; onChanged: () => void }>) {
  const mutation = useMutation({
    mutationFn: (status: WorkspaceVerificationStatus) =>
      workspaceService.setVerificationStatus(workspace.id, status),
    onSuccess: (updated) => {
      onChanged();
      notify.success(`Verification set to ${TIERS[updated.verification_status]?.label ?? updated.verification_status}`);
    },
    onError: (error) => notify.apiError(error, { title: "Could not change the verification tier" })
  });

  if (!isSuperuser) return null;

  return (
    <div>
      <label htmlFor="workspace-verification" className="text-sm font-medium leading-none">
        Verification tier
      </label>
      <Select
        value={workspace.verification_status}
        disabled={mutation.isPending}
        onValueChange={(next) => mutation.mutate(next as WorkspaceVerificationStatus)}
      >
        <SelectTrigger id="workspace-verification" className="mt-1.5 w-full sm:w-64">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ORDER.map((status) => (
            <SelectItem key={status} value={status}>
              {TIERS[status].label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="mt-1 max-w-prose text-xs text-muted-foreground">
        “Verified” and “Trusted” workspaces are listed in the public directory on the home page;
        “Trusted” also carries a badge there.
      </p>
    </div>
  );
}
