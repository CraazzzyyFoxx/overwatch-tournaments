"use client";

import React from "react";
import { ChevronRight } from "lucide-react";

import { useTranslations } from "next-intl";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface HowItWorksCardProps {
  onOpen: () => void;
}

/** The "New here? Read the analytics in 30s" prompt that opens the explainer. */
export default function HowItWorksCard({ onOpen }: HowItWorksCardProps) {
  const t = useTranslations();
  return (
    <button type="button" className={styles.cHowCard} onClick={onOpen}>
      <span className={styles.cHowMark}>?</span>
      <span style={{ flex: 1 }}>
        <span className={styles.cHowTitle}>{t("analytics.howItWorks.cardTitle")}</span>
        <span className={styles.cHowSub}>{t("analytics.howItWorks.cardSubtitle")}</span>
      </span>
      <ChevronRight size={16} className={styles.cChevron} aria-hidden="true" />
    </button>
  );
}
