"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { FileUp, FolderOpen, RefreshCw, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TONE_TEXT, type Tone } from "@/components/ui/tone";
import { useFormatter } from "@/lib/datetime/client";
import {
  directoryErrorCode, listLogFiles, LogDirectoryError,
  type LogDirectoryHandle, type LogFileEntry
} from "@/lib/logs/browser-directory";
import { useLogAutoUpload, useLogAutoUploadStore, type AutoUploadEntryState } from "@/lib/logs/use-log-auto-upload";
import { useLogDirectory } from "@/lib/logs/use-log-directory";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import type { Encounter } from "@/types/encounter.types";
import { AutoUploadStatus } from "./AutoUploadStatus";

interface TournamentLogUploadDialogProps {
  tournamentId: number;
  encounters: Encounter[];
  trigger: ReactNode;
  initialEncounterId?: number | null;
  onUploaded?: () => void;
}

const NO_ENCOUNTER_VALUE = "none";
// A log touched this recently is most likely still being written by the game.
const WRITING_MS = 60_000;

const ENTRY_TONE: Record<AutoUploadEntryState, Tone> = {
  waiting: "neutral",
  uploading: "info",
  uploaded: "success",
  rejected: "warning",
  failed: "danger"
};

export function TournamentLogUploadDialog(props: Readonly<TournamentLogUploadDialogProps>) {
  const accountId = useAuthProfileStore((state) => state.user?.id);
  // A different account must never inherit an open folder listing or selection.
  return <DirectoryUploadDialog key={accountId ?? "anonymous"} {...props} />;
}

function DirectoryUploadDialog({
  tournamentId, encounters, trigger, initialEncounterId = null, onUploaded
}: Readonly<TournamentLogUploadDialogProps>) {
  const t = useTranslations("accountSettings.logDirectory");
  const format = useFormatter();
  const directory = useLogDirectory();
  // Mounted with the trigger, not the open dialog: watching outlives the modal.
  useLogAutoUpload({ tournamentId, encounterId: initialEncounterId, onUploaded });
  const watcher = useLogAutoUploadStore();
  const encounterInputId = useId();
  const scanId = useRef(0);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("manual");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listing, setListing] = useState<{ handle: LogDirectoryHandle; files: LogFileEntry[]; at: number } | null>(null);
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const [selectedEncounterId, setSelectedEncounterId] = useState(
    initialEncounterId != null ? initialEncounterId.toString() : NO_ENCOUNTER_VALUE
  );
  const availableFiles = listing?.handle === directory.handle ? listing.files : [];
  const selectedFiles = availableFiles.filter((file) => selectedNames.has(file.name));
  // The pregame room passes its own encounter only: nothing to choose.
  const fixedEncounter = initialEncounterId != null && encounters.length === 1 ? encounters[0] : null;
  const watching = watcher.holder != null && watcher.status === "watching";
  const watcherEncounterId = watcher.target?.encounterId ?? null;
  const autoTarget = watcherEncounterId == null
    ? t("auto.targetTournament")
    : t("auto.targetEncounter", {
      encounter: encounters.find((encounter) => encounter.id === watcherEncounterId)?.name ?? `#${watcherEncounterId}`
    });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      const accountId = directory.accountId;
      if (accountId == null || useAuthProfileStore.getState().user?.id !== accountId) {
        throw new LogDirectoryError("account");
      }
      const files = await Promise.all(selectedFiles.map((entry) => entry.handle.getFile()));
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

  async function loadFiles(replace = false) {
    const currentScanId = ++scanId.current;
    setBusy(true);
    setError(null);
    try {
      const handle = await (replace ? directory.select() : directory.access());
      if (currentScanId !== scanId.current || !handle) return;
      const files = await listLogFiles(handle);
      if (currentScanId !== scanId.current) return;
      const at = Date.now();
      setListing({ handle, files, at });
      // The match just played: the newest log the game has stopped writing.
      const newestFinished = files.find((file) => at - file.lastModified >= WRITING_MS);
      setSelectedNames(new Set(newestFinished ? [newestFinished.name] : []));
      uploadMutation.reset();
    } catch (cause) {
      if (currentScanId === scanId.current) setError(t(`errors.${directoryErrorCode(cause)}`));
    } finally {
      if (currentScanId === scanId.current) setBusy(false);
    }
  }

  const locked = busy || uploadMutation.isPending;
  const canSubmit = selectedFiles.length > 0 && !locked;
  const visibleError = error ?? (directory.error ? t(`errors.${directoryErrorCode(directory.error)}`) : null);

  function handleOpenChange(nextOpen: boolean) {
    if (locked) return;
    if (nextOpen) {
      setTab("manual");
      setError(null);
      setSelectedEncounterId(initialEncounterId != null ? initialEncounterId.toString() : NO_ENCOUNTER_VALUE);
      uploadMutation.reset();
      // A saved folder is read at once (any permission prompt keeps this click);
      // without one, the empty state asks first instead of springing the picker.
      if (directory.handle) void loadFiles();
      else setListing(null);
    }
    setOpen(nextOpen);
  }

  function openSettings() {
    setOpen(false);
    useAccountSettingsModalStore.getState().open("logs");
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild disabled={directory.isLoading}>{trigger}</DialogTrigger>
      <DialogContent className="max-w-xl gap-5">
        <DialogHeader>
          <DialogTitle>{t("uploadTitle")}</DialogTitle>
          <DialogDescription>
            {fixedEncounter ? t("uploadHintEncounter", { encounter: fixedEncounter.name }) : t("uploadHintTournament")}
          </DialogDescription>
        </DialogHeader>
        <Tabs value={tab} onValueChange={setTab} className="min-w-0 space-y-4">
          <TabsList variant="pill" aria-label={t("tabs.label")}>
            <TabsTrigger value="manual">{t("tabs.manual")}</TabsTrigger>
            <TabsTrigger value="auto" dot={watching ? { tone: "accent", label: t("tabs.autoOn") } : undefined}>
              {t("tabs.auto")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="manual" className="mt-0 space-y-4">
            {directory.handle ? (
              <div className="flex items-center gap-1 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] py-1 pl-3 pr-1">
                <FolderOpen className="size-4 shrink-0 text-[color:var(--aqt-fg-muted)]" aria-hidden />
                <span className="ml-1.5 min-w-0 flex-1 truncate text-sm font-medium text-[color:var(--aqt-fg)]" title={directory.handle.name}>
                  {directory.handle.name}
                </span>
                <Button type="button" variant="ghost" size="sm" disabled={locked} onClick={() => void loadFiles()}>
                  <RefreshCw className={cn("size-3.5", busy && "animate-spin motion-reduce:animate-none")} aria-hidden />
                  {t("refresh")}
                </Button>
                <Button type="button" variant="ghost" size="sm" disabled={locked} onClick={() => void loadFiles(true)}>
                  {t("replace")}
                </Button>
              </div>
            ) : (
              <div className="space-y-3 rounded-lg border border-dashed border-[color:var(--aqt-border-2)] px-4 py-5">
                <div className="space-y-1">
                  <p className="text-ui font-semibold text-[color:var(--aqt-fg)]">{t("emptyTitle")}</p>
                  <p className="text-caption text-pretty text-[color:var(--aqt-fg-muted)]">{t("hint")}</p>
                </div>
                <Button type="button" variant="outline" disabled={locked || directory.isLoading} onClick={() => void loadFiles(true)}>
                  <FolderOpen className="size-4" aria-hidden />
                  {t("select")}
                </Button>
              </div>
            )}
            <p className="sr-only" role="status">{busy ? t("scanning") : ""}</p>
            {visibleError ? <p className="text-sm text-destructive" role="alert">{visibleError}</p> : null}
            {listing && listing.handle === directory.handle ? (
              availableFiles.length ? (
                <fieldset disabled={locked} className="min-w-0">
                  <legend className="sr-only">{t("files")}</legend>
                  <ul className="max-h-72 divide-y divide-[color:var(--aqt-border)] overflow-y-auto rounded-lg border border-[color:var(--aqt-border)]">
                    {availableFiles.map((file) => (
                      <li key={file.name}>
                        <label className="flex min-h-11 cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-[color:var(--aqt-overlay-2)] has-[:checked]:bg-[color:color-mix(in_srgb,var(--aqt-teal)_8%,transparent)]">
                          <input
                            type="checkbox"
                            className="size-4 shrink-0 accent-primary"
                            checked={selectedNames.has(file.name)}
                            onChange={(event) => {
                              const checked = event.target.checked;
                              setSelectedNames((current) => {
                                const next = new Set(current);
                                if (checked) next.add(file.name); else next.delete(file.name);
                                return next;
                              });
                            }}
                          />
                          <span className="min-w-0 flex-1 truncate text-[color:var(--aqt-fg)]" title={file.name}>{file.name}</span>
                          {listing.at - file.lastModified < WRITING_MS ? (
                            <span className="shrink-0 text-caption text-warning">{t("writing")}</span>
                          ) : (
                            <span className="shrink-0 text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">
                              {format.relativeTime(new Date(file.lastModified), { now: listing.at, style: "short" })}
                            </span>
                          )}
                          <span className="w-16 shrink-0 text-right text-caption tabular-nums text-[color:var(--aqt-fg-dim)]">
                            {format.number(Math.max(1, file.size / 1024), { style: "unit", unit: "kilobyte", maximumFractionDigits: 0 })}
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </fieldset>
              ) : <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("empty")}</p>
            ) : null}
            {uploadMutation.data?.errors.length ? (
              <ul className="space-y-1 text-sm text-destructive" role="alert">
                {uploadMutation.data.errors.map((failure, index) => <li key={index} className="break-all">{failure.filename ? `${failure.filename}: ` : ""}{failure.error}</li>)}
              </ul>
            ) : null}
            {fixedEncounter ? null : (
              <div className="space-y-2">
                <Label htmlFor={encounterInputId}>{t("encounter")}</Label>
                <Select value={selectedEncounterId} onValueChange={setSelectedEncounterId} disabled={locked}>
                  <SelectTrigger id={encounterInputId}><SelectValue placeholder={t("autoEncounter")} /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_ENCOUNTER_VALUE}>{t("autoEncounter")}</SelectItem>
                    {encounters.map((encounter) => <SelectItem key={encounter.id} value={encounter.id.toString()}>{encounter.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}
          </TabsContent>

          <TabsContent value="auto" className="mt-0 space-y-4">
            {directory.autoUpload ? (
              <>
                <AutoUploadStatus folder={directory.handle?.name ?? ""} idle={t("auto.otherTab")} target={autoTarget} />
                <AutoUploadFeed />
                <p className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">
                  {t("auto.tabNote")}{" "}
                  <button type="button" className="underline underline-offset-2 hover:text-[color:var(--aqt-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={openSettings}>
                    {t("auto.manage")}
                  </button>
                </p>
              </>
            ) : (
              <div className="space-y-3 rounded-lg border border-dashed border-[color:var(--aqt-border-2)] px-4 py-5">
                <div className="space-y-1">
                  <p className="text-ui font-semibold text-[color:var(--aqt-fg)]">{t("auto.offTitle")}</p>
                  <p className="text-caption text-pretty text-[color:var(--aqt-fg-muted)]">{t("auto.offHint")}</p>
                </div>
                <Button type="button" variant="outline" onClick={openSettings}>
                  <Settings className="size-4" aria-hidden />
                  {t("auto.openSettings")}
                </Button>
              </div>
            )}
          </TabsContent>
        </Tabs>
        <DialogFooter>
          {tab === "manual" ? (
            <>
              <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={locked}>{t("cancel")}</Button>
              <Button type="button" onClick={() => { setError(null); uploadMutation.mutate(); }} disabled={!canSubmit}>
                {uploadMutation.isPending ? <Spinner className="mr-2" /> : <FileUp className="mr-2 size-4" aria-hidden />}
                {t("upload", { count: selectedFiles.length })}
              </Button>
            </>
          ) : (
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>{t("close")}</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AutoUploadFeed() {
  const t = useTranslations("accountSettings.logDirectory.auto");
  const format = useFormatter();
  const entries = useLogAutoUploadStore((state) => state.entries);

  if (!entries.length) return <p className="text-caption text-pretty text-[color:var(--aqt-fg-muted)]">{t("feedEmpty")}</p>;
  return (
    <ul aria-label={t("feed")} className="divide-y divide-[color:var(--aqt-border)] rounded-lg border border-[color:var(--aqt-border)]">
      {entries.map((entry) => (
        <li key={entry.name} className="space-y-0.5 px-3 py-2">
          <div className="flex items-center gap-3 text-sm">
            <span className="min-w-0 flex-1 truncate text-[color:var(--aqt-fg)]" title={entry.name}>{entry.name}</span>
            <span className={cn("shrink-0 text-caption", TONE_TEXT[ENTRY_TONE[entry.state]])}>
              {t(`state.${entry.state}`, { time: format.dateTime(new Date(entry.at), { timeStyle: "short" }) })}
            </span>
          </div>
          {entry.detail ? <p className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">{entry.detail}</p> : null}
        </li>
      ))}
    </ul>
  );
}
