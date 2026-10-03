"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FolderOpen } from "lucide-react";
import { AutoUploadStatus } from "@/components/logs/AutoUploadStatus";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { directoryErrorCode } from "@/lib/logs/browser-directory";
import { useLogDirectory } from "@/lib/logs/use-log-directory";
import { SettingsGroup } from "./SettingsGroup";

export function LogDirectorySection() {
  const t = useTranslations("accountSettings.logDirectory");
  const directory = useLogDirectory();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(t(`errors.${directoryErrorCode(cause)}`));
    } finally {
      setBusy(false);
    }
  }

  const visibleError = error ?? (directory.error ? t(`errors.${directoryErrorCode(directory.error)}`) : null);

  return (
    <>
      <SettingsGroup title={t("title")} description={t("hint")}>
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] py-1.5 pl-3 pr-1.5">
          <FolderOpen className="size-4 shrink-0 text-[color:var(--aqt-fg-muted)]" aria-hidden />
          <p className="min-w-0 flex-1 truncate text-sm text-[color:var(--aqt-fg)]" role="status">
            {directory.isLoading ? t("loading") : directory.handle?.name ?? t("none")}
          </p>
          <Button type="button" size="sm" variant="outline" disabled={busy || directory.isLoading} onClick={() => void run(directory.select)}>
            {directory.handle ? t("replace") : t("select")}
          </Button>
          {directory.handle ? (
            <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void run(directory.forget)}>
              {t("forget")}
            </Button>
          ) : null}
        </div>
        {visibleError ? <p className="text-sm text-destructive" role="alert">{visibleError}</p> : null}
      </SettingsGroup>

      <SettingsGroup title={t("auto.title")}>
        <div className="flex items-start gap-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5">
          <div className="flex-1 space-y-1">
            <p id="log-auto-upload-label" className="text-sm text-[color:var(--aqt-fg)]">{t("auto.toggle")}</p>
            <p id="log-auto-upload-desc" className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">
              {directory.handle ? t("auto.toggleHint") : t("auto.needsFolder")}
            </p>
          </div>
          <Switch
            checked={directory.autoUpload}
            disabled={!directory.handle}
            onCheckedChange={directory.setAutoUpload}
            aria-labelledby="log-auto-upload-label"
            aria-describedby="log-auto-upload-desc"
          />
        </div>
        {directory.autoUpload ? (
          <AutoUploadStatus folder={directory.handle?.name ?? ""} idle={t("auto.idle")} />
        ) : null}
      </SettingsGroup>
    </>
  );
}
