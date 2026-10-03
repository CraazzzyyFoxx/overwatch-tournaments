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
