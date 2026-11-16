"use client";

import { useEffect, useState, type ClipboardEvent, type DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Maximize2, Paperclip, Pencil, Plus, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Markdown } from "@/components/Markdown";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { isImageAttachment, NoteImageThumb, NoteImageViewer } from "@/components/registration/NoteImages";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import Image from "@/components/ui/image";
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

/** A picked image's local preview until the upload makes it a stored file. */
function DraftImage({ file }: Readonly<{ file: File }>) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const reader = new FileReader();
    reader.onload = () => setUrl(String(reader.result));
    reader.readAsDataURL(file);
    return () => reader.abort();
  }, [file]);
  return url ? <Image src={url} alt="" width={24} height={24} unoptimized className="size-6 shrink-0 rounded-sm object-cover" /> : null;
}

/**
 * The organizers' internal thread on one registration or one registration
 * team: Markdown notes, oldest first, each with up to five private files.
 *
 * Writing needs the target's `update` grant; a note's body and its files are
 * its author's to change, while `delete` lets a moderator remove anyone's. The
 * server enforces all of it -- these flags only decide which controls show.
 *
 * Images show as thumbnails; a screenshot can be pasted or files dropped onto
 * the editor. "Expand" opens the same thread `wide`, in a sheet with the full
 * Markdown editor.
 */
export function RegistrationNotesPanel({
  tournamentId,
  target,
  canWrite,
  canModerate,
  subject,
  wide = false
}: Readonly<{
  tournamentId: number;
  target: RegistrationNoteTarget;
  /** `<resource>.update`: add notes. */
  canWrite: boolean;
  /** `<resource>.delete`: remove other people's notes and files. */
  canModerate: boolean;
  /** Whose notes, for the expanded sheet's heading: a player or a team. */
  subject?: string;
  /** The expanded thread: Markdown editor, composer always open, no heading of its own (the sheet has it). */
  wide?: boolean;
}>) {
  const t = useTranslations("registrationNotes");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const currentUserId = useAuthProfile().user?.id ?? null;
  const [draft, setDraft] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  // The composer (textarea, files, hint) stays folded behind one button until
  // asked for: in a panel no taller than its table it otherwise outweighs the thread.
  // The wide sheet exists to write, so there it is always open.
  const [composing, setComposing] = useState(wide);
  const [editing, setEditing] = useState<{ id: number; body: string } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RegistrationNote | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [viewing, setViewing] = useState<{ noteId: number; index: number } | null>(null);

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
      setComposing(wide);
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

  function addDraftFiles(picked: File[]) {
    setFiles([...files, ...acceptFiles(picked, NOTE_ATTACHMENTS_PER_NOTE - files.length)]);
  }

  async function attachToNote(note: RegistrationNote, picked: File[]) {
    // Sequential, like the composer's upload; a failure stops the rest, and the mutation cache has already toasted it.
    for (const file of acceptFiles(picked, NOTE_ATTACHMENTS_PER_NOTE - note.attachments.length)) {
      await attachMutation.mutateAsync({ noteId: note.id, file }).catch(() => undefined);
    }
  }

  /** Pasted screenshots and dropped files go to `take`; a paste of plain text stays an ordinary paste. */
  const fileInputProps = (take: (picked: File[]) => void) => ({
    onPaste: (event: ClipboardEvent<HTMLElement>) => {
      const picked = Array.from(event.clipboardData.files);
      if (picked.length === 0) return;
      event.preventDefault();
      take(picked);
    },
    onDragOver: (event: DragEvent<HTMLElement>) => {
      if (event.dataTransfer.types.includes("Files")) event.preventDefault();
    },
    onDrop: (event: DragEvent<HTMLElement>) => {
      const picked = Array.from(event.dataTransfer.files);
      if (picked.length === 0) return;
      event.preventDefault();
      take(picked);
    }
  });

  /** The body field: a plain textarea in the narrow panel, the toolbar editor in the wide sheet. */
  function bodyField(props: { label: string; value: string; onChange: (value: string) => void; rows: number; autoFocus?: boolean; disabled?: boolean }) {
    return wide ? (
      <MarkdownEditor label={props.label} value={props.value} onChange={props.onChange} maxLength={20000} placeholder={t("placeholder")} />
    ) : (
      <Textarea
        aria-label={props.label}
        placeholder={t("placeholder")}
        rows={props.rows}
        autoFocus={props.autoFocus}
        value={props.value}
        maxLength={20000}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.target.value)}
      />
    );
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
  const viewedImages = notes.find((note) => note.id === viewing?.noteId)?.attachments.filter(isImageAttachment) ?? [];

  return (
    <section className="space-y-3">
      {wide ? null : (
        <div className="flex items-center justify-between gap-2">
          <h3 className={eyebrowClass("muted")}>
            {t("title")}
            {notesQuery.data ? ` · ${notes.length}` : null}
          </h3>
          <span className="flex items-center gap-0.5">
            {canWrite && !composing ? (
              <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 px-2" onClick={() => setComposing(true)}>
                <Plus className="size-3.5" aria-hidden />
                {t("newNote")}
              </Button>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label={t("expand")}
              title={t("expand")}
              onClick={() => setExpanded(true)}
            >
              <Maximize2 className="size-3.5" aria-hidden />
            </Button>
          </span>
        </div>
      )}

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
                  <div className="space-y-2" {...fileInputProps((picked) => void attachToNote(note, picked))}>
                    {bodyField({
                      label: t("edit"),
                      value: editing.body,
                      onChange: (body) => setEditing({ id: note.id, body }),
                      rows: 4
                    })}
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

                {note.attachments.some(isImageAttachment) ? (
                  <ul className="flex flex-wrap gap-2">
                    {note.attachments.filter(isImageAttachment).map((attachment, index) => (
                      <li key={attachment.id} className="relative">
                        <NoteImageThumb
                          tournamentId={tournamentId}
                          noteId={note.id}
                          attachment={attachment}
                          onOpen={() => setViewing({ noteId: note.id, index })}
                        />
                        {mayDelete ? (
                          <Button
                            type="button"
                            variant="secondary"
                            size="icon"
                            className="absolute -top-1.5 -right-1.5 size-5 rounded-full border border-border"
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

                {note.attachments.some((attachment) => !isImageAttachment(attachment)) ? (
                  <ul className="space-y-1">
                    {note.attachments
                      .filter((attachment) => !isImageAttachment(attachment))
                      .map((attachment) => (
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

      {canWrite && composing ? (
        <div className="space-y-2" {...fileInputProps(addDraftFiles)}>
          {bodyField({
            label: t("newNote"),
            value: draft,
            onChange: setDraft,
            rows: 3,
            autoFocus: true,
            disabled: createMutation.isPending
          })}
          {files.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5">
              {files.map((file, index) => (
                <li
                  key={`${file.name}-${index}`}
                  className="flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs"
                >
                  {file.type.startsWith("image/") ? <DraftImage file={file} /> : null}
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
              onFiles={addDraftFiles}
            >
              <Paperclip className="size-3.5" aria-hidden />
              {t("addFiles")}
            </FileButton>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto"
              disabled={createMutation.isPending}
              onClick={() => {
                setDraft("");
                setFiles([]);
                setComposing(wide);
              }}
            >
              {t("cancel")}
            </Button>
            <Button
              type="button"
              size="sm"
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

      {viewing && viewing.index < viewedImages.length ? (
        <NoteImageViewer
          tournamentId={tournamentId}
          noteId={viewing.noteId}
          images={viewedImages}
          index={viewing.index}
          onIndexChange={(index) => setViewing({ noteId: viewing.noteId, index })}
          onClose={() => setViewing(null)}
        />
      ) : null}

      {wide ? null : (
        <Sheet open={expanded} onOpenChange={setExpanded}>
          <SheetContent variant="panel" className="w-full sm:max-w-3xl">
            <SheetHeader variant="panel">
              <SheetTitle>
                {t("title")}
                {notesQuery.data ? ` · ${notes.length}` : null}
              </SheetTitle>
              <SheetDescription>{subject ?? t("hint")}</SheetDescription>
            </SheetHeader>
            {/* `overscroll-contain` keeps a flick at the end of the thread from scrolling the page under the sheet. */}
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
              <RegistrationNotesPanel
                tournamentId={tournamentId}
                target={target}
                canWrite={canWrite}
                canModerate={canModerate}
                wide
              />
            </div>
          </SheetContent>
        </Sheet>
      )}
    </section>
  );
}
