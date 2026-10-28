import { Card } from "@/components/ui/card";

import { BalanceActionsBar } from "./BalanceActionsBar";
import { downloadPayload, type BalanceVariant } from "@/components/balancer/workspace-helpers";

type BalancerActionsPanelProps = {
  activeVariant: BalanceVariant | null;
  canRunBalance: boolean;
  isSavePending: boolean;
  isExportPending: boolean;
  isBalanceSaved: boolean;
  isBalanceExported: boolean;
  /** A saved balance exists to re-read ranks from. */
  canExportRanks: boolean;
  isExportRanksPending: boolean;
  tournamentId: number;
  onRunBalance: () => void;
  onSaveBalance: () => void;
  onExportBalance: () => void;
  onExportRanks: () => void;
  onCopyNames: () => void;
  onScreenshot: () => void;
};

export function BalancerActionsPanel({
  activeVariant,
  canRunBalance,
  isSavePending,
  isExportPending,
  isBalanceSaved,
  isBalanceExported,
  canExportRanks,
  isExportRanksPending,
  tournamentId,
  onRunBalance,
  onSaveBalance,
  onExportBalance,
  onExportRanks,
  onCopyNames,
  onScreenshot
}: Readonly<BalancerActionsPanelProps>) {
  if (!activeVariant) {
    return null;
  }

  return (
    <Card>
      <BalanceActionsBar
        activeVariantStats={
          activeVariant.payload.statistics != null
            ? {
                ...activeVariant.payload.statistics,
                unbalanced_count:
                  activeVariant.payload.benched_players?.length ??
                  activeVariant.payload.statistics.unbalanced_count ??
                  0
              }
            : null
        }
        activeVariant={activeVariant}
        canRunBalance={canRunBalance}
        isSavePending={isSavePending}
        isExportPending={isExportPending}
        isBalanceSaved={isBalanceSaved}
        isBalanceExported={isBalanceExported}
        canExportRanks={canExportRanks}
        isExportRanksPending={isExportRanksPending}
        onRunBalance={onRunBalance}
        onSaveBalance={onSaveBalance}
        onExportBalance={onExportBalance}
        onExportRanks={onExportRanks}
        onDownloadJson={() => downloadPayload(activeVariant.payload, tournamentId)}
        onCopyNames={onCopyNames}
        onScreenshot={onScreenshot}
      />
    </Card>
  );
}
