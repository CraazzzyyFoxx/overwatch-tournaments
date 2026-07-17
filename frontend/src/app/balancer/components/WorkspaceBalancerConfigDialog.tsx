"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { NumberInput } from "@/components/ui/number-input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import type { WorkspaceBalancerConfig } from "@/types/balancer-admin.types";

interface WorkspaceBalancerConfigDialogProps {
  workspaceId: number;
  config: WorkspaceBalancerConfig | null | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function WorkspaceBalancerConfigDialog({
  workspaceId,
  config,
  open,
  onOpenChange
}: WorkspaceBalancerConfigDialogProps) {
  const queryClient = useQueryClient();

  const [threshold, setThreshold] = useState<number | null>(
    config?.rank_delta_threshold ?? null
  );
  const [hideFromPool, setHideFromPool] = useState(
    config?.rank_delta_hide_from_pool ?? false
  );
  const [wasOpen, setWasOpen] = useState(open);

  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setThreshold(config?.rank_delta_threshold ?? null);
      setHideFromPool(config?.rank_delta_hide_from_pool ?? false);
    }
  }

  const mutation = useMutation({
    mutationFn: () =>
      balancerAdminService.upsertWorkspaceBalancerConfig(workspaceId, {
        rank_delta_threshold: threshold,
        rank_delta_hide_from_pool: hideFromPool
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspace-balancer-config", workspaceId] });
      notify.success("Pool settings saved.");
      onOpenChange(false);
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Pool rank-delta settings
          </DialogTitle>
          <DialogDescription>
            Controls how players with a large difference between their system rank and OW rank are
            displayed in the pool.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="delta-threshold">
              Rank delta threshold
              <span className="ml-1.5 text-xs text-muted-foreground">
                (rank points, empty = disabled)
              </span>
            </Label>
            <NumberInput
              id="delta-threshold"
              integer
              min={1}
              max={10000}
              placeholder="e.g. 500"
              value={threshold}
              onValueChange={setThreshold}
            />
          </div>

          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">Hide from pool</p>
              <p className="text-xs text-muted-foreground">
                When on, players above the threshold are removed from the pool view. When off, they
                get a warning badge only.
              </p>
            </div>
            <Switch checked={hideFromPool} onCheckedChange={setHideFromPool} />
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
              {mutation.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
