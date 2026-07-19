"use client";

import React from "react";
import { ScrollText } from "lucide-react";
import { useTranslations } from "next-intl";

import type { Achievement } from "@/types/achievement.types";
import ConditionTreeView from "@/app/(site)/achievements/components/ConditionTreeView";

interface Props {
  achievement: Achievement;
}

/** "How to earn" panel: the condition tree the achievement engine evaluates,
 *  rendered in the tactical card language. */
const AchievementConditionsCard = ({ achievement }: Props) => {
  const t = useTranslations();

  return (
    <section className="aqt-card-surface self-start">
      <div className="aqt-card-head">
        <div className="aqt-card-title">
          <span className="aqt-card-title-ic">
            <ScrollText size={15} />
          </span>
          <span>{t("achievements.conditionsTitle")}</span>
        </div>
      </div>
      <div className="aqt-card-body">
        {achievement.condition_tree ? (
          <ConditionTreeView tree={achievement.condition_tree} />
        ) : (
          <p className="text-sm text-[color:var(--aqt-fg-dim)]">
            {t("achievements.noConditionsDefined")}
          </p>
        )}
      </div>
    </section>
  );
};

export default AchievementConditionsCard;
