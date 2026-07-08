import { describe, it, expect } from "bun:test";
import { publicHost, publicHostname, publicOrigin } from "@/lib/request-origin";

function req(url: string, headers: Record<string, string> = {}): Request {
  return new Request(url, { headers });
}

describe("request-origin", () => {
  it("derives origin from x-forwarded-host/proto, ignoring the internal request.url host", () => {
    const r = req("http://0.0.0.0:3000/auth/callback", {
      "x-forwarded-host": "test-owt.craazzzyyfoxx.me",
      "x-forwarded-proto": "https",
    });
    expect(publicHost(r)).toBe("test-owt.craazzzyyfoxx.me");
    expect(publicHostname(r)).toBe("test-owt.craazzzyyfoxx.me");
    expect(publicOrigin(r)).toBe("https://test-owt.craazzzyyfoxx.me");
    expect(publicOrigin(r)).not.toContain("0.0.0.0");
  });

  it("takes the first value of a comma-joined forwarded list", () => {
    const r = req("http://0.0.0.0:3000/x", {
      "x-forwarded-host": "team.owt.craazzzyyfoxx.me, edge.internal",
      "x-forwarded-proto": "https, http",
    });
    expect(publicHost(r)).toBe("team.owt.craazzzyyfoxx.me");
    expect(publicOrigin(r)).toBe("https://team.owt.craazzzyyfoxx.me");
  });

  it("strips the port for publicHostname but keeps it in publicHost", () => {
    const r = req("http://x/y", { "x-forwarded-host": "localhost:3000", "x-forwarded-proto": "http" });
    expect(publicHost(r)).toBe("localhost:3000");
    expect(publicHostname(r)).toBe("localhost");
  });

  it("falls back to request.url host when no forwarded headers", () => {
    const r = req("http://localhost:3000/y");
    expect(publicHost(r)).toBe("localhost:3000");
    expect(publicOrigin(r)).toBe("http://localhost:3000");
  });
});
