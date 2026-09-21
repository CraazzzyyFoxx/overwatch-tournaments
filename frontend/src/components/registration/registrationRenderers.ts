import type { RendererRegistry } from "@/components/forms/types";
import { IDENTITY_PROVIDERS, identityKey } from "@/lib/forms/builtin-keys";

import BattleTagField from "./fields/BattleTagField";
import IdentityField from "./fields/IdentityField";
import NotesField from "./fields/NotesField";
import RolesField from "./fields/RolesField";
import SmurfTagsField from "./fields/SmurfTagsField";
import StreamPovField from "./fields/StreamPovField";

/**
 * Which component answers which builtin key.
 *
 * Every entry here is a key the SERVER owns the behaviour of — the verified
 * accounts, the BattleTag grammar, the role composition — so the registry is a
 * fixed table, not something a form can extend. A key with no entry falls
 * through to `GenericField`, which is the right answer for every custom
 * question and a survivable one for a builtin a newer server has added.
 */
export const registrationRenderers: RendererRegistry = {
  battle_tag: BattleTagField,
  smurf_tags: SmurfTagsField,
  roles: RolesField,
  stream_pov: StreamPovField,
  public_notes: NotesField,
  organizer_notes: NotesField,
  ...Object.fromEntries(
    IDENTITY_PROVIDERS.map((provider) => [identityKey(provider), IdentityField] as const),
  ),
};
