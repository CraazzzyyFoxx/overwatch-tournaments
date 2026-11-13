"use client";

import { useMemo, type CSSProperties } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { commands, type ICommand } from "@uiw/react-md-editor";

import { Markdown, MARKDOWN_REMARK_PLUGINS } from "@/components/Markdown";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { cn } from "@/lib/utils";

import styles from "./MarkdownEditor.module.css";

/**
 * `@uiw/react-md-editor` renders a `textarea` plus a toolbar and reads `window`
 * on mount, so it is client-only and loaded on demand: the editor's JS never
 * reaches a viewer who does not open the page that edits a document.
 *
 * `/nohighlight` is the same editor without `rehype-prism-plus` — the source
 * pane's syntax colouring. The preview is rendered by OUR component (see
 * `components.preview` below), so the highlighter would only be dead weight.
 */
const MDEditor = dynamic(() => import("@uiw/react-md-editor/nohighlight"), {
  ssr: false,
  loading: () => <Skeleton className="h-72 w-full rounded-lg" />
});

/**
 * The editor's stylesheet consumes GitHub's colour variables and falls back to
 * hard-coded greys when they are undefined. Mapping them onto our tokens here —
 * rather than importing the vendor's palette — is what makes the editor follow
 * the workspace theme, light and dark, with no `data-color-mode` juggling.
 */
const EDITOR_THEME = {
  "--color-canvas-default": "hsl(var(--background))",
  "--color-fg-default": "hsl(var(--foreground))",
  "--color-border-default": "hsl(var(--border))",
  "--color-accent-fg": "hsl(var(--primary))",
  "--color-danger-fg": "hsl(var(--destructive))",
  "--color-neutral-muted": "hsl(var(--muted))",
  // The vendor default is Helvetica; inherit the app's face instead.
  "--md-editor-font-family": "inherit"
} as CSSProperties;

type MarkdownEditorProps = {
  /** Markdown source. Controlled: `onChange` is the only way it moves. */
  value: string;
  onChange: (value: string) => void;
  /**
   * Read-only mode renders the document instead of a dead editor: a viewer
   * without the update permission gets something readable rather than a toolbar
   * whose every button is a no-op.
   */
  readOnly?: boolean;
  maxLength?: number;
  placeholder?: string;
  /** Labels the source `textarea`, which has no visible label of its own. */
  label: string;
  className?: string;
};

/** The three list buttons share `keyCommand: "list"` and differ by name. */
const LIST_MESSAGE_KEYS: Record<string, string> = {
  "ordered-list": "orderedList",
  "checked-list": "checkedList"
};

function toolbarMessageKey(command: ICommand): string | undefined {
  if (command.keyCommand === "list") return LIST_MESSAGE_KEYS[command.name ?? ""] ?? "unorderedList";
  // the heading dropdown
  if (command.keyCommand === "group") return "title";
  return command.keyCommand;
}

export function MarkdownEditor({
  value,
  onChange,
  readOnly = false,
  maxLength,
  placeholder,
  label,
  className
}: Readonly<MarkdownEditorProps>) {
  const t = useTranslations("adminBracket.markdownEditor");
  const toolbarCommands = useMemo(
    () =>
      commands.getCommands().map((command) => {
        const key = toolbarMessageKey(command);
        if (!key || key === "divider") return command;
        const label = t(`toolbar.${key}` as never);
        return {
          ...command,
          buttonProps: { ...command.buttonProps, title: label, "aria-label": label }
        };
      }),
    [t]
  );
  const toolbarExtraCommands = useMemo(
    () =>
      commands.getExtraCommands().map((command) => {
        const key = command.keyCommand === "preview" ? command.name : command.keyCommand;
        if (!key || key === "divider") return command;
        const label = t(`toolbar.${key}` as never);
        return {
          ...command,
          buttonProps: { ...command.buttonProps, title: label, "aria-label": label }
        };
      }),
    [t]
  );
  if (readOnly) {
    return (
      <div
        className={cn("rounded-lg border border-border bg-muted/20 p-4", className)}
        aria-label={label}
      >
        {value.trim() ? (
          <Markdown source={value} />
        ) : (
          <p className="text-caption text-muted-foreground">{t("nothingPublished")}</p>
        )}
      </div>
    );
  }

  return (
    <div className={cn(styles.editor, "overflow-hidden rounded-lg", className)} style={EDITOR_THEME}>
      <MDEditor
        value={value}
        onChange={(next) => onChange(next ?? "")}
        // Starts on the source pane; the toolbar's own buttons switch to the
        // split and preview modes, so the default does not have to guess which
        // one a given document needs.
        preview="edit"
        commands={toolbarCommands}
        extraCommands={toolbarExtraCommands}
        height={420}
        textareaProps={{ "aria-label": label, placeholder, maxLength }}
        // One markdown pipeline for the whole feature: the preview is the public
        // page's renderer, with the same plugins and the same component map.
        // Anything else makes "Preview" a claim the published page can break.
        previewOptions={{ remarkPlugins: MARKDOWN_REMARK_PLUGINS }}
        components={{ preview: (source) => <Markdown source={source} /> }}
      />
    </div>
  );
}
