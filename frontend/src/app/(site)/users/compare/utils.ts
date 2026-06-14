import { MapRead } from "@/types/map.types";
import { UserRoleType } from "@/types/user.types";
import { CompareScope } from "@/app/(site)/users/compare/types";

export const parsePositiveInt = (value: string | null, fallback: number): number => {
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.floor(parsed);
};

export const parseOptionalInt = (value: string | null): number | undefined => {
  if (!value) return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return undefined;
  return Math.floor(parsed);
};

export const parseRole = (value: string | null): UserRoleType | undefined => {
  if (value === "Tank" || value === "Damage" || value === "Support") return value;
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

export const formatDuration = (secondsRaw: number): string => {
  const seconds = Math.max(0, Math.floor(secondsRaw));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;

  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
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

const clampByte = (value: number): number => Math.max(0, Math.min(255, Math.round(value)));

const parseHexColor = (color: string): [number, number, number] | null => {
  const raw = color.trim().replace("#", "");
  if (![3, 6].includes(raw.length)) return null;

  const normalized =
    raw.length === 3 ? raw.split("").map((char) => `${char}${char}`).join("") : raw;

  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);

  if ([r, g, b].some((channel) => Number.isNaN(channel))) return null;
  return [r, g, b];
};

const parseRgbColor = (color: string): [number, number, number] | null => {
  const match = color.trim().match(/^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/i);
  if (!match) return null;

  const channels = [
    Number.parseInt(match[1], 10),
    Number.parseInt(match[2], 10),
    Number.parseInt(match[3], 10)
  ];

  if (channels.some((channel) => Number.isNaN(channel))) return null;
  return [clampByte(channels[0]), clampByte(channels[1]), clampByte(channels[2])];
};

const tintColor = (rgb: [number, number, number], delta: number): [number, number, number] => {
  const [r, g, b] = rgb;
  return [clampByte(r + delta), clampByte(g + delta), clampByte(b + delta)];
};

const toTriplet = (rgb: [number, number, number]): string => `${rgb[0]} ${rgb[1]} ${rgb[2]}`;

export const getGlowVarsFromColor = (
  dominantColor?: string | null
): { "--lg-a": string; "--lg-b": string; "--lg-c": string } | null => {
  if (!dominantColor) return null;

  const rgb = parseHexColor(dominantColor) ?? parseRgbColor(dominantColor);
  if (!rgb) return null;

  return {
    "--lg-a": toTriplet(rgb),
    "--lg-b": toTriplet(tintColor(rgb, 26)),
    "--lg-c": toTriplet(tintColor(rgb, -32))
  };
};
