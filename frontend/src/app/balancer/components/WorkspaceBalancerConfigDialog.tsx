"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
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
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import type { WorkspaceBalancerConfig } from "@/types/balancer-admin.types";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";

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
}: Readonly<WorkspaceBalancerConfigDialogProps>) {
  const queryClient = useQueryClient();
  // The pool knobs save with `team.update`; the channel every mix announces in
  // belongs to the workspace's Discord, so moving it stays `workspace.update`.
  // Read-only here rather than hidden: a host should see where mixes post.
  const { canAccessPermission } = usePermissions();
  const canSetChannel = canAccessPermission("workspace.update", workspaceId);

  const [threshold, setThreshold] = useState<number | null>(
    config?.rank_delta_threshold ?? null
  );
  const [hideFromPool, setHideFromPool] = useState(
    config?.rank_delta_hide_from_pool ?? false
  );
  // The picker speaks in strings and has no null: "" is its no-channel value.
  const [mixChannel, setMixChannel] = useState(config?.mix_discord_channel_id ?? "");
  const [wasOpen, setWasOpen] = useState(open);

  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setThreshold(config?.rank_delta_threshold ?? null);
      setHideFromPool(config?.rank_delta_hide_from_pool ?? false);
      setMixChannel(config?.mix_discord_channel_id ?? "");
    }
  }

  const mutation = useMutation({
    mutationFn: () =>
      balancerAdminService.upsertWorkspaceBalancerConfig(workspaceId, {
        rank_delta_threshold: threshold,
        rank_delta_hide_from_pool: hideFromPool,
        mix_discord_channel_id: mixChannel === "" ? null : mixChannel
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: balancerQueryKeys.workspaceConfig(workspaceId) });
      notify.success("Workspace settings saved.");
      onOpenChange(false);
    },
    onError: (cause) => notify.apiError(cause, { title: "Could not save the workspace settings" })
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Workspace balancer settings
          </DialogTitle>
          <DialogDescription>
            How players with a large gap between their system rank and OW rank appear in the pool,
            and where every mix in this workspace posts its matchup.
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

          <div className="space-y-1.5 border-t border-[color:var(--aqt-border)] pt-4">
            <Label htmlFor="mix-discord-channel">
              Mix Discord channel
              <span className="ml-1.5 text-xs text-muted-foreground">
                (where every mix posts its matchup)
              </span>
            </Label>
            <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <DiscordChannelSelect
                  id="mix-discord-channel"
                  workspaceId={workspaceId}
                  value={mixChannel}
                  onChange={setMixChannel}
                  disabled={!canSetChannel}
                  ariaLabel="Mix Discord channel"
                  placeholder="No channel"
                />
              </div>
              {canSetChannel && mixChannel !== "" ? (
                <Button variant="ghost" size="sm" onClick={() => setMixChannel("")}>
                  Clear
                </Button>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">
              {canSetChannel
                ? "Hosts post here by default. A single mix can be pointed elsewhere from its own settings, but only by a workspace admin."
                : "Set by workspace admins. Every mix here posts its matchup to this channel."}
            </p>
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
