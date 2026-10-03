import { expect, it } from "vitest";
import { listLogFiles, resolveWorkshopDirectory, type LogDirectoryHandle, type LogFileHandle } from "./browser-directory";

function directory(name: string, children: (LogFileHandle | LogDirectoryHandle)[] = []): LogDirectoryHandle {
  return {
    kind: "directory",
    name,
    queryPermission: async () => "granted",
    requestPermission: async () => "granted",
    async *values() { yield* children; },
    async getDirectoryHandle(child) {
      const found = children.find((entry) => entry.kind === "directory" && entry.name === child);
      if (!found) throw new DOMException("missing", "NotFoundError");
      return found as LogDirectoryHandle;
    }
  };
}

it("lists only immediate log files, newest first with name tie-break, without reading contents", async () => {
  const file = (name: string, lastModified: number): LogFileHandle => ({
    kind: "file",
    name,
    getFile: async () => {
      const result = new File(["abc"], name, { lastModified });
      result.text = async () => { throw new Error("Listing must not read file contents"); };
      return result;
    }
  });
  const logs = directory("logs", [
    file("a-oldest.log", 100),
    file("z-newest.LOG", 300),
    file("c-tied.csv", 200),
    file("b-tied.txt", 200),
    file("screenshot.png", 400),
    file("match.log.exe", 400),
    directory("nested.log", [file("hidden.log", 500)])
  ]);

  const entries = await listLogFiles(logs);
  expect(entries.map((entry) => entry.name)).toEqual(["z-newest.LOG", "b-tied.txt", "c-tied.csv", "a-oldest.log"]);
  expect(entries[0]).toMatchObject({ lastModified: 300, size: 3 });
  expect(await listLogFiles(directory("empty"))).toEqual([]);
});

it("descends from Documents or Overwatch into Workshop and keeps any other pick", async () => {
  const workshop = directory("Workshop");
  const overwatch = directory("Overwatch", [workshop]);

  expect(await resolveWorkshopDirectory(directory("Documents", [overwatch]))).toBe(workshop);
  expect(await resolveWorkshopDirectory(directory("Документы", [overwatch]))).toBe(workshop);
  expect(await resolveWorkshopDirectory(overwatch)).toBe(workshop);
  expect(await resolveWorkshopDirectory(workshop)).toBe(workshop);
  const unrelated = directory("Scrims");
  expect(await resolveWorkshopDirectory(unrelated)).toBe(unrelated);
  // A half-matching path keeps the original pick, not the intermediate folder.
  const documents = directory("Documents", [directory("Overwatch")]);
  expect(await resolveWorkshopDirectory(documents)).toBe(documents);
});
