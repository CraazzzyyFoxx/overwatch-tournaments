"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { usePersonEdit } from "@/components/admin/people/usePersonEdit";
import { EntityHubHeader } from "@/components/kit/EntityHubHeader";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { notify } from "@/lib/notify";
import { MAX_AVATAR_BYTES } from "@/lib/uploads";
import type { User } from "@/types/user.types";

/**
 * The person hub's header: the avatar beside the name, and the `<h1>` is the
 * name editor itself — the hub is where a person is edited, so a read-only
 * heading over a second name field would print the name twice.
 */
export function PersonHubHeader({
  person,
  personId,
  canEdit,
  actions
}: Readonly<{
  /** `undefined` while the person loads. */
  person: User | undefined;
  personId: number;
  /** `user.update`: avatar and name. */
  canEdit: boolean;
  actions?: ReactNode;
}>) {
  const t = useTranslations("adminPeople");
  const { uploadAvatar, deleteAvatar, rename, avatarBusy } = usePersonEdit(personId);

  return (
    <EntityHubHeader
      leading={
        person ? (
          <EditableAvatar
            src={person.avatar_url}
            name={person.name}
            size={40}
            editable={canEdit}
            busy={avatarBusy}
            onSelectFile={(file) => uploadAvatar.mutate(file)}
            onDelete={person.avatar_url ? () => deleteAvatar.mutate() : undefined}
            maxSizeBytes={MAX_AVATAR_BYTES}
            onError={(message) => notify.error(message)}
          />
        ) : (
          <Skeleton className="size-10 rounded-full" />
        )
      }
      title={
        person ? (
          <InlineEditText
            value={person.name}
            label={t("profile.playerName")}
            canEdit={canEdit}
            onSave={(name) => rename.mutateAsync(name)}
          />
        ) : (
          t("person.fallbackName", { id: personId })
        )
      }
      meta={[
        <span key="id" className="tabular-nums">
          #{personId}
        </span>
      ]}
      backHref="/admin/people"
      actions={actions}
    />
  );
}
