import type { RefObject } from "react";

import type { InternalBalancePayload } from "@/types/balancer-admin.types";
import type { DivisionGrid } from "@/types/workspace.types";
import type { RoleOntology } from "@/lib/roster/ontology";

import { BalanceEditor } from "@/components/balancer/BalanceEditor";
import { Card } from "@/components/ui/card";

import { BalancerSetupChecklist } from "./BalancerSetupChecklist";
import type { BalanceVariant } from "@/components/balancer/workspace-helpers";

type BalancerEditorPanelProps = {
  activeVariant: BalanceVariant | null;
  balanceEditorRef: RefObject<HTMLDivElement | null>;
  divisionGrid: DivisionGrid;
  ontology: RoleOntology | null;
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
  onBrowseExcluded: () => void;
  onReviewConflicts: () => void;
  onRunBalance: () => void;
};

export function BalancerEditorPanel({
  activeVariant,
  balanceEditorRef,
  divisionGrid,
  ontology,
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
  onBrowseExcluded,
  onReviewConflicts,
  onRunBalance
}: Readonly<BalancerEditorPanelProps>) {
  return (
    <Card className="flex min-h-0 flex-1 flex-col p-4">
      {activeVariant ? (
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <BalanceEditor
            ref={balanceEditorRef}
            value={activeVariant.payload}
            onChange={onChangePayload}
            divisionGrid={divisionGrid}
            ontology={ontology}
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
          onBrowseExcluded={onBrowseExcluded}
          onReviewConflicts={onReviewConflicts}
          onRunBalance={onRunBalance}
        />
      )}
    </Card>
  );
}
