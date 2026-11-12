"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { BadgeCheck, ShieldAlert, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { SettingRow } from "@/components/kit/SettingRow";
import type { Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { notify } from "@/lib/notify";
import workspaceService from "@/services/workspace.service";
import type { Workspace, WorkspaceVerificationStatus } from "@/types/workspace.types";

// `tone` is narrowed to the three that are also `StatusIcon` variants.
const TIERS: Record<
  WorkspaceVerificationStatus,
  { tone: Extract<Tone, "warning" | "info" | "success">; icon: LucideIcon }
> = {
  unverified: { tone: "warning", icon: ShieldAlert },
  verified: { tone: "info", icon: ShieldCheck },
  trusted: { tone: "success", icon: BadgeCheck }
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
  const t = useTranslations("adminAccess.verification");
  const tier = TIERS[status] ?? TIERS.unverified;
  return <StatusIcon icon={tier.icon} label={t(status)} variant={tier.tone} />;
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
  const t = useTranslations("adminAccess.verification");
  if (status !== "unverified") return null;

  return (
    <Alert>
      <AlertTitle>{t("notListed")}</AlertTitle>
      <AlertDescription>{t("notice")}</AlertDescription>
    </Alert>
  );
}

/**
 * Superuser-only trust tier control, as a `SettingRow` of its own. Renders
 * nothing for anyone else, so a non-superuser gets no empty row.
 */
export function WorkspaceVerificationControl({
  workspace,
  isSuperuser,
  onChanged
}: Readonly<{ workspace: Workspace; isSuperuser: boolean; onChanged: () => void }>) {
  const t = useTranslations("adminAccess.verification");
  const mutation = useMutation({
    mutationFn: (status: WorkspaceVerificationStatus) =>
      workspaceService.setVerificationStatus(workspace.id, status),
    onSuccess: (updated) => {
      onChanged();
      notify.success(t("changed", { tier: t(updated.verification_status) }));
    },
    onError: (error) => notify.apiError(error, { title: t("error") })
  });

  if (!isSuperuser) return null;

  return (
    <SettingRow htmlFor="workspace-verification" label={t("label")} hint={t("description")}>
      <Select
        value={workspace.verification_status}
        disabled={mutation.isPending}
        onValueChange={(next) => mutation.mutate(next as WorkspaceVerificationStatus)}
      >
        <SelectTrigger id="workspace-verification" className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ORDER.map((status) => (
            <SelectItem key={status} value={status}>
              {t(status)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </SettingRow>
  );
}
