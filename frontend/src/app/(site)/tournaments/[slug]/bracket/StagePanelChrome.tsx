"use client";

import type { ReactNode } from "react";
import { ListOrdered, Network } from "lucide-react";
import { useTranslations } from "next-intl";

import { LinkTabs } from "@/components/kit/LinkTabs";
import { Badge } from "@/components/ui/badge";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";

import type { BracketTabs } from "./bracketStages.model";

/**
 * Standings ⇄ bracket switch, icon-only like the tournaments list's view
 * switch. A mode switch that owns panels, so it is `Tabs` in the pill drawing.
 */
export function ViewTabs({
  hasStandings,
  bracketValue
}: Readonly<{ hasStandings: boolean; bracketValue: string }>) {
  const t = useTranslations();

  return (
    <TabsList variant="pill">
      {hasStandings && (
        <TabsTrigger value="standings">
          <ListOrdered aria-hidden width={14} height={14} />
          <span className="sr-only">{t("common.standings")}</span>
        </TabsTrigger>
      )}
      <TabsTrigger value={bracketValue}>
        <Network aria-hidden width={14} height={14} />
        <span className="sr-only">{t("common.bracket")}</span>
      </TabsTrigger>
    </TabsList>
  );
}

type StagePanelHeaderProps = {
  /** The stage tab rail, when there is more than one stage to switch between. */
  bracketTabs?: BracketTabs;
  /** Heading for the single-stage case: the stage item's name, else the stage's. */
  title: string;
  /** The mono line under it — the stage type, optionally prefixed by the stage. */
  subtitle: string;
  /** A stage the organizer generated but has not published yet. */
  isPreview: boolean;
  /**
   * Rendered beside the rail. The group panel puts the stage item's name and
   * its preview badge here, the elimination panel only the badge — so this is
   * the caller's call rather than a flag.
   */
  railSuffix?: ReactNode;
  viewTabs: ReactNode;
};

/**
 * The bar above every stage panel: either the stage rail or a heading, plus
 * the standings/bracket switch on the trailing side.
 */
export function StagePanelHeader({
  bracketTabs,
  title,
  subtitle,
  isPreview,
  railSuffix,
  viewTabs
}: Readonly<StagePanelHeaderProps>) {
  const t = useTranslations();
  const hasRail = bracketTabs !== undefined && bracketTabs.items.length > 1;

  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-4 py-4 sm:items-center">
      {hasRail ? (
        <div className="flex min-w-0 flex-col items-start gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <LinkTabs
              variant="pill"
              items={bracketTabs.items}
              activeKey={bracketTabs.activeKey}
              ariaLabel={t("tournamentDetail.stageTabsLabel")}
            />
            {railSuffix}
          </div>
          <Eyebrow as="p" tone="dim">
            {subtitle}
          </Eyebrow>
        </div>
      ) : (
        <div className="min-w-0">
          <h3 className="truncate text-lg font-semibold text-[color:var(--aqt-fg)]">
            {title}
            {isPreview && (
              <Badge variant="outline" className="ml-2 align-middle">
                {t("common.bracketPreview")}
              </Badge>
            )}
          </h3>
          <Eyebrow as="p" tone="dim" className="mt-1">
            {subtitle}
          </Eyebrow>
        </div>
      )}

      {viewTabs}
    </div>
  );
}
