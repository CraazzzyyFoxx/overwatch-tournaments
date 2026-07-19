"use client";

import React from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import styles from "../TournamentDetail.module.css";

type StateCopy = {
  title?: string;
  description?: string;
  className?: string;
};

type TournamentPageStateProps =
  | (StateCopy & {
      state: "initial-error";
      onRetry: () => void;
      children?: never;
      onReset?: never;
      isUpdating?: never;
    })
  | (StateCopy & {
      state: "refresh-error";
      onRetry: () => void;
      children: React.ReactNode;
      isUpdating?: boolean;
      onReset?: never;
    })
  | (StateCopy & {
      state: "empty";
      children?: never;
      onRetry?: never;
      onReset?: never;
      isUpdating?: never;
    })
  | (StateCopy & {
      state: "filtered-empty";
      onReset: () => void;
      children?: never;
      onRetry?: never;
      isUpdating?: never;
    });

export function TournamentPageState(props: TournamentPageStateProps) {
  const t = useTranslations();

  if (props.state === "refresh-error") {
    const title = props.title ?? t("tournamentDetail.pageState.refreshError.title");
    const description =
      props.description ?? t("tournamentDetail.pageState.refreshError.description");

    return (
      <div className={cn(styles.refreshState, props.className)}>
        {props.children}
        <div className={styles.refreshMessage} role="status" aria-live="polite">
          <span>
            <strong>{title}</strong> — {description}
          </span>
          <button type="button" className={styles.stateAction} onClick={props.onRetry}>
            {t("tournamentDetail.pageState.retry")}
          </button>
        </div>
        {props.isUpdating ? (
          <span className={styles.updating}>{t("tournamentDetail.pageState.updating")}</span>
        ) : null}
      </div>
    );
  }

  const copyKey =
    props.state === "initial-error"
      ? "initialError"
      : props.state === "filtered-empty"
        ? "filteredEmpty"
        : "empty";
  const title = props.title ?? t(`tournamentDetail.pageState.${copyKey}.title`);
  const description = props.description ?? t(`tournamentDetail.pageState.${copyKey}.description`);
  const titleId = `tournament-page-state-${props.state}-title`;

  return (
    <section
      className={cn(styles.stateCard, props.className)}
      role={props.state === "initial-error" ? "alert" : "status"}
      aria-labelledby={titleId}
    >
      <h2 id={titleId}>{title}</h2>
      <p>{description}</p>
      {props.state === "initial-error" ? (
        <button type="button" className={styles.stateAction} onClick={props.onRetry}>
          {t("tournamentDetail.pageState.retry")}
        </button>
      ) : null}
      {props.state === "filtered-empty" ? (
        <button type="button" className={styles.stateAction} onClick={props.onReset}>
          {t("tournamentDetail.pageState.resetFilters")}
        </button>
      ) : null}
    </section>
  );
}
