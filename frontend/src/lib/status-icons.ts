"use client";

import * as LucideIcons from "lucide-react";
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

export function getStatusIcon(iconSlug: string | null | undefined): LucideIcon {
  if (!iconSlug) {
    return BadgeHelp;
  }
  const candidate = (LucideIcons as Record<string, unknown>)[iconSlug];
  return candidate ? (candidate as LucideIcon) : BadgeHelp;
}
