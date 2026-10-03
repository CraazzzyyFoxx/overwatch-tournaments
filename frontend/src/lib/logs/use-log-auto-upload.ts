"use client";

import { useEffect, useId, useRef } from "react";
import { useTranslations } from "next-intl";
import { create } from "zustand";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { directoryErrorCode, listLogFiles, type LogDirectoryHandle } from "./browser-directory";
import { useLogDirectory } from "./use-log-directory";

export type AutoUploadEntryState = "waiting" | "uploading" | "uploaded" | "rejected" | "failed";

export interface AutoUploadEntry {
  name: string;
  state: AutoUploadEntryState;
  at: number;
  /** Server reason for `rejected`. */
  detail?: string;
}

interface AutoUploadState {
  /** Instance currently holding the cross-tab lock in this document; `null` = none here. */
  holder: string | null;
  status: "watching" | "permission" | "error";
  error: unknown;
  target: { tournamentId: number; encounterId: number | null } | null;
  entries: AutoUploadEntry[];
  /** Set while waiting for folder access; call from a click so the browser may prompt. */
  grant: (() => void) | null;
}

export const useLogAutoUploadStore = create<AutoUploadState>(() => ({
  holder: null,
  status: "watching",
  error: null,
  target: null,
  entries: [],
  grant: null
}));

const LOCK_NAME = "aqt-log-auto-upload";
const POLL_MS = 5_000;
// ponytail: a fixed quiet window stands in for "the match ended"; the server's
// match_end check is the real gate. A long in-match pause costs one rejected
// upload, and the next write to the file re-arms it.
const QUIET_MS = 20_000;
const FEED_SIZE = 8;

/** Resolves `true` when aborted, so loops read `while (!(await sleep(...)))`. */
function sleep(ms: number, signal: AbortSignal): Promise<boolean> {
  const { promise, resolve } = Promise.withResolvers<boolean>();
  if (signal.aborted) return Promise.resolve(true);
  const timer = setTimeout(() => resolve(false), ms);
  signal.addEventListener("abort", () => {
    clearTimeout(timer);
    resolve(true);
  }, { once: true });
  return promise;
}

function record(name: string, state: AutoUploadEntryState, detail?: string) {
  useLogAutoUploadStore.setState(({ entries }) => ({
    entries: [{ name, state, at: Date.now(), detail }, ...entries.filter((entry) => entry.name !== name)].slice(0, FEED_SIZE)
  }));
}

/** Waits until read access is granted; `false` when aborted first. */
async function ensurePermission(handle: LogDirectoryHandle, signal: AbortSignal): Promise<boolean> {
  while (await handle.queryPermission({ mode: "read" }) !== "granted") {
    useLogAutoUploadStore.setState({ status: "permission" });
    const { promise: answered, resolve } = Promise.withResolvers<void>();
    // requestPermission runs first in the click callback: it needs the activation.
    useLogAutoUploadStore.setState({
      grant: () => void handle.requestPermission({ mode: "read" }).catch(() => undefined).finally(resolve)
    });
    signal.addEventListener("abort", () => resolve(), { once: true });
    await answered;
    useLogAutoUploadStore.setState({ grant: null });
    if (signal.aborted) return false;
  }
  return true;
}

/**
 * Watches the saved log folder while a tournament page is open and uploads each
 * log that appears or changes after watching began, once it has been quiet.
 * Files already in the folder are never sent. One watcher per browser: the Web
 * Lock makes other tabs (and other dialogs on this page) wait their turn.
 */
export function useLogAutoUpload({
  tournamentId,
  encounterId,
  onUploaded
}: Readonly<{ tournamentId: number; encounterId: number | null; onUploaded?: () => void }>) {
  const t = useTranslations("accountSettings.logDirectory.auto");
  const directory = useLogDirectory();
  const instance = useId();
  const handle = directory.autoUpload ? directory.handle : null;
  const accountId = directory.accountId;
  const latest = useRef({ t, onUploaded });
  useEffect(() => {
    latest.current = { t, onUploaded };
  });

  useEffect(() => {
    if (!handle || accountId == null || !("locks" in navigator)) return;
    const controller = new AbortController();
    const { signal } = controller;
    const store = useLogAutoUploadStore;

    async function upload(file: File) {
      if (useAuthProfileStore.getState().user?.id !== accountId) throw new Error("account changed");
      return adminService.uploadMatchLogs({ tournamentId, encounterId, files: [file] });
    }

    async function watch(folder: LogDirectoryHandle) {
      let baseline: Map<string, number> | null = null;
      const tracked = new Map<string, { lastModified: number; size: number; since: number; tried: boolean }>();
      while (!signal.aborted) {
        if (!(await ensurePermission(folder, signal))) return;
        try {
          const files = await listLogFiles(folder);
          store.setState({ status: "watching", error: null });
          // Point of no history: whatever is in the folder now is left alone.
          if (!baseline) baseline = new Map(files.map((file) => [file.name, file.lastModified]));
          const now = Date.now();
          for (const file of files) {
            if (signal.aborted) return;
            if (baseline.get(file.name) === file.lastModified) continue;
            const seen = tracked.get(file.name);
            if (!seen || seen.lastModified !== file.lastModified || seen.size !== file.size) {
              tracked.set(file.name, { lastModified: file.lastModified, size: file.size, since: now, tried: false });
              record(file.name, "waiting");
              continue;
            }
            if (seen.tried || now - seen.since < QUIET_MS) continue;
            seen.tried = true;
            record(file.name, "uploading");
            try {
              const result = await upload(await file.handle.getFile());
              const failure = result.errors[0];
              if (failure) {
                // Unfinished or invalid: retried only when the file changes again.
                record(file.name, "rejected", failure.error);
              } else {
                baseline.set(file.name, file.lastModified);
                tracked.delete(file.name);
                record(file.name, "uploaded");
                latest.current.onUploaded?.();
                notify.success(latest.current.t("uploadedToast"), {
                  description: latest.current.t("uploadedToastDescription", { name: file.name })
                });
              }
            } catch {
              // Transport failure says nothing about the file: try again after another quiet window.
              Object.assign(seen, { tried: false, since: Date.now() });
              record(file.name, "failed");
            }
          }
        } catch (cause) {
          // A revoked grant loops back to ensurePermission; anything else is shown and retried.
          if (directoryErrorCode(cause) !== "permission") store.setState({ status: "error", error: cause });
        }
        if (await sleep(POLL_MS, signal)) return;
      }
    }

    navigator.locks
      .request(LOCK_NAME, { signal }, async () => {
        store.setState({ holder: instance, status: "watching", error: null, entries: [], target: { tournamentId, encounterId } });
        try {
          await watch(handle);
        } finally {
          if (store.getState().holder === instance) store.setState({ holder: null, grant: null, target: null });
        }
      })
      // AbortError: unmounted while another tab held the lock.
      .catch(() => undefined);
    return () => controller.abort();
  }, [handle, accountId, tournamentId, encounterId, instance]);
}
