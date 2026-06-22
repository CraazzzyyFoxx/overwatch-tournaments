"use client";

import React, { useEffect } from "react";

import { useTranslation } from "@/i18n/LanguageContext";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

export type SheetState =
  | { kind: "term"; term: GlossaryTerm }
  | { kind: "how" };

interface BottomSheetProps {
  state: SheetState | null;
  onClose: () => void;
}

function TermBody({ term }: { term: GlossaryTerm }) {
  const { t } = useTranslation();
  return (
    <>
      <div className={styles.cSheetKicker}>{t("analytics.sheet.glossaryKicker")}</div>
      <h3>{t(`analytics.glossary.${term}.label`)}</h3>
      <p>{t(`analytics.glossary.${term}.plain`)}</p>
    </>
  );
}

function HowBody() {
  const { t } = useTranslation();
  const steps = [1, 2, 3] as const;
  return (
    <>
      <div className={styles.cSheetKicker}>{t("analytics.howItWorks.kicker")}</div>
      <h3>{t("analytics.howItWorks.title")}</h3>
      <p>{t("analytics.howItWorks.intro")}</p>
      <div style={{ margin: "4px 0 14px" }}>
        {steps.map((step) => (
          <div className={styles.cSheetStep} key={step}>
            <span className={styles.cSheetStepNum}>{step}</span>
            <span>
              <span className={styles.cSheetStepTitle}>
                {t(`analytics.howItWorks.step${step}Title`)}
              </span>
              <span className={styles.cSheetStepBody}>
                {t(`analytics.howItWorks.step${step}Body`)}
              </span>
            </span>
          </div>
        ))}
      </div>
      <p className={styles.cSheetFoot}>{t("analytics.howItWorks.foot")}</p>
    </>
  );
}

/**
 * The glossary / how-it-works explainer overlay — a bottom sheet on mobile, a
 * centered modal ≥760px. Opened by info dots, dotted terms and the help card.
 */
export default function BottomSheet({ state, onClose }: BottomSheetProps) {
  const { t } = useTranslation();
  const open = state != null;
  const label =
    state?.kind === "how"
      ? t("analytics.howItWorks.title")
      : state?.kind === "term"
        ? t(`analytics.glossary.${state.term}.label`)
        : undefined;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      <div
        className={styles.cSheetScrim}
        data-open={open}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={styles.cSheet}
        data-open={open}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
        aria-label={label}
      >
        <div className={styles.cSheetGrip} />
        <div className={styles.cSheetBody}>
          {state?.kind === "term" ? <TermBody term={state.term} /> : null}
          {state?.kind === "how" ? <HowBody /> : null}
        </div>
      </div>
    </>
  );
}
