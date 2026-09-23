import { useTranslations } from "next-intl";
import TankIcon from "@/components/icons/TankIcon";
import DamageIcon from "@/components/icons/DamageIcon";
import SupportIcon from "@/components/icons/SupportIcon";
import FlexIcon from "@/components/icons/FlexIcon";
import { PLAYER_ROLE_LABEL_KEY } from "@/lib/roster/player-role";

/** Canonical English player role names, the only values that map to a glyph. */
const ROLE_ICON = {
  Tank: TankIcon,
  Damage: DamageIcon,
  Support: SupportIcon,
  Flex: FlexIcon
} as const;

type RoleName = keyof typeof ROLE_ICON;

/**
 * Player role glyph — tank, damage, support or flex.
 *
 * Renders nothing at all for an unrecognised or absent role — the wrapper used
 * to be emitted unconditionally, so an unknown role left an invisible element
 * that still claimed a slot in the surrounding flex/grid row.
 *
 * The glyph is announced as the localized role name by default. Pass
 * `decorative` (or `aria-hidden`) wherever the call site already renders the
 * role as visible or screen-reader-only text, so it is not announced twice.
 */
const PlayerRoleIcon = ({
  role,
  size = 24,
  color,
  decorative,
  label,
  "aria-hidden": ariaHidden
}: {
  role: string | null;
  size?: number;
  color?: string;
  /** Hide from assistive tech: the role is already announced next to the icon. */
  decorative?: boolean;
  /** Override the accessible name; defaults to the localized role name. */
  label?: string;
  "aria-hidden"?: boolean | "true" | "false";
}) => {
  const t = useTranslations();

  if (!role || !(role in ROLE_ICON)) {
    return null;
  }

  const roleName = role as RoleName;
  const Icon = ROLE_ICON[roleName];
  const hidden = decorative === true || ariaHidden === true || ariaHidden === "true";
  const accessibleName = label ?? t(PLAYER_ROLE_LABEL_KEY[roleName] as Parameters<typeof t>[0]);

  return (
    <span
      className="inline-flex"
      role={hidden ? undefined : "img"}
      aria-hidden={hidden || undefined}
      aria-label={hidden ? undefined : accessibleName}
    >
      <Icon height={size} width={size} color={color} />
    </span>
  );
};

export default PlayerRoleIcon;
