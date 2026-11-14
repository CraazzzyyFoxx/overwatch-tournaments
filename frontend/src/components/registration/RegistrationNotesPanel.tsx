"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Paperclip, Pencil, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Markdown } from "@/components/Markdown";
import { Textarea } from "@/components/ui/textarea";
import { FileButton } from "@/components/ui/file-button";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { eyebrowClass } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationNoteService, {
  NOTE_ATTACHMENT_ACCEPT,
  NOTE_ATTACHMENT_MAX_BYTES,
  NOTE_ATTACHMENTS_PER_NOTE
} from "@/services/registration-note.service";
import type {
  RegistrationNote,
  RegistrationNoteAttachment,
  RegistrationNoteTarget
} from "@/types/registration-note.types";

const STAMP = { dateStyle: "medium", timeStyle: "short" } as const;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * The organizers' internal thread on one registration or one registration
 * team: Markdown notes, oldest first, each with up to five private files.
 *
 * Writing needs the target's `update` grant; a note's body and its files are
 * its author's to change, while `delete` lets a moderator remove anyone's. The
 * server enforces all of it -- these flags only decide which controls show.
 */
export function RegistrationNotesPanel({
  tournamentId,
  target,
  canWrite,
  canModerate
}: Readonly<{
  tournamentId: number;
  target: RegistrationNoteTarget;
  /** `<resource>.update`: add notes. */
  canWrite: boolean;
  /** `<resource>.delete`: remove other people's notes and files. */
  canModerate: boolean;
}>) {
  const t = useTranslations("registrationNotes");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const currentUserId = useAuthProfile().user?.id ?? null;
  const [draft, setDraft] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [editing, setEditing] = useState<{ id: number; body: string } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RegistrationNote | null>(null);

  const isTeam = "teamId" in target;
  const targetId = isTeam ? target.teamId : target.registrationId;
  const notesKey = tournamentQueryKeys.registrationNotes(tournamentId, isTeam ? "team" : "registration", targetId);

  const notesQuery = useQuery({
    queryKey: notesKey,
    queryFn: () => registrationNoteService.list(tournamentId, target)
  });

  // Every write ends here: the thread and the list badges share one prefix.
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.registrationNotesAll(tournamentId) });

  const createMutation = useMutation({
    mutationFn: async () => {
      const note = await registrationNoteService.create(tournamentId, target, draft.trim());
      // Sequential: a failed file must not take the already-saved note down with it.
      for (const file of files) await registrationNoteService.uploadAttachment(tournamentId, note.id, file);
    },
    onSuccess: () => {
      setDraft("");
      setFiles([]);
    },
    onSettled: refresh
  });
  const updateMutation = useMutation({
    mutationFn: (input: { id: number; body: string }) =>
      registrationNoteService.update(tournamentId, input.id, input.body.trim()),
    onSuccess: () => setEditing(null),
    onSettled: refresh
  });
  const deleteMutation = useMutation({
    mutationFn: (noteId: number) => registrationNoteService.remove(tournamentId, noteId),
    onSuccess: () => setPendingDelete(null),
    onSettled: refresh
  });
  const attachMutation = useMutation({
    mutationFn: (input: { noteId: number; file: File }) =>
      registrationNoteService.uploadAttachment(tournamentId, input.noteId, input.file),
    onSettled: refresh
  });
  const removeAttachmentMutation = useMutation({
    mutationFn: (input: { noteId: number; attachmentId: number }) =>
      registrationNoteService.removeAttachment(tournamentId, input.noteId, input.attachmentId),
    onSettled: refresh
  });

  const busy =
    createMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending ||
    attachMutation.isPending ||
    removeAttachmentMutation.isPending;

  /** The client-side half of the server's caps, so a bad pick never starts an upload. */
  function acceptFiles(picked: File[], room: number): File[] {
    const tooBig = picked.filter((file) => file.size > NOTE_ATTACHMENT_MAX_BYTES);
    if (tooBig.length > 0) notify.error(t("fileTooLarge", { name: tooBig[0].name }));
    const fitting = picked.filter((file) => file.size <= NOTE_ATTACHMENT_MAX_BYTES);
    if (fitting.length > room) notify.error(t("tooManyFiles", { max: NOTE_ATTACHMENTS_PER_NOTE }));
    return fitting.slice(0, Math.max(room, 0));
  }

  async function openAttachment(note: RegistrationNote, attachment: RegistrationNoteAttachment) {
    // Opened before the await: a window opened after it is a popup the browser blocks.
    const tab = window.open("about:blank", "_blank");
    try {
      const url = await registrationNoteService.attachmentUrl(tournamentId, note.id, attachment.id);
      if (tab) {
        tab.opener = null;
        tab.location.href = url;
      } else {
        window.location.assign(url);
      }
    } catch {
      tab?.close();
      notify.error(t("openFailed"));
    }
  }

  const notes = notesQuery.data ?? [];

  return (
    <section className="space-y-3">
      <h3 className={eyebrowClass("muted")}>{t("title")}</h3>

      {notesQuery.isLoading ? (
        <Skeleton className="h-16 w-full rounded-md" />
      ) : notesQuery.isError ? (
        <p className="text-xs text-destructive">{t("loadFailed")}</p>
      ) : notes.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("empty")}</p>
      ) : (
        <ul className="space-y-3">
          {notes.map((note) => {
            const mine = currentUserId != null && note.author_id === currentUserId;
            const mayEdit = mine && canWrite;
            const mayDelete = (mine && canWrite) || canModerate;
            return (
              <li key={note.id} className="space-y-2 rounded-md border px-3 py-2">
                <div className="flex items-start justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    <span className="font-medium text-foreground">{note.author_username ?? t("deletedUser")}</span>
                    {" · "}
                    {format.dateTime(new Date(note.created_at), STAMP)}
                    {note.edited_at ? ` · ${t("edited")}` : null}
                  </span>
                  <span className="flex shrink-0 gap-0.5">
                    {mayEdit && note.attachments.length < NOTE_ATTACHMENTS_PER_NOTE ? (
                      <FileButton
                        variant="ghost"
                        size="icon"
                        className="size-6"
                        aria-label={t("attach")}
                        title={t("attach")}
                        accept={NOTE_ATTACHMENT_ACCEPT}
                        disabled={busy}
                        onFiles={(picked) => {
                          const [file] = acceptFiles(picked, NOTE_ATTACHMENTS_PER_NOTE - note.attachments.length);
                          if (file) attachMutation.mutate({ noteId: note.id, file });
                        }}
                      >
                        <Paperclip className="size-3.5" aria-hidden />
                      </FileButton>
                    ) : null}
                    {mayEdit ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-6"
                        aria-label={t("edit")}
                        title={t("edit")}
                        disabled={busy}
                        onClick={() => setEditing({ id: note.id, body: note.body })}
                      >
                        <Pencil className="size-3.5" aria-hidden />
                      </Button>
                    ) : null}
                    {mayDelete ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-6"
                        aria-label={t("delete")}
                        title={t("delete")}
                        disabled={busy}
                        onClick={() => setPendingDelete(note)}
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                      </Button>
                    ) : null}
                  </span>
                </div>

                {editing?.id === note.id ? (
                  <div className="space-y-2">
                    <Textarea
                      aria-label={t("edit")}
                      rows={4}
                      value={editing.body}
                      maxLength={20000}
                      onChange={(event) => setEditing({ id: note.id, body: event.target.value })}
                    />
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy || editing.body.trim() === ""}
                        onClick={() => updateMutation.mutate(editing)}
                      >
                        {t("save")}
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>
                        {t("cancel")}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <Markdown source={note.body} className="space-y-2 text-sm text-foreground" />
                )}

                {note.attachments.length > 0 ? (
                  <ul className="space-y-1">
                    {note.attachments.map((attachment) => (
                      <li key={attachment.id} className="flex items-center gap-1.5 text-xs">
                        <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        <Button
                          type="button"
                          variant="link"
                          className="h-auto min-w-0 justify-start truncate p-0 text-xs font-normal text-foreground"
                          title={attachment.filename}
                          onClick={() => void openAttachment(note, attachment)}
                        >
                          <span className="truncate">{attachment.filename}</span>
                        </Button>
                        <span className="shrink-0 text-muted-foreground">{formatSize(attachment.size_bytes)}</span>
                        {mayDelete ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="ml-auto size-5"
                            aria-label={t("removeFile", { name: attachment.filename })}
                            disabled={busy}
                            onClick={() =>
                              removeAttachmentMutation.mutate({ noteId: note.id, attachmentId: attachment.id })
                            }
                          >
                            <X className="size-3" aria-hidden />
                          </Button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {canWrite ? (
        <div className="space-y-2">
          <Textarea
            aria-label={t("newNote")}
            placeholder={t("placeholder")}
            rows={3}
            value={draft}
            maxLength={20000}
            disabled={createMutation.isPending}
            onChange={(event) => setDraft(event.target.value)}
          />
          {files.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5">
              {files.map((file, index) => (
                <li
                  key={`${file.name}-${index}`}
                  className="flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs"
                >
                  <span className="max-w-40 truncate">{file.name}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-4"
                    aria-label={t("removeFile", { name: file.name })}
                    onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                  >
                    <X className="size-3" aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="flex items-center gap-2">
            <FileButton
              variant="outline"
              size="sm"
              multiple
              accept={NOTE_ATTACHMENT_ACCEPT}
              disabled={createMutation.isPending || files.length >= NOTE_ATTACHMENTS_PER_NOTE}
              onFiles={(picked) =>
                setFiles((current) => [
                  ...current,
                  ...acceptFiles(picked, NOTE_ATTACHMENTS_PER_NOTE - current.length)
                ])
              }
            >
              <Paperclip className="size-3.5" aria-hidden />
              {t("addFiles")}
            </FileButton>
            <Button
              type="button"
              size="sm"
              className="ml-auto"
              disabled={createMutation.isPending || draft.trim() === ""}
              onClick={() => createMutation.mutate()}
            >
              {t("add")}
            </Button>
          </div>
          <p className="text-caption text-muted-foreground">{t("hint")}</p>
        </div>
      ) : null}

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => (open ? undefined : setPendingDelete(null))}
        intent={{
          title: t("deleteTitle"),
          description: t("deleteDescription"),
          confirmLabel: t("delete"),
          tone: "danger"
        }}
        pending={deleteMutation.isPending}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </section>
  );
}
