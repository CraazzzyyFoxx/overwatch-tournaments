"use client";

import {
  AlertTriangle,
  BadgeHelp,
  Bell,
  CheckCircle2,
  CircleDashed,
  Clock,
  Flag,
  Flame,
  Hourglass,
  Medal,
  MinusCircle,
  Radio,
  Rocket,
  ShieldBan,
  ShieldCheck,
  ShieldOff,
  Star,
  TimerReset,
  Undo2,
  UserCheck,
  UserRoundPlus,
  Users,
  XCircle,
  Zap,
  type LucideIcon,
} from "lucide-react";

export type StatusIconOption = {
  slug: string;
  Icon: LucideIcon;
};

export const STATUS_ICON_OPTIONS: StatusIconOption[] = [
  { slug: "BadgeHelp", Icon: BadgeHelp },
  { slug: "Clock", Icon: Clock },
  { slug: "CheckCircle2", Icon: CheckCircle2 },
  { slug: "XCircle", Icon: XCircle },
  { slug: "AlertTriangle", Icon: AlertTriangle },
  { slug: "MinusCircle", Icon: MinusCircle },
  { slug: "Undo2", Icon: Undo2 },
  { slug: "ShieldBan", Icon: ShieldBan },
  { slug: "ShieldOff", Icon: ShieldOff },
  { slug: "ShieldCheck", Icon: ShieldCheck },
  { slug: "Flag", Icon: Flag },
  { slug: "Bell", Icon: Bell },
  { slug: "Star", Icon: Star },
  { slug: "Flame", Icon: Flame },
  { slug: "Zap", Icon: Zap },
  { slug: "Rocket", Icon: Rocket },
  { slug: "Hourglass", Icon: Hourglass },
  { slug: "TimerReset", Icon: TimerReset },
  { slug: "Radio", Icon: Radio },
  { slug: "Users", Icon: Users },
  { slug: "UserCheck", Icon: UserCheck },
  { slug: "UserRoundPlus", Icon: UserRoundPlus },
  { slug: "Medal", Icon: Medal },
  { slug: "CircleDashed", Icon: CircleDashed },
];

// A Map, not an object literal: the slug is free-form data, and `"constructor"`
// would otherwise resolve to `Object`.
const ICONS_BY_SLUG = new Map<string, LucideIcon>(STATUS_ICON_OPTIONS.map(({ slug, Icon }) => [slug, Icon]));

/**
 * Resolves an icon slug against the icons the admin picker offers. The backend
 * stores `icon_slug` as a free-form string, so anything else falls back to
 * `BadgeHelp` — the alternative, a `lucide-react` namespace import, pulls the
 * whole 700 KB icon set into every route that renders a status.
 */
export function getStatusIcon(iconSlug: string | null | undefined): LucideIcon {
  return (iconSlug && ICONS_BY_SLUG.get(iconSlug)) || BadgeHelp;
}
