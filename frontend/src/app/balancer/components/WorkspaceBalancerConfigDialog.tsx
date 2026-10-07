"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import balancerAdminService from "@/services/balancer-admin.service";
import type {
  WorkspaceBalancerConfig,
  WorkspaceRankerRead,
  WorkspaceRankerUpsert
} from "@/types/balancer-admin.types";
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

  // Seeded from the server row rather than a prop: the ranker settings are
  // read by this dialog alone, so nothing above it carries them.
  const [rankerSeed, setRankerSeed] = useState<WorkspaceRankerRead | undefined>(undefined);
  const [ranker, setRanker] = useState<WorkspaceRankerUpsert | null>(null);
  const [rebuildOpen, setRebuildOpen] = useState(false);

  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setThreshold(config?.rank_delta_threshold ?? null);
      setHideFromPool(config?.rank_delta_hide_from_pool ?? false);
      setMixChannel(config?.mix_discord_channel_id ?? "");
      // Drops any edit left behind by the last open; the cached row re-seeds it.
      setRankerSeed(undefined);
    }
  }

  const rankerQuery = useQuery({
    queryKey: balancerQueryKeys.workspaceRanker(workspaceId),
    queryFn: () => balancerAdminService.getWorkspaceRanker(workspaceId),
    enabled: open
  });
  const stored = rankerQuery.data;
  if (stored != null && stored !== rankerSeed) {
    setRankerSeed(stored);
    setRanker({
      rating_min: stored.rating_min,
      rating_max: stored.rating_max,
      rating_avg: stored.rating_avg,
      gravity: stored.gravity,
      gate_steepness: stored.gate_steepness,
      sigma_init: stored.sigma_init,
      variant: stored.variant
    });
  }

  const setRankerField = <K extends keyof WorkspaceRankerUpsert>(
    key: K,
    value: WorkspaceRankerUpsert[K]
  ) => setRanker((current) => (current == null ? current : { ...current, [key]: value }));

  const saveRanker = useMutation({
    mutationFn: (body: WorkspaceRankerUpsert) =>
      balancerAdminService.upsertWorkspaceRanker(workspaceId, body),
    onSuccess: (saved) => {
      queryClient.setQueryData(balancerQueryKeys.workspaceRanker(workspaceId), saved);
      notify.success("Ranker settings saved.");
    },
    onError: (cause) => notify.apiError(cause, { title: "Could not save the ranker settings" })
  });

  const rebuildRanker = useMutation({
    mutationFn: () => balancerAdminService.rebuildWorkspaceRanker(workspaceId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: balancerQueryKeys.workspaceRanker(workspaceId) });
      notify.success(
        `Rebuilt ${result.hidden_ratings} hidden ratings from ${result.matches} matches.`
      );
      setRebuildOpen(false);
    },
    onError: (cause) => notify.apiError(cause, { title: "Could not rebuild the ranker ratings" })
  });

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
      <DialogContent className="max-h-[85vh] max-w-md overflow-y-auto">
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

          <div className="space-y-3 border-t border-[color:var(--aqt-border)] pt-4">
            <div>
              <p className="text-sm font-medium">Ranker</p>
              <p className="text-xs text-muted-foreground">
                Corrects every host&apos;s open rating with a hidden Bayesian rating learned from
                recorded mixes; hosts opt in from their own mix settings. Based on{" "}
                <a
                  href="https://github.com/mixtura-dev/mixtura-ranker"
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2"
                >
                  mixtura-ranker
                </a>{" "}
                by Dmitriy (@dmelackov).
              </p>
            </div>

            {ranker == null ? (
              <p className="text-xs text-muted-foreground">
                {rankerQuery.isError ? "Could not load the ranker settings." : "Loading…"}
              </p>
            ) : (
              <>
                <div className="grid grid-cols-3 gap-2">
                  <div className="space-y-1">
                    <Label htmlFor="ranker-rating-min" className="text-xs">
                      Min rating
                    </Label>
                    <NumberInput
                      id="ranker-rating-min"
                      integer
                      value={ranker.rating_min}
                      onValueChange={(next) => setRankerField("rating_min", next ?? 0)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="ranker-rating-avg" className="text-xs">
                      Average
                    </Label>
                    <NumberInput
                      id="ranker-rating-avg"
                      integer
                      value={ranker.rating_avg}
                      onValueChange={(next) => setRankerField("rating_avg", next ?? 0)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="ranker-rating-max" className="text-xs">
                      Max rating
                    </Label>
                    <NumberInput
                      id="ranker-rating-max"
                      integer
                      value={ranker.rating_max}
                      onValueChange={(next) => setRankerField("rating_max", next ?? 0)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="ranker-gravity" className="text-xs">
                      Gravity
                    </Label>
                    <NumberInput
                      id="ranker-gravity"
                      min={0}
                      value={ranker.gravity}
                      onValueChange={(next) => setRankerField("gravity", next ?? 0)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="ranker-gate-steepness" className="text-xs">
                      Gate steepness
                    </Label>
                    <NumberInput
                      id="ranker-gate-steepness"
                      min={0}
                      value={ranker.gate_steepness}
                      onValueChange={(next) => setRankerField("gate_steepness", next ?? 0)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="ranker-sigma-init" className="text-xs">
                      Initial sigma
                    </Label>
                    <NumberInput
                      id="ranker-sigma-init"
                      min={0}
                      value={ranker.sigma_init}
                      onValueChange={(next) => setRankerField("sigma_init", next ?? 0)}
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="ranker-variant" className="text-xs">
                    Formula
                  </Label>
                  <Select
                    value={ranker.variant}
                    onValueChange={(next) =>
                      setRankerField("variant", next as WorkspaceRankerUpsert["variant"])
                    }
                  >
                    <SelectTrigger id="ranker-variant" aria-label="Formula">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="corrected">Corrected</SelectItem>
                      <SelectItem value="reference">Reference</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Corrected follows the hidden rating faster; reference is the original
                    specification.
                  </p>
                </div>

                <p className="text-xs text-muted-foreground">
                  {rankerSeed?.hidden_ratings ?? 0} hidden ratings in this workspace. Changing the
                  min, average, max or initial sigma rebuilds all of them from match history, which
                  can take a few seconds.
                </p>

                <div className="flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setRebuildOpen(true)}
                    disabled={rebuildRanker.isPending}
                  >
                    {rebuildRanker.isPending ? "Rebuilding…" : "Rebuild from history"}
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => saveRanker.mutate(ranker)}
                    disabled={saveRanker.isPending}
                  >
                    {saveRanker.isPending ? "Saving…" : "Save ranker"}
                  </Button>
                </div>
              </>
            )}
          </div>

          <ConfirmDialog
            open={rebuildOpen}
            onOpenChange={setRebuildOpen}
            pending={rebuildRanker.isPending}
            intent={{
              title: "Rebuild ranker ratings?",
              description:
                "Every hidden rating of this workspace is recomputed from all recorded mix matches. Nothing else changes, but it can take a few seconds.",
              confirmLabel: "Rebuild",
              tone: "warning"
            }}
            onConfirm={() => rebuildRanker.mutate()}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
