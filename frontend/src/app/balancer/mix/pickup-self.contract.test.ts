import { describe, expect, it } from "vitest";

import { RESOURCE_QUERY_KEYS } from "@/lib/realtime/resources";
import { customGameKeys } from "@/services/custom-game.service";

/**
 * The seat panel is refreshed by somebody ELSE's write -- another player
 * joining, the host benching them -- and it gets that for free only while its
 * query key stays UNDER the key `workspace.pickup_mix` drops
 * (`lib/realtime/resources.ts`). A key of its own (`["custom-game-me", …]`)
 * type-checks, renders and then silently stops updating until a reload, which
 * is exactly the failure a pickup board must not have.
 */
describe("the caller's own seat", () => {
  it("is dropped by the mix realtime resource", () => {
    const dropped = RESOURCE_QUERY_KEYS["workspace.pickup_mix"](7, {});
    const me = customGameKeys.me(7, 12);

    expect(
      dropped.some((key) => key.length <= me.length && key.every((part, index) => part === me[index])),
    ).toBe(true);
  });

  it("separates two mixes in the same workspace", () => {
    expect(customGameKeys.me(7, 12)).not.toEqual(customGameKeys.me(7, 13));
  });
});
