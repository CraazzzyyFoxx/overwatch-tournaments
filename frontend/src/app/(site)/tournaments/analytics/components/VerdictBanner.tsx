"use client";

import React from "react";

import { useTranslation } from "@/i18n/LanguageContext";
import { CommunityVerdict, formatPlace } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import InfoDot from "@/app/(site)/tournaments/analytics/components/InfoDot";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface VerdictBannerProps {
  verdict: CommunityVerdict;
  onExplain?: (term: GlossaryTerm) => void;
}

/** Render a sentence, bolding the first occurrence of the team name. */
function highlightTeam(
  text: string,
  name: string,
  Wrapper: "b" | "strong",
): React.ReactNode {
  const index = text.indexOf(name);
  if (index === -1) return text;
  return (
    <>
      {text.slice(0, index)}
      <Wrapper>{name}</Wrapper>
      {text.slice(index + name.length)}
    </>
  );
}

/**
 * The headline "who's the story / who's the let-down" banner. Bolds the team
 * names and renders the let-down (when present) as a supporting line. Stays
 * quiet — a single calm sentence — when no team has strayed from its forecast.
 */
export default function VerdictBanner({ verdict, onExplain }: VerdictBannerProps) {
  const { t, locale } = useTranslation();
  const { story, letdown } = verdict;

  return (
    <div className={styles.cVerdict}>
      <div className={styles.cVerdictEyebrow}>{t("analytics.community.verdict.eyebrow")}</div>
      {story ? (
        <h2 className={styles.cVerdictH}>
          {highlightTeam(
            t("analytics.community.verdict.story", {
              team: story.name,
              predicted: formatPlace(story.predicted, locale),
              place: formatPlace(story.place, locale),
            }),
            story.name,
            "b",
          )}
        </h2>
      ) : (
        <h2 className={styles.cVerdictH}>{t("analytics.community.verdict.empty")}</h2>
      )}
      {letdown ? (
        <p className={styles.cVerdictSub}>
          {highlightTeam(
            t("analytics.community.verdict.letdown", {
              team: letdown.name,
              predicted: formatPlace(letdown.predicted, locale),
              place: formatPlace(letdown.place, locale),
            }),
            letdown.name,
            "strong",
          )}{" "}
          <InfoDot term="predicted_move" onExplain={onExplain} />
        </p>
      ) : null}
    </div>
  );
}
