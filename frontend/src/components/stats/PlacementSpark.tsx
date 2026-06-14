import React from "react";
import { cn } from "@/lib/utils";

interface SparkPoint {
  label: string;
  placement: number;
}

/** Tiny bar chart of tournament placements (lower = better; #1 highlighted). */
export const PlacementSpark = ({ data, max }: { data: SparkPoint[]; max?: number }) => {
  if (!data.length) return null;
  const top = max ?? Math.max(...data.map((d) => d.placement), 1);
  return (
    <div className="aqt-place-spark">
      {data.map((d, i) => {
        const heightPct = Math.max(6, 100 - (d.placement / top) * 100);
        const cls = d.placement === 1 ? "first" : d.placement <= 3 ? "podium" : "";
        return (
          <div key={i} className={cn("aqt-col", cls)} title={`#${d.placement} · ${d.label}`}>
            <span className="aqt-val">#{d.placement}</span>
            <div className="aqt-bar" style={{ height: `${heightPct}%` }} />
            <span className="aqt-lbl">{d.label}</span>
          </div>
        );
      })}
    </div>
  );
};
