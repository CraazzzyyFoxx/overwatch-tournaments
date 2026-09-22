import { describe, expect, it } from "bun:test";

import { INVITE_LINK_PATH, buildInviteLink, readInviteTokenFromHash } from "./invite-link";

const TOKEN = "PcWqruHUOoQe4AmdJagQPh_fpjqq2e9qJ61GJgRSIDI";

describe("invite link", () => {
  it("produces a pasteable URL, not a bare token", () => {
    // The bug this closes: the invite dialog copied the raw token, which the
    // recipient had nowhere to put — no route accepted one.
    const link = buildInviteLink(TOKEN, "https://anak.gg");

    expect(link).toBe(`https://anak.gg${INVITE_LINK_PATH}#${TOKEN}`);
    expect(link.startsWith("https://")).toBe(true);
  });

  it("keeps the token in the fragment, never the path or query", () => {
    // A fragment is the one part of a URL browsers never transmit: not in the
    // access log, not in `Referer`. A path or query token leaks to every hop.
    const link = buildInviteLink(TOKEN, "https://anak.gg");
    const url = new URL(link);

    expect(url.hash).toBe(`#${TOKEN}`);
    expect(url.pathname).toBe(INVITE_LINK_PATH);
    expect(url.pathname).not.toContain(TOKEN);
    expect(url.search).toBe("");
  });

  it("round-trips through the landing page's reader", () => {
    const link = buildInviteLink(TOKEN, "https://anak.gg");

    expect(readInviteTokenFromHash(new URL(link).hash)).toBe(TOKEN);
  });

  it("reads a fragment with or without its leading hash", () => {
    expect(readInviteTokenFromHash(`#${TOKEN}`)).toBe(TOKEN);
    expect(readInviteTokenFromHash(TOKEN)).toBe(TOKEN);
  });

  it("treats an empty fragment as no link rather than an empty token", () => {
    // Different recourses: "you arrived without a link" is not "your link is
    // broken". An empty-string token would fire a doomed request and report the
    // second when the first is true.
    expect(readInviteTokenFromHash("")).toBeNull();
    expect(readInviteTokenFromHash("#")).toBeNull();
    expect(readInviteTokenFromHash("#   ")).toBeNull();
  });

  it("decodes a fragment a chat client percent-encoded on the way", () => {
    expect(readInviteTokenFromHash("#ab%2Bcd")).toBe("ab+cd");
  });

  it("strips whitespace picked up anywhere in the token, not just the ends", () => {
    // A real token is a bare base64url string and never contains whitespace, so
    // a space or line break wrapped in mid-token (pasted from a wrapped `<code>`
    // block, or reflowed by a chat client) is corruption, not part of the value.
    // Removing it can only rescue a mangled link, never break a valid one.
    const [head, tail] = [TOKEN.slice(0, 10), TOKEN.slice(10)];
    expect(readInviteTokenFromHash(`#${head} ${tail}`)).toBe(TOKEN);
    expect(readInviteTokenFromHash(`#${head}\n${tail}`)).toBe(TOKEN);
  });
});
