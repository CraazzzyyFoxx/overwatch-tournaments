"use client";

import { useId, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { FileUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { directoryErrorCode, listLogFiles, LogDirectoryError, type LogDirectoryHandle, type LogFileHandle } from "@/lib/logs/browser-directory";
import { useLogDirectory } from "@/lib/logs/use-log-directory";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import type { Encounter } from "@/types/encounter.types";

interface TournamentLogUploadDialogProps {
  tournamentId: number;
  encounters: Encounter[];
  trigger: ReactNode;
  initialEncounterId?: number | null;
  onUploaded?: () => void;
}

const NO_ENCOUNTER_VALUE = "none";

export function TournamentLogUploadDialog(props: Readonly<TournamentLogUploadDialogProps>) {
  const accountId = useAuthProfileStore((state) => state.user?.id);
  // A different account must never inherit an open folder listing or selection.
  return <DirectoryUploadDialog key={accountId ?? "anonymous"} {...props} />;
}

function DirectoryUploadDialog({
  tournamentId, encounters, trigger, initialEncounterId = null, onUploaded
}: Readonly<TournamentLogUploadDialogProps>) {
  const t = useTranslations("accountSettings.logDirectory");
  const directory = useLogDirectory();
  const encounterInputId = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listing, setListing] = useState<{ handle: LogDirectoryHandle; files: LogFileHandle[] } | null>(null);
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const [selectedEncounterId, setSelectedEncounterId] = useState(
    initialEncounterId != null ? initialEncounterId.toString() : NO_ENCOUNTER_VALUE
  );
  const availableFiles = listing?.handle === directory.handle ? listing.files : [];
  const selectedFiles = availableFiles.filter((file) => selectedNames.has(file.name));
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const file of selectedFiles) {
    if (seen.has(file.name)) duplicates.add(file.name);
    seen.add(file.name);
  }
  const duplicateFileNames = Array.from(duplicates).sort((a, b) => a.localeCompare(b));

  const uploadMutation = useMutation({
    mutationFn: async () => {
      const accountId = directory.accountId;
      if (accountId == null || useAuthProfileStore.getState().user?.id !== accountId) {
        throw new LogDirectoryError("account");
      }
      const files = await Promise.all(selectedFiles.map((handle) => handle.getFile()));
      if (useAuthProfileStore.getState().user?.id !== accountId) throw new LogDirectoryError("account");
      return adminService.uploadMatchLogs({
        tournamentId,
        files,
        encounterId: selectedEncounterId === NO_ENCOUNTER_VALUE ? null : Number(selectedEncounterId)
      });
    },
    onSuccess: (result) => {
      const uploadedCount = result.uploaded.length;
      const errorCount = result.errors.length;
      const uploadedNames = new Set(result.uploaded.map((item) => item.filename.split(/[\\/]/).at(-1) ?? item.filename));
      setSelectedNames((names) => new Set(Array.from(names).filter((name) => !uploadedNames.has(name))));
      setListing((current) => current ? { ...current, files: current.files.filter((file) => !uploadedNames.has(file.name)) } : null);
      if (uploadedCount) onUploaded?.();
      if (errorCount) {
        // Keep the dialog and failed selection: retry must not resend successes.
        notify.error(t("partial"), {
          description: t("partialDescription", { uploaded: uploadedCount, failed: errorCount })
        });
      } else {
        setOpen(false);
        notify.success(t("queued"), { description: t("queuedDescription", { count: uploadedCount }) });
      }
    },
    onError: (cause) => {
      setError(cause instanceof LogDirectoryError || (cause instanceof Error && ["NotFoundError", "NotAllowedError", "SecurityError"].includes(cause.name))
        ? t(`errors.${directoryErrorCode(cause)}`)
        : t("errors.upload"));
    }
  });

  async function loadFiles(replace = false, closeOnCancel = false) {
    setBusy(true);
    setError(null);
    try {
      const handle = await (replace ? directory.select() : directory.access());
      if (!handle) {
        if (closeOnCancel) setOpen(false);
        return;
      }
      const files = await listLogFiles(handle);
      setListing({ handle, files });
      setSelectedNames(new Set());
      uploadMutation.reset();
    } catch (cause) {
      setError(t(`errors.${directoryErrorCode(cause)}`));
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = selectedFiles.length > 0 && duplicateFileNames.length === 0 && !busy && !uploadMutation.isPending;
  const visibleError = error ?? (directory.error ? t(`errors.${directoryErrorCode(directory.error)}`) : null);
  const locked = busy || uploadMutation.isPending;

  function handleOpenChange(nextOpen: boolean) {
    if (locked) return;
    if (nextOpen) {
      setSelectedEncounterId(initialEncounterId != null ? initialEncounterId.toString() : NO_ENCOUNTER_VALUE);
      setListing(null);
      setSelectedNames(new Set());
      uploadMutation.reset();
      // Preloaded handle: picker/permission runs directly in this click callback.
      void loadFiles(false, true);
    }
    setOpen(nextOpen);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild disabled={directory.isLoading}>{trigger}</DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("uploadTitle")}</DialogTitle>
          <DialogDescription>{t("uploadHint")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <p className="break-all text-sm">{directory.handle?.name ?? t("none")}</p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" disabled={locked || directory.isLoading} onClick={() => void loadFiles(true)}>
                {directory.handle ? t("replace") : t("select")}
              </Button>
              <Button type="button" variant="outline" disabled={locked || !directory.handle} onClick={() => void loadFiles()}>
                {t("refresh")}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground" role="status">{busy ? t("scanning") : t("selection", { count: selectedFiles.length })}</p>
            {visibleError ? <p className="text-sm text-destructive" role="alert">{visibleError}</p> : null}
            {!busy && listing?.handle === directory.handle ? (
              availableFiles.length ? (
                <fieldset disabled={locked} className="space-y-2">
                  <legend className="text-sm font-medium">{t("files")}</legend>
                  <div className="max-h-60 overflow-y-auto rounded-md border border-border">
                    {availableFiles.map((file) => (
                      <label key={file.name} className="flex min-h-10 cursor-pointer items-center gap-3 px-3 py-2 text-sm">
                        <input type="checkbox" className="size-4 shrink-0 accent-primary" checked={selectedNames.has(file.name)} onChange={(event) => {
                          const checked = event.target.checked;
                          setSelectedNames((current) => {
                            const next = new Set(current);
                            if (checked) next.add(file.name); else next.delete(file.name);
                            return next;
                          });
                        }} />
                        <span className="break-all">{file.name}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              ) : <p className="text-xs text-muted-foreground">{t("empty")}</p>
            ) : null}
            {duplicateFileNames.length ? <p className="text-xs text-destructive" role="alert">{t("duplicate", { names: duplicateFileNames.join(", ") })}</p> : null}
            {uploadMutation.data?.errors.length ? (
              <ul className="space-y-1 text-sm text-destructive" role="alert">
                {uploadMutation.data.errors.map((failure, index) => <li key={index} className="break-all">{failure.filename ? `${failure.filename}: ` : ""}{failure.error}</li>)}
              </ul>
            ) : null}
          </div>
          <div className="space-y-2">
            <Label htmlFor={encounterInputId}>{t("encounter")}</Label>
            <Select value={selectedEncounterId} onValueChange={setSelectedEncounterId} disabled={locked}>
              <SelectTrigger id={encounterInputId}><SelectValue placeholder={t("noEncounter")} /></SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_ENCOUNTER_VALUE}>{t("noEncounter")}</SelectItem>
                {encounters.map((encounter) => <SelectItem key={encounter.id} value={encounter.id.toString()}>{encounter.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={locked}>{t("cancel")}</Button>
          <Button type="button" onClick={() => { setError(null); uploadMutation.mutate(); }} disabled={!canSubmit}>
            {uploadMutation.isPending ? <Spinner className="mr-2" /> : <FileUp className="mr-2 size-4" aria-hidden />}
            {t("upload")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
