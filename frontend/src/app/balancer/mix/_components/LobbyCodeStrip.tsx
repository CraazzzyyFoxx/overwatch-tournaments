"use client";

import { useTranslations } from "next-intl";
import { Copy, KeyRound } from "lucide-react";

import { InlineEditText } from "@/components/kit/InlineEditText";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";

function CopyLobbyCodeButton({ code }: Readonly<{ code: string }>) {
  const t = useTranslations("mixes.room");

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={t("lobbyCodeCopy")}
      onClick={() =>
        navigator.clipboard
          .writeText(code)
          .then(() => notify.success(t("lobbyCodeCopied")))
          .catch(() => notify.error(t("lobbyCodeCopyFailed")))
      }
    >
      <Copy aria-hidden="true" />
    </Button>
  );
}

/** The stored code with a copy button: what a player taps instead of asking in chat. */
export function LobbyCode({ code, className }: Readonly<{ code: string; className?: string }>) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1", className)}>
      <span className="break-all font-mono font-bold text-[color:var(--aqt-fg)]">{code}</span>
      <CopyLobbyCodeButton code={code} />
    </span>
  );
}

/**
 * The lobby's in-game join code (`lobby.lobby_code`): a host edits it inline, every viewer copies it from here. Kept
 * across matches and writable while one is live, so it is the host's `canWrite`, not the desk's `reshape`. A reader
 * sees nothing while there is no code; the screenshot shows the code alone, without the editor or the copy button.
 */
export function LobbyCodeStrip({
  lobbyCode,
  canWrite,
  capturing = false,
  className,
  onLobbyCodeChange
}: Readonly<{
  lobbyCode: string | null;
  canWrite: boolean;
  capturing?: boolean;
  className?: string;
  /** Trimmed; `null` clears. A rejected promise keeps the editor open with the draft. */
  onLobbyCodeChange: (lobbyCode: string | null) => Promise<unknown>;
}>) {
  const t = useTranslations("mixes.room");

  const editing = canWrite && !capturing;
  if (!editing && lobbyCode == null) return null;

  return (
    <div
      className={cn("flex flex-wrap items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3", className)}
    >
      <span className="flex h-10 w-[53px] shrink-0 items-center justify-center rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)]">
        <KeyRound className="size-4 text-[color:var(--aqt-fg-faint)]" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <Eyebrow className="mr-2">{t("lobbyCodeLabel")}</Eyebrow>
        {editing ? (
          <div className="mt-1 flex min-w-0 items-center gap-1">
            <InlineEditText
              value={lobbyCode ?? ""}
              label={t("lobbyCodeLabel")}
              required={false}
              placeholder={t("lobbyCodePlaceholder")}
              maxLength={64}
              textClassName="font-mono text-ui font-bold text-[color:var(--aqt-fg)]"
              inputClassName="w-56 font-mono"
              onSave={(next) => onLobbyCodeChange(next || null)}
            />
            {lobbyCode != null ? <CopyLobbyCodeButton code={lobbyCode} /> : null}
          </div>
        ) : lobbyCode == null ? null : capturing ? (
          <span className="break-all font-mono text-ui font-bold text-[color:var(--aqt-fg)]">{lobbyCode}</span>
        ) : (
          <LobbyCode code={lobbyCode} className="text-ui" />
        )}
      </div>
    </div>
  );
}
