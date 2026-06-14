import type { RefObject } from "react";

import type { InternalBalancePayload } from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { BalanceEditor } from "@/components/balancer/BalanceEditor";
import { cn } from "@/lib/utils";

import { PANEL_CLASS } from "./balancer-page-helpers";
import { BalancerSetupChecklist } from "./BalancerSetupChecklist";
import type { BalanceVariant } from "./workspace-helpers";

type BalancerEditorPanelProps = {
  activeVariant: BalanceVariant | null;
  balanceEditorRef: RefObject<HTMLDivElement | null>;
  divisionGrid: DivisionGrid;
  selectedPlayerId: number | null;
  collapsedTeamIds: number[];
  poolPlayerCount: number;
  invalidPlayerCount: number;
  canRunBalance: boolean;
  isRunPending: boolean;
  realtimeTopic?: string | null;
  currentUserId?: number | null;
  workspaceId?: number | null;
  onChangePayload: (payload: InternalBalancePayload) => void;
  onSelectPlayer: (playerId: number | null) => void;
  onToggleTeam: (teamId: number) => void;
  onBrowseAvailable: () => void;
  onReviewConflicts: () => void;
  onRunBalance: () => void;
};

export function BalancerEditorPanel({
  activeVariant,
  balanceEditorRef,
  divisionGrid,
  selectedPlayerId,
  collapsedTeamIds,
  poolPlayerCount,
  invalidPlayerCount,
  canRunBalance,
  isRunPending,
  realtimeTopic = null,
  currentUserId = null,
  workspaceId = null,
  onChangePayload,
  onSelectPlayer,
  onToggleTeam,
  onBrowseAvailable,
  onReviewConflicts,
  onRunBalance
}: BalancerEditorPanelProps) {
  return (
    <div className={cn(PANEL_CLASS, "flex min-h-0 flex-1 flex-col p-4")}>
      {activeVariant ? (
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <BalanceEditor
            ref={balanceEditorRef}
            value={activeVariant.payload}
            onChange={onChangePayload}
            divisionGrid={divisionGrid}
            selectedPlayerId={selectedPlayerId}
            onSelectPlayer={onSelectPlayer}
            collapsedTeamIds={collapsedTeamIds}
            onToggleTeam={onToggleTeam}
            realtimeTopic={realtimeTopic}
            currentUserId={currentUserId}
            workspaceId={workspaceId}
          />
        </div>
      ) : (
        <BalancerSetupChecklist
          poolPlayerCount={poolPlayerCount}
          invalidPlayerCount={invalidPlayerCount}
          canRunBalance={canRunBalance}
          isRunPending={isRunPending}
          onBrowseAvailable={onBrowseAvailable}
          onReviewConflicts={onReviewConflicts}
          onRunBalance={onRunBalance}
        />
      )}
    </div>
  );
}
