"use client";

import { forwardRef, type CSSProperties, type ReactNode } from "react";
import { Pencil, ShieldX } from "lucide-react";
import { useTranslations } from "next-intl";

import { HandleLabel } from "@/components/HandleLabel";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger
} from "@/components/ui/context-menu";
import { hasBlockingIssues } from "@/components/balancer/balancer-page-helpers";
import {
  isRoleEntryActive,
  type PlayerValidationIssue
} from "@/components/balancer/workspace-helpers";
import { roleTint, type RoleOntology } from "@/lib/roster/ontology";
import { cn } from "@/lib/utils";
import type { AdminRegistration, BalancerPlayerRecord } from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";

import {
  BalancerStatusContextMenuItems,
  BalancerStatusMenu,
  type StatusOptionGroups
} from "./BalancerStatusMenu";
import {
  AdditionalHandleStrip,
  HandleContextMenuItems,
  HandleCopyButton
} from "./HandleCopyControls";
import { IssueChip, issueChipKey, useIssueMessage } from "./IssueChip";

export type PoolPlayerCardProps = {
  player: BalancerPlayerRecord;
  issues: PlayerValidationIssue[];
  registration: AdminRegistration | null;
  statusOptions?: StatusOptionGroups;
  /** The tournament owner's role dictionary: role glyphs and tints. `null` while it loads. */
  ontology: RoleOntology | null;
  /** The owner game's grid the division crest resolves in. */
  divisionGrid: DivisionGrid;
  selected: boolean;
  actionsDisabled: boolean;
  onSelectPlayer?: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
  /** `row`: a dense pool-list row, actions on the name line. `card`: a triage-lane card, actions on their own line. */
  variant: "row" | "card";
  /** The control before the name: the bulk-select toggle or the drag grip. */
  leading?: ReactNode;
  /** Context-menu items after the shared ones. */
  menuItems?: ReactNode;
  className?: string;
  style?: CSSProperties;
};

/**
 * One balancing-pool player: ranked-role glyphs, handle, division crest and top
 * rank, Flex / Ready / issue chips, alt handles, the balancer status menu, the
 * copy and exclude actions, and the right-click menu — the same card in the pool
 * list and the triage board, which only differ in `leading` and `variant`.
 *
 * Subtrees marked `data-card-action` keep their own clicks: the list item around
 * the card opens the player sheet on any other click.
 */
export const PoolPlayerCard = forwardRef<HTMLDivElement, PoolPlayerCardProps>(
  function PoolPlayerCard(
    {
      player,
      issues,
      registration,
      statusOptions,
      ontology,
      divisionGrid,
      selected,
      actionsDisabled,
      onSelectPlayer,
      onSetPoolMembership,
      onSetBalancerStatus,
      variant,
      leading,
      menuItems,
      className,
      style
    },
    ref
  ) {
    const t = useTranslations("balancerTool.pool");
    const tCommon = useTranslations("common");
    const issueMessage = useIssueMessage();
    // The Ready lane's rule: an advisory rank-delta warning does not block it.
    const isReady = player.is_in_pool && !hasBlockingIssues(issues);
    const sortedEntries = [...player.role_entries_json].sort(
      (left, right) => left.priority - right.priority
    );
    const rankedEntries = sortedEntries.filter(
      (entry) => isRoleEntryActive(entry) && entry.rank_value !== null
    );
    const rankedRoleCodes = rankedEntries
      .map((entry) => entry.role)
      .filter((roleCode, index, all) => all.indexOf(roleCode) === index);
    const primaryEntry = rankedEntries[0] ?? sortedEntries[0] ?? null;
    const primaryRole = primaryEntry?.role ?? null;
    const issueSummary = issues.map(issueMessage).join(" | ");
    const handles = [player.identity, ...player.additional_handles];
    const onStatusChange = registration
      ? (status: string) => onSetBalancerStatus?.(player.id, status)
      : undefined;
    const isCard = variant === "card";

    const statusMenu = (
      <BalancerStatusMenu
        size="compact"
        value={registration?.balancer_status}
        statusOptions={statusOptions}
        disabled={actionsDisabled}
        onChange={onStatusChange}
      />
    );
    const handleActions = (
      <>
        <HandleCopyButton handle={player.identity} />
        {/* Exclude only: an excluded player comes back through a balancer status change. */}
        {player.is_in_pool ? (
          <Button
            type="button"
            variant="outline"
            size={isCard ? "xs" : "icon-sm"}
            disabled={actionsDisabled || !onSetPoolMembership}
            aria-label={t("card.excludeLabel", { name: player.identity })}
            title={t("card.excludeTitle")}
            onClick={() => onSetPoolMembership?.(player.id, false)}
          >
            <ShieldX aria-hidden="true" />
            {isCard ? t("card.exclude") : null}
          </Button>
        ) : null}
      </>
    );

    return (
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <Card
            ref={ref}
            style={style}
            title={issueSummary || player.identity}
            className={cn(
              "cursor-pointer transition-colors",
              isCard
                ? "p-2.5"
                : "rounded-lg border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-2.5 py-2 hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-3)]",
              selected && "border-primary/45 bg-primary/[0.08]",
              className
            )}
          >
            <div className="flex items-start gap-2">
              {leading}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className="flex min-w-0 flex-1 items-center gap-1.5">
                    {rankedRoleCodes.length > 0 ? (
                      <span className="flex shrink-0 items-center gap-1">
                        {rankedRoleCodes.map((roleCode) => (
                          <PlayerRoleIcon
                            key={roleCode}
                            role={roleCode}
                            ontology={ontology}
                            size={15}
                          />
                        ))}
                      </span>
                    ) : (
                      <span className="shrink-0 text-label text-[color:var(--aqt-fg-dim)]">
                        {t("noRoles")}
                      </span>
                    )}
                    <Button
                      type="button"
                      variant="link"
                      size="inline"
                      data-card-action
                      onClick={() => onSelectPlayer?.(player.id)}
                      title={t("edit", { name: player.identity })}
                      className="min-w-0 justify-start"
                    >
                      <HandleLabel
                        handle={player.identity}
                        className="text-caption font-medium text-[color:var(--aqt-fg)]"
                        tagClassName="text-label"
                      />
                    </Button>
                  </div>

                  <div className="flex shrink-0 items-center gap-1" data-card-action>
                    <div className="flex items-center gap-2 pr-1">
                      <RankCrest
                        division={primaryEntry?.division_number ?? null}
                        grid={divisionGrid}
                        size={20}
                      />
                      {primaryEntry?.rank_value != null ? (
                        <span
                          className="min-w-10 text-right text-caption font-semibold tabular-nums text-cyan-300"
                          style={
                            primaryRole ? { color: roleTint(ontology, primaryRole) } : undefined
                          }
                        >
                          {primaryEntry.rank_value}
                        </span>
                      ) : (
                        <span className="text-label text-[color:var(--aqt-fg-dim)]">-</span>
                      )}
                    </div>
                    {isCard ? null : (
                      <>
                        {statusMenu}
                        {handleActions}
                      </>
                    )}
                  </div>
                </div>

                {player.is_flex ||
                isReady ||
                issues.length > 0 ||
                player.additional_handles.length > 0 ? (
                  <div className="mt-1.5 flex flex-wrap items-center gap-1">
                    {player.is_flex ? (
                      <Badge hue="var(--aqt-flex)" shape="pill" size="sm" voice="label">
                        {tCommon("roles.flex")}
                      </Badge>
                    ) : null}
                    {isReady ? (
                      <Badge tone="success" shape="pill" size="sm" voice="label">
                        {t("card.ready")}
                      </Badge>
                    ) : null}
                    {issues.map((issue) => (
                      <IssueChip
                        key={`${player.id}-${issueChipKey(issue)}`}
                        issue={issue}
                        divisionGrid={divisionGrid}
                        ontology={ontology}
                      />
                    ))}
                    <AdditionalHandleStrip additionalHandles={player.additional_handles} />
                  </div>
                ) : null}
              </div>
            </div>

            {isCard ? (
              <div className="mt-2 flex items-center justify-between gap-2" data-card-action>
                {statusMenu}
                <div className="flex items-center gap-1">{handleActions}</div>
              </div>
            ) : null}
          </Card>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-56">
          <ContextMenuLabel>{t("playerActions")}</ContextMenuLabel>
          <ContextMenuItem onClick={() => onSelectPlayer?.(player.id)}>
            <Pencil className="h-4 w-4" />
            {t("card.editProfile")}
          </ContextMenuItem>
          <HandleContextMenuItems handles={handles} />
          {onSetPoolMembership && player.is_in_pool ? (
            <>
              <ContextMenuSeparator />
              <ContextMenuItem
                disabled={actionsDisabled}
                onClick={() => onSetPoolMembership(player.id, false)}
              >
                <ShieldX className="h-4 w-4" />
                {t("card.excludeTitle")}
              </ContextMenuItem>
            </>
          ) : null}
          <BalancerStatusContextMenuItems
            value={registration?.balancer_status}
            statusOptions={statusOptions}
            disabled={actionsDisabled}
            onChange={onStatusChange}
          />
          {menuItems}
        </ContextMenuContent>
      </ContextMenu>
    );
  }
);
