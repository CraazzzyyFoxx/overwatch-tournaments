"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import type { DivisionGridVersion } from "@/types/workspace.types";

interface DraftEditorActionsProps {
  version: DivisionGridVersion;
  activeVersionId: number | null;
  editable: boolean;
  canPublish: boolean;
  canDelete: boolean;
  canUndo: boolean;
  publishable: boolean;
  publishing: boolean;
  /** Readiness says every source is mapped, so the version may become the default. */
  activationReady: boolean;
  activating: boolean;
  onUndo: () => void;
  onDiscard: () => void;
  onPublish: () => void;
  onActivate: () => void;
  /** Clones a published version into a new draft. */
  onClone: () => void;
}

/**
 * The editor header's buttons: undo, discard, publish a draft, activate or
 * clone a published version. Publish and activate stay on screen while their
 * precondition is unmet: disabled, with the reason beside them.
 */
export function DraftEditorActions({
  version,
  activeVersionId,
  editable,
  canPublish,
  canDelete,
  canUndo,
  publishable,
  publishing,
  activationReady,
  activating,
  onUndo,
  onDiscard,
  onPublish,
  onActivate,
  onClone
}: Readonly<DraftEditorActionsProps>) {
  const t = useTranslations("adminSettings.divisions");
  const reasonId = useId();
  const isDraft = version.status === "draft";
  const showPublish = canPublish && isDraft;
  const showActivate = canPublish && !isDraft && version.id !== activeVersionId;
  const reason =
    showPublish && !publishable
      ? t("editorDetails.publishBlocked")
      : showActivate && !activationReady
        ? t("editorDetails.mappingBlocked")
        : null;
  const describedBy = reason ? reasonId : undefined;
  return (
    <>
      {editable ? (
        <Button variant="outline" size="sm" disabled={!canUndo} onClick={onUndo}>
          {t("editor.undo")}
        </Button>
      ) : null}
      {editable && canDelete ? (
        <Button variant="ghost" size="sm" onClick={onDiscard}>
          {t("editor.discardDraft")}
        </Button>
      ) : null}
      {showPublish ? (
        <Button
          size="sm"
          disabled={!publishable || publishing}
          aria-describedby={describedBy}
          onClick={onPublish}
        >
          {t("editor.publishVersion", { version: version.version })}
        </Button>
      ) : null}
      {canPublish && !isDraft ? (
        <Button variant="outline" size="sm" onClick={onClone}>
          {t("editor.createDraft")}
        </Button>
      ) : null}
      {showActivate ? (
        <Button
          size="sm"
          disabled={!activationReady || activating}
          aria-describedby={describedBy}
          onClick={onActivate}
        >
          {t("activateVersion", { version: version.version })}
        </Button>
      ) : null}
      {reason ? (
        <p id={reasonId} className="max-w-xs text-caption text-muted-foreground">
          {reason}
        </p>
      ) : null}
    </>
  );
}
