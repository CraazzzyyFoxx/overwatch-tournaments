import { describe, expect, it } from "bun:test";

import type { BuiltInFieldConfig } from "@/types/registration.types";
import type { SocialAccount } from "@/types/user.types";
import * as registrationValidation from "./validation";

const smurfTagsConfig: BuiltInFieldConfig = {
  enabled: true,
  required: false,
  validation: {
    regex: String.raw`([\w0-9]{2,12}#[0-9]{4,})`,
    error_message: "Each smurf BattleTag must match Player#1234.",
  },
};

const verifiedBattleTagConfig: BuiltInFieldConfig = {
  enabled: true,
  required: false,
  require_verified: true,
};

function account(partial: Partial<SocialAccount> & Pick<SocialAccount, "provider" | "username">): SocialAccount {
  return {
    id: 1,
    user_id: 1,
    url: null,
    is_verified: true,
    is_primary: false,
    ...partial,
  };
}

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

describe("require_verified identity validation", () => {
  it("returns null when the field is not gated", () => {
    expect(
      registrationValidation.getVerifiedFieldError(
        "battle_tag",
        "Player#1234",
        { enabled: true, required: false },
        [],
      ),
    ).toBeNull();
  });

  it("requires linking a verified account when the registrant has none", () => {
    expect(
      registrationValidation.getVerifiedFieldError(
        "battle_tag",
        "Player#1234",
        verifiedBattleTagConfig,
        [account({ provider: "discord", username: "someone" })],
      ),
    ).toBe("Link a verified BattleTag account via OAuth to register.");
  });

  it("accepts a value that matches a verified account (case/format-insensitive)", () => {
    expect(
      registrationValidation.getVerifiedFieldError(
        "battle_tag",
        " crazzzyyfoxx # 2875 ",
        verifiedBattleTagConfig,
        [account({ provider: "battlenet", username: "CrazzzyyFoxx#2875" })],
      ),
    ).toBeNull();
  });

  it("rejects a value that does not match any verified account", () => {
    expect(
      registrationValidation.getVerifiedFieldError(
        "battle_tag",
        "Other#9999",
        verifiedBattleTagConfig,
        [account({ provider: "battlenet", username: "CrazzzyyFoxx#2875" })],
      ),
    ).toBe("BattleTag must match an OAuth-verified account on your profile.");
  });

  it("ignores unverified accounts of the same provider", () => {
    expect(
      registrationValidation.getVerifiedFieldError(
        "battle_tag",
        "Player#1234",
        verifiedBattleTagConfig,
        [account({ provider: "battlenet", username: "Player#1234", is_verified: false })],
      ),
    ).toBe("Link a verified BattleTag account via OAuth to register.");
  });

  it("flags an empty value when a verified account exists", () => {
    expect(
      registrationValidation.getVerifiedFieldError(
        "discord_nick",
        "",
        { enabled: true, required: false, require_verified: true },
        [account({ provider: "discord", username: "verified_user" })],
      ),
    ).toBe("Select your verified Discord account.");
  });
});
