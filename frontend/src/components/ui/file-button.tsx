"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";

interface FilePickerOptions {
  /** The `accept` list, e.g. `"application/json,.json"`. */
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  /** The picked files; never called with an empty list. */
  onFiles: (files: File[]) => void;
}

/**
 * The hidden `<input type="file">` behind a picker whose trigger is not a
 * button — a menu item, whose content unmounts as the menu closes, so the input
 * has to live with the page. Render `input` once; call `open()` from the
 * trigger. A button trigger is `FileButton`.
 */
export function useFilePicker({ accept, multiple, disabled, onFiles }: FilePickerOptions) {
  const ref = React.useRef<HTMLInputElement>(null);
  // Stable, so a trigger callback memoised on it stays memoised.
  const open = React.useCallback(() => ref.current?.click(), []);
  const input = (
    <input
      ref={ref}
      type="file"
      accept={accept}
      multiple={multiple}
      disabled={disabled}
      hidden
      onChange={(event) => {
        const files = Array.from(event.target.files ?? []);
        // Picking the same file twice in a row must still fire `change`.
        event.target.value = "";
        if (files.length > 0) onFiles(files);
      }}
    />
  );
  return { input, open };
}

export interface FileButtonProps
  extends
    Omit<React.ComponentPropsWithoutRef<typeof Button>, "type" | "onClick" | "asChild">,
    FilePickerOptions {}

/** A `Button` that opens the system file picker. */
export function FileButton({
  accept,
  multiple,
  disabled,
  onFiles,
  ...props
}: Readonly<FileButtonProps>) {
  const picker = useFilePicker({ accept, multiple, disabled, onFiles });
  return (
    <>
      {picker.input}
      <Button type="button" disabled={disabled} onClick={picker.open} {...props} />
    </>
  );
}
