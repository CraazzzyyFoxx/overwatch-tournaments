import {
  Camera,
  Check,
  Copy,
  Download,
  Gauge,
  MoreHorizontal,
  Sparkles,
  Upload
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import type { InternalBalancePayload } from "@/types/balancer-admin.types";
import { MUTED_BUTTON_CLASS } from "@/components/balancer/balancer-page-helpers";
import { Spinner } from "@/components/ui/spinner";
import { BalanceStatsRow, type VariantStats } from "./BalanceStatsRow";

type BalanceActionsBarProps = {
  activeVariantStats: VariantStats;
  activeVariant: { payload: InternalBalancePayload } | null;
  canRunBalance: boolean;
  isSavePending: boolean;
  isExportPending: boolean;
  /** Active variant is exactly the persisted balance — nothing new to save. */
  isBalanceSaved: boolean;
  /** That persisted balance is already exported to tournament teams. */
  isBalanceExported: boolean;
  /** A saved balance exists whose ranks can be pushed onto the exported players. */
  canExportRanks: boolean;
  isExportRanksPending: boolean;
  onRunBalance: () => void;
  onSaveBalance: () => void;
  onExportBalance: () => void;
  onExportRanks: () => void;
  onDownloadJson: () => void;
  onCopyNames: () => void;
  onScreenshot: () => void;
};

export function BalanceActionsBar({
  activeVariantStats,
  activeVariant,
  canRunBalance,
  isSavePending,
  isExportPending,
  isBalanceSaved,
  isBalanceExported,
  canExportRanks,
  isExportRanksPending,
  onRunBalance,
  onSaveBalance,
  onExportBalance,
  onExportRanks,
  onDownloadJson,
  onCopyNames,
  onScreenshot
}: Readonly<BalanceActionsBarProps>) {
  return (
    <div className="flex flex-col gap-3 p-3 lg:flex-row lg:items-center lg:justify-between">
      <BalanceStatsRow stats={activeVariantStats} />

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          className={MUTED_BUTTON_CLASS}
          onClick={onRunBalance}
          disabled={!canRunBalance || isExportPending}
        >
          <Sparkles className="mr-2 h-4 w-4" />
          Regenerate
        </Button>
        <Button
          type="button"
          className="rounded-lg bg-primary text-primary-foreground hover:bg-primary/90"
          onClick={onSaveBalance}
          title={
            isBalanceSaved
              ? "This balance is already saved — edit the rosters or generate a new variant to save again."
              : undefined
          }
          disabled={!activeVariant || isBalanceSaved || isSavePending || isExportPending}
        >
          {isSavePending ? (
            <Spinner className="mr-2" />
          ) : (
            <Check className="mr-2 h-4 w-4" />
          )}
          {isBalanceSaved ? "Saved" : "Save"}
        </Button>
        <Button
          type="button"
          variant="outline"
          className={MUTED_BUTTON_CLASS}
          onClick={onExportBalance}
          title={
            isBalanceExported
              ? "This balance is already exported — edit the rosters or generate a new variant to export again."
              : undefined
          }
          disabled={!activeVariant || isBalanceExported || isExportPending || isSavePending}
        >
          {isExportPending ? (
            <Spinner className="mr-2" />
          ) : (
            <Upload className="mr-2 h-4 w-4" />
          )}
          {isBalanceExported ? "Exported" : "Export to tournament"}
        </Button>
        <Button
          type="button"
          variant="outline"
          className={MUTED_BUTTON_CLASS}
          onClick={onExportRanks}
          title="Push the saved balance's ranks onto the already-exported players. Teams and the bracket stay untouched."
          disabled={!canExportRanks || isExportRanksPending || isExportPending || isSavePending}
        >
          {isExportRanksPending ? (
            <Spinner className="mr-2" />
          ) : (
            <Gauge className="mr-2 h-4 w-4" />
          )}
          Re-export ranks
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              className={MUTED_BUTTON_CLASS}
              disabled={!activeVariant}
            >
              <MoreHorizontal className="mr-2 h-4 w-4" aria-hidden="true" />
              Advanced
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuItem onClick={onDownloadJson}>
              <Download className="h-4 w-4" aria-hidden="true" />
              Download JSON
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onCopyNames}>
              <Copy className="h-4 w-4" aria-hidden="true" />
              Copy names
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onScreenshot}>
              <Camera className="h-4 w-4" aria-hidden="true" />
              Save as image
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
