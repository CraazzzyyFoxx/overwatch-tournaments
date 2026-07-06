import { describe, expect, it } from "bun:test";
import { PLATFORM_ZONE, resolveHost } from "@/lib/host";

describe("resolveHost", () => {
  it("treats apex + www as platform", () => {
    expect(resolveHost(PLATFORM_ZONE)).toEqual({ mode: "platform" });
    expect(resolveHost(`www.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
    expect(resolveHost(null)).toEqual({ mode: "platform" });
  });

  it("extracts a tenant subdomain", () => {
    expect(resolveHost(`team-a.${PLATFORM_ZONE}`)).toEqual({ mode: "tenant", subdomain: "team-a" });
    expect(resolveHost(`TEAM-A.${PLATFORM_ZONE}:443`)).toEqual({ mode: "tenant", subdomain: "team-a" });
  });

  it("rejects reserved + multi-segment labels as platform", () => {
    expect(resolveHost(`api.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
    expect(resolveHost(`a.b.${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
  });

  it("treats suffix-collision, foreign, and empty hosts as platform", () => {
    // Leading-dot suffix check must NOT match a host that merely ends with the zone string.
    expect(resolveHost(`evil${PLATFORM_ZONE}`)).toEqual({ mode: "platform" });
    expect(resolveHost("example.com")).toEqual({ mode: "platform" });
    expect(resolveHost("")).toEqual({ mode: "platform" });
  });
});
