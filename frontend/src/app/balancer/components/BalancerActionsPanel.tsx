import { cn } from "@/lib/utils";

import { BalanceActionsBar } from "./BalanceActionsBar";
import { PANEL_CLASS } from "./balancer-page-helpers";
import { downloadPayload, type BalanceVariant } from "./workspace-helpers";

type BalancerActionsPanelProps = {
  activeVariant: BalanceVariant | null;
  canRunBalance: boolean;
  isSavePending: boolean;
  isExportPending: boolean;
  tournamentId: number;
  onRunBalance: () => void;
  onSaveBalance: () => void;
  onExportBalance: () => void;
  onCopyNames: () => void;
  onScreenshot: () => void;
};

export function BalancerActionsPanel({
  activeVariant,
  canRunBalance,
  isSavePending,
  isExportPending,
  tournamentId,
  onRunBalance,
  onSaveBalance,
  onExportBalance,
  onCopyNames,
  onScreenshot
}: BalancerActionsPanelProps) {
  if (!activeVariant) {
    return null;
  }

  return (
    <div className={cn(PANEL_CLASS)}>
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
        onRunBalance={onRunBalance}
        onSaveBalance={onSaveBalance}
        onExportBalance={onExportBalance}
        onDownloadJson={() => downloadPayload(activeVariant.payload, tournamentId)}
        onCopyNames={onCopyNames}
        onScreenshot={onScreenshot}
      />
    </div>
  );
}
