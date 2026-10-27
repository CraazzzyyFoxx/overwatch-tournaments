"use client";

import * as React from "react";
import { AlertCircle, Inbox, SearchX, FileQuestion } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type PageStateKind = "error" | "empty" | "filtered-empty" | "not-found";

interface PageStateCardProps {
  state: PageStateKind;
  title?: string;
  description?: string;
  /** Shown for `error`; also used as "Clear filters" for `filtered-empty`. */
  onAction?: () => void;
  actionLabel?: string;
  /**
   * The title's heading level: `2` for a card under the page's own `<h1>` (a section, a tab, a detail pane);
   * `1` when the card stands in for the whole page (a gate, a not-found or failed page) and no other `<h1>` renders.
   */
  headingLevel?: 1 | 2;
  className?: string;
}

const ICONS: Record<PageStateKind, React.ComponentType<{ className?: string }>> = {
  error: AlertCircle,
  empty: Inbox,
  "filtered-empty": SearchX,
  "not-found": FileQuestion
};

// Full literal keys, not `common.pageState.${state}` template strings: next-intl
// is configured with typed messages, and a template literal widens to `string`,
// which the typed `t()` rightly rejects.
const COPY: Record<PageStateKind, { title: string; description: string }> = {
  error: {
    title: "common.pageState.error.title",
    description: "common.pageState.error.description"
  },
  empty: {
    title: "common.pageState.empty.title",
    description: "common.pageState.empty.description"
  },
  "filtered-empty": {
    title: "common.pageState.filteredEmpty.title",
    description: "common.pageState.filteredEmpty.description"
  },
  "not-found": {
    title: "common.pageState.notFound.title",
    description: "common.pageState.notFound.description"
  }
};

/**
 * The single empty / error / not-found surface for the public site.
 *
 * Before this existed the site had four competing error designs and a dozen
 * bare-text fallbacks, and — worse — several routes had no error branch at all,
 * so a failed fetch was rendered to the user as "there is nothing here". Every
 * state here carries an explanation and, where recovery is possible, an action.
 */
export function PageStateCard({
  state,
  title,
  description,
  onAction,
  actionLabel,
  headingLevel = 2,
  className
}: Readonly<PageStateCardProps>) {
  const t = useTranslations();
  const Icon = ICONS[state];
  const Heading = headingLevel === 1 ? "h1" : "h2";

  const copy = COPY[state];
  const resolvedTitle = title ?? t(copy.title as never);
  // The default empty copy speaks of tournaments being played: it belongs to the default title, not to a caller's
  // own empty state (an organizer's "No stages yet", "Select a workspace").
  const resolvedDescription =
    description ?? (state === "empty" && title != null ? null : t(copy.description as never));
  const resolvedActionLabel =
    actionLabel ?? (state === "filtered-empty" ? t("common.clearFilters") : t("common.retry"));

  return (
    <Card
      asChild
      className={cn("flex flex-col items-center gap-3 px-6 py-10 text-center", className)}
    >
      <section
        // `error` is the only state that reports a failure the user did not cause,
        // so it is the only one announced assertively.
        role={state === "error" ? "alert" : "status"}
      >
        <Icon
          aria-hidden
          className={cn(
            "size-6",
            state === "error" ? "text-[color:var(--aqt-rose)]" : "text-[color:var(--aqt-fg-faint)]"
          )}
        />
        <div className="space-y-1">
          <Heading className="text-body font-semibold text-[color:var(--aqt-fg)]">
            {resolvedTitle}
          </Heading>
          {resolvedDescription ? (
            <p className="mx-auto max-w-prose text-caption text-[color:var(--aqt-fg-muted)]">
              {resolvedDescription}
            </p>
          ) : null}
        </div>
        {onAction ? (
          <Button variant="outline" size="sm" className="mt-1" onClick={onAction}>
            {resolvedActionLabel}
          </Button>
        ) : null}
      </section>
    </Card>
  );
}
