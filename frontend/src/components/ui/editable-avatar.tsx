"use client";

import { useState } from "react";
import { Camera, Pencil, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn, initials } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useFilePicker } from "@/components/ui/file-button";
import Image from "@/components/ui/image";
import { Spinner } from "@/components/ui/spinner";

const DEFAULT_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";

export interface EditableAvatarProps {
  /** Current image URL — or a local object-URL preview in deferred (form) flows. */
  src?: string | null;
  /** Used to derive the initials fallback when there is no image. */
  name?: string | null;
  /** Pixel size of the square/circle — the height when `width` is given. Default 80. */
  size?: number;
  /**
   * Pixel width, when the frame is not square — a 3:1 tournament banner is the
   * same editor as a square icon, only wider. Defaults to `size`. Every layer
   * inside is `absolute inset-0`, so the frame's own box is the only place the
   * two axes need to be told apart.
   */
  width?: number;
  /** "circle" for user/player avatars, "rounded" for workspace icons. Default "circle". */
  shape?: "circle" | "rounded";
  /** When false, renders read-only (no overlay, dropzone, or delete). Default true. */
  editable?: boolean;
  /** Show a spinner overlay and block interaction (upload/delete pending). */
  busy?: boolean;
  /** Called with a validated file chosen via click or drag-and-drop. */
  onSelectFile: (file: File) => void;
  /** When provided and an image is present, shows a small delete icon inside the avatar. */
  onDelete?: () => void;
  /** Accepted MIME types for the picker + drop validation. */
  accept?: string;
  /** Optional client-side max size; oversized files are rejected via onError. */
  maxSizeBytes?: number;
  /** Reports a validation message (wrong type / too large). */
  onError?: (message: string) => void;
  /** Disable all interaction without changing the read-only look. */
  disabled?: boolean;
  /**
   * Localized copy for the accessible names, the hover overlay and the two
   * client-side validation messages. Every field is optional and falls back to
   * the English default, so callers that have not been localized keep working.
   */
  labels?: {
    /** Accessible name of the picker surface. */
    change?: string;
    /** Overlay word when there is no image yet. */
    upload?: string;
    /** Overlay word when replacing an existing image. */
    edit?: string;
    /** Overlay word while a file is dragged over the frame. */
    drop?: string;
    /** Accessible name and tooltip of the delete button. */
    remove?: string;
    /** Reported through `onError` for a disallowed MIME type. */
    unsupportedType?: string;
    /** Reported through `onError` for an oversized file. Already formatted. */
    tooLarge?: string;
  };
  className?: string;
}

/**
 * A controlled avatar/icon editor: click or drag-and-drop an image to replace it,
 * with a small delete icon inside the frame. Works for both immediate-upload flows
 * (call an upload mutation in `onSelectFile`, pass `busy`) and deferred form flows
 * (stage the file + a local preview in `onSelectFile`, pass the preview as `src`).
 */
export function EditableAvatar({
  src,
  name,
  size = 80,
  width,
  shape = "circle",
  editable = true,
  busy = false,
  onSelectFile,
  onDelete,
  accept = DEFAULT_ACCEPT,
  maxSizeBytes,
  onError,
  disabled = false,
  labels,
  className
}: Readonly<EditableAvatarProps>) {
  const t = useTranslations("kit.avatar");
  const [dragging, setDragging] = useState(false);
  // A stored avatar whose file no longer loads draws the initials, not an empty frame.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const imageSrc = src && src !== failedSrc ? src : null;
  const interactive = editable && !disabled && !busy;
  const radius = shape === "circle" ? "rounded-full" : "rounded-md";

  const accepts = (type: string) =>
    accept
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean)
      .includes(type);

  const handleFile = (file: File | undefined | null) => {
    if (!file) return;
    if (!accepts(file.type)) {
      onError?.(labels?.unsupportedType ?? t("unsupportedType"));
      return;
    }
    if (maxSizeBytes && file.size > maxSizeBytes) {
      onError?.(
        labels?.tooLarge ?? t("tooLarge", { max: Math.round(maxSizeBytes / (1024 * 1024)) })
      );
      return;
    }
    onSelectFile(file);
  };
  const picker = useFilePicker({
    accept,
    disabled: !interactive,
    onFiles: ([file]) => handleFile(file)
  });

  const frameClass = cn(
    "absolute inset-0 block overflow-hidden border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] p-0",
    radius
  );
  // Spans only: this sits inside a `<button>` when editable.
  const content = (
    <>
      {imageSrc ? (
        <Image
          src={imageSrc}
          alt={name ?? t("alt")}
          width={width ?? size}
          height={size}
          className="h-full w-full select-none object-cover"
          onError={() => setFailedSrc(imageSrc)}
        />
      ) : (
        <span
          className={cn(
            "flex h-full w-full items-center justify-center font-medium text-[color:var(--aqt-fg-muted)]",
            size >= 72 ? "text-title" : size >= 56 ? "text-heading" : "text-label"
          )}
        >
          {initials(name)}
        </span>
      )}

      {/* Edit affordance — on hover/focus, or while dragging a file over the frame */}
      {interactive && (
        <span
          className={cn(
            "absolute inset-0 flex flex-col items-center justify-center gap-1 bg-[color:color-mix(in_srgb,var(--aqt-bg)_70%,transparent)] text-[color:var(--aqt-fg)] transition-opacity",
            dragging
              ? "opacity-100"
              : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
          )}
        >
          {src ? (
            <Pencil className="size-4" aria-hidden />
          ) : (
            <Camera className="size-4" aria-hidden />
          )}
          <span className="text-label font-semibold uppercase tracking-label">
            {dragging
              ? (labels?.drop ?? t("drop"))
              : src
                ? (labels?.edit ?? t("edit"))
                : (labels?.upload ?? t("upload"))}
          </span>
        </span>
      )}

      {/* Busy overlay */}
      {busy && (
        <span className="absolute inset-0 flex items-center justify-center bg-[color:color-mix(in_srgb,var(--aqt-bg)_70%,transparent)] text-[color:var(--aqt-fg)]">
          <Spinner className="size-5" />
        </span>
      )}
    </>
  );

  return (
    <div
      className={cn("group relative shrink-0", className)}
      style={{ width: width ?? size, height: size }}
      aria-busy={busy || undefined}
    >
      {editable ? (
        <>
          {picker.input}
          <button
            type="button"
            disabled={!interactive}
            aria-label={labels?.change ?? t("change")}
            onClick={picker.open}
            onDragOver={(e) => {
              if (!interactive) return;
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              if (interactive) handleFile(e.dataTransfer.files?.[0]);
            }}
            className={cn(
              frameClass,
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              interactive && "cursor-pointer",
              dragging && "ring-2 ring-ring ring-offset-2 ring-offset-background"
            )}
          >
            {content}
          </button>
        </>
      ) : (
        <div className={frameClass}>{content}</div>
      )}

      {/* Small delete icon inside the frame */}
      {interactive && src && onDelete && (
        <Button
          variant="ghost-destructive"
          size="icon-xs"
          onClick={onDelete}
          className={cn(
            "absolute z-10 rounded-full bg-[color:var(--aqt-card-2)]",
            shape === "circle" ? "bottom-1 right-1" : "bottom-0.5 right-0.5"
          )}
          aria-label={labels?.remove ?? t("remove")}
          title={labels?.remove ?? t("remove")}
        >
          <Trash2 aria-hidden />
        </Button>
      )}
    </div>
  );
}
