"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, ImageOff, X } from "lucide-react";
import { useTranslations } from "next-intl";

import Image from "@/components/ui/image";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle
} from "@craazzzyyfoxx/admin-kit/ui/dialog";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationNoteService from "@/services/registration-note.service";
import type { RegistrationNoteAttachment } from "@/types/registration-note.types";

export const isImageAttachment = (attachment: RegistrationNoteAttachment) =>
  attachment.content_type.startsWith("image/");

/** The server signs a file link for five minutes (`_URL_TTL_SECONDS`): a minute short of that it is fetched anew. */
const URL_STALE_MS = 4 * 60 * 1000;

function useAttachmentUrl(tournamentId: number, noteId: number, attachmentId: number) {
  return useQuery({
    queryKey: tournamentQueryKeys.registrationNoteFileUrl(tournamentId, attachmentId),
    queryFn: () => registrationNoteService.attachmentUrl(tournamentId, noteId, attachmentId),
    staleTime: URL_STALE_MS,
    gcTime: URL_STALE_MS,
    // The thumbnail itself shows the failure; a toast per broken image would only repeat it.
    meta: { suppressErrorToast: true }
  });
}

/** One image of a note as a square thumbnail; a click opens it in `NoteImageViewer`. */
export function NoteImageThumb({
  tournamentId,
  noteId,
  attachment,
  onOpen
}: Readonly<{
  tournamentId: number;
  noteId: number;
  attachment: RegistrationNoteAttachment;
  onOpen: () => void;
}>) {
  const t = useTranslations("registrationNotes");
  const url = useAttachmentUrl(tournamentId, noteId, attachment.id);
  return (
    <Button
      type="button"
      variant="ghost"
      onClick={onOpen}
      title={attachment.filename}
      aria-label={t("openImage", { name: attachment.filename })}
      className="relative size-20 overflow-hidden rounded-md border border-border bg-muted p-0"
    >
      {url.data ? (
        <Image src={url.data} alt="" fill sizes="80px" unoptimized className="object-cover" />
      ) : url.isError ? (
        <ImageOff className="size-4 text-muted-foreground" aria-hidden />
      ) : (
        <Skeleton className="size-full rounded-none" />
      )}
    </Button>
  );
}

/** A note's images full size, one at a time: arrows (buttons or ← →) step through them. */
export function NoteImageViewer({
  tournamentId,
  noteId,
  images,
  index,
  onIndexChange,
  onClose
}: Readonly<{
  tournamentId: number;
  noteId: number;
  images: readonly RegistrationNoteAttachment[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}>) {
  const t = useTranslations("registrationNotes");
  const current = images[index];
  const url = useAttachmentUrl(tournamentId, noteId, current.id);
  const step = (delta: number) => onIndexChange((index + delta + images.length) % images.length);
  const many = images.length > 1;

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent
        showCloseButton={false}
        className="gap-3 p-3 sm:max-w-5xl"
        onKeyDown={(event) => {
          if (!many) return;
          if (event.key === "ArrowLeft") step(-1);
          if (event.key === "ArrowRight") step(1);
        }}
      >
        <div className="flex items-center gap-2">
          <DialogTitle className="min-w-0 flex-1 truncate text-sm font-medium">
            {current.filename}
          </DialogTitle>
          <DialogDescription className="shrink-0 text-xs text-muted-foreground">
            {many ? `${index + 1} / ${images.length}` : null}
          </DialogDescription>
          {url.data ? (
            <Button
              asChild
              variant="ghost"
              size="icon"
              className="size-7"
              title={t("openOriginal")}
            >
              <a
                href={url.data}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("openOriginal")}
              >
                <ExternalLink className="size-4" aria-hidden />
              </a>
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label={t("close")}
            onClick={onClose}
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>
        <div className="relative h-[75vh] w-full">
          {url.data ? (
            <Image
              src={url.data}
              alt={current.filename}
              fill
              sizes="(min-width: 640px) 64rem, 100vw"
              unoptimized
              className="object-contain"
            />
          ) : url.isError ? (
            <p className="flex h-full items-center justify-center text-sm text-muted-foreground">
              {t("openFailed")}
            </p>
          ) : (
            <Skeleton className="size-full" />
          )}
          {many ? (
            <>
              <Button
                type="button"
                variant="secondary"
                size="icon"
                className="absolute top-1/2 left-2 -translate-y-1/2"
                aria-label={t("previousImage")}
                onClick={() => step(-1)}
              >
                <ChevronLeft className="size-4" aria-hidden />
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="icon"
                className="absolute top-1/2 right-2 -translate-y-1/2"
                aria-label={t("nextImage")}
                onClick={() => step(1)}
              >
                <ChevronRight className="size-4" aria-hidden />
              </Button>
            </>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
