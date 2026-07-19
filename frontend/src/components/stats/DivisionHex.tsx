import React from "react";
import { cn } from "@/lib/utils";
import { type AqtRoleKey, normalizeRole } from "@/components/hero/heroRole";

interface DivisionHexProps {
  division: number;
  role?: string | null;
  variant?: AqtRoleKey | "amber" | "violet" | "gold" | "gray";
  size?: number;
  className?: string;
}

/** Hex-shaped division badge, colored by role (or explicit variant). */
export const DivisionHex = ({ division, role, variant, size = 30, className }: DivisionHexProps) => {
  const normalized = variant ?? normalizeRole(role) ?? "gray";
  const bgClass = `aqt-bg-${normalized}`;
  const height = size * 1.13;
  return (
    <span
      className={cn("relative inline-flex items-center justify-center flex-shrink-0", className)}
      style={{ width: size, height }}
    >
      <span className={cn("absolute inset-0 aqt-hex-shape", bgClass)} />
      <span
        className="relative aqt-display font-extrabold leading-none"
        style={{
          fontSize: size * 0.45,
          color: "var(--aqt-bg)"
        }}
      >
        {division}
      </span>
    </span>
  );
};
