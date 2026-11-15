"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@craazzzyyfoxx/admin-kit/ui/dialog";

import { SocialAccountsEditor } from "@/components/admin/SocialAccountsEditor";
import { usePersonEdit } from "@/components/admin/people/usePersonEdit";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { notify } from "@/lib/notify";
import { MAX_AVATAR_BYTES } from "@/lib/uploads";
import type { User } from "@/types/user.types";

interface PlayerProfileBodyProps {
  user: User;
  /** Avatar + name editing (user.update). */
  canEdit: boolean;
  /** Full identity management — add/edit/delete/set-primary (superuser only). */
  canManageIdentity: boolean;
  /** Toggle per-workspace / global display visibility (user.read). */
  canSetVisibility: boolean;
  /** Current workspace for the per-workspace visibility toggle. */
  workspaceId: number | null;
  canMerge?: boolean;
  onMergeRequested?: (user: User) => void;
}

/**
 * Avatar, name, id, and the social-account editor: the People browser's
 * quick edit. The person hub edits the same things in its header and Profile
 * tab, through the same `usePersonEdit`.
 */
function PlayerProfileBody({
  user: initialUser,
  canEdit,
  canManageIdentity,
  canSetVisibility,
  workspaceId,
  canMerge = false,
  onMergeRequested,
}: Readonly<PlayerProfileBodyProps>) {
  const t = useTranslations("adminPeople.profile");
  const [user, setUser] = useState(initialUser);
  const { uploadAvatar, deleteAvatar, rename, applyUser, avatarBusy } = usePersonEdit(user.id, setUser);
  const socialHeadingId = useId();

  return (
    <>
      <div className="flex flex-col items-center gap-3 border-b border-border pb-4">
        <EditableAvatar
          src={user.avatar_url}
          name={user.name}
          size={80}
          editable={canEdit}
          busy={avatarBusy}
          onSelectFile={(file) => uploadAvatar.mutate(file)}
          onDelete={user.avatar_url ? () => deleteAvatar.mutate() : undefined}
          maxSizeBytes={MAX_AVATAR_BYTES}
          onError={(message) => notify.error(message)}
        />
        <InlineEditText
          value={user.name}
          label={t("playerName")}
          canEdit={canEdit}
          onSave={(name) => rename.mutateAsync(name)}
          textClassName="text-heading font-semibold"
        />
        <span className="text-caption tabular-nums text-muted-foreground">{t("idLabel", { id: user.id })}</span>
        {canMerge && onMergeRequested ? (
          <Button type="button" variant="outline" size="sm" onClick={() => onMergeRequested(user)}>
            {t("merge")}
          </Button>
        ) : null}
      </div>

      {/* Open under the dialog's own (screen-reader) title: the dialog is the surface. */}
      <section aria-labelledby={socialHeadingId} className="space-y-3">
        <h3 id={socialHeadingId} className="text-ui font-semibold text-foreground">
          {t("socialIdentities")}
        </h3>
        <SocialAccountsEditor
          userId={user.id}
          accounts={user.social_accounts ?? []}
          canManage={canManageIdentity}
          canSetVisibility={canSetVisibility}
          workspaceId={workspaceId}
          onUserUpdated={applyUser}
        />
      </section>
    </>
  );
}

// ─── Main dialog ────────────────────────────────────────────────────────────

interface PlayerProfileDialogProps extends PlayerProfileBodyProps {
  onClose: () => void;
}

export function PlayerProfileDialog({
  onClose,
  ...body
}: Readonly<PlayerProfileDialogProps>) {
  const t = useTranslations("adminPeople.profile");
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader className="sr-only">
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <PlayerProfileBody {...body} />
      </DialogContent>
    </Dialog>
  );
}
