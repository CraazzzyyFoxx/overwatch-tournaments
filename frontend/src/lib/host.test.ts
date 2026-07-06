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
});
