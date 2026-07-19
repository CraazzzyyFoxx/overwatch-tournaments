import { describe, expect, it } from "bun:test";
import { PLATFORM_ZONE, resolveHost } from "@/lib/host";

describe("resolveHost", () => {
  it("treats apex + www as platform", () => {
    expect(resolveHost(PLATFORM_ZONE)).toEqual({ mode: "platform" });
    expect(resolveHost(`www.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
    expect(resolveHost(null)).toEqual({ mode: "platform" });
  });

  it("returns lookup host for subdomains and custom domains", () => {
    expect(resolveHost(`team-a.${PLATFORM_ZONE}`)).toEqual({ mode: "tenant", host: `team-a.${PLATFORM_ZONE}` });
    expect(resolveHost(`TEAM-A.${PLATFORM_ZONE}:443`)).toEqual({ mode: "tenant", host: `team-a.${PLATFORM_ZONE}` });
    expect(resolveHost("tourney.customer.com")).toEqual({ mode: "tenant", host: "tourney.customer.com" });
  });

  it("rejects reserved + multi-segment platform-zone labels as platform", () => {
    expect(resolveHost(`api.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
    expect(resolveHost(`a.b.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
  });

  it("treats a suffix-collision host as a plain custom-domain lookup, not a platform-zone match", () => {
    // Leading-dot suffix check must NOT match a host that merely ends with the zone string —
    // it falls through to the generic dotted-host case and is sent to the backend as a
    // full-host lookup (which will legitimately not_found it), not special-cased as platform.
    expect(resolveHost(`evil${PLATFORM_ZONE}`)).toEqual({ mode: "tenant", host: `evil${PLATFORM_ZONE}` });
  });

  it("treats apex, www, localhost, IP, and no-dot hosts as platform", () => {
    for (const h of [PLATFORM_ZONE, `www.${PLATFORM_ZONE}`, "localhost:3000", "127.0.0.1", "gateway", ""]) {
      expect(resolveHost(h)).toEqual({ mode: "platform" });
    }
  });
});
