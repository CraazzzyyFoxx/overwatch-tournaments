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
}

type DirectoryWindow = Window & {
  showDirectoryPicker?: (options: { mode: "read" }) => Promise<LogDirectoryHandle>;
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
  try {
    // Called before any await so the picker retains the click's user activation.
    return await browser.showDirectoryPicker({ mode: "read" });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") return null;
    throw error;
  }
}

export async function allowLogDirectoryRead(handle: LogDirectoryHandle): Promise<void> {
  // Even a preloaded granted permission can be revoked before the next click.
  // requestPermission is silent when granted and is invoked before any await.
  if (await handle.requestPermission({ mode: "read" }) !== "granted") {
    throw new LogDirectoryError("permission");
  }
}

export async function listLogFiles(handle: LogDirectoryHandle, order: "name" | "newest" = "name"): Promise<LogFileHandle[]> {
  const files: LogFileHandle[] = [];
  for await (const entry of handle.values()) {
    if (entry.kind === "file" && /\.(log|txt|csv)$/i.test(entry.name)) files.push(entry);
  }
  if (order === "name") return files.sort((a, b) => a.name.localeCompare(b.name));
  const datedFiles = await Promise.all(files.map(async (file) => ({
    handle: file,
    lastModified: (await file.getFile()).lastModified
  })));
  return datedFiles
    .sort((a, b) => b.lastModified - a.lastModified || a.handle.name.localeCompare(b.handle.name))
    .map((file) => file.handle);
}
