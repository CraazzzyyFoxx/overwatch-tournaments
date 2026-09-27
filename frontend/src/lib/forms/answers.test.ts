import { describe, expect, it } from "vitest";

import { answerFlag, answerList, answerSearchText, answerText } from "@/lib/forms/answers";

/**
 * The typed reads every roster, table and chip goes through. Each case here is
 * a value shape the server really stores for some field kind — a checkbox that
 * round-tripped as a string, a `smurf_tags` list, a number answer — plus the
 * one shape the types forbid and a cell must survive anyway: no document.
 */
describe("answer readers", () => {
  it("reads text, list and checkbox answers in the shapes the server stores them", () => {
    const answers = {
      identity_discord: "anak",
      blank: "   ",
      seed: 7,
      smurf_tags: ["Alt#2222", 5, "Main#1111"],
      stream_pov: "true",
      rules: false,
    };

    expect(answerText(answers, "identity_discord")).toBe("anak");
    expect(answerText(answers, "blank")).toBeNull();
    expect(answerText(answers, "seed")).toBe("7");
    // A non-string item is not a tag; dropping it beats rendering "5" as one.
    expect(answerList(answers, "smurf_tags")).toEqual(["Alt#2222", "Main#1111"]);
    expect(answerFlag(answers, "stream_pov")).toBe(true);
    expect(answerFlag(answers, "rules")).toBe(false);
  });

  it("reads a missing document as no answer instead of throwing", () => {
    // Every read model declares `answers`, so this is not a shape the types
    // admit — but these run inside table cells, and one row that arrived
    // without its document must not take the screen down.
    for (const document of [undefined, null]) {
      expect(answerText(document, "public_notes")).toBeNull();
      expect(answerList(document, "smurf_tags")).toEqual([]);
      expect(answerFlag(document, "stream_pov")).toBe(false);
    }
  });

  it("offers nothing to search on for an answer nobody would type", () => {
    // `false` would otherwise stringify and make every unticked row match.
    expect(answerSearchText(false)).toBeNull();
    expect(answerSearchText([])).toBeNull();
    expect(answerSearchText("")).toBeNull();
    expect(answerSearchText(["a", "b"])).toBe("a b");
    expect(answerSearchText(12)).toBe("12");
  });
});
