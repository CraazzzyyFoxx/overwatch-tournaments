import {
  Crosshair,
  Globe,
  Layers,
  Map,
  Swords,
  Target,
  Trophy,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";

import type {
  AchievementCategory,
  AchievementGrain,
  AchievementScope,
} from "@/types/admin.types";

/**
 * The vocabulary both achievement screens speak: the enum values a rule can
 * take and the icon each one is drawn with. The list and the detail page used
 * to keep private copies that drifted apart.
 */
export const CATEGORIES: AchievementCategory[] = [
  "overall",
  "hero",
  "division",
  "team",
  "standing",
  "match"
];
export const SCOPES: AchievementScope[] = ["global", "tournament", "match"];
export const GRAINS: AchievementGrain[] = ["user", "user_tournament", "user_match"];

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  overall: Globe,
  hero: Crosshair,
  division: Layers,
  team: Users,
  standing: Trophy,
  match: Swords
};

const SCOPE_ICONS: Record<string, LucideIcon> = {
  global: Globe,
  tournament: Trophy,
  match: Map
};

const GRAIN_ICONS: Record<string, LucideIcon> = {
  user: User,
  user_tournament: Target,
  user_match: Crosshair
};

/** Table-cell form: icon plus the value itself, for the rule list. */
export function IconLabel({ icon: Icon, label }: Readonly<{ icon: LucideIcon; label: string }>) {
  return (
    <span className="flex items-center gap-1.5">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      <span className="capitalize">{label}</span>
    </span>
  );
}

export function categoryIcon(category: string): LucideIcon {
  return CATEGORY_ICONS[category] ?? Globe;
}

export function scopeIcon(scope: string): LucideIcon {
  return SCOPE_ICONS[scope] ?? Globe;
}

export function grainIcon(grain: string): LucideIcon {
  return GRAIN_ICONS[grain] ?? User;
}

/** Detail-card form: the icon alone, beside a labelled value. */
export function CategoryIcon({ category }: Readonly<{ category: string }>) {
  const Icon = categoryIcon(category);
  return <Icon className="h-4 w-4 text-muted-foreground" />;
}

export function ScopeIcon({ scope }: Readonly<{ scope: string }>) {
  const Icon = scopeIcon(scope);
  return <Icon className="h-4 w-4 text-muted-foreground" />;
}

export function GrainIcon({ grain }: Readonly<{ grain: string }>) {
  const Icon = grainIcon(grain);
  return <Icon className="h-4 w-4 text-muted-foreground" />;
}
