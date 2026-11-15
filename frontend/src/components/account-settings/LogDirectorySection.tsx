"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, FolderOpen } from "lucide-react";
import { SettingGroup, SettingRow, settingHintId } from "@/components/kit/SettingRow";
import { AutoUploadStatus } from "@/components/logs/AutoUploadStatus";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { directoryErrorCode } from "@/lib/logs/browser-directory";
import { useLogDirectory } from "@/lib/logs/use-log-directory";

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
    <div className="space-y-6">
      <SettingGroup id="logs-folder" level={4} title={t("title")} description={t("hint")}>
        <div className="py-3 first:pt-0 last:pb-0">
          <div className="flex flex-wrap items-center gap-2">
            <FolderOpen className="size-4 shrink-0 text-[color:var(--aqt-fg-muted)]" aria-hidden />
            <div
              className="min-w-0 flex-1 truncate text-body text-[color:var(--aqt-fg)]"
              role="status"
              title={directory.handle?.name}
            >
              {directory.isLoading ? (
                <>
                  <span className="sr-only">{t("loading")}</span>
                  <Skeleton aria-hidden className="h-4 w-32" />
                </>
              ) : (
                directory.handle?.name ?? t("none")
              )}
            </div>
            <Button type="button" size="sm" variant="outline" disabled={busy || directory.isLoading} onClick={() => void run(directory.select)}>
              {directory.handle ? t("replace") : t("select")}
            </Button>
            {directory.handle ? (
              <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void run(directory.forget)}>
                {t("forget")}
              </Button>
            ) : null}
          </div>
          {visibleError ? (
            <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-caption text-danger">
              <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              <span className="min-w-0 [overflow-wrap:anywhere]">{visibleError}</span>
            </p>
          ) : null}
        </div>
      </SettingGroup>

      <SettingGroup id="logs-auto" level={4} title={t("auto.title")}>
        <SettingRow
          htmlFor="log-auto-upload"
          label={t("auto.toggle")}
          hint={directory.handle ? t("auto.toggleHint") : t("auto.needsFolder")}
        >
          <Switch
            id="log-auto-upload"
            aria-describedby={settingHintId("log-auto-upload")}
            checked={directory.autoUpload}
            disabled={!directory.handle}
            onCheckedChange={directory.setAutoUpload}
          />
        </SettingRow>
        {directory.autoUpload ? (
          <AutoUploadStatus folder={directory.handle?.name ?? ""} idle={t("auto.idle")} framed={false} />
        ) : null}
      </SettingGroup>
    </div>
  );
}
