import { expect, it } from "vitest";
import { listLogFiles, type LogDirectoryHandle, type LogFileHandle } from "./browser-directory";

it("offers only immediate log files, including uppercase suffixes, without reading file contents", async () => {
  const file = (name: string): LogFileHandle => ({
    kind: "file",
    name,
    getFile: async () => { throw new Error("Listing must not read file contents"); }
  });
  const nested: LogDirectoryHandle = {
    kind: "directory",
    name: "nested.log",
    queryPermission: async () => "granted",
    requestPermission: async () => "granted",
    async *values() { yield file("hidden.log"); }
  };
  const directory: LogDirectoryHandle = {
    ...nested,
    name: "logs",
    async *values() {
      yield file("round.LOG");
      yield file("notes.txt");
      yield file("match.csv");
      yield file("screenshot.png");
      yield file("match.log.exe");
      yield nested;
    }
  };
  expect((await listLogFiles(directory)).map((entry) => entry.name)).toEqual([
    "match.csv", "notes.txt", "round.LOG"
  ]);
});

it("orders upload candidates by local modification time, breaking ties by filename, including empty folders", async () => {
  const file = (name: string, lastModified: number): LogFileHandle => ({
    kind: "file",
    name,
    getFile: async () => {
      const result = new File(["irrelevant event timestamps"], name, { lastModified });
      result.text = async () => { throw new Error("Ordering must not read file contents"); };
      return result;
    }
  });
  const directory: LogDirectoryHandle = {
    kind: "directory",
    name: "logs",
    queryPermission: async () => "granted",
    requestPermission: async () => "granted",
    async *values() {
      yield file("a-oldest.log", 100);
      yield file("z-newest.log", 300);
      yield file("c-tied.csv", 200);
      yield file("b-tied.txt", 200);
    }
  };

  expect((await listLogFiles(directory, "newest")).map((entry) => entry.name)).toEqual([
    "z-newest.log", "b-tied.txt", "c-tied.csv", "a-oldest.log"
  ]);
  expect(await listLogFiles({ ...directory, async *values() {} }, "newest")).toEqual([]);
});
