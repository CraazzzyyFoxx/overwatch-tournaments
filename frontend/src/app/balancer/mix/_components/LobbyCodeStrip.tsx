"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Copy, KeyRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";

/** The stored code with a copy button: what a player taps instead of asking in chat. */
export function LobbyCode({ code, className }: Readonly<{ code: string; className?: string }>) {
  const t = useTranslations("mixes.room");

  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1", className)}>
      <span className="break-all font-mono font-bold text-[color:var(--aqt-fg)]">{code}</span>
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
    </span>
  );
}

/**
 * The lobby's in-game join code (`lobby.lobby_code`): a host pastes it once, every viewer copies it from here. Kept
 * across matches and writable while one is live, so it is the host's `canWrite`, not the desk's `reshape`. A reader
 * sees nothing while there is no code; the screenshot shows the code alone, without the form or the copy button.
 */
export function LobbyCodeStrip({
  lobbyCode,
  canWrite,
  saving,
  capturing = false,
  className,
  onLobbyCodeChange
}: Readonly<{
  lobbyCode: string | null;
  canWrite: boolean;
  saving: boolean;
  capturing?: boolean;
  className?: string;
  /** Trimmed; `null` clears. */
  onLobbyCodeChange: (lobbyCode: string | null) => void;
}>) {
  const t = useTranslations("mixes.room");
  const [draft, setDraft] = useState(lobbyCode ?? "");
  const [stored, setStored] = useState(lobbyCode);
  // Reset during render when the stored code moves (a save coming back, another host's write).
  if (stored !== lobbyCode) {
    setStored(lobbyCode);
    setDraft(lobbyCode ?? "");
  }

  const editing = canWrite && !capturing;
  if (!editing && lobbyCode == null) return null;
  const trimmed = draft.trim();
  const dirty = trimmed !== (lobbyCode ?? "");

  return (
    <div
      className={cn("flex flex-wrap items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3", className)}
    >
      <span className="flex h-10 w-[53px] shrink-0 items-center justify-center rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)]">
        <KeyRound className="size-4 text-[color:var(--aqt-fg-faint)]" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <Eyebrow>{t("lobbyCodeLabel")}</Eyebrow>
        {editing ? (
          <form
            className="mt-1 flex flex-wrap items-center gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              if (dirty) onLobbyCodeChange(trimmed || null);
            }}
          >
            <Input
              size="sm"
              variant="surface"
              className="w-56 font-mono"
              value={draft}
              maxLength={64}
              placeholder={t("lobbyCodePlaceholder")}
              aria-label={t("lobbyCodeLabel")}
              onChange={(event) => setDraft(event.target.value)}
            />
            <Button type="submit" variant="outline" size="sm" disabled={!dirty || saving}>
              {saving ? <Spinner className="mr-1.5 size-3.5" /> : null}
              {t("lobbyCodeSave")}
            </Button>
            {lobbyCode != null ? <LobbyCode code={lobbyCode} /> : null}
          </form>
        ) : lobbyCode == null ? null : capturing ? (
          <span className="break-all font-mono text-ui font-bold text-[color:var(--aqt-fg)]">{lobbyCode}</span>
        ) : (
          <LobbyCode code={lobbyCode} className="text-ui" />
        )}
      </div>
    </div>
  );
}
