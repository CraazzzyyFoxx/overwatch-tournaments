export interface LogFileHandle {
  readonly kind: "file";
  readonly name: string;
  getFile(): Promise<File>;
}

export interface LogDirectoryHandle {
  readonly kind: "directory";
  readonly name: string;
  queryPermission(options: { mode: "read" }): Promise<PermissionState>;
  requestPermission(options: { mode: "read" }): Promise<PermissionState>;
  values(): AsyncIterable<LogFileHandle | LogDirectoryHandle>;
  getDirectoryHandle(name: string): Promise<LogDirectoryHandle>;
}

/** A listed log with the metadata `getFile()` exposes without reading the bytes. */
export interface LogFileEntry {
  readonly handle: LogFileHandle;
  readonly name: string;
  readonly lastModified: number;
  readonly size: number;
}

type DirectoryWindow = Window & {
  showDirectoryPicker?: (options: { mode: "read"; id: string; startIn: "documents" }) => Promise<LogDirectoryHandle>;
};

type DirectoryErrorCode = "unsupported" | "storage" | "permission" | "missing" | "read" | "account";

export class LogDirectoryError extends Error {
  constructor(public readonly code: DirectoryErrorCode) {
    super(code);
    this.name = "LogDirectoryError";
  }
}

export function directoryErrorCode(error: unknown): DirectoryErrorCode {
  if (error instanceof LogDirectoryError) return error.code;
  if (error instanceof Error && error.name === "NotFoundError") return "missing";
  if (error instanceof Error && ["NotAllowedError", "SecurityError"].includes(error.name)) return "permission";
  return "read";
}

// IndexedDB is already origin-isolated; the key also isolates signed-in accounts.
async function directoryStorage<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
  let db: IDBDatabase | undefined;
  try {
    db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("anak-log-directory", 1);
      let blocked = false;
      request.onupgradeneeded = () => request.result.createObjectStore("directories");
      request.onsuccess = () => {
        if (blocked) request.result.close();
        else resolve(request.result);
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => {
        blocked = true;
        reject(new LogDirectoryError("storage"));
      };
    });
    return await new Promise<T>((resolve, reject) => {
      const transaction = db!.transaction("directories", mode);
      const request = operation(transaction.objectStore("directories"));
      // Commit, not just request success: quota/transaction failures must surface.
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
      request.onerror = () => reject(request.error);
    });
  } catch {
    throw new LogDirectoryError("storage");
  } finally {
    db?.close();
  }
}

export async function readLogDirectory(accountId: number): Promise<LogDirectoryHandle | null> {
  return (await directoryStorage<LogDirectoryHandle | undefined>("readonly", (store) => store.get(accountId))) ?? null;
}

export async function saveLogDirectory(accountId: number, handle: LogDirectoryHandle): Promise<void> {
  // Pass the actual handle to IDB: the browser structured-clones its capability.
  await directoryStorage("readwrite", (store) => store.put(handle, accountId));
}

export async function forgetLogDirectory(accountId: number): Promise<void> {
  await directoryStorage("readwrite", (store) => store.delete(accountId));
}

export async function pickLogDirectory(): Promise<LogDirectoryHandle | null> {
  const browser = window as DirectoryWindow;
  if (!window.isSecureContext || !browser.showDirectoryPicker) {
    throw new LogDirectoryError("unsupported");
  }
  let picked: LogDirectoryHandle;
  try {
    // Called before any await so the picker retains the click's user activation.
    // A web page cannot name a path; Documents is the closest the API lets us start.
    picked = await browser.showDirectoryPicker({ mode: "read", id: "overwatch-workshop", startIn: "documents" });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") return null;
    throw error;
  }
  return resolveWorkshopDirectory(picked);
}

// Overwatch writes Workshop logs to <Documents>\Overwatch\Workshop on every
// machine; only the Documents location differs (user name, OneDrive).
const WORKSHOP_PATH = ["Overwatch", "Workshop"];

/** Picking Documents or Overwatch lands in Workshop; any other folder is kept as picked. */
export async function resolveWorkshopDirectory(handle: LogDirectoryHandle): Promise<LogDirectoryHandle> {
  let current = handle;
  for (const name of WORKSHOP_PATH.slice(WORKSHOP_PATH.indexOf(handle.name) + 1)) {
    try {
      current = await current.getDirectoryHandle(name);
    } catch {
      return handle;
    }
  }
  return current;
}

export async function allowLogDirectoryRead(handle: LogDirectoryHandle): Promise<void> {
  // Even a preloaded granted permission can be revoked before the next click.
  // requestPermission is silent when granted and is invoked before any await.
  if (await handle.requestPermission({ mode: "read" }) !== "granted") {
    throw new LogDirectoryError("permission");
  }
}

/** Immediate .log/.txt/.csv files, newest first by local modification time. */
export async function listLogFiles(handle: LogDirectoryHandle): Promise<LogFileEntry[]> {
  const files: LogFileHandle[] = [];
  for await (const entry of handle.values()) {
    if (entry.kind === "file" && /\.(log|txt|csv)$/i.test(entry.name)) files.push(entry);
  }
  const entries = await Promise.all(files.map(async (file) => {
    const { lastModified, size } = await file.getFile();
    return { handle: file, name: file.name, lastModified, size };
  }));
  return entries.sort((a, b) => b.lastModified - a.lastModified || a.name.localeCompare(b.name));
}
