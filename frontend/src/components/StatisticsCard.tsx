"use client";

import type { ReactNode } from "react";
import { useFormatter } from "@/lib/datetime/client";

interface StatisticsCardProps {
  name: string;
  value: number | string;
  icon?: ReactNode;
  iconClassName?: string;
}

/**
 * Headline platform metric tile.
 *
 * Numbers go through next-intl's formatter, not a hardcoded `en-US`, so a
 * Russian reader sees `1 557` rather than `1,557`.
 */
const StatisticsCard = ({
  name,
  value,
  icon,
  iconClassName = "bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-dim)]"
}: StatisticsCardProps) => {
  const format = useFormatter();
  const formattedValue =
    typeof value === "number" && Number.isFinite(value) ? format.number(value) : value;

  return (
    <div className="relative flex flex-col gap-3 rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-5 py-4 transition-colors duration-200 hover:bg-[color:var(--aqt-overlay-2)]">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">{name}</p>
        {icon && (
          <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${iconClassName}`}>
            {icon}
          </div>
        )}
      </div>
      <div className="text-3xl font-bold tabular-nums tracking-tight text-[color:var(--aqt-fg)]">
        {formattedValue}
      </div>
    </div>
  );
};

export default StatisticsCard;
