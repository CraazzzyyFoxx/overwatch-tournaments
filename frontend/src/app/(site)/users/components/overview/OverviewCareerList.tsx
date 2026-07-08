import React from "react";
import { getTranslations } from "next-intl/server";
import { Medal } from "lucide-react";
import { UserProfile } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";

interface Props {
  profile: UserProfile;
}

const fmt = (value: number | null | undefined, digits = 2, suffix = "") => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}${suffix}`;
};

const Row = ({ label, value, highlight }: { label: string; value: string; highlight?: string }) => (
  <div className="flex items-center justify-between border-b border-[color:var(--aqt-border)] px-[18px] py-[9px] last:border-b-0">
    <span className="text-[12.5px] text-[color:var(--aqt-fg-muted)]">{label}</span>
    <span
      className="aqt-tnum text-[13px] font-bold"
      style={{ color: highlight ?? "var(--aqt-fg)" }}
    >
      {value}
    </span>
  </div>
);

const OverviewCareerList = async ({ profile }: Props) => {
  const t = await getTranslations();
  const winrate = profile.maps_total > 0 ? (profile.maps_won / profile.maps_total) * 100 : null;
  const proximity = profile.avg_closeness === null ? null : profile.avg_closeness * 100;

  return (
    <CardSurface flush title={t("users.overview.career.title")} icon={<Medal size={15} />}>
      <Row label={t("users.overview.career.tournaments")} value={`${profile.tournaments_count}`} />
      <Row
        label={t("users.overview.career.tournamentsWon")}
        value={`${profile.tournaments_won}`}
        highlight={profile.tournaments_won > 0 ? "var(--aqt-amber)" : undefined}
      />
      <Row label={t("users.overview.career.winrate")} value={fmt(winrate, 2, "%")} />
      <Row label={t("users.overview.career.maps")} value={`${profile.maps_won} / ${profile.maps_total}`} />
      <Row label={t("users.overview.career.proximity")} value={fmt(proximity, 0, "%")} />
      <Row label={t("users.overview.career.avgPlacement")} value={fmt(profile.avg_placement)} />
      <Row label={t("users.overview.career.avgPlayoffPlace")} value={fmt(profile.avg_playoff_placement)} />
      <Row label={t("users.overview.career.avgGroupPlace")} value={fmt(profile.avg_group_placement, 0)} />
    </CardSurface>
  );
};

export default OverviewCareerList;
