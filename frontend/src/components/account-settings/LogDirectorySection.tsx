"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { directoryErrorCode, listLogFiles, type LogDirectoryHandle, type LogFileHandle } from "@/lib/logs/browser-directory";
import { useLogDirectory } from "@/lib/logs/use-log-directory";
import { SettingsGroup } from "./SettingsGroup";

export function LogDirectorySection() {
  const t = useTranslations("accountSettings.logDirectory");
  const directory = useLogDirectory();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listing, setListing] = useState<{ handle: LogDirectoryHandle; files: LogFileHandle[] } | null>(null);
  const files = listing?.handle === directory.handle ? listing.files : null;

  async function view(replace: boolean) {
    setBusy(true);
    setError(null);
    try {
      const handle = await (replace ? directory.select() : directory.access());
      if (handle) setListing({ handle, files: await listLogFiles(handle) });
    } catch (cause) {
      setError(t(`errors.${directoryErrorCode(cause)}`));
    } finally {
      setBusy(false);
    }
  }

  async function forget() {
    setBusy(true);
    setError(null);
    try {
      await directory.forget();
      setListing(null);
    } catch (cause) {
      setError(t(`errors.${directoryErrorCode(cause)}`));
    } finally {
      setBusy(false);
    }
  }

  const visibleError = error ?? (directory.error ? t(`errors.${directoryErrorCode(directory.error)}`) : null);

  return (
    <SettingsGroup title={t("title")} description={t("hint")}>
      <p className="break-all text-sm text-[color:var(--aqt-fg)]" role="status">
        {directory.isLoading ? t("loading") : directory.handle?.name ?? t("none")}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={busy || directory.isLoading} onClick={() => void view(true)}>
          {directory.handle ? t("replace") : t("select")}
        </Button>
        <Button type="button" variant="outline" disabled={busy || !directory.handle} onClick={() => void view(false)}>
          {t("refresh")}
        </Button>
        <Button type="button" variant="ghost" disabled={busy || !directory.handle} onClick={() => void forget()}>
          {t("forget")}
        </Button>
      </div>
      <p className="text-caption text-[color:var(--aqt-fg-muted)]" role="status">{busy ? t("scanning") : ""}</p>
      {visibleError ? <p className="text-sm text-destructive" role="alert">{visibleError}</p> : null}
      {files ? (
        files.length ? (
          <ul aria-label={t("files")} className="max-h-48 space-y-1 overflow-y-auto text-sm">
            {files.map((file) => <li key={file.name} className="break-all">{file.name}</li>)}
          </ul>
        ) : <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("empty")}</p>
      ) : null}
    </SettingsGroup>
  );
}
