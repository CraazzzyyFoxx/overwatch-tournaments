"use client";

import { useRef, useState, type DragEvent } from "react";
import { Camera, Loader2, Pencil, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";

const DEFAULT_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";

export interface EditableAvatarProps {
  /** Current image URL — or a local object-URL preview in deferred (form) flows. */
  src?: string | null;
  /** Used to derive the initials fallback when there is no image. */
  name?: string | null;
  /** Pixel size of the square/circle. Default 80. */
  size?: number;
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
  className?: string;
}

function initialsOf(name?: string | null): string {
  if (!name) return "?";
  return (
    name
      .split(/[#\s]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase() ?? "")
      .join("") || "?"
  );
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
  shape = "circle",
  editable = true,
  busy = false,
  onSelectFile,
  onDelete,
  accept = DEFAULT_ACCEPT,
  maxSizeBytes,
  onError,
  disabled = false,
  className,
}: EditableAvatarProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
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
      onError?.("Unsupported file type");
      return;
    }
    if (maxSizeBytes && file.size > maxSizeBytes) {
      onError?.(`File too large (max ${Math.round(maxSizeBytes / (1024 * 1024))} MB)`);
      return;
    }
    onSelectFile(file);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    if (!interactive) return;
    handleFile(e.dataTransfer.files?.[0]);
  };

  return (
    <div className={cn("group relative shrink-0", className)} style={{ width: size, height: size }}>
      {/* Image / fallback + interaction surface */}
      <div
        className={cn(
          "absolute inset-0 overflow-hidden border border-border/60 bg-muted",
          radius,
          interactive && "cursor-pointer",
          dragging && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        )}
        role={interactive ? "button" : undefined}
        tabIndex={interactive ? 0 : undefined}
        aria-label={interactive ? "Change image" : undefined}
        onClick={() => interactive && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (interactive && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          if (!interactive) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={name ?? "avatar"} className="h-full w-full select-none object-cover" />
        ) : (
          <div
            className="flex h-full w-full items-center justify-center font-medium text-muted-foreground"
            style={{ fontSize: Math.max(12, Math.round(size * 0.3)) }}
          >
            {initialsOf(name)}
          </div>
        )}

        {/* Edit affordance — on hover/focus, or while dragging a file over the frame */}
        {interactive && (
          <div
            className={cn(
              "absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/50 text-white transition-opacity",
              dragging ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
            )}
          >
            {src ? <Pencil className="h-4 w-4" /> : <Camera className="h-4 w-4" />}
            <span className="text-[10px] font-medium uppercase tracking-wide">
              {dragging ? "Drop" : src ? "Edit" : "Upload"}
            </span>
          </div>
        )}

        {/* Busy overlay */}
        {busy && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-white">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        )}
      </div>

      {/* Small delete icon inside the frame */}
      {interactive && src && onDelete && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className={cn(
            "absolute z-10 rounded-full border border-border bg-background/90 p-1 text-destructive/80 shadow-sm backdrop-blur-sm transition-colors hover:bg-destructive hover:text-destructive-foreground",
            shape === "circle" ? "bottom-1 right-1" : "bottom-0.5 right-0.5",
          )}
          aria-label="Remove image"
          title="Remove image"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      )}

      {editable && (
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          disabled={!interactive}
          onChange={(e) => {
            handleFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      )}
    </div>
  );
}

export default EditableAvatar;
