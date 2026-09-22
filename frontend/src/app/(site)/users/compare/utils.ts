import { MapRead } from "@/types/map.types";
import { PLAYER_ROLE_LABEL_KEY } from "@/lib/roster/player-role";
import { UserRoleType } from "@/types/user.types";
import { CompareScope } from "@/app/(site)/users/compare/types";

export const parseOptionalInt = (value: string | null): number | undefined => {
  if (!value) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return undefined;
  return Math.floor(parsed);
};

export const parseRole = (value: string | null): UserRoleType | undefined => {
  if (value === "Tank" || value === "Damage" || value === "Support" || value === "Flex") return value;
  return undefined;
};

export const parseScope = (value: string | null): CompareScope => {
  if (value === "hero") return "hero";
  return "overall";
};

export const normalizeNumber = (value: number | string | null | undefined): number | null => {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

export type RoleLabelKey = (typeof PLAYER_ROLE_LABEL_KEY)[UserRoleType];

export const roleLabelKey = (role: UserRoleType): RoleLabelKey => PLAYER_ROLE_LABEL_KEY[role];

export interface DurationUnits {
  h: string;
  m: string;
  s: string;
}

export const formatDuration = (
  secondsRaw: number,
  units: DurationUnits = { h: "h", m: "m", s: "s" }
): string => {
  const seconds = Math.max(0, Math.floor(secondsRaw));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;

  if (h > 0) return `${h}${units.h} ${m}${units.m} ${s}${units.s}`;
  if (m > 0) return `${m}${units.m} ${s}${units.s}`;
  return `${s}${units.s}`;
};

export const formatMetricValue = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }

  if (Number.isInteger(value)) {
    return value.toString();
  }

  return value.toFixed(2);
};

export const formatPercent = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }

  return `${value.toFixed(2)}%`;
};

export const getMapIconSrc = (map?: MapRead | null): string | null => {
  const candidate = map?.image_path || map?.gamemode?.image_path;
  if (!candidate) return null;
  if (candidate.trim().length === 0) return null;
  return candidate;
};
