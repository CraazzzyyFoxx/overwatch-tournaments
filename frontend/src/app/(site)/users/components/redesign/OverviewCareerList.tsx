import React from "react";
import { UserProfile } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/redesign/atoms";

interface Props {
  profile: UserProfile;
}

const fmt = (value: number | null | undefined, digits = 2, suffix = "") => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}${suffix}`;
};

const Row = ({ label, value, highlight }: { label: string; value: string; highlight?: string }) => (
  <div className="flex items-center justify-between border-b border-[color:var(--aqt-border)] px-[18px] py-[11px] last:border-b-0">
    <span className="text-[color:var(--aqt-fg-muted)]">{label}</span>
    <span
      className="aqt-tnum text-[15px] font-bold"
      style={{ color: highlight ?? "var(--aqt-fg)" }}
    >
      {value}
    </span>
  </div>
);

const OverviewCareerList = ({ profile }: Props) => {
  const winrate = profile.maps_total > 0 ? (profile.maps_won / profile.maps_total) * 100 : null;
  const proximity = profile.avg_closeness === null ? null : profile.avg_closeness * 100;

  return (
    <CardSurface flush title="Career" icon={<span>◧</span>}>
      <Row label="Tournaments" value={`${profile.tournaments_count}`} />
      <Row
        label="Tournaments won"
        value={`${profile.tournaments_won}`}
        highlight={profile.tournaments_won > 0 ? "var(--aqt-amber)" : undefined}
      />
      <Row label="Winrate" value={fmt(winrate, 2, "%")} />
      <Row label="Maps" value={`${profile.maps_won} / ${profile.maps_total}`} />
      <Row label="Proximity" value={fmt(proximity, 0, "%")} />
      <Row label="Avg placement" value={fmt(profile.avg_placement)} />
      <Row label="Avg playoff place" value={fmt(profile.avg_playoff_placement)} />
      <Row label="Avg group place" value={fmt(profile.avg_group_placement, 0)} />
    </CardSurface>
  );
};

export default OverviewCareerList;
