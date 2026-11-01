// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { LogDirectoryHandle, LogFileHandle } from "./browser-directory";
import { useLogAutoUpload, useLogAutoUploadStore } from "./use-log-auto-upload";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const files = new Map<string, { lastModified: number; body: string }>();
const folder: LogDirectoryHandle = {
  kind: "directory",
  name: "Workshop",
  queryPermission: async () => "granted",
  requestPermission: async () => "granted",
  async *values() {
    for (const [name, meta] of files) {
      yield { kind: "file", name, getFile: async () => new File([meta.body], name, { lastModified: meta.lastModified }) } as LogFileHandle;
    }
  },
  getDirectoryHandle: async () => { throw new Error("none"); }
};

const upload = vi.fn();
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn() } }));
vi.mock("@/services/admin.service", () => ({ default: { uploadMatchLogs: (...args: unknown[]) => upload(...args) } }));
vi.mock("@/stores/auth-profile.store", () => ({ useAuthProfileStore: { getState: () => ({ user: { id: 1 } }) } }));
vi.mock("./use-log-directory", () => ({ useLogDirectory: () => ({ autoUpload: true, handle: folder, accountId: 1 }) }));

afterEach(() => vi.useRealTimers());

it("ignores existing files, waits for quiet, uploads once, retries a rejected file after it changes", async () => {
  vi.useFakeTimers();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: { request: (_name: string, _opts: unknown, cb: () => Promise<void>) => cb() }
  });
  files.set("old.log", { lastModified: 1, body: "old" });

  function Probe() {
    useLogAutoUpload({ enabled: true, scope: { tournamentId: 42, encounterId: 7 } });
    return null;
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Probe />));
  const tick = async (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

  await tick(5_000);
  files.set("live.log", { lastModified: Date.now(), body: "0,match_start,0" });
  await tick(5_000); // seen, waiting
  expect(useLogAutoUploadStore.getState().entries[0]).toMatchObject({ name: "live.log", state: "waiting" });

  upload.mockResolvedValueOnce({ uploaded: [], errors: [{ filename: "live.log", error: "not finished" }] });
  await tick(25_000); // quiet window passes → one rejected attempt
  expect(upload).toHaveBeenCalledTimes(1);
  expect(upload.mock.calls[0][0]).toMatchObject({ tournamentId: 42, encounterId: 7 });
  expect(useLogAutoUploadStore.getState().entries[0]).toMatchObject({ state: "rejected", detail: "not finished" });

  await tick(30_000); // unchanged after rejection: no retry
  expect(upload).toHaveBeenCalledTimes(1);

  files.set("live.log", { lastModified: Date.now(), body: "0,match_start,0\n0,match_end,9" });
  upload.mockResolvedValueOnce({ uploaded: [{ filename: "live.log" }], errors: [] });
  await tick(30_000);
  expect(upload).toHaveBeenCalledTimes(2);
  expect(useLogAutoUploadStore.getState().entries[0]).toMatchObject({ state: "uploaded" });

  await tick(60_000); // uploaded file stays uploaded; old.log never sent
  expect(upload).toHaveBeenCalledTimes(2);
  expect(upload.mock.calls.flatMap((call) => call[0].files.map((file: File) => file.name))).toEqual(["live.log", "live.log"]);

  act(() => root.unmount());
});

it("never watches on a page that did not opt in, even with the account setting on", async () => {
  vi.useFakeTimers();
  upload.mockClear();
  function AdminProbe() {
    useLogAutoUpload({ enabled: false, scope: { tournamentId: 42, encounterId: null } });
    return null;
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<AdminProbe />));
  files.set("admin-page.log", { lastModified: Date.now(), body: "0,match_end,1" });
  await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
  expect(upload).not.toHaveBeenCalled();
  act(() => root.unmount());
});

it("targets a mix lobby and keeps watching when the host re-renders with an equal scope object", async () => {
  vi.useFakeTimers();
  upload.mockReset();
  files.clear();
  const baseline = Date.now();
  files.set("old.log", { lastModified: baseline, body: "old" });
  function LobbyProbe() {
    // A fresh object each render, as the lobby room builds it: only its value may restart the watcher.
    useLogAutoUpload({ enabled: true, scope: { customGameId: 5, lobbyIndex: 1 } });
    return null;
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<LobbyProbe />));
  const tick = async (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  await tick(5_000);
  await act(async () => root.render(<LobbyProbe />));
  files.set("mix.log", { lastModified: Date.now(), body: "0,match_start,0\n0,match_end,9" });
  upload.mockResolvedValue({ uploaded: [{ filename: "mix.log" }], errors: [] });
  await tick(40_000);
  expect(upload).toHaveBeenCalledTimes(1);
  expect(upload.mock.calls[0][0]).toMatchObject({ customGameId: 5, lobbyIndex: 1 });
  expect(upload.mock.calls[0][0]).not.toHaveProperty("encounterId");
  act(() => root.unmount());
});
