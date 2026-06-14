import { describe, expect, it } from "bun:test";

import type { BuiltInFieldConfig } from "@/types/registration.types";
import * as registrationValidation from "./validation";

const smurfTagsConfig: BuiltInFieldConfig = {
  enabled: true,
  required: false,
  validation: {
    regex: String.raw`([\w0-9]{2,12}#[0-9]{4,})`,
    error_message: "Each smurf BattleTag must match Player#1234.",
  },
};

describe("registration validation helpers", () => {
  it("returns the first live validation error for the current step", () => {
    expect(
      registrationValidation.getFirstLiveValidationError(
        {
          battle_tag: null,
          discord_nick: "Discord format is invalid.",
          twitch_nick: "Twitch format is invalid.",
        },
        ["battle_tag", "discord_nick", "twitch_nick"],
      ),
    ).toBe("Discord format is invalid.");
  });

  it("hides the footer validation message when the same problem is already shown inline", () => {
    expect(
      registrationValidation.getStepDisplayValidationError(
        "BattleTag format is invalid.",
        "BattleTag format is invalid.",
      ),
    ).toBeNull();

    expect(
      registrationValidation.getStepDisplayValidationError(
        null,
        "BattleTag is required.",
      ),
    ).toBe("BattleTag is required.");
  });

  it("uses the default BattleTag mask when the form has no explicit battle_tag validation", () => {
    expect(
      registrationValidation.getBuiltInValueValidationError(
        "battle_tag",
        "dsadasdas",
      ),
    ).toBe("BattleTag format is invalid.");

    expect(
      registrationValidation.getBuiltInValueValidationError(
        "battle_tag",
        " CrazzzyyFoxx # 2875 ",
      ),
    ).toBeNull();
  });

  it("rejects invalid smurf BattleTags before they are added to the list", () => {
    expect(
      registrationValidation.getBuiltInValueValidationError?.(
        "smurf_tags",
        "dsadasdas",
        smurfTagsConfig,
      ),
    ).toBe("Each smurf BattleTag must match Player#1234.");
  });

  it("normalizes smurf BattleTags before validating them", () => {
    expect(
      registrationValidation.getBuiltInValueValidationError?.(
        "smurf_tags",
        " CrazzzyyFoxx # 2875 ",
        smurfTagsConfig,
      ),
    ).toBeNull();
    expect(
      registrationValidation.normalizeBuiltInFieldValue?.(
        "smurf_tags",
        " CrazzzyyFoxx # 2875 ",
      ),
    ).toBe("CrazzzyyFoxx#2875");
  });
});
